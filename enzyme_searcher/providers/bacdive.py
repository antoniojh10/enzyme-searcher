"""BacDive adapter: enzyme activity measured on cultured strains.

Uses the official `bacdive` package (API V2, public since Feb 2026: no account needed).
If BACDIVE_USER / BACDIVE_PASS are set they are passed through for older package versions.
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
from typing import Any, Callable, Iterable, Iterator

from ..http import with_retries
from ..model import Evidence, Observation, Organism, OrganismKind
from ..normalize import bare_genus
from .base import Provider, register

log = logging.getLogger(__name__)
BATCH_SIZE = 100  # ids per fetch/ request (API maximum)


def default_client() -> Any:
    import bacdive

    user, password = os.environ.get("BACDIVE_USER"), os.environ.get("BACDIVE_PASS")
    return bacdive.BacdiveClient(user, password) if user and password else bacdive.BacdiveClient()


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _quiet(fn: Callable, *args, **kwargs):
    """The bacdive client prints to stdout ('Your search did not receive any results.')."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


@register
class BacDiveProvider(Provider):
    name = "bacdive"
    evidence = Evidence.MEASURED_ACTIVITY
    description = "BacDive: enzyme tests (API ZYM and others) measured on cultured strains"

    def __init__(self, max_organisms: int | None = None, client_factory: Callable[[], Any] = default_client):
        super().__init__(max_organisms)
        self._client_factory = client_factory
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    # ------------------------------------------------------------------ raw fetching
    @with_retries(attempts=4, base_delay=2.0)
    def list_ids(self, genus: str) -> list[str]:
        client = self.client
        # A one-element list keeps the client from splitting 'Candidatus X' into two ranks.
        if not _quiet(client.search, taxonomy=[bare_genus(genus)]):
            return []
        ids = list(client.result.get("results", []))
        while client.result.get("next") and (self.max_organisms is None or len(ids) < self.max_organisms):
            client.result = client.do_api_call(client.result["next"])
            ids.extend(client.result.get("results", []))
        ids = [str(i) for i in ids]
        return ids[: self.max_organisms] if self.max_organisms else ids

    @with_retries(attempts=4, base_delay=2.0)
    def fetch_batch(self, ids: list[str]) -> list[dict]:
        client = self.client
        _quiet(client.search, id=";".join(ids))
        return [entry for entry in client.retrieve() if isinstance(entry, dict)]

    def fetch_raw(self, genus: str, ecs: Iterable[str] = ()) -> Iterator[dict]:
        ids = self.list_ids(genus)
        log.info("[bacdive] %s: %d strains", genus, len(ids))
        for start in range(0, len(ids), BATCH_SIZE):
            yield from self.fetch_batch(ids[start:start + BATCH_SIZE])

    # ------------------------------------------------------------------- adapter
    def to_canonical(self, raw: dict, genus: str) -> Organism | None:
        general = raw.get("General") or {}
        bacdive_id = str(general.get("BacDive-ID", ""))
        taxonomy = raw.get("Name and taxonomic classification") or {}
        species = taxonomy.get("species") or (taxonomy.get("LPSN") or {}).get("species") or ""
        physiology = raw.get("Physiology and metabolism")
        enzymes = _as_list(physiology.get("enzymes")) if isinstance(physiology, dict) else []
        if not bacdive_id or not enzymes:
            return None

        references = {str(r.get("@id")): r for r in _as_list(raw.get("Reference")) if isinstance(r, dict)}
        collections = self._collection_numbers(raw)
        strain = (collections[0] if collections
                  else str(taxonomy.get("strain designation") or "").split(",")[0].strip()
                  or f"BacDive {bacdive_id}")
        observations = []
        for enzyme in enzymes:
            if not isinstance(enzyme, dict) or not enzyme.get("value"):
                continue
            ref = references.get(str(enzyme.get("@ref")), {})
            observations.append(Observation(
                enzyme=enzyme["value"], ec=enzyme.get("ec", ""), result=enzyme.get("activity"),
                method=enzyme.get("method") or ref.get("title") or ref.get("catalogue") or "",
                reference=f"BacDive:{bacdive_id}"))
        return Organism(key=bacdive_id, species=species, strain=strain, kind=OrganismKind.STRAIN,
                        collection_numbers=tuple(collections),
                        url=f"https://bacdive.dsmz.de/strain/{bacdive_id}", observations=observations)

    @staticmethod
    def _collection_numbers(raw: dict) -> list[str]:
        numbers: list[str] = []
        for section in _as_list(raw.get("Literature")) + _as_list(raw.get("External links")):
            if isinstance(section, dict) and section.get("culture collection no."):
                numbers += [n.strip() for n in str(section["culture collection no."]).split(",") if n.strip()]
        dsm = (raw.get("General") or {}).get("DSM-Number")
        if dsm and f"DSM {dsm}" not in numbers:
            numbers.append(f"DSM {dsm}")
        return list(dict.fromkeys(numbers))
