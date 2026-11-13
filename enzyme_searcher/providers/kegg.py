"""KEGG adapter: EC numbers annotated in sequenced genomes (REST API, no key).

API notes (verified Nov 2026):
  * `find/genome/<genus>` returns full organism names *with strain*; `list/genome` only
    returns the species, so it is not used for names.
  * `link/enzyme/<org>` works; `link/ec/<org>` returns HTTP 400.
  * KEGG asks for at most 3 requests per second. Requests run 3 at a time under a shared
    rate limiter, because latency (~1.5 s), not the limit, is the bottleneck.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Iterator

import requests

from ..http import RateLimiter, with_retries
from ..model import Evidence, Observation, Organism, OrganismKind
from ..normalize import bare_genus, is_candidatus, normalize_ec, split_species_strain
from .base import Provider, register

log = logging.getLogger(__name__)
BASE_URL = "https://rest.kegg.jp"
PARALLEL_REQUESTS = 3


class KeggError(Exception):
    pass


class KeggClient:
    """Plain-text GET against rest.kegg.jp with rate limiting and retries."""

    def __init__(self, session: requests.Session | None = None, limiter: RateLimiter | None = None,
                 timeout: float = 60):
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "enzyme-searcher (python-requests)")
        self.limiter = limiter or RateLimiter(3)
        self.timeout = timeout

    @with_retries(attempts=5, base_delay=1.0, exceptions=(requests.RequestException, KeggError))
    def get(self, path: str) -> str:
        """Return the response body; '' for 400/404 (KEGG's answer to 'nothing found')."""
        self.limiter.wait()
        response = self.session.get(f"{BASE_URL}/{path}", timeout=self.timeout)
        if response.status_code in (400, 404):
            return ""
        if response.status_code == 429 or response.status_code >= 500:
            raise KeggError(f"HTTP {response.status_code} for {path}")
        response.raise_for_status()
        return response.text


def parse_genome_list(text: str) -> list[dict]:
    """'T01102\\tgbr; Gordonia bronchialis DSM 43247' -> {'tnum', 'code', 'name'}."""
    genomes = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or ";" not in parts[1]:
            continue
        code, name = (s.strip() for s in parts[1].split(";", 1))
        if code and name and " " not in code:
            genomes.append({"tnum": parts[0].strip(), "code": code, "name": name})
    return genomes


def belongs_to_genus(name: str, genus: str) -> bool:
    """True when the organism name starts with the genus (with or without 'Candidatus')."""
    name = name.lower().split(" (")[0] + " "
    target = bare_genus(genus).lower() + " "
    return name.startswith(target) or name.startswith("candidatus " + target)


def parse_enzyme_links(text: str) -> list[str]:
    """'gbr:Gbro_0002\\tec:2.7.7.7' lines -> sorted unique EC numbers."""
    ecs = {normalize_ec(line.split("\t")[1]) for line in text.splitlines() if "\t" in line}
    return sorted(ec for ec in ecs if ec)


def parse_enzyme_names(text: str) -> dict[str, str]:
    """'1.1.1.1\\talcohol dehydrogenase; ADH; ...' -> {'1.1.1.1': 'alcohol dehydrogenase'}."""
    names = {}
    for line in text.splitlines():
        if "\t" in line:
            ec, rest = line.split("\t", 1)
            ec = normalize_ec(ec)
            if ec:
                names[ec] = " ".join(rest.split(";")[0].lower().split())
    return names


@register
class KeggProvider(Provider):
    name = "kegg"
    evidence = Evidence.GENOME_ANNOTATION
    description = "KEGG: enzymes (EC) annotated in sequenced genomes"

    def __init__(self, max_organisms: int | None = None, client: KeggClient | None = None):
        super().__init__(max_organisms)
        self.client = client or KeggClient()

    def list_genomes(self, genus: str) -> list[dict]:
        found = parse_genome_list(self.client.get(f"find/genome/{bare_genus(genus)}"))
        genomes = [g for g in found if belongs_to_genus(g["name"], genus)]
        if is_candidatus(genus):  # 'Candidatus Nitrotoga' must not match plain 'Nitrotoga ...'
            genomes = [g for g in genomes if g["name"].lower().startswith("candidatus ")]
        return genomes[: self.max_organisms] if self.max_organisms else genomes

    def fetch_raw(self, genus: str, ecs: Iterable[str] = ()) -> Iterator[tuple[dict, list[str]]]:
        genomes = self.list_genomes(genus)
        log.info("[kegg] %s: %d genomes", genus, len(genomes))

        def download(genome: dict) -> tuple[dict, list[str]]:
            return genome, parse_enzyme_links(self.client.get(f"link/enzyme/{genome['code']}"))

        with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS, thread_name_prefix="kegg") as pool:
            yield from pool.map(download, genomes)

    def to_canonical(self, raw: tuple[dict, list[str]], genus: str) -> Organism | None:
        genome, ecs = raw
        species, strain = split_species_strain(genome["name"], genus)
        reference = f"KEGG:{genome['code']}"
        return Organism(
            key=genome["code"], species=species, strain=strain, kind=OrganismKind.GENOME,
            collection_numbers=(strain,) if strain else (),
            url=f"https://www.kegg.jp/entry/{genome['tnum']}",
            observations=[Observation(ec=ec, result="+", method="genome annotation", reference=reference)
                          for ec in ecs])
