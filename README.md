# Too Much Information

Joins the utility and weather exports for a single house in the Chihuahuan
Desert and builds one self-contained HTML dashboard from them.

**[See the dashboard →](https://www.banasiak.com/tmi)**

It began as *why is my garage so hot?* and did not stay there. The build is
Python standard library only — no pip install, no network at build time, no
telemetry in the output.

This file covers the repository: how to run it, how to feed it, and how it is
put together. **What the numbers actually say is the dashboard's job**, and it
recomputes every figure from the raw exports on each build. [The write-up][post]
says how it got this far and what the numbers cost to trust.

[post]: https://blog.banasiak.com/2026/08/too-much-information/

| Source | Pattern | Grain |
|---|---|---|
| AmbientWeather WS-2000 | `data/ambientweather_*.csv` | 5 minutes |
| El Paso Electric, interval | `data/epe-interval_*.csv` | 15 minutes |
| El Paso Electric, billing | `data/epe-billing_*.csv` | per bill |
| Municipal water & gas (UtilityHawk) | `data/utilityhawk_*.json` | daily |
| Municipal water, hourly | `data/utilityhawk-hourly_*.csv` | hourly |
| Utility bills, PDF | `data/bills/*.pdf` | per bill |
| NOAA GHCN-Daily | `data/noaa/*.json` | daily |
| NREL PVWatts | `data/pvwatts_hourly_*.csv` | hourly, typical year |

The dashboard's own manifest says what each source settles and where it stops
being a measurement. Counts and spans are read off the data there rather than
written down here, so they cannot go stale.

## Adding data

Filenames carry dates so that gaps are visible in a directory listing, and
nothing in the code refers to a file by name — every loader takes whatever
currently matches its pattern (see `src/datafiles.py`).

**A newer export.** Drop it in as
`data/<source>_<coverage-start>_<coverage-end>.<ext>`, matching the existing
names. Leave the old one in place: overlapping files are merged, deduplicated on
the timestamp, with the later file winning. Nothing needs renaming or editing.

```
data/ambientweather_2025-08-07_2026-08-06.csv
data/ambientweather_2026-08-07_2027-02-01.csv   <- just add it
```

**A bill.** Save it as `data/bills/<provider>_<YYYY-MM-DD>.pdf` — `epe` keyed by
the billing period's end date, `lascruces` by the meter read date. Sorted, the
directory shows at a glance which months are missing.

Bills are reference material, not build inputs: rates in `src/tariff.py` are
typed in by hand and checked against the bills on every build. A parser silently
misreading a tariff would be worse than a transcription slip, which the
self-check catches. To transcribe a new one:

```bash
python3 tools/read_bill.py data/bills/lascruces_2026-08-14.pdf
```

Then add any new rate or rider point to `src/tariff.py` and a `Check()` for the
bill total to `validate()`. If any check drifts, the build aborts rather than
shipping a page full of confidently wrong money.

## Build

```bash
python3 build.py
```

Writes `build/dashboard.html`. Standard library only — no pip install, no
network access at build time or view time. Open the file in any browser.

To write somewhere else:

```bash
python3 build.py --out /tmp/dashboard.html
```

Structural checks on the output (no browser required):

```bash
python3 tools/validate.py
```

The build never touches the network; only the two fetch tools do, and neither
runs during a build. NOAA temperatures for the years before the weather station
existed are cached separately, and only need refreshing when the billing history
grows:

```bash
python3 tools/fetch_noaa.py
```

Four sources are optional — the billing export, the hourly water meter, the
PVWatts runs and the NOAA cache. A missing one drops the section that needed it
and leaves the rest of the page standing. That is checked rather than asserted:

```bash
python3 tools/degraded.py
```

It builds five times, hiding each optional source in turn and then all four at
once. With all four gone the page still assembles from eleven of its fourteen
sections. The electric loader detects whether it has been handed the interval
export or a billing summary and parses either.

### Requirements

Python 3.10+ and nothing else, for everything on the build path: `build.py`,
`src/` and `tools/validate.py` import from the standard library only and shell
out to nothing.

One helper sits off that path and does have a dependency. `tools/read_bill.py`
pulls the rate lines out of a bill PDF using **poppler's `pdftotext`**, which
has to be on the `PATH`:

```bash
sudo apt-get install -y poppler-utils
```

It is only needed when transcribing a new bill, and the script checks for it and
prints that same line if it is missing. Nothing else in the repository requires
it, and a build with no poppler installed produces a byte-identical dashboard —
the rates it would have helped you read are already in `src/tariff.py`.

## Tests

```bash
python3 -m unittest discover -s tests
```

No fixtures and no network: `data/` holds raw utility exports carrying an
account holder's name, service address and account numbers, so it is gitignored
and cannot be checked in. What the tests cover instead is everything that does
not need a reading — the transcribed tariffs, the psychrometrics, the solar
geometry, the formatting rules, and the layering invariants below.

## Layout

Three layers, in one direction: **measure, then argue, then render.**

```
build.py            CLI: analyse, build sections, render, report what it saw
src/
  analysis.py       Analysis — every figure the page is allowed to quote
  house.py          the hand-supplied constants, all of them, in one screen
  sections/         one module per section of the page, in reading order
    __init__.py     MODULES: the reading order, and the pre-render guards
    overview.py     costs.py  electricity.py  solar.py  irrigation.py
    hourly_water.py pool.py   weather.py      zones.py  anomalies.py
    bills.py        watch.py  equipment.py    provenance.py
  sources.py        parsers; everything keyed to local calendar date
  model.py          regressions, balance-point fitting, anomaly detection
  tariff.py         all four tariffs, transcribed from PDF bills; self-checking
  charts.py         inline-SVG chart builders
  datafiles.py      where the raw exports live and how they are named
  solar.py          sun position, diffuse split, irradiance on tilted surfaces
  noaa.py           calibrated proxy for the years before the station existed
  zones.py          house/patio/garage/shed compared as four building envelopes
  equipment.py      appliance nameplates, transcribed by hand; self-checking
  psychro.py        moist-air properties; mixing ratio at this altitude
  palette.py        design tokens (validated colour set)
  costs.py          annual operating and unit costs, priced from the tariffs
  prose.py          number-to-text rules applied page-wide
  report.py         HTML/CSS/JS assembly
tests/              pure-logic tests; no exports required
tools/
  validate.py       structural checks on the generated page
  degraded.py       builds with each optional source hidden, to prove it still does
  fetch_noaa.py     caches NOAA daily temperatures
  fetch_hourly.py   pulls hourly water/gas from the UtilityHawk portal
  ingest_hourly.py  renames raw hourly exports into the loader's convention
  read_bill.py      dumps a bill PDF's rate lines for transcription
data/               every raw input; entirely .gitignored
```

`analysis.py` measures the house and knows nothing about HTML. Each section
module takes that one `Analysis` and returns a `Section` — or `None`, when the
source it needs is absent. **A section never reads another section's working.**
That is what lets the page be assembled from whatever sources happen to be
present: a missing export drops one section instead of breaking a later one.
`tests/test_architecture.py` enforces the import rule and `tools/degraded.py`
enforces the behaviour, because both were conventions kept by hand until the
hand slipped — every optional source crashed the build, three of them in the
last section on the page.

Every number on the page traces to exactly one field of `Analysis`, so
presentation cannot introduce a figure of its own — and a field nobody reads is
a test failure, not a leftover.

## Why the code is shaped this way

These are the decisions a reader of `model.py` would otherwise have to reverse
engineer. What each one concluded about this house is on the dashboard.

- **Degree-days are integrated, not approximated.** With 288 temperature samples
  a day there is no reason to derive them from `(Tmax + Tmin) / 2`. The
  difference matters most near the balance point, which is where the fits live.
- **Balance points are fitted, not assumed.** The conventional 65°F base is
  wrong for most houses, so each signature scans candidates and keeps the one
  that best explains routine behaviour.
- **Outlier trimming uses a proportional noise model.** Utility meters are not
  homoscedastic: a furnace running eight hours produces residuals an order of
  magnitude larger than one that never fires. A single pooled sigma, dominated
  by flat summer days, would declare the whole heating season anomalous.
- **Both R² values are reported.** A fit scored only on the days it kept
  flatters itself, so where trimming happens the retained and all-days figures
  appear side by side — the gap between them is itself a finding.
- **Detection and attribution are separate.** The detector only reports a
  departure from what the weather predicts. Naming a cause requires a different
  source, which keeps thresholds from being tuned until a story appears.
- **A null result is reported with its sensitivity.** "No leak found" without
  the smallest leak the test could have seen implies far more than the data
  supports.
- **Rates are transcribed, never inferred.** The `COST` column in the Green
  Button billing export carries only the *Total Energy Charges* line — no
  customer charge, no riders, no franchise fee, no tax — so anything derived
  from it understates the real bill, quietly and by a lot. Two inference-based
  conclusions were wrong for that reason and the PDFs corrected them.
  `tariff.KNOWN_GAPS` enumerates what a year of bills still cannot pin down.

## Privacy

**The entire `data/` directory is `.gitignore`d**, along with `build/`. The rule
covers the directory rather than a list of filenames, so a new export cannot be
committed by accident merely because nobody remembered to add its name.

The exports carry the account holder's name, service address and account
numbers; a year of 15-minute electricity is enough to infer sleep schedules and
identify the weeks the house was empty; and the generated dashboard embeds the
same data. The NOAA cache is ignored too — it is public and has no PII, but it
regenerates in one command, so an exception would only weaken the rule.

## Charts

Colour follows the utility stream, never the rank: electricity is always blue,
gas always orange, water always aqua, in every chart on the page. The
categorical set was validated for colour-vision deficiency and contrast in both
light and dark modes. Every chart ships a table view, so no value is reachable
by colour alone, and no chart uses two y-axes.
