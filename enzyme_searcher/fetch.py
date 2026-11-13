"""Fetch orchestration: which chunks to fetch, in which order, and with which cache.

The unit of work is a Chunk (one provider × one genus). `fetch_all` takes a `fetcher`
callable so the caller decides how chunks are cached:
  * in a marimo notebook, a function decorated with `mo.persistent_cache` (survives
    molab sessions);
  * from the command line, `DiskCache`.
A failed chunk raises inside the fetcher, so it is never cached and is retried next time.
"""
from __future__ import annotations

import hashlib
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .model import Chunk
from .providers import DEFAULT_PROVIDERS, available_providers, get_provider

log = logging.getLogger(__name__)


class Fetcher(Protocol):
    def __call__(self, provider: str, genus: str, ecs: tuple[str, ...]) -> Chunk: ...


def fetch_chunk(provider: str, genus: str, ecs: tuple[str, ...] = (), max_organisms: int | None = None) -> Chunk:
    """Fetch one chunk with a fresh provider instance (pure function of its arguments)."""
    return get_provider(provider, max_organisms=max_organisms).fetch(genus, ecs=ecs)


@dataclass
class FetchError:
    provider: str
    genus: str
    message: str


@dataclass
class FetchResult:
    chunks: list[Chunk] = field(default_factory=list)
    errors: list[FetchError] = field(default_factory=list)


ProgressCallback = Callable[[int, int, str, str], None]  # (done, total, provider, genus)


def fetch_all(genera: Iterable[str], providers: Iterable[str] = DEFAULT_PROVIDERS,
              fetcher: Fetcher | None = None, on_progress: ProgressCallback | None = None) -> FetchResult:
    """Fetch every (provider, genus) chunk. Providers that need EC numbers (BRENDA) run after
    the others for the same genus and receive the EC numbers those chunks found."""
    genera, providers = list(genera), list(providers)
    registry = available_providers()
    if unknown := [p for p in providers if p not in registry]:
        raise KeyError(f"unknown providers: {', '.join(unknown)}; available: {', '.join(sorted(registry))}")
    fetcher = fetcher or (lambda provider, genus, ecs: fetch_chunk(provider, genus, ecs))
    independent = [p for p in providers if not registry[p].needs_ecs]
    dependent = [p for p in providers if registry[p].needs_ecs]

    result, done, total = FetchResult(), 0, len(genera) * len(providers)
    for genus in genera:
        found: set[str] = set()
        for group, ecs in ((independent, ()), (dependent, None)):
            for provider in group:
                if ecs is None:
                    ecs = tuple(sorted(found))
                try:
                    chunk = fetcher(provider, genus, ecs)
                    result.chunks.append(chunk)
                    found |= {e for e in chunk.observations["ec"].dropna() if e}
                except Exception as exc:  # noqa: BLE001 – keep going with the other chunks
                    log.error("[%s] %s failed: %s", provider, genus, exc)
                    result.errors.append(FetchError(provider, genus, str(exc)))
                done += 1
                if on_progress:
                    on_progress(done, total, provider, genus)
    return result


class DiskCache:
    """Pickle-per-chunk cache for command-line use: <root>/<snapshot>/<provider>/<genus>-<ecs hash>.pkl"""

    def __init__(self, root: str | Path, snapshot: str = "default", max_organisms: int | None = None):
        self.root = Path(root) / snapshot
        self.max_organisms = max_organisms

    def path(self, provider: str, genus: str, ecs: tuple[str, ...]) -> Path:
        digest = hashlib.sha1(";".join(ecs).encode()).hexdigest()[:10] if ecs else "all"
        limit = f"-max{self.max_organisms}" if self.max_organisms else ""
        return self.root / provider / f"{genus.replace(' ', '_')}{limit}-{digest}.pkl"

    def __call__(self, provider: str, genus: str, ecs: tuple[str, ...]) -> Chunk:
        path = self.path(provider, genus, ecs)
        if path.exists():
            return pickle.loads(path.read_bytes())
        chunk = fetch_chunk(provider, genus, ecs, self.max_organisms)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(chunk))
        tmp.replace(path)  # atomic: an interruption never leaves a half-written chunk
        return chunk
