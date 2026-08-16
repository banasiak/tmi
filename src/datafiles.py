"""Where the raw exports live, and how they are named.

Everything under `data/` follows one of three conventions:

    data/<source>_<start>_<end>.<ext>     a dated export covering a date range
    data/bills/<provider>_<date>.pdf      one bill, keyed by the date it closes
    data/noaa/<station-id>.json           cached public weather

The point of putting dates in the filenames is that gaps become visible in a
directory listing. Sorting `data/bills/` shows immediately that there is an EPE
bill for October and January but nothing for November or December — which is a
question you would otherwise have to go looking for.

Nothing in the codebase hardcodes a filename. Loaders take whatever matches the
pattern, so adding a newer export is a matter of dropping the file in: no
renaming of what is already there, no edits here. Where several files match,
they are read in filename order and merged, with later readings winning on any
duplicated timestamp — so a fresh export that overlaps an old one corrects it
rather than double-counting.

Bills are reference material rather than build inputs: the rates in `tariff.py`
are transcribed from them by hand and checked against them on every build. Use
`tools/read_bill.py` to pull the rate lines out of a new one.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BILLS = DATA / "bills"
NOAA = DATA / "noaa"

# Glob per kind of export. The trailing date range is not parsed — filenames are
# sorted as strings, and ISO dates sort chronologically for free.
PATTERNS = {
    "weather": "ambientweather_*.csv",
    "electric": "epe-interval_*.csv",
    "billing": "epe-billing_*.csv",
    "utilities": "utilityhawk_*.json",
    "hourly_water": "utilityhawk-hourly_*.csv",
    # One file per orientation, named for the tilt and azimuth it was run at, so
    # a directory listing shows which planes exist without opening anything.
    # These are the only inputs here not measured at the house.
    "pvwatts": "pvwatts_hourly_*.csv",
}

# What to tell the user when one is missing, since the filename carries a date
# range they will need to fill in themselves.
EXAMPLES = {
    "weather": "ambientweather_2025-08-07_2026-08-06.csv",
    "electric": "epe-interval_2025-08-01_2026-08-01.csv",
    "billing": "epe-billing_2023-07-20_2026-07-20.csv",
    "utilities": "utilityhawk_2025-08-06_2026-08-06.json",
    "pvwatts": "pvwatts_hourly_22.6_90.csv",
}

DESCRIPTIONS = {
    "weather": "AmbientWeather station export (5-minute samples)",
    "electric": "El Paso Electric interval export (15-minute kWh and demand)",
    "billing": "El Paso Electric billing summary (one row per bill)",
    "utilities": "City of Las Cruces UtilityHawk export (daily water and gas)",
    "pvwatts": "NREL PVWatts hourly run (one file per roof plane)",
}


def find(kind: str, required: bool = True) -> list[Path]:
    """Every file matching a kind, in filename — and therefore date — order."""
    if kind not in PATTERNS:
        raise KeyError(f"unknown data kind {kind!r}")
    matches = sorted(DATA.glob(PATTERNS[kind]))
    if not matches and required:
        raise FileNotFoundError(
            f"No {DESCRIPTIONS[kind]} found.\n"
            f"  Expected: {DATA / PATTERNS[kind]}\n"
            f"  For example: data/{EXAMPLES[kind]}"
        )
    return matches


def bills(provider: str | None = None) -> list[Path]:
    """Bill PDFs, oldest first. `provider` is 'epe' or 'lascruces'."""
    pattern = f"{provider}_*.pdf" if provider else "*.pdf"
    return sorted(BILLS.glob(pattern))


def describe() -> str:
    """One line per input, for the build log."""
    lines = []
    for kind in PATTERNS:
        found = find(kind, required=False)
        if not found:
            lines.append(f"  {kind:10s} MISSING  (expects data/{PATTERNS[kind]})")
        else:
            names = ", ".join(p.name for p in found)
            lines.append(f"  {kind:10s} {names}")
    epe, lc = bills("epe"), bills("lascruces")
    lines.append(f"  bills      {len(epe)} EPE, {len(lc)} Las Cruces")
    return "\n".join(lines)
