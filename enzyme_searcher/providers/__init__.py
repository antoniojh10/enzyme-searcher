"""Provider adapters. Importing this package registers every built-in provider."""
from .base import Provider, ProviderUnavailable, available_providers, get_provider, register
from . import bacdive, brenda, kegg, midas  # noqa: F401  (registration side effect)

DEFAULT_PROVIDERS = ("bacdive", "kegg", "midas")

__all__ = ["DEFAULT_PROVIDERS", "Provider", "ProviderUnavailable", "available_providers",
           "get_provider", "register"]
