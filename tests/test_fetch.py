import enzyme_searcher as es
from enzyme_searcher.fetch import DiskCache
from enzyme_searcher.model import build_chunk


def test_order_and_ecs_passed_to_dependent_providers(providers):
    seen = []

    def fetcher(provider, genus, ecs):
        seen.append((provider, genus, len(ecs)))
        if provider == "brenda":  # BRENDA needs credentials; return an empty chunk instead
            return build_chunk("brenda", es.Evidence.LITERATURE, genus, [], queried=0)
        return es.fetch_chunk(provider, genus, ecs)

    progress = []
    result = es.fetch_all(["Gordonia"], ["brenda", "kegg", "bacdive"], fetcher=fetcher,
                          on_progress=lambda d, t, p, g: progress.append((d, t, p)))
    assert [s[0] for s in seen] == ["kegg", "bacdive", "brenda"]
    assert seen[2][2] > 500  # BRENDA receives every EC found for the genus
    assert progress[-1] == (3, 3, "brenda") and not result.errors


def test_errors_are_collected_not_raised(providers):
    def fetcher(provider, genus, ecs):
        if genus == "Gordonia" and provider == "bacdive":
            raise ConnectionError("down")
        return es.fetch_chunk(provider, genus, ecs)

    result = es.fetch_all(["Gordonia", "Nitrospira"], ["bacdive", "kegg"], fetcher=fetcher)
    assert [(e.provider, e.genus, e.message) for e in result.errors] == [("bacdive", "Gordonia", "down")]
    assert len(result.chunks) == 3


def test_disk_cache_reuses_chunks(tmp_path, providers, kegg_session):
    cache = DiskCache(tmp_path, snapshot="s1", max_organisms=2)
    first = es.fetch_all(["Gordonia"], ["kegg"], fetcher=cache)
    calls = len(kegg_session.paths)
    second = es.fetch_all(["Gordonia"], ["kegg"], fetcher=cache)
    assert len(kegg_session.paths) == calls
    assert second.chunks[0].observations.equals(first.chunks[0].observations)
    es.fetch_all(["Gordonia"], ["kegg"], fetcher=DiskCache(tmp_path, snapshot="s2", max_organisms=2))
    assert len(kegg_session.paths) > calls  # a new snapshot fetches again
