"""enzyme_searcher: enzymes of bacterial genera from BacDive, KEGG and BRENDA in one clean format.

    import enzyme_searcher as es
    result = es.fetch_all(["Gordonia"])                     # or pass a cached fetcher
    ds = es.Dataset.from_chunks(result.chunks, es.fetch_enzyme_names())
    ds.tidy()            # one row per organism × enzyme
    ds.genus_enzyme()    # positive / tested per genus × enzyme × evidence
    ds.genus_traits()    # MiDAS traits per genus (PAO, NOB, ...)
"""
from .dataset import Dataset
from .fetch import DiskCache, FetchResult, fetch_all, fetch_chunk
from .genera import flatten, load_genera, parse_genera
from .model import Chunk, Evidence, Observation, Organism, OrganismKind, Trait
from .providers import DEFAULT_PROVIDERS, Provider, available_providers, get_provider, register
from .reference import fetch_enzyme_names

__all__ = [
    "DEFAULT_PROVIDERS", "Chunk", "Dataset", "DiskCache", "Evidence", "FetchResult", "Observation",
    "Organism", "OrganismKind", "Provider", "available_providers", "fetch_all", "fetch_chunk",
    "fetch_enzyme_names", "flatten", "get_provider", "load_genera", "parse_genera", "register", "Trait",
]
