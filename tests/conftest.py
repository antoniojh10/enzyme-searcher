"""Test doubles built from recorded API responses (tests/fixtures)."""
import json
from pathlib import Path

import pytest

from enzyme_searcher.http import RateLimiter
from enzyme_searcher.providers.bacdive import BacDiveProvider
from enzyme_searcher.providers.kegg import KeggClient, KeggProvider
from enzyme_searcher.providers.midas import MidasClient, MidasProvider

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def recorded_strains() -> list[dict]:
    """Real BacDive V2 payloads: 156420 (G. terrae, with enzymes) and 10543 (no enzyme data)."""
    return json.loads(fixture_text("bacdive_fetch_156420_10543.json"))


def strain(bacdive_id, species, collection, enzymes):
    """A synthetic strain with the same shape as a real BacDive V2 entry."""
    return {
        "General": {"BacDive-ID": bacdive_id},
        "Name and taxonomic classification": {"species": species},
        "Physiology and metabolism": {"enzymes": [
            {"@ref": 1, "value": v, "activity": a, **({"ec": ec} if ec else {})} for v, a, ec in enzymes]},
        "Literature": {"@ref": 1, "culture collection no.": collection},
        "Reference": [{"@id": 1, "title": "API zym"}],
    }


class FakeBacDiveClient:
    """Mimics bacdive.BacdiveClient (search / retrieve / do_api_call, with pagination)."""

    def __init__(self, by_genus: dict[str, list[dict]], page_size: int = 2):
        self.by_genus = by_genus
        self.by_id = {str(s["General"]["BacDive-ID"]): s for strains in by_genus.values() for s in strains}
        self.page_size = page_size
        self.result: dict = {}
        self.calls: list[dict] = []

    def _page(self, genus, n):
        ids = [s["General"]["BacDive-ID"] for s in self.by_genus.get(genus, [])]
        nxt = f"taxon/{genus}?page={n + 1}" if (n + 1) * self.page_size < len(ids) else None
        return {"count": len(ids), "next": nxt, "results": ids[n * self.page_size:(n + 1) * self.page_size]}

    def search(self, **kw):
        self.calls.append(kw)
        if "taxonomy" in kw:
            self.result = self._page(kw["taxonomy"][0], 0)
            return self.result["count"]
        ids = kw["id"].split(";")
        self.result = {"count": len(ids), "next": None, "results": ids}
        return len(ids)

    def do_api_call(self, url):
        genus, page = url.split("taxon/")[1].split("?page=")
        return self._page(genus, int(page))

    def retrieve(self):
        for i in self.result["results"]:
            yield self.by_id[str(i)]


class Response:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeKeggSession:
    """Serves the recorded rest.kegg.jp responses; behaves like KEGG for unknown paths (400)."""

    ROUTES = {
        "find/genome/Gordonia": "kegg_find_genome_gordonia.txt",
        "find/genome/Nitrotoga": "kegg_find_genome_nitrotoga.txt",
        "find/genome/Nitrospira": "kegg_find_genome_nitrospira.txt",
        "link/enzyme/gbr": "kegg_link_enzyme_gbr.txt",
        "link/enzyme/gpo": "kegg_link_enzyme_gpo.txt",
        "list/enzyme": "kegg_list_enzyme_subset.txt",
    }

    def __init__(self, failures: int = 0):
        self.headers: dict = {}
        self.paths: list[str] = []
        self.failures = failures

    def get(self, url, timeout=None):
        path = url.split("rest.kegg.jp/")[1]
        self.paths.append(path)
        if self.failures:
            self.failures -= 1
            return Response(503)
        if path in self.ROUTES:
            return Response(200, fixture_text(self.ROUTES[path]))
        if path.startswith("link/enzyme/"):  # genomes without a recording: a small synthetic list
            return Response(200, f"{path[12:]}:1\tec:1.11.1.6\n{path[12:]}:2\tec:3.5.1.5\n")
        return Response(400)


class FakeMidasSession:
    """Serves recorded MiDAS /api/microbes responses; unknown names get MiDAS's HTTP 500."""

    def __init__(self):
        self.headers: dict = {}
        self.paths: list[str] = []

    def get(self, url, timeout=None):
        name = url.split("/api/microbes/")[1]
        self.paths.append(name)
        path = FIXTURES / f"midas_microbe_{name}.json"
        if not path.exists():
            return JsonResponse(500, {"message": "Microbe not found"})
        return JsonResponse(200, json.loads(path.read_text()))


class JsonResponse(Response):
    def __init__(self, status, payload):
        super().__init__(status, json.dumps(payload))
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture
def midas_session():
    return FakeMidasSession()


@pytest.fixture
def midas_client(midas_session):
    return MidasClient(session=midas_session, limiter=RateLimiter(1000, sleep=lambda s: None))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


@pytest.fixture
def kegg_session():
    return FakeKeggSession()


@pytest.fixture
def kegg_client(kegg_session):
    return KeggClient(session=kegg_session, limiter=RateLimiter(1000, sleep=lambda s: None))


@pytest.fixture
def bacdive_client():
    return FakeBacDiveClient({
        "Gordonia": recorded_strains() + [
            strain(1001, "Gordonia rubripertincta", "DSM 43197",
                   [("catalase", "+", "1.11.1.6"), ("urease", "-", "3.5.1.5"), ("Urease", "+", "3.5.1.5")])],
        "Nitrospira": [],
    })


@pytest.fixture
def providers(monkeypatch, bacdive_client, kegg_client, midas_client):
    """Make get_provider() build providers wired to the fakes (as fetch_chunk does)."""
    from enzyme_searcher.providers import base

    def fake_get_provider(name, **kwargs):
        if name == "bacdive":
            return BacDiveProvider(client_factory=lambda: bacdive_client, **kwargs)
        if name == "kegg":
            return KeggProvider(client=kegg_client, **kwargs)
        if name == "midas":
            return MidasProvider(client=midas_client, **kwargs)
        return base._REGISTRY[name](**kwargs)

    monkeypatch.setattr("enzyme_searcher.fetch.get_provider", fake_get_provider)
    return fake_get_provider
