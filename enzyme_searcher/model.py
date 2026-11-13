"""Canonical, provider-independent data model.

Every provider adapter converts its raw API payloads into `Organism` objects carrying
`Observation`s. `build_chunk` then normalizes them and packs them into DataFrames, so
storage, the notebook and the researcher never deal with provider-specific formats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

import pandas as pd

from .normalize import RESULT_PRIORITY, normalize_ec, normalize_enzyme_name, normalize_result


class Evidence(StrEnum):
    """What a '+' means. Lets data from different providers be combined without losing meaning."""
    MEASURED_ACTIVITY = "measured_activity"   # phenotypic test on a cultured strain (BacDive)
    GENOME_ANNOTATION = "genome_annotation"   # gene annotated in a sequenced genome (KEGG)
    LITERATURE = "literature"                 # reported in the literature (BRENDA)
    EXPERT_CURATION = "expert_curation"       # curated genus-level knowledge (MiDAS field guide)


class OrganismKind(StrEnum):
    STRAIN = "strain"   # a cultured strain
    GENOME = "genome"   # a sequenced genome / assembly
    MAG = "mag"         # metagenome-assembled genome
    TAXON = "taxon"     # a species-level name with no specific strain


@dataclass(slots=True)
class Observation:
    enzyme: str = ""          # name as reported by the provider (normalized later)
    ec: str = ""              # EC number; the main key across providers
    result: str = "NA"        # '+', '-' or 'NA'
    method: str = ""
    reference: str = ""
    detail: str = ""          # free text (e.g. substrates, pH, temperature)


@dataclass(slots=True)
class Trait:
    """A qualitative, usually genus-level property (e.g. 'PAO', 'Nitrite reduction', 'Filamentous')."""
    name: str
    value: str = "NA"         # '+', '-', 'variable' or 'NA' (not assessed)
    category: str = ""        # e.g. 'metabolism', 'property'
    context: str = ""         # e.g. 'in situ', 'other' (where the evidence comes from)
    reference: str = ""       # DOIs or citation ids


@dataclass(slots=True)
class Organism:
    key: str                  # provider-native id (BacDive-ID, KEGG org code, ...)
    species: str
    strain: str = ""
    kind: OrganismKind = OrganismKind.STRAIN
    collection_numbers: tuple[str, ...] = ()
    url: str = ""
    observations: list[Observation] = field(default_factory=list)
    traits: list[Trait] = field(default_factory=list)


ORGANISM_COLUMNS = ["organism_id", "provider", "genus", "species", "strain", "kind",
                    "collection_numbers", "url"]
OBSERVATION_COLUMNS = ["organism_id", "evidence", "ec", "enzyme", "result", "method", "reference", "detail"]
TRAIT_COLUMNS = ["organism_id", "evidence", "category", "trait", "context", "value", "reference"]
_CATEGORICAL = {"provider", "genus", "kind", "evidence", "result", "method", "category", "trait", "context", "value"}


@dataclass
class Chunk:
    """Canonical data from one provider for one genus: the unit that is fetched and cached."""
    provider: str
    genus: str
    fetched_at: str
    queried: int                      # raw items the provider returned (e.g. strains looked at)
    organisms: pd.DataFrame
    observations: pd.DataFrame
    traits: pd.DataFrame = field(default_factory=lambda: _frame([], TRAIT_COLUMNS))
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.observations.empty and self.traits.empty

    def __setstate__(self, state: dict) -> None:
        # Chunks cached by an older version of the package lack newer fields; give them defaults
        # (marimo's persistent cache does not invalidate when the library code changes).
        state.setdefault("traits", _frame([], TRAIT_COLUMNS))
        state.setdefault("notes", [])
        self.__dict__.update(state)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _frame(rows: list[dict], columns: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in columns:
        df[col] = df[col].astype("category") if col in _CATEGORICAL else df[col].astype("string")
    return df


def dedupe_observations(observations: list[Observation]) -> list[Observation]:
    """Normalize and keep one observation per EC (or per name when there is no EC).

    When several references disagree for the same organism, '+' wins over '-', and '-' over 'NA'.
    """
    best: dict[str, Observation] = {}
    for obs in observations:
        obs.ec = normalize_ec(obs.ec)
        obs.enzyme = normalize_enzyme_name(obs.enzyme)
        obs.result = normalize_result(obs.result)
        if not obs.ec and not obs.enzyme:
            continue
        key = obs.ec or f"name:{obs.enzyme}"
        if key not in best or RESULT_PRIORITY[obs.result] < RESULT_PRIORITY[best[key].result]:
            best[key] = obs
    return list(best.values())


_TRAIT_VALUES = {"positive": "+", "+": "+", "negative": "-", "-": "-", "variable": "variable"}


def normalize_trait_value(value: object) -> str:
    """'Positive' -> '+', 'Negative' -> '-', 'Variable' -> 'variable', anything else -> 'NA'."""
    return _TRAIT_VALUES.get(str(value).strip().lower(), "NA") if value is not None else "NA"


def build_chunk(provider: str, evidence: Evidence, genus: str, organisms: list[Organism],
                queried: int, notes: list[str] | None = None) -> Chunk:
    org_rows, obs_rows, trait_rows = [], [], []
    for org in organisms:
        observations = dedupe_observations(org.observations)
        if not observations and not org.traits:
            continue
        organism_id = f"{provider}:{org.key}"
        org_rows.append({"organism_id": organism_id, "provider": provider, "genus": genus,
                         "species": org.species, "strain": org.strain, "kind": str(org.kind),
                         "collection_numbers": "; ".join(org.collection_numbers), "url": org.url})
        obs_rows.extend({"organism_id": organism_id, "evidence": str(evidence), "ec": o.ec,
                         "enzyme": o.enzyme, "result": o.result, "method": o.method,
                         "reference": o.reference, "detail": o.detail} for o in observations)
        trait_rows.extend({"organism_id": organism_id, "evidence": str(evidence), "category": t.category,
                           "trait": t.name, "context": t.context, "value": normalize_trait_value(t.value),
                           "reference": t.reference} for t in org.traits)
    return Chunk(provider=provider, genus=genus, fetched_at=utc_now(), queried=queried,
                 organisms=_frame(org_rows, ORGANISM_COLUMNS),
                 observations=_frame(obs_rows, OBSERVATION_COLUMNS),
                 traits=_frame(trait_rows, TRAIT_COLUMNS), notes=list(notes or []))
