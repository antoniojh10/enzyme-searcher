"""Reference data shared by all providers: canonical enzyme names by EC number."""
from __future__ import annotations

import pandas as pd

from .providers.kegg import KeggClient, parse_enzyme_names


def fetch_enzyme_names(client: KeggClient | None = None) -> pd.DataFrame:
    """Canonical EC -> name table from the KEGG ENZYME list (one request, ~1 MB)."""
    names = parse_enzyme_names((client or KeggClient()).get("list/enzyme"))
    return pd.DataFrame(sorted(names.items()), columns=["ec", "name"]).astype("string")
