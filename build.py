#!/usr/bin/env python3
"""Build the utility/weather dashboard.

    python3 build.py [--out build/dashboard.html]

Finds the raw exports under data/, joins them on local calendar date, fits the
models, and writes one self-contained HTML file. No dependencies beyond the
standard library, and no network access at build time.

The work is done elsewhere: `src.analysis` measures the house, `src.sections`
argues about it, and `src.report` renders the result. This file only wires the
three together and reports what it saw.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src import analysis, report, sections
from src.sections import overview

ROOT = Path(__file__).resolve().parent


def build(out_path: Path) -> None:
    """Measure the house, build the page, write it to `out_path`."""
    data = analysis.analyse()
    page = sections.build_all(data)

    html = report.render_page(
        title="Too Much Information...",
        heading="✨ Too Much Information",
        # Counts read off the page rather than typed, so neither can drift out of
        # date the way a hand-written one would.
        subtitle=(
            f"It started with <em>why is my garage so hot?</em> and did not stay "
            f"there. One house, one year, {overview.source_count(data)} sources, "
            f"{len(page)} sections, and a garage that is still hot."
        ),
        sections=page,
        footer="Made with ❤️ by Claude Opus 5 \U0001f916",
        source_url="https://github.com/banasiak/tmi",
        story_url="https://blog.banasiak.com/2026/08/too-much-information/",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    _summarise(data, out_path)


def _summarise(data: analysis.Analysis, out_path: Path) -> None:
    """What was joined, what was cross-checked, and where it went."""
    print(f"  weather      {len(data.weather):>5} days")
    print(f"  electricity  {len(data.electric):>5} days ({len(data.with_elec)} joined)")
    print(f"  water/gas    {len(data.with_util):>5} days")
    if data.bills:
        print(f"  bills        {len(data.bills):>5} periods, "
              f"{data.bills[0].start} .. {data.bills[-1].end}")
        if data.meter_check:
            print(
                f"  meter check  {data.meter_check.periods:>5} periods cross-validated, "
                f"{data.meter_check.total_deviation_pct:+.2f}% vs billed"
            )
    else:
        print("  bills            0  (no billing.csv — costs will use fallback rates)")
    print(f"  anomalies    {len(data.anomalies):>5} flagged")
    print(f"\n  -> {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "build" / "dashboard.html",
        help="where to write the dashboard (default: build/dashboard.html)",
    )
    args = parser.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
