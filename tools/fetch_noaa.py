#!/usr/bin/env python3
"""Cache NOAA GHCN-Daily temperatures for the years the backyard station misses.

    python3 tools/fetch_noaa.py [--years 2023-2026]

The billing history reaches back three years; the weather station covers one.
Without a proxy for the earlier period there is no way to tell whether a bigger
bill meant more consumption or just a hotter month.

This is the only part of the project that touches the network, and it is kept
out of `build.py` deliberately: the dashboard build stays offline and
reproducible, reading whatever this script last cached into data/noaa/.

Station choice is validated, not assumed — see `src/noaa.py`, which calibrates
each candidate against the backyard station over the overlapping year and keeps
the one that agrees best.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "noaa"
BASE = "https://www.ncei.noaa.gov/access/services/data/v1"
AGENT = {"User-Agent": "home-utilities-dashboard/1.0"}

# Candidates near Las Cruces that report temperature, nearest first. Cooperative
# (USC) and first-order/airport (USW) stations only — the dense US1NM network in
# this valley is CoCoRaHS, which reports precipitation and nothing else.
#
# Deliberately no distances here. Two ranges to named landmarks are enough to
# trilaterate a house, and nothing in this file needs them: the ordering carries
# the only fact the fetch cares about, which is which station to prefer.
STATIONS = {
    "USC00298535": "NMSU State University",
    "USW00093041": "Las Cruces Municipal Airport",
}


def fetch(station: str, start: str, end: str) -> list[dict]:
    url = (
        f"{BASE}?dataset=daily-summaries&stations={station}"
        f"&startDate={start}&endDate={end}"
        f"&dataTypes=TMAX,TMIN,PRCP&format=json&units=standard"
    )
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=90) as r:
        return json.loads(r.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-07-01")
    parser.add_argument("--end", default="2026-08-06")
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for station, label in STATIONS.items():
        try:
            rows = fetch(station, args.start, args.end)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  {station}  FAILED: {type(exc).__name__}")
            continue
        usable = [r for r in rows if r.get("TMAX") and r.get("TMIN")]
        (CACHE / f"{station}.json").write_text(json.dumps(rows))
        print(
            f"  {station}  {len(rows):5d} rows, {len(usable):5d} with both TMAX and TMIN"
            f"  ({label})"
        )
        ok += 1

    if not ok:
        print("\nNothing cached. The dashboard will build without weather normalisation.")
        return 1
    print(f"\ncached to {CACHE}  —  build.py reads this offline from now on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
