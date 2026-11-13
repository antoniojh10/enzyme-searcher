"""Command line, for use outside the notebook.

    uv run python -m enzyme_searcher providers
    uv run python -m enzyme_searcher fetch --genus Gordonia --excel gordonia.xlsx
    uv run python -m enzyme_searcher fetch --providers bacdive,kegg --max-organisms 20
"""
from __future__ import annotations

import argparse
import logging
import pickle
import sys
from datetime import date
from pathlib import Path

from .dataset import Dataset
from .fetch import DiskCache, fetch_all
from .genera import flatten, load_genera
from .normalize import normalize_genus
from .providers import DEFAULT_PROVIDERS, available_providers
from .reference import fetch_enzyme_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="enzyme_searcher", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("providers", help="list available providers")
    f = sub.add_parser("fetch", help="fetch data and print a summary")
    f.add_argument("--genus", action="append", help="genus to fetch (repeatable; default: all in genera.txt)")
    f.add_argument("--genera-file", help="genus list (default: the packaged genera.txt)")
    f.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS))
    f.add_argument("--max-organisms", type=int, help="limit strains/genomes per genus (quick tests)")
    f.add_argument("--cache", default=".es-cache", help="cache directory (default .es-cache)")
    f.add_argument("--snapshot", default=date.today().strftime("%Y-%m"),
                   help="cache label; a new label fetches everything again (default: current month)")
    f.add_argument("--excel", help="write the dataset to this .xlsx file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if args.command == "providers":
        for name, cls in available_providers().items():
            print(f"{name:10s} {cls.evidence:18s} {cls.description}")
        return 0

    groups = load_genera(args.genera_file) if args.genera_file else load_genera()
    genera = [normalize_genus(g) for g in args.genus] if args.genus else flatten(groups)
    cache = DiskCache(args.cache, args.snapshot, args.max_organisms)
    result = fetch_all(genera, args.providers.split(","), fetcher=cache,
                       on_progress=lambda d, t, p, g: logging.info("%d/%d done (%s, %s)", d, t, p, g))
    names_path = Path(args.cache) / args.snapshot / "enzyme_names.pkl"
    if names_path.exists():
        names = pickle.loads(names_path.read_bytes())
    else:
        names = fetch_enzyme_names()
        names_path.parent.mkdir(parents=True, exist_ok=True)
        names_path.write_bytes(pickle.dumps(names))
    ds = Dataset.from_chunks(result.chunks, names)
    print(ds.summary().to_string(index=False))
    for err in result.errors:
        print(f"ERROR {err.provider} / {err.genus}: {err.message}", file=sys.stderr)
    if args.excel:
        for note in ds.to_excel(args.excel):
            print("note:", note)
        print(f"written {args.excel}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
