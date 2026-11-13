from enzyme_searcher.providers.midas import MidasProvider, midas_name


def test_name_mapping():
    assert midas_name("Candidatus Microthrix") == "Ca_Microthrix" and midas_name("Gordonia") == "Gordonia"


def test_traits_from_recorded_payload(midas_client, midas_session):
    chunk = MidasProvider(client=midas_client).fetch("Nitrospira")
    assert midas_session.paths == ["Nitrospira"]
    assert chunk.observations.empty and len(chunk.organisms) == 1
    org = chunk.organisms.iloc[0]
    assert (org.kind, org.species) == ("taxon", "Nitrospira") and org.url.endswith("/genus/Nitrospira")
    t = chunk.traits.set_index(["trait", "context"])
    assert t.loc[("NOB", "in situ"), "value"] == "+"
    assert t.loc[("NOB", "in situ"), "evidence"] == "expert_curation"
    assert set(chunk.traits.value) <= {"+", "-", "variable", "NA"}
    assert set(chunk.traits.category) == {"metabolism", "property"}
    assert {"in situ", "other"} == set(chunk.traits.context)


def test_candidatus_genus(midas_client, midas_session):
    chunk = MidasProvider(client=midas_client).fetch("Candidatus Microthrix")
    assert midas_session.paths == ["Ca_Microthrix"] and not chunk.is_empty
    t = chunk.traits.set_index(["trait", "context"])
    assert t.loc[("Aerobic heterotroph", "in situ"), "value"] == "+"


def test_unknown_genus_is_empty_not_an_error(midas_client):
    chunk = MidasProvider(client=midas_client).fetch("Turneriella")
    assert chunk.is_empty and chunk.notes == ["no midas data"]
