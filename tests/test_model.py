from enzyme_searcher.model import Evidence, Observation, Organism, build_chunk, dedupe_observations


def test_dedupe_prefers_positive_and_normalizes():
    obs = dedupe_observations([
        Observation(enzyme="Urease", ec="EC 3.5.1.5", result="-"),
        Observation(enzyme="urease", ec="3.5.1.5", result="+"),
        Observation(enzyme="Esterase  (C 4)", result="positive"),
        Observation(enzyme="esterase (c 4)", result="NA"),
        Observation(enzyme="", ec="not an ec"),
    ])
    assert [(o.ec, o.enzyme, o.result) for o in obs] == [("3.5.1.5", "urease", "+"), ("", "esterase (c 4)", "+")]


def test_build_chunk_skips_organisms_without_observations():
    chunk = build_chunk("src", Evidence.MEASURED_ACTIVITY, "Gordonia", [
        Organism(key="1", species="Gordonia terrae", strain="DSM 1", collection_numbers=("DSM 1", "ATCC 2"),
                 observations=[Observation(enzyme="catalase", ec="1.11.1.6", result="+")]),
        Organism(key="2", species="Gordonia sputi"),
    ], queried=2)
    assert chunk.queried == 2 and len(chunk.organisms) == 1 and not chunk.is_empty
    org = chunk.organisms.iloc[0]
    assert (org.organism_id, org.genus, org.collection_numbers) == ("src:1", "Gordonia", "DSM 1; ATCC 2")
    assert chunk.observations.iloc[0].evidence == "measured_activity"
