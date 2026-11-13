"""Provider interface (adapter pattern) and registry.

To add a data source, create a module in this package with a `Provider` subclass that
implements two methods and decorate it with `@register`:

    @register
    class MyProvider(Provider):
        name = "mysource"
        evidence = Evidence.MEASURED_ACTIVITY
        description = "What this source contributes"

        def fetch_raw(self, genus, ecs=()):      # talk to the API, yield raw payloads
            ...
        def to_canonical(self, raw, genus):      # adapter: raw payload -> Organism | None
            ...

Nothing else in the package (fetching, caching, dataset, notebook) needs to change.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Iterable

from ..model import Chunk, Evidence, Organism, build_chunk
from ..normalize import is_candidatus

log = logging.getLogger(__name__)


class ProviderUnavailable(RuntimeError):
    """The provider cannot run in this environment (e.g. missing credentials)."""


class Provider(ABC):
    name: ClassVar[str]
    evidence: ClassVar[Evidence]
    description: ClassVar[str] = ""
    # True when the provider enriches EC numbers found by the other providers (e.g. BRENDA).
    needs_ecs: ClassVar[bool] = False

    def __init__(self, max_organisms: int | None = None):
        self.max_organisms = max_organisms

    @abstractmethod
    def fetch_raw(self, genus: str, ecs: Iterable[str] = ()) -> Iterable[Any]:
        """Yield raw payloads for a genus, exactly as the API returns them."""

    @abstractmethod
    def to_canonical(self, raw: Any, genus: str) -> Organism | None:
        """Convert one raw payload into the canonical model (None to skip it)."""

    def fetch(self, genus: str, ecs: Iterable[str] = ()) -> Chunk:
        """Template method: fetch raw payloads, adapt them and pack a Chunk."""
        organisms, queried = [], 0
        for raw in self.fetch_raw(genus, ecs=ecs):
            queried += 1
            organism = self.to_canonical(raw, genus)
            if organism is not None:
                organisms.append(organism)
        chunk = build_chunk(self.name, self.evidence, genus, organisms, queried)
        if chunk.is_empty:
            note = f"no {self.name} data"
            if is_candidatus(genus):
                note += " (Candidatus taxon)"
            chunk.notes.append(note)
            log.info("[%s] %s: %s", self.name, genus, note)
        else:
            log.info("[%s] %s: %d organisms, %d observations (%d queried)", self.name, genus,
                     len(chunk.organisms), len(chunk.observations), queried)
        return chunk


_REGISTRY: dict[str, type[Provider]] = {}


def register(cls: type[Provider]) -> type[Provider]:
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"provider '{cls.name}' is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def available_providers() -> dict[str, type[Provider]]:
    return dict(_REGISTRY)


def get_provider(name: str, **kwargs: Any) -> Provider:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown provider '{name}'; available: {', '.join(sorted(_REGISTRY))}") from None
    return cls(**kwargs)
