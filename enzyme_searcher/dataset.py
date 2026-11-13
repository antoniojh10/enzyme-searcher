"""The researcher-facing dataset: clean, provider-independent DataFrames plus summaries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .model import OBSERVATION_COLUMNS, ORGANISM_COLUMNS, TRAIT_COLUMNS, Chunk, Evidence

EXCEL_MAX_ROWS = 1_048_575
TIDY_COLUMNS = ["genus", "provider", "evidence", "species", "strain", "kind", "ec", "enzyme",
                "enzyme_reported", "result", "method", "reference", "detail", "organism_id", "url"]


def _ec_sort_key(ec: str) -> list[int]:
    return [int(p) if p.isdigit() else 10**6 for p in str(ec).replace("n", "").split(".")]


@dataclass
class Dataset:
    organisms: pd.DataFrame      # one row per organism (strain, genome, taxon) and provider
    observations: pd.DataFrame   # one row per organism × enzyme
    enzymes: pd.DataFrame        # canonical EC -> name
    provenance: pd.DataFrame     # what was fetched, when, and with what result
    traits: pd.DataFrame | None = None  # qualitative genus-level traits (MiDAS)

    def __post_init__(self) -> None:
        if self.traits is None:
            self.traits = pd.DataFrame(columns=TRAIT_COLUMNS)

    # ---------------------------------------------------------------- building
    @classmethod
    def from_chunks(cls, chunks: Iterable[Chunk], enzymes: pd.DataFrame | None = None) -> "Dataset":
        chunks = list(chunks)
        organisms = [c.organisms for c in chunks if not c.organisms.empty]
        observations = [c.observations for c in chunks if not c.observations.empty]
        traits = [c.traits for c in chunks if not c.traits.empty]
        provenance = pd.DataFrame([{
            "provider": c.provider, "genus": c.genus, "fetched_at": c.fetched_at, "queried": c.queried,
            "organisms": len(c.organisms), "observations": len(c.observations), "traits": len(c.traits),
            "notes": "; ".join(c.notes),
        } for c in chunks])
        return cls(
            organisms=(pd.concat(organisms, ignore_index=True) if organisms
                       else pd.DataFrame(columns=ORGANISM_COLUMNS)),
            observations=(pd.concat(observations, ignore_index=True) if observations
                          else pd.DataFrame(columns=OBSERVATION_COLUMNS)),
            enzymes=enzymes if enzymes is not None else pd.DataFrame(columns=["ec", "name"]),
            provenance=provenance,
            traits=pd.concat(traits, ignore_index=True) if traits else None)

    # ------------------------------------------------------------------- views
    def tidy(self) -> pd.DataFrame:
        """Long format, one row per organism × enzyme: the table to filter, group and plot.

        `enzyme` is the canonical name (KEGG ENZYME name for the EC, otherwise the most common
        reported name), so the same EC has one name across providers. `enzyme_reported` keeps
        what the provider said.
        """
        obs = self.observations.rename(columns={"enzyme": "enzyme_reported"})
        df = obs.merge(self.organisms, on="organism_id", how="left")
        df["enzyme"] = self._canonical_names(df)
        for col in ("genus", "provider", "evidence", "kind", "result"):
            df[col] = df[col].astype("category")
        return df[TIDY_COLUMNS]

    def _canonical_names(self, df: pd.DataFrame) -> pd.Series:
        names = dict(zip(self.enzymes["ec"], self.enzymes["name"]))
        reported = df.loc[df["ec"] != "", ["ec", "enzyme_reported"]].astype(str)
        reported = reported[reported["enzyme_reported"] != ""]
        for ec, name in reported.groupby("ec")["enzyme_reported"].agg(lambda s: s.mode().iloc[0]).items():
            names.setdefault(ec, name)
        ecs, rep = df["ec"].astype(str), df["enzyme_reported"].astype(str)
        mapped = ecs.map(names)
        return mapped.where(mapped.notna() & (ecs != ""), rep).astype("string")

    def summary(self) -> pd.DataFrame:
        """Per genus and provider: organisms with data, organisms queried, distinct EC numbers."""
        if self.provenance.empty:
            return pd.DataFrame()
        ecs = (self.observations[self.observations["ec"] != ""]
               .merge(self.organisms[["organism_id", "genus", "provider"]], on="organism_id")
               .groupby(["genus", "provider"], observed=True)["ec"].nunique().rename("distinct_ec"))
        out = self.provenance.merge(ecs.reset_index(), on=["genus", "provider"], how="left")
        out["distinct_ec"] = out["distinct_ec"].fillna(0).astype(int)
        return out[["genus", "provider", "organisms", "queried", "observations", "distinct_ec", "traits",
                    "notes", "fetched_at"]]

    def genus_enzyme(self) -> pd.DataFrame:
        """Per genus × enzyme × evidence: how many organisms are positive out of how many.

        * measured_activity: positive strains / strains tested for that enzyme.
        * genome_annotation: genomes with the EC / all genomes of the genus (absence = not annotated).
        * literature: organisms reporting it (no denominator).
        """
        cols = ["genus", "ec", "enzyme", "evidence", "n_positive", "n_tested", "fraction_positive"]
        df = self.tidy()
        if df.empty:
            return pd.DataFrame(columns=cols)
        df = df.assign(key=df["ec"].where(df["ec"] != "", "name:" + df["enzyme"].astype(str)),
                       positive=df["result"] == "+")
        g = (df.groupby(["genus", "key", "evidence"], observed=True)
               .agg(ec=("ec", "first"), enzyme=("enzyme", "first"),
                    n_positive=("positive", "sum"), n_tested=("organism_id", "nunique"))
               .reset_index())
        genomes = (self.organisms[self.organisms["kind"] == "genome"].groupby("genus", observed=True).size())
        is_genome = g["evidence"] == Evidence.GENOME_ANNOTATION
        g.loc[is_genome, "n_tested"] = g.loc[is_genome, "genus"].map(genomes).astype(int)
        g["n_tested"] = g["n_tested"].where(g["evidence"] != Evidence.LITERATURE)
        g["fraction_positive"] = (g["n_positive"] / g["n_tested"]).round(3)
        g = g.sort_values(["genus", "evidence", "n_positive"], ascending=[True, True, False], kind="stable")
        return g[cols].reset_index(drop=True)

    def genus_traits(self, context: str | None = "in situ", wide: bool = False) -> pd.DataFrame:
        """Qualitative traits per genus ('+', '-', 'variable', 'NA').

        `context` selects where the evidence comes from in MiDAS ('in situ' or 'other'); None keeps both.
        With wide=True returns a genus × trait table (handy for a heatmap or a quick look).
        """
        t = self.traits.merge(self.organisms[["organism_id", "genus", "provider"]], on="organism_id")
        if context is not None:
            t = t[t["context"] == context]
        t = t[["genus", "provider", "category", "trait", "context", "value", "reference"]].astype(
            {"genus": str, "trait": str, "value": str})
        if wide:
            return t.pivot_table(index="genus", columns="trait", values="value", aggfunc="first")
        return t.reset_index(drop=True)

    def matrix(self, evidence: str | None = None, value: str = "fraction_positive",
               min_positive: int = 1) -> pd.DataFrame:
        """Genus × enzyme pivot (e.g. for a heatmap). Columns are enzymes with an EC number."""
        ge = self.genus_enzyme()
        ge = ge[(ge["ec"] != "") & (ge["n_positive"] >= min_positive)]
        if evidence:
            ge = ge[ge["evidence"] == evidence]
        m = ge.pivot_table(index="genus", columns="ec", values=value, aggfunc="max", observed=True)
        return m[sorted(m.columns, key=_ec_sort_key)]

    # ------------------------------------------------------------------ export
    def to_excel(self, target) -> list[str]:
        """Write summary, genus_enzyme, organisms and observations sheets. Returns notes about
        anything left out (genome annotations are dropped from the long sheet if it would not fit)."""
        notes = []
        tidy = self.tidy()
        if len(tidy) > EXCEL_MAX_ROWS:
            tidy = tidy[tidy["evidence"] != Evidence.GENOME_ANNOTATION]
            notes.append("Genome annotations (KEGG) are summarized in 'genus_enzyme' but not listed in "
                         "'observations': there are more rows than Excel allows. Filter by genus to export them.")
        with pd.ExcelWriter(target, engine="xlsxwriter") as writer:
            self.summary().to_excel(writer, sheet_name="summary", index=False)
            self.genus_enzyme().to_excel(writer, sheet_name="genus_enzyme", index=False)
            self.organisms.to_excel(writer, sheet_name="organisms", index=False)
            tidy.to_excel(writer, sheet_name="observations", index=False)
            if not self.traits.empty:
                self.genus_traits(context=None).to_excel(writer, sheet_name="traits", index=False)
            if notes:
                pd.DataFrame({"note": notes}).to_excel(writer, sheet_name="notes", index=False)
        return notes

    def filter(self, genera: Iterable[str] | None = None, providers: Iterable[str] | None = None) -> "Dataset":
        """Subset by genus and/or provider."""
        orgs = self.organisms
        if genera is not None:
            orgs = orgs[orgs["genus"].isin(list(genera))]
        if providers is not None:
            orgs = orgs[orgs["provider"].isin(list(providers))]
        prov = self.provenance
        if genera is not None:
            prov = prov[prov["genus"].isin(list(genera))]
        if providers is not None:
            prov = prov[prov["provider"].isin(list(providers))]
        keep = orgs["organism_id"]
        obs = self.observations[self.observations["organism_id"].isin(keep)]
        traits = self.traits[self.traits["organism_id"].isin(keep)]
        return Dataset(orgs.reset_index(drop=True), obs.reset_index(drop=True), self.enzymes,
                       prov.reset_index(drop=True), traits.reset_index(drop=True))
