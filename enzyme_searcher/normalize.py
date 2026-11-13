"""Normalization rules shared by every provider adapter."""
from __future__ import annotations

import re
from typing import Any

_EC_RE = re.compile(r"^\d+\.(\d+|-)\.(\d+|-)\.(n?\d+|-)$")
_POSITIVE = {"+", "positive", "pos", "yes", "1", "true"}
_NEGATIVE = {"-", "−", "negative", "neg", "no", "0", "false"}
RESULT_PRIORITY = {"+": 0, "-": 1, "NA": 2}


def normalize_genus(name: str) -> str:
    """'Ca. Microthrix' / 'candidatus  microthrix' -> 'Candidatus Microthrix'; 'gordonia' -> 'Gordonia'."""
    text = " ".join(name.strip().split())
    text = re.sub(r"^(ca\.|candidatus)\s*", "Candidatus ", text, flags=re.IGNORECASE).strip()
    words = text.split(" ")
    if words[0] == "Candidatus" and len(words) > 1:
        return "Candidatus " + words[1].capitalize()
    return words[0].capitalize()


def is_candidatus(genus: str) -> bool:
    return genus.startswith("Candidatus ")


def bare_genus(genus: str) -> str:
    """Genus name without the 'Candidatus' qualifier (what the APIs search by)."""
    return genus.removeprefix("Candidatus ")


def normalize_ec(value: Any) -> str:
    """'EC 3.2.1.21' / 'ec:3.2.1.21' -> '3.2.1.21'; anything that is not an EC number -> ''."""
    if value is None:
        return ""
    text = re.sub(r"^ec[:\s]*", "", str(value).strip().lower()).strip()
    return text if _EC_RE.match(text) else ""


def normalize_enzyme_name(name: Any) -> str:
    """Lower case, single spaces."""
    return " ".join(str(name).lower().split()) if name else ""


def normalize_result(value: Any) -> str:
    """Map provider-specific activity values to '+', '-' or 'NA'."""
    text = str(value).strip().lower() if value is not None else ""
    if text in _POSITIVE:
        return "+"
    if text in _NEGATIVE:
        return "-"
    return "NA"


def split_species_strain(full_name: str, genus: str) -> tuple[str, str]:
    """Split an organism name into species and strain.

    'Gordonia bronchialis DSM 43247'      -> ('Gordonia bronchialis', 'DSM 43247')
    'Gordonia sp. KTR9'                   -> ('Gordonia sp.', 'KTR9')
    'Candidatus Nitrospira inopinata'     -> ('Candidatus Nitrospira inopinata', '')
    'Nitrospira moscoviensis NSP M-1'     -> ('Nitrospira moscoviensis', 'NSP M-1')
    """
    name = full_name.split(" (")[0].strip()
    prefix = ""
    if name.startswith("Candidatus "):
        prefix, name = "Candidatus ", name.removeprefix("Candidatus ")
    words = name.split()
    n_genus = len(bare_genus(genus).split())
    species = prefix + " ".join(words[: n_genus + 1])
    return species, " ".join(words[n_genus + 1:])


def normalize_collection_number(value: str) -> str:
    """'DSM 43247' / 'dsm-43247' -> 'DSM43247' (used to match the same strain across providers)."""
    return re.sub(r"[\s\-_:]", "", value.upper())
