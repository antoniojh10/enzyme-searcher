from enzyme_searcher.providers.bacdive import BacDiveProvider

from .conftest import FakeBacDiveClient, recorded_strains


def provider(client, **kw):
    return BacDiveProvider(client_factory=lambda: client, **kw)


def test_adapter_on_recorded_payload():
    with_enzymes, without = recorded_strains()
    org = provider(None).to_canonical(with_enzymes, "Gordonia")
    assert org.key == "156420" and org.species.startswith("Gordonia")
    assert org.strain == org.collection_numbers[0] and org.url.endswith("/156420")
    obs = {o.enzyme: o for o in org.observations}
    assert obs["alpha-glucosidase"].ec == "3.2.1.20" and obs["alpha-glucosidase"].result == "+"
    assert obs["alpha-glucosidase"].reference == "BacDive:156420" and obs["alpha-glucosidase"].method
    assert provider(None).to_canonical(without, "Gordonia") is None  # no enzyme section


def test_fetch_paginates_batches_and_dedupes(bacdive_client):
    chunk = provider(bacdive_client).fetch("Gordonia")
    assert chunk.queried == 3 and len(chunk.organisms) == 2
    rub = chunk.observations[chunk.observations.organism_id == "bacdive:1001"]
    assert dict(zip(rub.ec, rub.result)) == {"1.11.1.6": "+", "3.5.1.5": "+"}  # '+' wins
    assert bacdive_client.calls[0] == {"taxonomy": ["Gordonia"]}


def test_max_organisms(bacdive_client):
    chunk = provider(bacdive_client, max_organisms=1).fetch("Gordonia")
    assert chunk.queried == 1


def test_candidatus_without_data_does_not_fail(bacdive_client):
    chunk = provider(bacdive_client).fetch("Candidatus Microthrix")
    assert chunk.is_empty and chunk.notes == ["no bacdive data (Candidatus taxon)"]
    assert bacdive_client.calls[-1] == {"taxonomy": ["Microthrix"]}


def test_collection_numbers_include_all_and_dsm():
    raw = {"General": {"BacDive-ID": 9, "DSM-Number": 43247},
           "Name and taxonomic classification": {"species": "Gordonia bronchialis"},
           "Physiology and metabolism": {"enzymes": [{"value": "catalase", "activity": "+"}]},
           "Literature": {"culture collection no.": "ATCC 25592, JCM 3198"}}
    org = provider(None).to_canonical(raw, "Gordonia")
    assert org.collection_numbers == ("ATCC 25592", "JCM 3198", "DSM 43247") and org.strain == "ATCC 25592"
