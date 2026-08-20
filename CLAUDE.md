# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A build script that joins one house's utility and weather exports into a single
self-contained `build/dashboard.html`. Python 3.10+, **standard library only**,
no network at build time. `README.md` covers usage; this file covers the rules
that are easy to break from inside the code.

## Commands

```bash
python3 build.py                          # -> build/dashboard.html
python3 build.py --out /tmp/dash.html     # write elsewhere
python3 tools/validate.py                 # structural checks on the built page
python3 tools/degraded.py                 # rebuild 5x with optional sources hidden
python3 -m unittest discover -s tests     # 62 tests, no data/ required
python3 -m unittest tests.test_tariff -v  # one module
python3 -m unittest tests.test_physics.Psychrometrics.test_saturation_pressure_at_known_temperatures
```

Off the build path, and the only things that touch the network or shell out:
`tools/fetch_noaa.py` (caches NOAA daily temps), `tools/fetch_hourly.py`
(UtilityHawk portal, credentials from env only), `tools/ingest_hourly.py`
(renames raw hourly exports into the loader's convention), `tools/read_bill.py`
(needs poppler's `pdftotext`).

After changing anything that renders, run `build.py` **and** `validate.py` —
there is no browser here, so geometry and nesting bugs are only caught there.
After changing anything that reads a source, also run `degraded.py`.

## Layering — `analysis` → `sections` → `report`

The direction is enforced by `tests/test_architecture.py`, not just documented.

- `src/analysis.py` measures the house and knows nothing about HTML. It may not
  import `report`, `charts`, `palette` or `sections`, and may not contain markup.
- `src/sections/*.py` each expose `build(data: Analysis) -> Section | None` and
  read **only** from `Analysis`. **A section must never import another section** —
  that is what lets a missing export drop one section instead of corrupting a
  later one. Sections open by unpacking every field they use (`bills = data.bills`)
  under the comment `# Everything this section reads from the analysis layer.`
- `src/report.py` assembles HTML/CSS/JS; `src/charts.py` emits inline SVG.

`Analysis` is a contract, checked both ways: **every declared field must be read
by some section or `build.py`, and nothing may read a field that isn't declared.**
Adding a field without a consumer fails the suite; so does a typo in `data.foo`.

## Adding or changing a section

1. Create `src/sections/<name>.py` with `build(data)`.
2. Register it in `MODULES` in [src/sections/\_\_init\_\_.py](src/sections/__init__.py)
   — that tuple *is* the reading order, and an unregistered module on disk is a
   test failure.
3. Give the `Section` a unique `id` and a **unique emoji**. `build_all` refuses to
   build on a missing emoji, a duplicate emoji, or a duplicate id.
4. If any input may be absent, return `None` rather than raising. The pattern in
   use is `section: Section | None = None`, assigned only once the inputs exist.

Optional sources are `billing`, `hourly_water`, `pvwatts`, `noaa`. Every one of
them crashed the build once, always the same way — prose quoting a figure whose
source had not loaded — usually in `provenance`, the last section on the page.
`tools/degraded.py` is what keeps that fixed.

## Numbers are transcribed, never inferred

`src/tariff.py` (rates) and `src/equipment.py` (nameplates) are typed in by hand
from PDFs and photographs, and each self-checks against its source on every
build — `analysis.verify_transcriptions()` calls `sys.exit` if any check drifts,
because a confidently wrong dashboard is worse than none. Adding a bill means
adding rate points plus a `Check()` for its total in `tariff.validate()`.

Do not derive rates from the billing export's `COST` column: it carries only
*Total Energy Charges*, so anything built on it understates the bill by 26–57%.
`tariff.KNOWN_GAPS` states what a year of bills still cannot pin down.

`src/equipment.py` is **a record, not a library** — unreferenced constants there
(refrigerant charge, locked-rotor amps, garage dimensions) are kept deliberately
and must not be swept as dead code. A test asserts that reasoning stays in its
docstring.

`src/house.py` holds every hand-supplied constant and **no logic** (a test
asserts it declares no functions or classes). Don't hardcode a house constant in
a section or in `analysis.py`.

## Data, files and privacy

`data/` and `build/` are gitignored **as directories**, on purpose — the exports
carry the account holder's name, service address, account numbers, and a year of
15-minute electricity. Never check in a fixture from `data/`, never paste export
contents into code, tests, or commit messages, and don't add exceptions to
`.gitignore`.

Nothing addresses a data file by name. `src/datafiles.py` globs a pattern per
kind; several matches are read in filename order and merged, later readings
winning on duplicate timestamps. Tests therefore run on a clean checkout with no
`data/` at all — anything needing real exports belongs in `tools/`, not `tests/`.

Everything is keyed to **local calendar date** (`America/Denver`), joined in
`sources.py`. The one exception is the OpenEVSE charge log, which reports UTC.

## Rendering conventions

- Colour follows the utility **stream**, never the rank: electricity blue, gas
  orange, water aqua, in every chart. Tokens live in `src/palette.py`, which
  documents the CVD/contrast validation behind each choice — including the pairs
  that were rejected. Charts reference CSS custom properties, never literal hex,
  which is what makes light/dark work.
- Every figure ships a table twin (`Figure.table_headers` / `table_rows`), so no
  value is reachable by colour alone. No chart uses two y-axes. No dashed chrome.
  `validate.py` checks all of these against the built page.
- The page must stay self-contained: no `src=` or `<link href=>` pointing off-box.
- Use `prose.money()` and `prose.spell()` rather than formatting inline — page-wide
  rules exist so the same quantity never appears in two shapes, and `money()`
  keeps small rates distinguishable from zero.
- Prefer counting over asserting. The subtitle's source and section counts are
  read off the built page (`overview.source_count`) because a hand-typed "nine
  sources" outlived the source it counted.
- Where a figure comes from an equation, put the equation on the page with
  `report.Formula` rather than asserting the result.

## Modelling decisions worth not undoing

Degree-days are integrated from 5-minute samples, not `(Tmax+Tmin)/2`. Balance
points are fitted per signature, not assumed at 65°F. Outlier trimming uses a
proportional noise model, because utility residuals are not homoscedastic. Both
retained and all-days R² are reported. Detection and attribution are kept
separate — the detector reports a departure from prediction and never names a
cause. Null results are reported with the smallest effect the test could have
seen. `src/model.py` implements its own OLS rather than importing numpy, which
is what keeps `python3 build.py` runnable anywhere.
