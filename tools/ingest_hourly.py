#!/usr/bin/env python3
"""Rename raw UtilityHawk hourly exports into the convention the loader expects.

    python3 tools/ingest_hourly.py ~/Downloads/*.csv
    python3 tools/ingest_hourly.py ~/Downloads            # a whole directory
    python3 tools/ingest_hourly.py --dry-run ~/Downloads

The portal names every download the same thing, so a batch of them collides on
arrival and tells you nothing about what is inside. This reads the date range out
of the `Timestamp` column and writes `data/utilityhawk-hourly_<start>_<end>.csv`,
which is the pattern `datafiles.PATTERNS["hourly_water"]` globs for.

Two things worth knowing about what it does with duplicates:

  * Identical content already present is skipped rather than rewritten, so
    re-running over the same download folder is safe.
  * A *different* file claiming a range that already exists is refused, because
    the loader merges every match and lets later readings win on a duplicated
    timestamp. Silently shadowing an older export is exactly the failure this
    naming scheme exists to prevent — pass --force if that is genuinely what you
    want.

The range in the name is the range the *loader* will see, not the range the export
labels. Two adjustments get there, and both matter:

  * The vendor stamps each hour with the hour it ENDS, so `sources.py` shifts
    every stamp back an hour. A week downloaded as 20–27 July is 19 July 23:00
    through 26 July 23:00 once shifted.
  * That leaves one stray hour of the preceding day, which the loader discards
    along with any other incomplete day. So the name carries the complete days
    only — here, 20 to 26 July.

Naming a file by its raw first and last stamp instead would put a day on the end
that the build never reads, and would make two adjacent weeks look like they
overlap when they do not.

Each export carries two meters — water and gas — interleaved on the same
timestamps, so the row count is twice the hour count.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Enough of the header to be sure this is the hourly water/gas export and not one
# of the other CSVs the same portal hands out.
REQUIRED = {"Timestamp", "Water Use (Gallons)", "Water Reading"}


def span(path: Path) -> tuple[dt.date, dt.date, int, int]:
    """The complete days the loader will keep, plus hour and partial-day counts.

    Mirrors `sources.load_hourly_water` and `model.analyse_hourly_water`: shift
    the hour-ending stamps back an hour, then keep only dates carrying all 24.
    """
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"not an hourly export — no {', '.join(sorted(missing))}")
        hours: dict[dt.date, set[int]] = {}
        for row in reader:
            if not row.get("Timestamp"):
                continue
            # One meter is enough to establish the range; the other is on the
            # same stamps, and a set makes the duplication harmless anyway.
            stamp = dt.datetime.fromisoformat(row["Timestamp"]) - dt.timedelta(hours=1)
            hours.setdefault(stamp.date(), set()).add(stamp.hour)

    if not hours:
        raise ValueError("no timestamps")
    whole = sorted(d for d, h in hours.items() if len(h) == 24)
    if not whole:
        raise ValueError(
            f"no complete day — longest is {max(len(h) for h in hours.values())} hours"
        )
    return whole[0], whole[-1], sum(len(h) for h in hours.values()), len(hours) - len(whole)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> int:
    """Report coverage, gaps and redundant files across everything in data/.

    The loader globs every match and merges them, letting later readings win on a
    duplicated timestamp, so an overlap is harmless to the build but corrosive to
    the directory listing — which is the one place coverage is supposed to be
    legible at a glance. This names the files whose every day is already carried
    by some *other* file, which are exactly the ones safe to remove.
    """
    files: dict[Path, set[dt.date]] = {}
    for path in sorted(DATA.glob("utilityhawk-hourly_*.csv")):
        try:
            start, end, _, _ = span(path)
        except ValueError as exc:
            print(f"  unreadable  {path.name} — {exc}")
            continue
        files[path] = {
            start + dt.timedelta(days=i) for i in range((end - start).days + 1)
        }

    if not files:
        print("No hourly exports in data/.")
        return 1

    covered = set().union(*files.values())
    lo, hi = min(covered), max(covered)
    missing = sorted(
        d for i in range((hi - lo).days + 1)
        for d in [lo + dt.timedelta(days=i)]
        if d not in covered
    )

    print(f"{len(files)} file(s), {lo} .. {hi}")
    print(f"  {len(covered):,} of {(hi - lo).days + 1:,} days covered")

    if missing:
        # Collapse to runs; a list of 300 dates helps nobody.
        runs, start_run, prev = [], missing[0], missing[0]
        for d in missing[1:]:
            if (d - prev).days > 1:
                runs.append((start_run, prev))
                start_run = d
            prev = d
        runs.append((start_run, prev))
        print(f"  {len(missing)} day(s) missing, in {len(runs)} run(s):")
        for a, b in runs[:12]:
            print(f"    {a}" + (f" .. {b}  ({(b - a).days + 1} days)" if b != a else ""))
        if len(runs) > 12:
            print(f"    … and {len(runs) - 12} more")
    else:
        print("  no gaps")

    redundant = [
        p for p, days in files.items()
        if days <= set().union(*(d for q, d in files.items() if q is not p))
    ]
    overlapping = [
        p for p, days in files.items()
        if p not in redundant
        and any(days & d for q, d in files.items() if q is not p)
    ]

    if redundant:
        print(f"\n  {len(redundant)} file(s) fully covered by others — safe to delete:")
        for p in sorted(redundant):
            print(f"    {p.name}")
        print("\n  rm " + " ".join(f"data/{p.name}" for p in sorted(redundant)))
    if overlapping:
        print(f"\n  {len(overlapping)} file(s) partly overlap another — keep both, "
              f"the loader merges them:")
        for p in sorted(overlapping):
            print(f"    {p.name}")
    if not redundant and not overlapping:
        print("\n  no overlaps")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="*", type=Path,
                    help="CSV files, or directories to scan for them")
    ap.add_argument("--audit", action="store_true",
                    help="report coverage, gaps and redundant files in data/, "
                         "and name the ones safe to delete")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen and change nothing")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing range with different content")
    ap.add_argument("--move", action="store_true",
                    help="move rather than copy")
    args = ap.parse_args()

    if args.audit:
        return audit()
    if not args.paths:
        ap.error("give some files or directories, or use --audit")

    candidates: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            candidates.extend(sorted(p.glob("*.csv")))
        elif p.is_file():
            candidates.append(p)
        else:
            print(f"  skip   {p} — not found")

    if not candidates:
        print("Nothing to do: no CSV files found.")
        return 1

    DATA.mkdir(exist_ok=True)
    written = skipped = refused = 0
    for src in candidates:
        try:
            start, end, hours, partial = span(src)
        except (ValueError, KeyError) as exc:
            print(f"  skip   {src.name} — {exc}")
            skipped += 1
            continue

        dest = DATA / f"utilityhawk-hourly_{start:%Y-%m-%d}_{end:%Y-%m-%d}.csv"
        days = (end - start).days + 1
        note = f"{days} complete day{'s' if days != 1 else ''}, {hours:,} hours"
        if partial:
            # One is the stray hour the shift always leaves behind; more than
            # that means the download itself has a hole in it.
            note += f", {partial} partial day{'s' if partial != 1 else ''} dropped"
        if days * 24 != hours - partial:
            note += " — gappy, worth a look"

        if dest.exists():
            if digest(dest) == digest(src):
                print(f"  have   {dest.name} — identical, skipping")
                skipped += 1
                continue
            if not args.force:
                print(f"  REFUSE {dest.name} — exists with different content; "
                      f"--force to replace")
                refused += 1
                continue

        print(f"  {'would write' if args.dry_run else 'write '} {dest.name}  ({note})")
        if not args.dry_run:
            if args.move:
                shutil.move(str(src), dest)
            else:
                shutil.copy2(src, dest)
        written += 1

    print(f"\n{written} written, {skipped} skipped, {refused} refused.")
    if refused:
        return 1
    if written and not args.dry_run:
        print("Now run: python3 build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
