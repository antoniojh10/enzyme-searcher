"""Adding a provider = one class. Nothing else changes."""
import pytest

import enzyme_searcher as es
from enzyme_searcher.providers import base


@pytest.fixture
def toy_provider():
    @es.register
    class ToyProvider(es.Provider):
        name = "toy"
        evidence = es.Evidence.MEASURED_ACTIVITY
        description = "a source that answers from a dict"
        DATA = {"Gordonia": [{"id": "x1", "sp": "Gordonia toy", "tests": {"1.11.1.6": "positive"}}]}

        def fetch_raw(self, genus, ecs=()):
            yield from self.DATA.get(genus, [])

        def to_canonical(self, raw, genus):
            return es.Organism(key=raw["id"], species=raw["sp"],
                               observations=[es.Observation(ec=ec, result=r) for ec, r in raw["tests"].items()])

    yield ToyProvider
    base._REGISTRY.pop("toy")


def test_new_provider_flows_end_to_end(toy_provider):
    assert "toy" in es.available_providers()
    result = es.fetch_all(["Gordonia", "Turneriella"], providers=["toy"])
    ds = es.Dataset.from_chunks(result.chunks)
    assert ds.tidy()[["genus", "provider", "species", "ec", "result"]].values.tolist() == [
        ["Gordonia", "toy", "Gordonia toy", "1.11.1.6", "+"]]
    assert ds.provenance.set_index("genus").loc["Turneriella", "notes"] == "no toy data"


def test_duplicate_name_rejected(toy_provider):
    class Other(toy_provider):
        pass
    with pytest.raises(ValueError):
        es.register(Other)


def test_unknown_provider():
    with pytest.raises(KeyError):
        es.get_provider("nope")
    with pytest.raises(KeyError):
        es.fetch_all(["Gordonia"], providers=["nope"])
