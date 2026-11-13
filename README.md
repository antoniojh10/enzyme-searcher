# enzyme-searcher

Enzymes and metabolic traits of bacterial genera (activated sludge focus) from several public
sources, converted into **one clean, provider-independent format** and explored in a
[marimo](https://marimo.io) notebook.

| Provider | Evidence | What it contributes |
|---|---|---|
| `bacdive` | `measured_activity` | Enzyme tests (API ZYM and others) on cultured strains — [BacDive](https://bacdive.dsmz.de) |
| `kegg` | `genome_annotation` | EC numbers annotated in sequenced genomes — [KEGG](https://www.kegg.jp) (academic use only) |
| `midas` | `expert_curation` | Curated genus-level traits (PAO, NOB, fermentation, filamentous…), incl. *Candidatus* genera — [MiDAS field guide](https://www.midasfieldguide.org) (CC BY-SA 4.0) |
| `brenda` | `literature` | Optional: substrates, pH and temperature for the EC numbers found — [BRENDA](https://www.brenda-enzymes.org) (needs an account or the downloaded JSON) |

## Use it in molab (no installation)

1. Open `notebooks/explore.py` from this GitHub repo in [molab](https://molab.marimo.io)
   (new notebook → paste the GitHub URL of the file).
2. Press **Cargar / descargar datos**. The first time it downloads everything (~10 min for the 36
   genera); each provider × genus is stored with `mo.persistent_cache`, which molab keeps between
   sessions, so later loads take seconds. If a session stops halfway, pressing again resumes.
3. Work with `df`, `genus_enzyme`, `traits` and `ds` in the last cells.

To refresh the data, change `SNAPSHOT` in the notebook (e.g. to the current month) and press the button.
For BRENDA, add `BRENDA_USER`/`BRENDA_PASS` (or `BRENDA_JSON`) to the notebook's `.env` and select the source.

## Run locally

The notebook loads `enzyme_searcher` from this repository (no install from GitHub), so any of these work:

```bash
uv sync
uv run marimo edit notebooks/explore.py          # project environment
uvx marimo edit --sandbox notebooks/explore.py   # isolated env built from the notebook header
uv run marimo run notebooks/explore.py           # app view, code hidden
```

If cells show as stale (yellow) when the notebook opens, press **Run all** (bottom right):
that happens when marimo's `runtime.auto_instantiate` setting is `false`.

```bash
uv run python -m enzyme_searcher providers       # list providers
uv run python -m enzyme_searcher fetch --genus Gordonia --excel gordonia.xlsx
uv run pytest -q
```

## Data model

Every provider adapter turns its raw API payloads into the same canonical objects
(`enzyme_searcher/model.py`):

- **organisms** — `organism_id` (`bacdive:156420`, `kegg:gbr`, `midas:tetrasphaera`), `provider`,
  `genus`, `species`, `strain`, `kind` (`strain`, `genome`, `mag`, `taxon`), `collection_numbers`
  (all culture-collection ids, to match the same strain across providers), `url`.
- **observations** — one per organism × enzyme: `ec` (main key), `enzyme`, `result` (`+`, `-`, `NA`),
  `evidence`, `method`, `reference`, `detail`.
- **traits** — qualitative properties: `trait`, `category`, `context` (`in situ`, `other`),
  `value` (`+`, `-`, `variable`, `NA`), `reference`.

Normalization (in one place, for every provider): genus names (`Ca.` → `Candidatus`), EC numbers,
lower-case enzyme names with one canonical name per EC (KEGG ENZYME), results, and de-duplication
per organism (`+` wins over `-`, `-` over `NA`).

`Dataset` (`enzyme_searcher/dataset.py`) is what the researcher uses:
`tidy()`, `genus_enzyme()` (positive / tested per genus × enzyme × evidence), `genus_traits()`,
`matrix()`, `summary()`, `filter()`, `to_excel()`.

## Adding a provider

Create `enzyme_searcher/providers/<name>.py`, import it in `providers/__init__.py`, done:

```python
from ..model import Evidence, Observation, Organism, Trait
from .base import Provider, register

@register
class MySource(Provider):
    name = "mysource"
    evidence = Evidence.MEASURED_ACTIVITY
    description = "What it contributes"

    def fetch_raw(self, genus, ecs=()):          # talk to the API; yield raw payloads
        ...

    def to_canonical(self, raw, genus):          # adapter: raw payload -> Organism | None
        return Organism(key=..., species=..., observations=[Observation(ec=..., result=...)])
```

Fetching, caching, the dataset, the Excel export and the notebook pick it up automatically.
Add a test with a recorded response in `tests/fixtures/` (see `tests/test_midas.py`).

## Project layout

```
enzyme_searcher/
  model.py  normalize.py  http.py  genera.py  genera.txt (default genus list)
  providers/  base.py (interface + registry)  bacdive.py  kegg.py  midas.py  brenda.py
  fetch.py      fetch_all(): order, progress, errors; DiskCache for CLI use
  dataset.py    Dataset: the researcher-facing tables
  reference.py  canonical enzyme names
notebooks/explore.py   marimo notebook
tests/                 pytest with recorded API responses (no network)
```

## API notes (verified Nov 2026)

- BacDive API V2 is public; the `bacdive` package ≥ 2.0 needs no account.
- KEGG: `find/genome/<genus>` returns names with strain (`list/genome` does not); `link/enzyme/<org>`
  works, `link/ec/<org>` returns 400. Max 3 requests/s; requests run 3 at a time.
- MiDAS: data comes from the site's undocumented JSON API (`/api/microbes/<name>`, *Candidatus* as
  `Ca_<Genus>`); it may change without notice.
- molab keeps only `mo.persistent_cache` data (plus code, uploads and `.env`) between sessions.

## Licenses of the data

KEGG data is for academic use. MiDAS data is CC BY-SA 4.0: credit MiDAS and share derived data
under the same license. Cite BacDive and BRENDA as their sites request.
