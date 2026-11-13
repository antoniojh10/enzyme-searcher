"""Genus list: one genus per line, '# Group' lines define groups."""
from __future__ import annotations

from pathlib import Path

from .normalize import normalize_genus

DEFAULT_GENERA_FILE = Path(__file__).resolve().parent / "genera.txt"


def parse_genera(text: str) -> dict[str, list[str]]:
    """Return {group: [genus, ...]} preserving order. 'Ca.' is expanded to 'Candidatus'.

    A comment line is a group header when it is short and does not end with a period;
    genera listed before the first header go to 'Other'.
    """
    groups: dict[str, list[str]] = {}
    current, seen = "Other", set()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if title and len(title) <= 60 and not title.endswith("."):
                current = title
            continue
        if not line:
            continue
        genus = normalize_genus(line)
        if genus not in seen:
            seen.add(genus)
            groups.setdefault(current, []).append(genus)
    return groups


def load_genera(path: str | Path = DEFAULT_GENERA_FILE) -> dict[str, list[str]]:
    return parse_genera(Path(path).read_text(encoding="utf-8"))


def flatten(groups: dict[str, list[str]]) -> list[str]:
    return [g for genera in groups.values() for g in genera]
