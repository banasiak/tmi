#!/usr/bin/env python3
"""Build with each optional source hidden, and prove the page still assembles.

Four of the sources are optional: the billing export, the hourly water meter,
the PVWatts runs and the NOAA cache. The design says a missing one drops the
section that needed it and leaves the rest of the page intact — that is why
`Analysis` fields are `X | None` and why `build()` may return `None`.

That was a convention, not a guarantee, and it was quietly false: all four
crashed the build. Three of them died in the *provenance* section, which is the
last thing on the page, so twelve sections of work went in the bin at the final
step. Every failure took the same shape — prose quoting a figure whose source
had not loaded.

    python3 tools/degraded.py

Needs `data/`, so it lives here rather than in `tests/` — the test suite runs on
a clean checkout where the exports are absent by design.
"""

from __future__ import annotations

import contextlib
import io
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OPTIONAL = ("billing", "hourly_water", "pvwatts", "noaa")


def attempt(hide: frozenset[str]) -> tuple[bool, str]:
    """Build once with `hide` unavailable. Returns (ok, one-line report)."""
    for name in [m for m in list(sys.modules) if m.startswith("src")]:
        del sys.modules[name]

    from src import datafiles
    real_find, real_noaa = datafiles.find, datafiles.NOAA
    datafiles.find = (
        lambda kind, required=True:
        [] if kind in hide else real_find(kind, required)
    )
    if "noaa" in hide:
        datafiles.NOAA = real_noaa / "__absent__"

    from src import analysis, report, sections
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            data = analysis.analyse()
            page = sections.build_all(data)
            html = report.render_page(title="t", heading="h", subtitle="s",
                                      sections=page, footer="f")
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        site = [l.strip() for l in tb if "/src/" in l]
        return False, f"{tb[-1]}\n{'':>22}{site[-1] if site else ''}"
    return True, f"{len(page):>2} sections, {len(html) / 1024:>7,.0f} KB"


def main() -> None:
    cases = [frozenset({k}) for k in OPTIONAL] + [frozenset(OPTIONAL)]
    failures = 0
    for hide in cases:
        label = "all four missing" if len(hide) > 1 else f"without {sorted(hide)[0]}"
        ok, report = attempt(hide)
        print(f"  {label:<20} {'ok  ' if ok else 'FAIL'}  {report}")
        failures += not ok
    print()
    if failures:
        sys.exit(f"{failures} of {len(cases)} degraded builds failed.")
    print(f"All {len(cases)} degraded builds assembled a page.")


if __name__ == "__main__":
    main()
