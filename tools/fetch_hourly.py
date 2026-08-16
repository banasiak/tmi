#!/usr/bin/env python3
"""Pull hourly water/gas exports from the UtilityHawk portal, a week at a time.

    export UTILITYHAWK_USER='...'
    read -rs UTILITYHAWK_PASS && export UTILITYHAWK_PASS
    python3 tools/fetch_hourly.py --from 2025-08-07 --to 2026-08-06

    python3 tools/fetch_hourly.py --dry-run --from 2026-06-01 --to 2026-08-01
    python3 tools/fetch_hourly.py --gaps            # fill what data/ is missing

The weekly loop is not laziness on anyone's part — the server rejects an hourly
export spanning more than seven days, which the app enforces client-side with the
message "The start time and end time must include no more than 7 days". A year is
therefore 53 requests no matter who is making them. This makes them, names each
file the way `tools/ingest_hourly.py` would, and skips weeks already on disk so it
can be re-run and resumed.

Endpoints, read off the portal's own bundle (`/desktop/app.js`):

    POST /login             username, password — sets a session cookie
    POST /timeseries/export firstTime, lastTime (UTC ISO), interval, accountNumber,
                            meterNumber, exportAllAccounts, exportAllMeters
                            -> {success, message, district, username, type, filename}
    GET  /download          district, username, type, filename -> the CSV
    POST /logout

Credentials come from the environment or an interactive prompt, never from the
command line — argv is world-readable in `ps` on most systems. Nothing is written
to disk but the CSVs themselves, and `data/` is gitignored in full because these
files carry the account holder's name, service address and account number.

Be a decent client: the default 2s pause between weeks is there because this is
somebody's municipal utility portal, not a CDN.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))

from tools.ingest_hourly import span  # noqa: E402  (needs ROOT on the path first)

BASE = "https://lascnm.utilityhawk.us"
LOCAL = ZoneInfo("America/Denver")
# The server's own cap on an hourly export. Requesting more returns an error
# rather than a truncated file, so this is a hard step size.
MAX_DAYS = 7
UA = "weather-dashboard/1.0 (personal utility data export)"


class Portal:
    def __init__(self, base: str = BASE, timeout: int = 180) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.opener.addheaders = [("User-Agent", UA)]

    def _open(self, url: str, data: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        return self.opener.open(req, timeout=self.timeout)

    def login(self, username: str, password: str) -> None:
        body = urllib.parse.urlencode(
            {"username": username, "password": password}
        ).encode()
        try:
            resp = self._open(
                f"{self.base}/login",
                body,
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"Login failed: HTTP {exc.code}. Check the credentials.")
        text = resp.read(4000).decode("utf-8", "replace")
        # A failed sign-in re-serves the login form rather than returning 401.
        if 'id="userAuth"' in text and "authToken" not in text:
            raise SystemExit(
                "Login failed: the portal returned the sign-in form again. "
                "Check UTILITYHAWK_USER / UTILITYHAWK_PASS."
            )
        if not any(c.name for c in self.jar):
            raise SystemExit("Login failed: no session cookie was set.")

    def logout(self) -> None:
        try:
            self._open(f"{self.base}/logout", b"")
        except Exception:
            pass

    def export_week(
        self,
        first: dt.datetime,
        last: dt.datetime,
        account: str | None = None,
        meter: str | None = None,
    ) -> bytes:
        """One hourly export, returned as raw CSV bytes.

        `accountNumber` and `meterNumber` are filters, not requirements. The app
        sends them only when the user has picked a specific account or meter from
        the form — and it deletes its own `exportAllAccounts`/`exportAllMeters`
        radio values before posting, so those never reach the server at all.
        Omitting all of it exports every meter the signed-in user owns, which is
        what this wants: the file interleaves water and gas, and the parser needs
        both.
        """
        params = {
            "firstTime": first.astimezone(dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "lastTime": last.astimezone(dt.timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "interval": "1 hour",
        }
        if account:
            params["accountNumber"] = account
        if meter:
            params["meterNumber"] = meter

        resp = self._open(
            f"{self.base}/timeseries/export",
            urllib.parse.urlencode(params).encode(),
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        payload = json.loads(resp.read().decode("utf-8", "replace"))
        if not payload.get("success"):
            raise RuntimeError(payload.get("message") or "export refused, no message")

        query = urllib.parse.urlencode(
            {
                k: payload[k]
                for k in ("district", "username", "type", "filename")
                if payload.get(k)
            }
        )
        blob = self._open(f"{self.base}/download?{query}").read()
        head = blob[:200].decode("utf-8", "replace")
        if "Timestamp" not in head:
            raise RuntimeError(f"download was not a CSV — starts {head[:80]!r}")
        return blob


def weeks(first: dt.date, last: dt.date):
    """Successive <=7-day windows covering [first, last]."""
    cursor = first
    while cursor <= last:
        end = min(cursor + dt.timedelta(days=MAX_DAYS), last + dt.timedelta(days=1))
        yield cursor, end
        cursor = end


def have() -> set[dt.date]:
    """Every calendar day already covered by a file in data/."""
    days: set[dt.date] = set()
    for path in DATA.glob("utilityhawk-hourly_*.csv"):
        try:
            start, end, _, _ = span(path)
        except Exception:
            continue
        days.update(
            start + dt.timedelta(days=i) for i in range((end - start).days + 1)
        )
    return days


def account_from_disk() -> tuple[str, str] | None:
    """Read the account number off an export already present, so it need not be typed."""
    for path in sorted(DATA.glob("utilityhawk-hourly_*.csv")):
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("Account"):
                    return row["Account"], row.get("Meter", "")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=dt.date.fromisoformat)
    ap.add_argument("--to", dest="end", type=dt.date.fromisoformat)
    ap.add_argument("--gaps", action="store_true",
                    help="fetch only the days data/ does not already cover")
    ap.add_argument("--account",
                    help="restrict to one account (default: every account you own)")
    ap.add_argument("--meter",
                    help="restrict to one meter (default: every meter — you want "
                         "this, the export interleaves water and gas)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the weeks that would be fetched, and stop")
    ap.add_argument("--pause", type=float, default=2.0,
                    help="seconds between requests (default 2)")
    args = ap.parse_args()

    if not args.start or not args.end:
        ap.error("--from and --to are required (use --gaps to skip what you have)")
    if args.start > args.end:
        ap.error("--from is after --to")

    if args.account:
        print(f"Restricted to account {args.account}")
    else:
        # No filter is the right default: the session already identifies the
        # account, and an empty data/ must not be able to block a fetch. This
        # used to be required and read off an existing export, which failed in
        # exactly the case the tool exists for — starting from nothing.
        found = account_from_disk()
        print(
            f"All accounts and meters for the signed-in user"
            + (f" (data/ suggests {found[0]})" if found else "")
        )

    covered = have() if args.gaps else set()
    todo = []
    for first, end in weeks(args.start, args.end):
        wanted = {first + dt.timedelta(days=i) for i in range((end - first).days)}
        if args.gaps and wanted <= covered:
            continue
        todo.append((first, end))

    if not todo:
        print("Nothing to fetch — data/ already covers that range.")
        return 0

    print(f"{len(todo)} week(s) to fetch, {args.start} .. {args.end}")
    if args.dry_run:
        for first, end in todo:
            print(f"  {first} .. {end - dt.timedelta(days=1)}")
        print("\nDry run: nothing fetched. Drop --dry-run to go.")
        return 0

    user = os.environ.get("UTILITYHAWK_USER") or input("UtilityHawk username: ").strip()
    # Never from argv: command lines are readable by other users via ps.
    password = os.environ.get("UTILITYHAWK_PASS") or getpass.getpass("Password: ")
    if not user or not password:
        raise SystemExit("No credentials supplied.")

    portal = Portal()
    portal.login(user, password)
    print("Signed in.\n")

    written = failed = 0
    try:
        for i, (first, end) in enumerate(todo, 1):
            label = f"{first} .. {end - dt.timedelta(days=1)}"
            try:
                blob = portal.export_week(
                    dt.datetime.combine(first, dt.time(), LOCAL),
                    dt.datetime.combine(end, dt.time(), LOCAL),
                    args.account,
                    args.meter,
                )
            except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
                print(f"  [{i}/{len(todo)}] {label}  FAILED — {exc}")
                failed += 1
                continue

            tmp = DATA / f".fetch-{first:%Y%m%d}.csv"
            tmp.write_bytes(blob)
            try:
                start, stop, hours, _ = span(tmp)
            except ValueError as exc:
                print(f"  [{i}/{len(todo)}] {label}  UNUSABLE — {exc}")
                tmp.unlink()
                failed += 1
                continue

            dest = DATA / f"utilityhawk-hourly_{start:%Y-%m-%d}_{stop:%Y-%m-%d}.csv"
            if dest.exists() and dest.read_bytes() == blob:
                print(f"  [{i}/{len(todo)}] {label}  already have {dest.name}")
                tmp.unlink()
            else:
                tmp.replace(dest)
                print(f"  [{i}/{len(todo)}] {label}  -> {dest.name} ({hours:,} hours)")
                written += 1

            if i < len(todo):
                time.sleep(args.pause)
    finally:
        portal.logout()

    print(f"\n{written} file(s) written, {failed} failed.")
    if written:
        print("Now run: python3 build.py")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
