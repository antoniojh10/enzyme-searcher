import pandas as pd
import pytest

import enzyme_searcher as es


@pytest.fixture
def dataset(providers, kegg_client):
    result = es.fetch_all(["Gordonia", "Nitrospira"], fetcher=lambda p, g, e: es.fetch_chunk(p, g, e, 2))
    return es.Dataset.from_chunks(result.chunks, es.fetch_enzyme_names(kegg_client))


def test_tidy_has_canonical_names(dataset):
    tidy = dataset.tidy()
    assert set(tidy.provider) == {"bacdive", "kegg"}
    assert set(tidy.loc[tidy.ec == "1.11.1.6", "enzyme"]) == {"catalase"}
    # names without EC keep the reported name
    no_ec = tidy[(tidy.provider == "bacdive") & (tidy.ec == "")]
    assert (no_ec.enzyme == no_ec.enzyme_reported).all() and len(no_ec) > 0


def test_genus_enzyme_fractions(dataset):
    ge = dataset.genus_enzyme().set_index(["genus", "ec", "evidence"])
    cat = ge.loc[("Gordonia", "1.11.1.6", "genome_annotation")]
    assert (cat.n_positive, cat.n_tested, cat.fraction_positive) == (2, 2, 1.0)
    ure = ge.loc[("Gordonia", "3.5.1.5", "measured_activity")]
    assert ure.n_tested >= 1 and 0 <= ure.fraction_positive <= 1


def test_summary_and_provenance(dataset):
    s = dataset.summary().set_index(["genus", "provider"])
    assert s.loc[("Nitrospira", "bacdive"), "notes"] == "no bacdive data"
    assert s.loc[("Gordonia", "kegg"), "organisms"] == 2 and s.loc[("Gordonia", "kegg"), "distinct_ec"] > 500


def test_matrix(dataset):
    m = dataset.matrix(evidence="genome_annotation")
    assert set(m.index) == {"Gordonia", "Nitrospira"} and m.loc["Gordonia", "1.11.1.6"] == 1.0


def test_filter(dataset):
    sub = dataset.filter(genera=["Nitrospira"], providers=["kegg"])
    assert set(sub.organisms.genus) == {"Nitrospira"} and set(sub.organisms.provider) == {"kegg"}
    assert set(sub.observations.organism_id) <= set(sub.organisms.organism_id)


def test_excel(dataset, tmp_path, monkeypatch):
    path = tmp_path / "out.xlsx"
    assert dataset.to_excel(path) == []
    sheets = pd.read_excel(path, sheet_name=None)
    assert set(sheets) == {"summary", "genus_enzyme", "organisms", "observations", "traits"}
    monkeypatch.setattr("enzyme_searcher.dataset.EXCEL_MAX_ROWS", 10)
    notes = dataset.to_excel(path)
    assert notes and set(pd.read_excel(path, sheet_name="observations").evidence) == {"measured_activity"}


def test_empty_dataset():
    ds = es.Dataset.from_chunks([])
    assert ds.tidy().empty and ds.genus_enzyme().empty


def test_traits_in_dataset(providers, kegg_client, tmp_path):
    result = es.fetch_all(["Nitrospira", "Candidatus Microthrix"], providers=["midas"])
    ds = es.Dataset.from_chunks(result.chunks)
    wide = ds.genus_traits(wide=True)
    assert wide.loc["Nitrospira", "NOB"] == "+" and wide.loc["Candidatus Microthrix", "Aerobic heterotroph"] == "+"
    assert set(ds.genus_traits(context=None)["context"]) == {"in situ", "other"}
    assert ds.summary().set_index("genus").loc["Nitrospira", "traits"] > 0
    assert len(ds.filter(genera=["Nitrospira"]).traits) == len(ds.traits) / 2
    path = tmp_path / "t.xlsx"
    ds.to_excel(path)
    assert "traits" in pd.read_excel(path, sheet_name=None)


def test_old_cached_chunks_still_load():
    """Chunks pickled before `traits` existed must keep working (marimo cache survives upgrades)."""
    import pickle
    from enzyme_searcher.model import Evidence, build_chunk
    chunk = build_chunk("x", Evidence.MEASURED_ACTIVITY, "G", [], 0)
    state = dict(chunk.__dict__)
    del state["traits"]
    old = es.Chunk.__new__(es.Chunk)
    old.__setstate__(state)
    restored = pickle.loads(pickle.dumps(old))
    assert restored.traits.empty and restored.is_empty
