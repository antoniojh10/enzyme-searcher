"""MiDAS adapter: curated metabolic traits of activated sludge genera.

Source: MiDAS field guide (https://www.midasfieldguide.org), licensed CC BY-SA 4.0. Data
derived from it must credit MiDAS and be shared under the same license.

The site loads its data from an undocumented JSON API (`/api/microbes/<name>`), which is
what this adapter reads; it may change without notice. Candidatus genera are named
'Ca_<Genus>' there. MiDAS gives genus-level traits (PAO, NOB, fermentation, ...), not EC
numbers, so it contributes `Trait`s rather than enzyme observations.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

import requests

from ..http import RateLimiter, with_retries
from ..model import Evidence, Organism, OrganismKind, Trait
from ..normalize import bare_genus, is_candidatus
from .base import Provider, register

log = logging.getLogger(__name__)
BASE_URL = "https://www.midasfieldguide.org"
CATEGORIES = {"metabolism": "metabolism", "properties": "property"}


class MidasClient:
    def __init__(self, session: requests.Session | None = None, limiter: RateLimiter | None = None,
                 timeout: float = 60):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "enzyme-searcher (python-requests)")
        self.limiter = limiter or RateLimiter(2)
        self.timeout = timeout

    @with_retries(attempts=4, base_delay=2.0, exceptions=(requests.RequestException,))
    def microbe(self, name: str) -> dict | None:
        """The genus record, or None when MiDAS does not know the name (it answers HTTP 500)."""
        self.limiter.wait()
        response = self.session.get(f"{BASE_URL}/api/microbes/{name}", timeout=self.timeout)
        if response.status_code in (404, 500):
            return None
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) and data.get("name") else None


def midas_name(genus: str) -> str:
    return f"Ca_{bare_genus(genus)}" if is_candidatus(genus) else genus


def _references(entry: dict) -> str:
    dois = [c.get("doi") or f"PMID:{c.get('pmID')}" for c in entry.get("pubMedCitations") or [] if isinstance(c, dict)]
    urls = [c.get("url", "") for c in entry.get("urlCitations") or [] if isinstance(c, dict)]
    return "; ".join(dict.fromkeys(r for r in dois + urls if r and r != "PMID:None"))


@register
class MidasProvider(Provider):
    name = "midas"
    evidence = Evidence.EXPERT_CURATION
    description = "MiDAS field guide: curated metabolic traits of activated sludge genera (CC BY-SA 4.0)"

    def __init__(self, max_organisms: int | None = None, client: MidasClient | None = None):
        super().__init__(max_organisms)
        self.client = client or MidasClient()

    def fetch_raw(self, genus: str, ecs: Iterable[str] = ()) -> Iterator[dict]:
        record = self.client.microbe(midas_name(genus))
        if record is not None:
            yield record

    def to_canonical(self, raw: dict[str, Any], genus: str) -> Organism | None:
        traits = []
        for section, category in CATEGORIES.items():
            for trait, contexts in (raw.get(section) or {}).items():
                for context, entry in (contexts or {}).items():
                    if isinstance(entry, dict):
                        traits.append(Trait(name=trait, value=entry.get("value"), category=category,
                                            context=context.lower(), reference=_references(entry)))
        url_name = raw.get("name", midas_name(genus)).replace(" ", "_")
        return Organism(key=raw.get("urlSafeName") or url_name, species=genus, kind=OrganismKind.TAXON,
                        url=f"{BASE_URL}/guide/fieldguide/genus/{url_name}", traits=traits)
