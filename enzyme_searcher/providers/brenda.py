"""BRENDA adapter (optional): literature data for the EC numbers found by other providers.

Two backends:
  * JSON: the file downloaded from https://www.brenda-enzymes.org/download.php
    (set BRENDA_JSON to its path). No network needed.
  * SOAP: zeep client with BRENDA_USER (e-mail) and BRENDA_PASS from the environment
    (on molab, put them in the notebook's .env file).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Iterable, Iterator, Protocol

from ..http import with_retries
from ..model import Evidence, Observation, Organism, OrganismKind
from ..normalize import bare_genus
from .base import Provider, ProviderUnavailable, register

log = logging.getLogger(__name__)
WSDL = "https://www.brenda-enzymes.org/soap/brenda_zeep.wsdl"
MAX_SUBSTRATES = 5


class BrendaEntry(dict):
    """{'ec', 'organism', 'name', 'substrates', 'ph', 'temperature'} for one EC and organism."""


class BrendaBackend(Protocol):
    def entries(self, ec: str, genus: str) -> list[BrendaEntry]: ...


def matches_genus(organism: str, genus: str) -> bool:
    name, target = organism.lower().strip(), bare_genus(genus).lower()
    return name == target or name.startswith(target + " ") or name.startswith("candidatus " + target + " ")


class JsonBackend:
    def __init__(self, path: str):
        log.info("[brenda] loading %s", path)
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh).get("data", {})

    def entries(self, ec: str, genus: str) -> list[BrendaEntry]:
        record = self.data.get(ec)
        if not record:
            return []
        # id -> organism name, through 'organisms' and, when present, 'proteins'
        organisms = {k: (v.get("value") if isinstance(v, dict) else str(v))
                     for k, v in (record.get("organisms") or {}).items()}
        for pid, proteins in (record.get("proteins") or {}).items():
            for protein in proteins if isinstance(proteins, list) else [proteins]:
                if isinstance(protein, dict) and str(protein.get("organism")) in organisms:
                    organisms[str(pid)] = organisms[str(protein["organism"])]
        wanted = {k: v for k, v in organisms.items() if v and matches_genus(v, genus)}
        out = []
        for organism in sorted(set(wanted.values())):
            ids = {k for k, v in wanted.items() if v == organism}

            def values(field: str) -> list[str]:
                found = []
                for item in record.get(field) or []:
                    if not isinstance(item, dict):
                        continue
                    refs = {str(i) for i in (item.get("organisms") or []) + (item.get("proteins") or [])}
                    if refs & ids:
                        found.append(str(item.get("value", "")).strip())
                return found

            out.append(BrendaEntry(ec=ec, organism=organism, name=record.get("name", ""),
                                   substrates=values("substrates_products"), ph=values("ph_range"),
                                   temperature=values("temperature_range")))
        return out


class SoapBackend:
    """Parameters follow BRENDA's 'field*value' convention; signatures from its SOAP docs."""
    SIGNATURES = {
        "getOrganism": ["ecNumber", "organism", "sequenceCode", "commentary", "literature", "textmining"],
        "getRecommendedName": ["ecNumber", "recommendedName", "goNumber"],
        "getSubstrate": ["ecNumber", "substrate", "commentary", "organism", "ligandStructureId", "literature"],
        "getPhRange": ["ecNumber", "phRange", "phRangeMaximum", "commentary", "organism", "literature"],
        "getTemperatureRange": ["ecNumber", "temperatureRange", "temperatureRangeMaximum",
                                "commentary", "organism", "literature"],
    }

    def __init__(self, service: Any | None = None):
        self.email = os.environ.get("BRENDA_USER", "")
        password = os.environ.get("BRENDA_PASS", "")
        if service is None:
            if not (self.email and password):
                raise ProviderUnavailable("BRENDA needs BRENDA_USER and BRENDA_PASS (or BRENDA_JSON)")
            from zeep import Client, Settings
            service = Client(WSDL, settings=Settings(strict=False)).service
        self.service = service
        self.password = hashlib.sha256(password.encode()).hexdigest()  # BRENDA expects the SHA-256

    @with_retries(attempts=4, base_delay=2.0)
    def call(self, method: str, ec: str) -> list[dict]:
        args = [f"{field}*{ec if field == 'ecNumber' else ''}" for field in self.SIGNATURES[method]]
        result = getattr(self.service, method)(self.email, self.password, *args) or []
        try:
            from zeep.helpers import serialize_object
            result = serialize_object(result)
        except ImportError:
            pass
        return [dict(r) for r in result] if isinstance(result, list) else []

    def entries(self, ec: str, genus: str) -> list[BrendaEntry]:
        organisms = sorted({r.get("organism", "") for r in self.call("getOrganism", ec)
                            if matches_genus(r.get("organism", ""), genus)})
        if not organisms:
            return []
        name = next((r.get("recommendedName", "") for r in self.call("getRecommendedName", ec)), "")
        substrates, ph, temperature = (self.call(m, ec) for m in ("getSubstrate", "getPhRange", "getTemperatureRange"))

        def of(rows: list[dict], organism: str, field: str) -> list[str]:
            return [str(r.get(field, "")) for r in rows if r.get("organism") == organism]

        return [BrendaEntry(ec=ec, organism=o, name=name, substrates=of(substrates, o, "substrate"),
                            ph=of(ph, o, "phRange"), temperature=of(temperature, o, "temperatureRange"))
                for o in organisms]


def default_backend() -> BrendaBackend:
    path = os.environ.get("BRENDA_JSON")
    return JsonBackend(path) if path else SoapBackend()


@register
class BrendaProvider(Provider):
    name = "brenda"
    evidence = Evidence.LITERATURE
    description = "BRENDA: literature data (substrates, pH, temperature) for the EC numbers found"
    needs_ecs = True

    def __init__(self, max_organisms: int | None = None, backend: BrendaBackend | None = None):
        super().__init__(max_organisms)
        self._backend = backend

    @property
    def backend(self) -> BrendaBackend:
        if self._backend is None:
            self._backend = default_backend()
        return self._backend

    def fetch_raw(self, genus: str, ecs: Iterable[str] = ()) -> Iterator[dict]:
        """Yield one payload per organism, grouping its entries across EC numbers."""
        by_organism: dict[str, list[BrendaEntry]] = {}
        for ec in sorted(set(ecs)):
            try:
                for entry in self.backend.entries(ec, genus):
                    by_organism.setdefault(entry["organism"], []).append(entry)
            except ProviderUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 – one EC must not stop the rest
                log.error("[brenda] %s / %s failed: %s", genus, ec, exc)
        for organism, entries in by_organism.items():
            yield {"organism": organism, "entries": entries}

    def to_canonical(self, raw: dict, genus: str) -> Organism | None:
        observations = []
        for e in raw["entries"]:
            parts = []
            if substrates := sorted({s for s in e["substrates"] if s})[:MAX_SUBSTRATES]:
                parts.append("substrates: " + " | ".join(substrates))
            if ph := sorted({p for p in e["ph"] if p}):
                parts.append("pH: " + ", ".join(ph))
            if temperature := sorted({t for t in e["temperature"] if t}):
                parts.append("T(°C): " + ", ".join(temperature))
            observations.append(Observation(enzyme=e["name"], ec=e["ec"], result="+", method="literature",
                                            reference=f"BRENDA:{e['ec']}", detail="; ".join(parts)))
        return Organism(key=raw["organism"], species=raw["organism"], kind=OrganismKind.TAXON,
                        url=f"https://www.brenda-enzymes.org/enzyme.php?ecno={raw['entries'][0]['ec']}",
                        observations=observations)
