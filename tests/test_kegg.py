from enzyme_searcher.http import RateLimiter
from enzyme_searcher.providers.kegg import (KeggClient, KeggProvider, belongs_to_genus, parse_enzyme_links,
                                            parse_genome_list)
from enzyme_searcher.reference import fetch_enzyme_names

from .conftest import FakeKeggSession, fixture_text


def test_parsers_on_recorded_responses():
    genomes = parse_genome_list(fixture_text("kegg_find_genome_gordonia.txt"))
    assert genomes[0] == {"tnum": "T01102", "code": "gbr", "name": "Gordonia bronchialis DSM 43247"}
    ecs = parse_enzyme_links(fixture_text("kegg_link_enzyme_gbr.txt"))
    assert "1.11.1.6" in ecs and len(ecs) == len(set(ecs)) > 500


def test_genus_matching():
    assert belongs_to_genus("Candidatus Nitrospira inopinata", "Nitrospira")
    assert not belongs_to_genus("Nitrospirillum amazonense", "Nitrospira")


def test_fetch_gordonia(kegg_client, kegg_session):
    chunk = KeggProvider(client=kegg_client, max_organisms=2).fetch("Gordonia")
    orgs = chunk.organisms.set_index("organism_id")
    assert orgs.loc["kegg:gbr", ["species", "strain", "kind"]].tolist() == ["Gordonia bronchialis", "DSM 43247", "genome"]
    assert orgs.loc["kegg:gpo", "strain"] == "VH2"
    assert set(chunk.observations.result) == {"+"} and set(chunk.observations.evidence) == {"genome_annotation"}
    assert kegg_session.paths == ["find/genome/Gordonia", "link/enzyme/gbr", "link/enzyme/gpo"]


def test_candidatus_species_inside_regular_genus(kegg_client):
    chunk = KeggProvider(client=kegg_client).fetch("Nitrospira")
    species = set(chunk.organisms.species)
    assert "Candidatus Nitrospira inopinata" in species and "Nitrospira moscoviensis" in species
    assert len(chunk.organisms) == 9


def test_candidatus_genus(kegg_client):
    chunk = KeggProvider(client=kegg_client).fetch("Candidatus Nitrotoga")
    assert set(chunk.organisms.species) == {"Candidatus Nitrotoga sp.", "Candidatus Nitrotoga arctica"}


def test_genus_without_genomes(kegg_client):
    chunk = KeggProvider(client=kegg_client).fetch("Turneriella")
    assert chunk.is_empty and chunk.notes == ["no kegg data"]


def test_retries_server_errors():
    session = FakeKeggSession(failures=2)
    client = KeggClient(session=session, limiter=RateLimiter(1000, sleep=lambda s: None))
    assert client.get("find/genome/Gordonia").startswith("T01102")
    assert session.paths == ["find/genome/Gordonia"] * 3


def test_enzyme_names(kegg_client):
    names = fetch_enzyme_names(kegg_client).set_index("ec")["name"]
    assert names["1.11.1.6"] == "catalase"
