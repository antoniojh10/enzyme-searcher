"""Run the marimo notebook end to end with the recorded fixtures instead of the real APIs."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import enzyme_searcher as es

NOTEBOOK = Path(__file__).resolve().parent.parent / "notebooks" / "explore.py"


class Control:
    """Stands in for a marimo UI element: only `.value` is read."""

    def __init__(self, value):
        self.value = value


def load_app():
    spec = importlib.util.spec_from_file_location("explore", NOTEBOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def test_notebook_passes_marimo_check():
    out = subprocess.run([sys.executable, "-m", "marimo", "check", str(NOTEBOOK)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_notebook_runs_end_to_end(providers, kegg_client):
    _, defs = load_app().run(defs={
        "genera_input": Control(["Gordonia", "Nitrospira", "Candidatus Microthrix"]),
        "providers_input": Control(["bacdive", "kegg", "midas"]),
        "limit_input": Control(2),
        "load_button": Control(True),
        "cached_chunk": lambda p, g, e, snapshot, limit: es.fetch_chunk(p, g, e, limit or None),
        "cached_enzyme_names": lambda snapshot: es.fetch_enzyme_names(kegg_client),
    })
    df, ds = defs["df"], defs["ds"]
    assert set(df["genus"]) == {"Gordonia", "Nitrospira"} and not defs["result"].errors
    assert "no bacdive data (Candidatus taxon)" in set(ds.provenance["notes"])
    assert len(defs["genus_enzyme"]) > 0
    traits = defs["traits"]
    assert {"Nitrospira", "Candidatus Microthrix"} <= set(traits["genus"]) and set(traits["context"]) == {"in situ"}
    producers = defs["producers"]
    assert len(producers) > 0 and set(producers["genus"]) <= {"Gordonia", "Nitrospira"}


def test_notebook_waits_for_the_button():
    _, defs = load_app().run()  # as opened: the button has not been pressed
    assert "load_button" in defs and "df" not in defs  # nothing is downloaded until the button is pressed


def _names(requirements):
    import re
    return {re.split(r"[<>=@\[ ;]", r, maxsplit=1)[0].strip().lower() for r in requirements}


def test_notebook_header_matches_package_dependencies():
    """The notebook loads enzyme_searcher from the repo, so its PEP 723 header must list the
    package's own dependencies (sandbox mode and molab install only what the header declares)."""
    import re
    import tomllib
    header = re.search(r"^# /// script\n(.*?)^# ///$", NOTEBOOK.read_text(), re.S | re.M).group(1)
    script = tomllib.loads("\n".join(line.removeprefix("# ").removeprefix("#") for line in header.splitlines()))
    project = tomllib.loads((NOTEBOOK.parent.parent / "pyproject.toml").read_text())["project"]
    declared = _names(script["dependencies"])
    assert _names(project["dependencies"]) <= declared
    assert not any("git+" in d for d in script["dependencies"])  # never fetch the package from GitHub
