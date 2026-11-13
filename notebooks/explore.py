# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo>=0.25",
#     "altair>=5.4",
#     "pandas>=2.1",
#     "xlsxwriter>=3.1",
#     "bacdive>=2.0",
#     "requests>=2.31",
#     "enzyme-searcher @ git+https://github.com/antoniojh10/enzyme-searcher",
# ]
# ///
# On molab (and with `marimo edit --sandbox`) enzyme_searcher is installed from GitHub.
# When the notebook sits inside a clone of the repository, the first cell imports that local
# copy instead, so local edits are used without pushing them.
# Keep these dependencies in sync with pyproject.toml (tests/test_notebook.py checks it).

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Enzimas por género")


@app.cell
def _():
    import io
    import sys
    from pathlib import Path

    import altair as alt
    import marimo as mo
    import pandas as pd

    # 1. Inside a clone of the repository: import the local copy (local edits win).
    _repo = (mo.notebook_dir() or Path.cwd()).resolve().parent
    if (_repo / "enzyme_searcher" / "__init__.py").exists() and str(_repo) not in sys.path:
        sys.path.insert(0, str(_repo))
    # 2. Otherwise (molab, a copied notebook): use the installed package, installing it from
    #    GitHub if needed. It is not on PyPI, so marimo's automatic installer cannot find it.
    try:
        import enzyme_searcher as es
    except ModuleNotFoundError:
        import importlib
        import shutil
        import subprocess

        _source = "git+https://github.com/antoniojh10/enzyme-searcher"
        _uv = shutil.which("uv")
        _cmd = ([_uv, "pip", "install", "--python", sys.executable, _source] if _uv
                else [sys.executable, "-m", "pip", "install", _source])
        subprocess.run(_cmd, check=True, capture_output=True)
        importlib.invalidate_caches()
        import enzyme_searcher as es
    return alt, es, io, mo, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Enzimas por género bacteriano

    Reúne, en un único formato, la actividad enzimática **medida en cepas** (BacDive), las enzimas
    **anotadas en genomas** (KEGG), los **rasgos metabólicos** curados de fangos activados (MiDAS) y,
    opcionalmente, datos de **literatura** (BRENDA).

    1. Elige géneros y fuentes y pulsa **Cargar / descargar datos**. La primera vez descarga desde las
       APIs (todos los géneros: ~10 min); después lo lee de la caché del notebook al instante.
    2. Explora el resumen y las gráficas, o trabaja directamente con `df` (una fila por organismo × enzima).
    """)
    return


@app.cell
def _():
    # Data version. Cached data is reused while this label stays the same; change it
    # (e.g. to the current month) to download everything again.
    SNAPSHOT = "2026-11"
    return (SNAPSHOT,)


@app.cell
def _(es, mo):
    @mo.persistent_cache
    def cached_chunk(provider: str, genus: str, ecs: tuple, snapshot: str, max_organisms: int):
        """One provider × one genus. Persisted by marimo (also on molab), so it is fetched once."""
        return es.fetch_chunk(provider, genus, ecs, max_organisms or None)

    @mo.persistent_cache
    def cached_enzyme_names(snapshot: str):
        return es.fetch_enzyme_names()
    return cached_chunk, cached_enzyme_names


@app.cell(hide_code=True)
def _(es, mo):
    _all_genera = es.flatten(es.load_genera())
    genera_input = mo.ui.multiselect(options=_all_genera, value=_all_genera, label="Géneros", full_width=True)
    providers_input = mo.ui.multiselect(options=list(es.available_providers()), value=list(es.DEFAULT_PROVIDERS),
                                        label="Fuentes")
    limit_input = mo.ui.number(start=0, stop=100_000, step=1, value=0,
                               label="Máx. cepas/genomas por género (0 = sin límite; útil para pruebas)")
    load_button = mo.ui.run_button(label="Cargar / descargar datos", kind="success")
    mo.vstack([genera_input, mo.hstack([providers_input, limit_input], justify="start", gap=2), load_button])
    return genera_input, limit_input, load_button, providers_input


@app.cell(hide_code=True)
def _(SNAPSHOT, cached_chunk, cached_enzyme_names, es, genera_input, limit_input, load_button, mo,
      providers_input):
    mo.stop(not load_button.value, mo.md("Pulsa **Cargar / descargar datos** para empezar."))
    _total = len(genera_input.value) * len(providers_input.value)
    with mo.status.progress_bar(total=_total, title="Cargando datos",
                                subtitle="Lo ya descargado sale de la caché", remove_on_exit=True) as _bar:
        result = es.fetch_all(
            genera_input.value, providers_input.value,
            fetcher=lambda p, g, e: cached_chunk(p, g, e, SNAPSHOT, int(limit_input.value or 0)),
            on_progress=lambda done, total, p, g: _bar.update(subtitle=f"{p} · {g}"))
    ds = es.Dataset.from_chunks(result.chunks, cached_enzyme_names(SNAPSHOT))
    df = ds.tidy()
    return df, ds, result


@app.cell(hide_code=True)
def _(mo, result):
    mo.stop(not result.errors)
    mo.callout(mo.md("**Algunas descargas fallaron** (no se guardaron en caché; vuelve a pulsar el botón "
                     "para reintentarlas):\n\n" + "\n".join(f"- `{e.provider}` · {e.genus}: {e.message}"
                                                          for e in result.errors)), kind="warn")
    return


@app.cell(hide_code=True)
def _(SNAPSHOT, df, ds, mo):
    _fetched = ds.provenance["fetched_at"]
    mo.vstack([
        mo.md(f"## Resumen\n\nVersión de datos **{SNAPSHOT}** · descargados entre {_fetched.min()} y "
              f"{_fetched.max()} · {len(df):,} observaciones de {len(ds.organisms):,} organismos."),
        mo.ui.table(ds.summary(), page_size=10, selection=None),
    ])
    return


@app.cell(hide_code=True)
def _(io, mo, ds):
    def _excel() -> bytes:
        buffer = io.BytesIO()
        ds.to_excel(buffer)
        return buffer.getvalue()

    mo.download(data=_excel, filename="enzimas_por_genero.xlsx", label="Descargar Excel (todo)",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Mapa de calor género × enzima

    Fracción de organismos positivos: cepas positivas / cepas probadas (BacDive) o genomas con la enzima
    anotada / genomas del género (KEGG). Se muestran las enzimas presentes en más géneros.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    evidence_input = mo.ui.dropdown(
        options={"Actividad medida (BacDive)": "measured_activity", "Anotación genómica (KEGG)": "genome_annotation"},
        value="Actividad medida (BacDive)", label="Evidencia")
    top_input = mo.ui.slider(start=10, stop=80, step=5, value=30, label="Nº de enzimas", show_value=True)
    mo.hstack([evidence_input, top_input], justify="start", gap=2)
    return evidence_input, top_input


@app.cell(hide_code=True)
def _(alt, ds, evidence_input, mo, top_input):
    genus_enzyme = ds.genus_enzyme()
    _ge = genus_enzyme[(genus_enzyme["evidence"] == evidence_input.value) & (genus_enzyme["n_tested"] > 0)].copy()
    _top = (_ge[_ge["n_positive"] > 0].groupby("enzyme")["genus"].nunique()
            .sort_values(ascending=False).head(top_input.value).index)
    _ge = _ge[_ge["enzyme"].isin(_top)].astype({"genus": str, "enzyme": str})
    _ge["label"] = _ge["enzyme"] + _ge["ec"].map(lambda ec: f" ({ec})" if ec else "")
    heatmap = (
        alt.Chart(_ge).mark_rect().encode(
            x=alt.X("genus:N", title="Género", sort="ascending", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("label:N", title=None, sort=alt.EncodingSortField("n_positive", op="sum", order="descending")),
            color=alt.Color("fraction_positive:Q", title="Fracción +", scale=alt.Scale(scheme="viridis", domain=[0, 1])),
            tooltip=["genus", "enzyme", "ec", "n_positive", "n_tested", alt.Tooltip("fraction_positive", format=".0%")],
        ).properties(width="container", height=max(200, 16 * len(_top)))
    )
    mo.ui.altair_chart(heatmap) if len(_ge) else mo.md("_No hay datos para esta evidencia._")
    return (genus_enzyme,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Rasgos metabólicos (MiDAS)

    Conocimiento curado por género del [MiDAS field guide](https://www.midasfieldguide.org)
    (licencia CC BY-SA 4.0: citar MiDAS y compartir derivados con la misma licencia). Cubre también
    géneros *Candidatus* sin cepas cultivadas. *In situ*: evidencia en plantas reales; *Other*: cultivos,
    genomas u otros sistemas.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    context_input = mo.ui.dropdown(options={"In situ": "in situ", "Otra evidencia": "other"},
                                   value="In situ", label="Contexto")
    context_input
    return (context_input,)


@app.cell(hide_code=True)
def _(alt, context_input, ds, mo):
    traits = ds.genus_traits(context=context_input.value)
    _labels = {"+": "Positivo", "-": "Negativo", "variable": "Variable", "NA": "No evaluado"}
    _t = traits.assign(valor=traits["value"].map(_labels))
    _chart = (
        alt.Chart(_t).mark_rect(stroke="white").encode(
            x=alt.X("trait:N", title=None, axis=alt.Axis(labelAngle=-40)),
            y=alt.Y("genus:N", title="Género"),
            color=alt.Color("valor:N", title="Valor", scale=alt.Scale(
                domain=["Positivo", "Variable", "Negativo", "No evaluado"],
                range=["#1a9850", "#fdae61", "#d73027", "#e0e0e0"])),
            tooltip=["genus", "trait", "valor", "category", "reference"],
        ).properties(width="container", height=max(150, 18 * _t["genus"].nunique()))
    )
    mo.ui.altair_chart(_chart) if len(_t) else mo.md("_Sin datos de MiDAS: añade la fuente `midas` y vuelve a cargar._")
    return (traits,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## ¿Qué microorganismos producen una enzima?

    Elige una enzima para ver, por género, cuántos organismos la tienen y cuáles son.
    """)
    return


@app.cell(hide_code=True)
def _(df, mo):
    _counts = df[df["result"] == "+"].groupby("enzyme", observed=True)["genus"].nunique()
    _options = sorted(_counts.index.astype(str), key=lambda e: (-_counts[e], e))
    enzyme_input = mo.ui.dropdown(options=_options, value=_options[0] if _options else None,
                                  searchable=True, label="Enzima")
    enzyme_input
    return (enzyme_input,)


@app.cell(hide_code=True)
def _(alt, enzyme_input, genus_enzyme, mo):
    mo.stop(enzyme_input.value is None)
    _sel = genus_enzyme[(genus_enzyme["enzyme"] == enzyme_input.value) & (genus_enzyme["n_tested"] > 0)]
    _sel = _sel.astype({"genus": str, "evidence": str})
    bars = (
        alt.Chart(_sel).mark_bar().encode(
            y=alt.Y("genus:N", title="Género", sort="-x"),
            x=alt.X("fraction_positive:Q", title="Fracción de organismos positivos", scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("evidence:N", title="Evidencia"),
            yOffset="evidence:N",
            tooltip=["genus", "evidence", "n_positive", "n_tested", alt.Tooltip("fraction_positive", format=".0%")],
        ).properties(width="container", height=max(120, 28 * _sel["genus"].nunique()))
    )
    mo.ui.altair_chart(bars)
    return


@app.cell(hide_code=True)
def _(df, enzyme_input, mo):
    mo.stop(enzyme_input.value is None)
    producers = (df[(df["enzyme"] == enzyme_input.value) & (df["result"] == "+")]
                 [["genus", "species", "strain", "provider", "evidence", "ec", "method", "url"]]
                 .sort_values(["genus", "species", "strain"]).reset_index(drop=True))
    mo.vstack([mo.md(f"**{len(producers):,} organismos positivos para _{enzyme_input.value}_**"),
               mo.ui.table(producers, page_size=15, selection=None)])
    return (producers,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Tu análisis

    Variables disponibles:

    - `df` — tabla larga: una fila por organismo × enzima (`genus`, `species`, `strain`, `provider`,
      `evidence`, `ec`, `enzyme`, `result`, `method`, `reference`, `url`, …).
    - `genus_enzyme` — por género × enzima × evidencia: `n_positive`, `n_tested`, `fraction_positive`.
    - `traits` — rasgos de MiDAS por género (`trait`, `value`: `+`, `-`, `variable`, `NA`);
      `ds.genus_traits(wide=True)` da la tabla género × rasgo.
    - `ds.matrix(evidence="measured_activity")` — matriz género × EC lista para un heatmap.
    - `producers` — los organismos positivos para la enzima elegida arriba.

    Ejemplo: especies de *Pseudomonas* con ureasa medida positiva.
    """)
    return


@app.cell
def _(df):
    df[(df["genus"] == "Pseudomonas") & (df["enzyme"] == "urease")
       & (df["evidence"] == "measured_activity") & (df["result"] == "+")]
    return


if __name__ == "__main__":
    app.run()
