#!/usr/bin/env python3
"""Pull the rate lines out of a bill PDF, ready to transcribe into tariff.py.

    python3 tools/read_bill.py data/bills/lascruces_2026-07-16.pdf
    python3 tools/read_bill.py --all

Bills are reference material, not build inputs: `src/tariff.py` holds rates
typed in by hand and checks them against the bills on every build. That is
deliberate — a parser silently misreading a tariff would be far worse than a
transcription error, which the self-check catches.

So adding a bill is a three-step job, and this script is step two:

    1. drop the PDF into data/bills/ as <provider>_<YYYY-MM-DD>.pdf
       (EPE: the billing period's end date. Las Cruces: the meter read date.)
    2. run this to see the rate lines
    3. add any new rate or rider point to src/tariff.py, and add a Check() for
       the bill total to validate()

Requires poppler's pdftotext on the PATH.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BILLS = ROOT / "data" / "bills"

# Lines worth showing: anything naming a rate, a rider, a total, or a read date.
KEEP = re.compile(
    r"Billing Date|Read Date|Start Date|End Date|Amount Due \d"
    r"|Energy Charge|Total Energy|Customer Charge"
    r"|Fuel and|Renewable|Transportation|Advanced Metering|Efficient Use"
    r"|Access Fee|Cost of Gas|Cost of Service|Decarbon"
    r"|gallons x|Dth x|kWh\s+@|Water Rights|Litigation|DIF Rate"
    r"|Franchise|Gross Receipts|^\s+Taxes|Total Charges"
    r"|Dekatherms|1000 Gallons|Monthly Fee|Recycling",
    re.IGNORECASE,
)


def extract(pdf: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return [f"  pdftotext failed: {result.stderr.strip()[:120]}"]
    out, seen = [], set()
    for line in result.stdout.splitlines():
        stripped = " ".join(line.split())
        if not stripped or not KEEP.search(line) or stripped in seen:
            continue
        seen.add(stripped)
        out.append(f"  {stripped}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, help="a bill under data/bills/")
    parser.add_argument("--all", action="store_true", help="every bill on file")
    args = parser.parse_args()

    if not shutil.which("pdftotext"):
        print("pdftotext not found. Install poppler-utils:")
        print("  sudo apt-get install -y poppler-utils")
        return 1

    if args.all:
        targets = sorted(BILLS.glob("*.pdf"))
    elif args.pdf:
        targets = [args.pdf]
    else:
        targets = sorted(BILLS.glob("*.pdf"))
        print(f"{len(targets)} bills on file:\n")
        for path in targets:
            print(f"  {path.name}")
        print("\nPass one, or --all, to see its rate lines.")
        return 0

    for path in targets:
        if not path.exists():
            print(f"missing: {path}")
            continue
        print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")
        print("\n".join(extract(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
