import json

import pytest

from enzyme_searcher.providers.base import ProviderUnavailable
from enzyme_searcher.providers.brenda import BrendaProvider, JsonBackend, SoapBackend


@pytest.fixture
def brenda_json(tmp_path):
    data = {"data": {
        "1.11.1.6": {"name": "Catalase",
                     "organisms": {"1": {"value": "Gordonia terrae"}, "2": {"value": "Homo sapiens"}},
                     "substrates_products": [{"value": "2 H2O2 = O2 + 2 H2O", "organisms": ["1", "2"]}],
                     "ph_range": [{"value": "5-9", "organisms": ["1"]}],
                     "temperature_range": [{"value": "20-45", "organisms": ["1"]}]},
        "3.5.1.5": {"name": "urease", "organisms": {"1": {"value": "Gordonia terrae"}}},
    }}
    path = tmp_path / "brenda.json"
    path.write_text(json.dumps(data))
    return str(path)


def test_json_backend_groups_by_organism(brenda_json):
    chunk = BrendaProvider(backend=JsonBackend(brenda_json)).fetch("Gordonia", ecs=("1.11.1.6", "3.5.1.5", "9.9.9.9"))
    assert list(chunk.organisms.species) == ["Gordonia terrae"]
    obs = chunk.observations.set_index("ec")
    assert set(obs.index) == {"1.11.1.6", "3.5.1.5"} and set(obs.evidence) == {"literature"}
    assert "pH: 5-9" in obs.loc["1.11.1.6", "detail"] and "T(°C): 20-45" in obs.loc["1.11.1.6", "detail"]


def test_soap_backend_hashes_password(monkeypatch):
    monkeypatch.setenv("BRENDA_USER", "u@example.org")
    monkeypatch.setenv("BRENDA_PASS", "secret")

    class Service:
        calls = []

        def __getattr__(self, method):
            def call(email, password, *args):
                Service.calls.append((method, password, args))
                return {"getOrganism": [{"organism": "Gordonia terrae"}, {"organism": "Homo sapiens"}],
                        "getRecommendedName": [{"recommendedName": "catalase"}],
                        "getSubstrate": [{"organism": "Gordonia terrae", "substrate": "H2O2"}],
                        "getPhRange": [], "getTemperatureRange": []}[method]
            return call

    entries = SoapBackend(service=Service()).entries("1.11.1.6", "Gordonia")
    assert [e["organism"] for e in entries] == ["Gordonia terrae"] and entries[0]["substrates"] == ["H2O2"]
    _, password, args = Service.calls[0]
    assert password != "secret" and len(password) == 64 and args[0] == "ecNumber*1.11.1.6"


def test_unavailable_without_credentials(monkeypatch):
    for var in ("BRENDA_USER", "BRENDA_PASS", "BRENDA_JSON"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ProviderUnavailable):
        BrendaProvider().fetch("Gordonia", ecs=("1.11.1.6",))
