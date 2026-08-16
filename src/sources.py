"""Parsers for the three raw exports.

Each loader returns plain Python structures keyed by local calendar date, so the
rest of the pipeline never has to think about the quirks of a given vendor's
format again.

Source quirks handled here:
  electric.csv    UTF-8 BOM, a free-text header block above the real CSV header,
                  thousands separators inside quoted numbers, "$" on costs.
  utilities.json  UtilityHawk nests every metric in a stats object and repeats it
                  across rollup windows; timestamps are UTC but land on local
                  midnight, so the offset flips with DST. The hourly water CSV
                  is the same platform and the same meter, branded AquaHawk.
  awn.csv         5-minute samples, newest first, degree signs in the headers,
                  and a handful of sensors that drop out (shed, lightning).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


from . import psychro

# Everything on this page is local wall time — the clock the utility meters
# and the weather station all keep. Only the charger reports in UTC.
LOCAL_ZONE = "America/Denver"

# A day needs at least this many of the 288 expected 5-minute samples before we
# trust its aggregates. Partial days would bias degree-days toward whichever
# part of the day happened to be recorded.
MIN_SAMPLES_PER_DAY = 240


def _as_paths(source) -> list[Path]:
    """Accept a single path or a sequence, so callers need not care which.

    Every loader takes whatever `datafiles.find()` returned. Reading several
    exports in filename order means a newer one naturally overwrites an older
    one wherever they overlap, instead of the two being summed.
    """
    if isinstance(source, (str, Path)):
        return [Path(source)]
    return [Path(p) for p in source]


# ---------------------------------------------------------------------------
# electric.csv  —  El Paso Electric "Green Button" billing summary
# ---------------------------------------------------------------------------


@dataclass
class BillingPeriod:
    start: dt.date
    end: dt.date
    kwh: float
    cost: float

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def kwh_per_day(self) -> float:
        return self.kwh / self.days

    @property
    def rate(self) -> float:
        """Implied all-in $/kWh. EPE's seasonal split falls out of this cleanly."""
        return self.cost / self.kwh if self.kwh else 0.0


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", "").strip())


def load_billing(source) -> list[BillingPeriod]:
    """Read EPE's *billing summary* export (one row per bill)."""
    by_start: dict[dt.date, BillingPeriod] = {}
    for path in _as_paths(source):
      with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            # The header block above the real table has no recognisable TYPE
            # column, so filtering on the row label skips it without hardcoding
            # a line count that a future export might change.
            if not row or row[0] != "Electric billing":
                continue
            period = BillingPeriod(
                start=dt.date.fromisoformat(row[1]),
                end=dt.date.fromisoformat(row[2]),
                kwh=float(row[3].replace(",", "")),
                cost=_money(row[4]),
            )
            by_start[period.start] = period
    return sorted(by_start.values(), key=lambda p: p.start)


# --- interval export -------------------------------------------------------

# Intervals per day in a 15-minute export. Spring-forward days legitimately
# carry 92 (the skipped hour); fall-back days may carry 100.
INTERVALS_PER_DAY = 96
MIN_INTERVALS_PER_DAY = 92


@dataclass
class ElectricDay:
    """One local day of 15-minute electric readings.

    `baseload_kw` is the workhorse: the day's quietest sustained draw, taken as
    the 5th percentile of interval power rather than the strict minimum so a
    single reporting dropout cannot define it. It is the closest thing the meter
    gives to "what this house draws when nobody is asking it for anything".
    """

    date: dt.date
    kwh: float
    peak_kw: float
    baseload_kw: float
    intervals: int
    # 96 slots of kWh, index = interval-of-day; None where the meter reported
    # nothing (the spring-forward hour, or a dropout).
    profile: list[float | None] = field(default_factory=list)

    @property
    def baseload_kwh(self) -> float:
        """What the day would have used had it never risen above its floor."""
        return self.baseload_kw * 24.0

    @property
    def variable_kwh(self) -> float:
        return max(self.kwh - self.baseload_kwh, 0.0)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * q), len(ordered) - 1)
    return ordered[idx]


def load_electric_intervals(source) -> list[ElectricDay]:
    """Read EPE's 15-minute interval export.

    Timestamps are local wall time, which is the same clock the weather station
    and the water/gas meters use, so days align without conversion. The
    DEMAND column is average kW over the interval; kWh is the integral, and the
    two are consistent at kW = kWh * 4.
    """
    # slot -> kWh per day, so a later export overwrites an earlier reading of
    # the same interval rather than adding to it.
    buckets: dict[dt.date, dict[str, float]] = defaultdict(dict)
    for path in _as_paths(source):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if not row or row[0] != "Electric usage":
                    continue
                try:
                    day = dt.date.fromisoformat(row[1])
                    kwh = float(row[4])
                except (ValueError, IndexError):
                    continue
                buckets[day][row[2]] = kwh

    days: list[ElectricDay] = []
    for day, slots in buckets.items():
        if len(slots) < MIN_INTERVALS_PER_DAY:
            continue
        readings = sorted(slots.items())
        kwhs = [k for _, k in readings]
        # A 15-minute interval's average power is four times its energy.
        powers = [k * 4.0 for k in kwhs]

        profile: list[float | None] = [None] * INTERVALS_PER_DAY
        for slot, kwh in readings:
            hh, mm = int(slot[:2]), int(slot[3:5])
            idx = hh * 4 + mm // 15
            if 0 <= idx < INTERVALS_PER_DAY:
                profile[idx] = kwh

        days.append(
            ElectricDay(
                date=day,
                kwh=sum(kwhs),
                peak_kw=max(powers),
                baseload_kw=_percentile(powers, 0.05),
                intervals=len(readings),
                profile=profile,
            )
        )
    days.sort(key=lambda d: d.date)
    return days


def load_electric(source):
    """Dispatch on which EPE export this is.

    The portal offers both a billing summary and a 15-minute interval download,
    so detect rather than assume; the row label in the TYPE column is the
    discriminator, and it survives any renaming of the file.
    """
    paths = _as_paths(source)
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                if row[0] == "Electric usage":
                    return load_electric_intervals(paths)
                if row[0] == "Electric billing":
                    return load_billing(paths)
    return []



# ---------------------------------------------------------------------------
# utilities.json  —  City of Las Cruces UtilityHawk
# ---------------------------------------------------------------------------


@dataclass
class UtilityDay:
    date: dt.date
    water_gal: float
    gas_cf: float
    # UtilityHawk ships its own weather alongside usage. We keep it only to
    # cross-check the backyard station, never as the modeling input.
    ref_high_f: float | None = None
    ref_low_f: float | None = None
    ref_rain_in: float | None = None


def _local_date(iso_utc: str) -> dt.date:
    """UtilityHawk stamps each day at local midnight expressed in UTC.

    That means the offset is -6 during MDT and -7 during MST; reading the hour
    back off the timestamp recovers the offset without needing a tz database.
    """
    stamp = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return (stamp - dt.timedelta(hours=stamp.hour)).date()


def load_utilities(source) -> list[UtilityDay]:
    by_date: dict[dt.date, UtilityDay] = {}
    for path in _as_paths(source):
      with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)

      for entry in payload.get("timeseries", []):
        # The final entry of an export is often a stub with weather but no meter
        # reads yet; skip anything without both utilities.
        if "waterUse" not in entry or "naturalgasUse" not in entry:
            continue
        day = UtilityDay(
            date=_local_date(entry["startTime"]),
            water_gal=entry["waterUse"]["gallons"],
            gas_cf=entry["naturalgasUse"]["cubic feet"],
            ref_high_f=entry.get("highTemp", {}).get("fahrenheit"),
            ref_low_f=entry.get("lowTemp", {}).get("fahrenheit"),
            ref_rain_in=entry.get("rainfall", {}).get("inches"),
        )
        by_date[day.date] = day
    return sorted(by_date.values(), key=lambda d: d.date)


# ---------------------------------------------------------------------------
# awn.csv  —  AmbientWeather WS-2000
# ---------------------------------------------------------------------------

# Column name -> short field name. Anything not listed is ignored, which keeps
# the aggregation loop cheap over ~105k rows.
AWN_NUMERIC = {
    "Outdoor Temperature (°F)": "t_out",
    "Feels Like (°F)": "t_feels",
    "Dew Point (°F)": "dew",
    "Humidity (%)": "rh",
    "Wind Speed (mph)": "wind",
    "Wind Gust (mph)": "gust",
    "Solar Radiation (W/m^2)": "solar",
    "Ultra-Violet Radiation Index": "uv",
    "Relative Pressure (inHg)": "pressure",
    "Daily Rain (in)": "rain_daily",
    "Rain Rate (in/hr)": "rain_rate",
    "Lightning strikes per day": "strikes",
    "Indoor Temperature (°F)": "t_in",
    "Indoor Humidity (%)": "rh_in",
    "Garage Temperature (°F)": "t_garage",
    "Patio Temperature (°F)": "t_patio",
    "Shed Temperature (°F)": "t_shed",
    "Pool Temperature (°F)": "t_pool",
    # Per-zone moisture. Dew point is what the station transmits; mixing ratio
    # is derived from it in `psychro`, because only an absolute measure lets two
    # rooms at different temperatures be compared.
    "Indoor Dew Point (°F)": "dew_in",
    "Patio Humidity (%)": "rh_patio",
    "Patio Dew Point (°F)": "dew_patio",
    "Garage Humidity (%)": "rh_garage",
    "Garage Dew Point (°F)": "dew_garage",
    "Shed Humidity (%)": "rh_shed",
    "Shed Dew Point (°F)": "dew_shed",
    "Absolute Pressure (inHg)": "pressure_abs",
}

# The five sensed volumes, ordered outermost to innermost. Every zone table and
# every small-multiple panel on the page follows this order, so the ladder reads
# the same way everywhere.
ZONE_ORDER = ["outdoor", "shed", "garage", "patio", "indoor"]
ZONE_LABELS = {
    "outdoor": "Outdoors",
    "shed": "Shed",
    "garage": "Garage",
    "patio": "Patio",
    "indoor": "House",
}
# short key -> (temperature channel, dew point channel)
ZONE_CHANNELS = {
    "outdoor": ("t_out", "dew"),
    "shed": ("t_shed", "dew_shed"),
    "garage": ("t_garage", "dew_garage"),
    "patio": ("t_patio", "dew_patio"),
    "indoor": ("t_in", "dew_in"),
}


@dataclass
class WeatherDay:
    """Daily aggregate of 5-minute station samples.

    Degree-days here are *integrated* over the day's samples rather than derived
    from (Tmax+Tmin)/2. With 288 samples a day the difference is material near
    the balance point, which is exactly where the fits live.
    """

    date: dt.date
    samples: int
    t_min: float
    t_max: float
    t_mean: float
    dew_mean: float
    rh_mean: float
    wind_mean: float
    gust_max: float
    solar_mean: float
    solar_peak: float
    pressure_mean: float
    rain_in: float
    rain_rate_max: float
    strikes: float
    t_in_mean: float | None
    t_in_min: float | None
    t_in_max: float | None
    rh_in_mean: float | None
    t_pool_mean: float | None
    t_garage_mean: float | None
    # Carried so the garage can be quoted on the same footing as the house.
    # Without them the only garage damping figure available was a mean-on-mean
    # slope, which was printed next to the house's swing-on-swing one as if the
    # two were the same measurement — 88% against 11%, when on swing the garage
    # is 58%.
    t_garage_min: float | None
    t_garage_max: float | None
    t_patio_mean: float | None
    # Fraction of the day each sample spent above/below a base, integrated.
    _temps: list[float] = field(default_factory=list, repr=False)

    @property
    def t_swing(self) -> float:
        return self.t_max - self.t_min

    @property
    def t_in_swing(self) -> float | None:
        if self.t_in_max is None or self.t_in_min is None:
            return None
        return self.t_in_max - self.t_in_min

    @property
    def t_garage_swing(self) -> float | None:
        if self.t_garage_max is None or self.t_garage_min is None:
            return None
        return self.t_garage_max - self.t_garage_min

    def hdd(self, base: float) -> float:
        """Heating degree-days, integrated over the day's samples."""
        return sum(max(0.0, base - t) for t in self._temps) / len(self._temps)

    def cdd(self, base: float) -> float:
        """Cooling degree-days, integrated over the day's samples."""
        return sum(max(0.0, t - base) for t in self._temps) / len(self._temps)


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def load_weather(source) -> list[WeatherDay]:
    # (day, timestamp) -> readings, so overlapping exports deduplicate on the
    # sample rather than double-counting it into the daily aggregate.
    seen: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)

    for path in _as_paths(source):
      with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        # Resolve header names once; AmbientWeather occasionally reorders or
        # drops sensor columns between exports.
        present = {
            col: short for col, short in AWN_NUMERIC.items() if col in reader.fieldnames
        }
        for row in reader:
            # "Simple Date" is already local wall time, which is the boundary the
            # utility meters use too, so days line up without conversion.
            stamp = row["Simple Date"]
            day = stamp[:10]
            sample: dict[str, float] = {}
            for col, short in present.items():
                raw = row[col]
                if not raw:
                    continue
                try:
                    sample[short] = float(raw)
                except ValueError:
                    continue
            seen[day][stamp] = sample

    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for day, samples in seen.items():
        for _, sample in sorted(samples.items()):
            for short, value in sample.items():
                buckets[day][short].append(value)

    days: list[WeatherDay] = []
    for day, bucket in buckets.items():
        temps = bucket.get("t_out", [])
        if len(temps) < MIN_SAMPLES_PER_DAY:
            continue
        # "Daily Rain" is a running accumulator that resets at midnight, so the
        # day's total is its maximum, not its sum.
        rain = max(bucket.get("rain_daily", [0.0]) or [0.0])
        days.append(
            WeatherDay(
                date=dt.date.fromisoformat(day),
                samples=len(temps),
                t_min=min(temps),
                t_max=max(temps),
                t_mean=statistics.fmean(temps),
                dew_mean=_mean(bucket.get("dew", [])) or 0.0,
                rh_mean=_mean(bucket.get("rh", [])) or 0.0,
                wind_mean=_mean(bucket.get("wind", [])) or 0.0,
                gust_max=max(bucket.get("gust", [0.0]) or [0.0]),
                solar_mean=_mean(bucket.get("solar", [])) or 0.0,
                solar_peak=max(bucket.get("solar", [0.0]) or [0.0]),
                pressure_mean=_mean(bucket.get("pressure", [])) or 0.0,
                rain_in=rain,
                rain_rate_max=max(bucket.get("rain_rate", [0.0]) or [0.0]),
                # Like daily rain, the strike counter accumulates and resets at
                # midnight, so the day's total is its maximum.
                strikes=max(bucket.get("strikes", [0.0]) or [0.0]),
                t_in_mean=_mean(bucket.get("t_in", [])),
                t_in_min=min(bucket["t_in"]) if bucket.get("t_in") else None,
                t_in_max=max(bucket["t_in"]) if bucket.get("t_in") else None,
                rh_in_mean=_mean(bucket.get("rh_in", [])),
                t_pool_mean=_mean(bucket.get("t_pool", [])),
                t_garage_mean=_mean(bucket.get("t_garage", [])),
                t_garage_min=min(bucket["t_garage"]) if bucket.get("t_garage") else None,
                t_garage_max=max(bucket["t_garage"]) if bucket.get("t_garage") else None,
                t_patio_mean=_mean(bucket.get("t_patio", [])),
                _temps=temps,
            )
        )
    days.sort(key=lambda d: d.date)
    return days


@dataclass
class HourlyWater:
    """Hourly water from the city portal, with the meter register alongside.

    Same platform and same meter as the daily `utilities` feed — the city brands
    the water side AquaHawk and the account side UtilityHawk. So this is not a
    second opinion on the daily figures, it is the same figures read more
    finely: it can correct them, never corroborate them.

    Both columns are kept because they are not the same measurement. `gallons`
    is the vendor's smoothed hourly series; `reading` is the raw cumulative
    register, which advances in **10-gallon steps**. Any question about small
    or slow flows has to be answered from the register, because the smoothed
    column renders one 10-gallon tick as a plausible-looking 2 gal/h trickle
    that was never observed.

    The same export carries the **gas** meter interleaved on the same hours, and
    that is kept too. It arrives free — one row per meter per hour, in one file —
    and it is the only sub-daily view of gas anywhere in this project: the
    billing export is monthly and the daily feed cannot say whether 400 cf went
    into one evening's spa or was spread across a cold day. Gas hours are sparse
    where the meter did not tick, since the register moves in whole cubic feet.
    """

    stamps: list[dt.datetime]
    gallons: list[float]
    # Cumulative, thousands of gallons — and `None` where the vendor shipped the
    # row with the register column empty. That happens: 24 hours in a year here,
    # always a single evening hour, always with a perfectly good `use` value
    # beside it. Requiring both columns used to drop those rows, which meant
    # discarding the better measurement because the worse one was missing — and
    # then losing the whole day downstream, since a day needs 24 hours to count.
    reading: list[float | None]
    # The gas meter off the same rows, on its own stamps: it reports on hours the
    # water meter may not, so it gets its own axis rather than being padded onto
    # the water one.
    gas_stamps: list[dt.datetime] = field(default_factory=list)
    gas_cf: list[float] = field(default_factory=list)
    gas_reading: list[float | None] = field(default_factory=list)

    RESOLUTION_GAL = 10.0
    # The gas register is printed in whole cubic feet, so a quiet hour shows no
    # movement at all — the same rounding trap as the water register, one order
    # of magnitude finer.
    RESOLUTION_CF = 1.0

    def __len__(self) -> int:
        return len(self.stamps)

    @property
    def gas_span(self) -> tuple[dt.datetime, dt.datetime] | None:
        return (self.gas_stamps[0], self.gas_stamps[-1]) if self.gas_stamps else None

    @property
    def span(self) -> tuple[dt.datetime, dt.datetime] | None:
        return (self.stamps[0], self.stamps[-1]) if self.stamps else None

    def register_flow(self, start: dt.datetime, end: dt.datetime) -> float | None:
        """Gallons the register advanced between two times, or None if unseen.

        Also None when either end of the window is one of the rows whose register
        was blank — a difference against a missing reading is not a measurement
        of nothing.
        """
        idx = {s: i for i, s in enumerate(self.stamps)}
        if start not in idx or end not in idx:
            return None
        a, b = self.reading[idx[start]], self.reading[idx[end]]
        if a is None or b is None:
            return None
        return (b - a) * 1000.0


def load_hourly_water(source) -> HourlyWater:
    """Parse the city portal's hourly water export.

    The file carries one row per meter per hour, so the gas meter contributes a
    row with every water column blank. Those are skipped rather than read as
    zero — an absent reading is not a reading of nothing. Meter order within the
    file is not fixed: a whole-account export leads with gas, a single-meter one
    with water. Rows are keyed by timestamp, so it makes no difference.

    Separately, a handful of genuine water rows arrive with `Water Use` filled
    and `Water Reading` empty. Those keep their use figure and carry a `None`
    register — see the note on `HourlyWater.reading`.

    **The vendor stamps each row with the hour it ENDS.** Verified against the
    raw register: `use[H]` reproduces `reading[H] - reading[H-1]` on 167 of 167
    hours, and `reading[H+1] - reading[H]` on only 146. So water stamped 21:00
    flowed between 20:00 and 21:00. Every stamp is shifted back an hour here so
    it names the interval's start, which is what the rest of the code assumes
    when it talks about the hour something happened.

    This matters. Taken at face value the export put the irrigation controller
    an hour later than it runs, and misfiled each midnight hour's water — which
    actually flowed 23:00–00:00 the day before — onto the following day.
    """
    water: dict[dt.datetime, tuple[float, float | None]] = {}
    gas: dict[dt.datetime, tuple[float, float | None]] = {}
    columns = (
        (water, "Water Use (Gallons)", "Water Reading"),
        (gas, "Natural Gas Use (Cu Ft)", "Natural Gas Reading"),
    )
    for path in _as_paths(source):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    stamp = dt.datetime.fromisoformat(row["Timestamp"])
                except (ValueError, KeyError):
                    continue
                # Hour-ending to hour-starting; see the docstring.
                stamp -= dt.timedelta(hours=1)
                for into, use_col, read_col in columns:
                    use = (row.get(use_col) or "").strip()
                    # A row belongs to one meter, so the other meter's columns
                    # are blank — that is what identifies it, and skipping is
                    # right. But a row with `use` and no `reading` is a real
                    # reading with a hole in its register, and the use figure in
                    # it is good: keep the hour, carry the gap.
                    if not use:
                        continue
                    read = (row.get(read_col) or "").strip()
                    try:
                        into[stamp] = (float(use), float(read) if read else None)
                    except ValueError:
                        continue

    stamps = sorted(water)
    gas_stamps = sorted(gas)
    return HourlyWater(
        stamps=stamps,
        gallons=[water[s][0] for s in stamps],
        reading=[water[s][1] for s in stamps],
        gas_stamps=gas_stamps,
        gas_cf=[gas[s][0] for s in gas_stamps],
        gas_reading=[gas[s][1] for s in gas_stamps],
    )




# ---------------------------------------------------------------------------
# Per-zone samples
# ---------------------------------------------------------------------------


@dataclass
class ZoneSeries:
    """The five zones at native 5-minute resolution, stored column-wise.

    Column-wise rather than a list of records because every question asked of it
    — damping ratios, phase lag, coupling slopes — wants one channel across all
    samples, never one sample across all channels. At 105k samples the row-wise
    form costs a few hundred megabytes for no benefit.

    Only samples where *all five* zones reported are kept, so a zone that drops
    out for an afternoon cannot shift a between-zone difference. `dropped`
    records the cost of that rule.
    """

    stamps: list[dt.datetime]
    temp: dict[str, list[float]]
    rh: dict[str, list[float]]
    dew: dict[str, list[float]]
    # Mixing ratio, g of water vapour per kg of dry air.
    w: dict[str, list[float]]
    solar: list[float]
    wind: list[float]
    rain: list[float]
    dropped: int

    def __len__(self) -> int:
        return len(self.stamps)

    @property
    def coverage(self) -> float:
        total = len(self.stamps) + self.dropped
        return len(self.stamps) / total if total else 0.0

    def by_day(self) -> dict[dt.date, list[int]]:
        """Sample indices grouped by local calendar date."""
        out: dict[dt.date, list[int]] = defaultdict(list)
        for i, stamp in enumerate(self.stamps):
            out[stamp.date()].append(i)
        return out


def load_zone_series(source, min_samples: int = MIN_SAMPLES_PER_DAY) -> ZoneSeries:
    """Load every zone's temperature, humidity and mixing ratio.

    Mixing ratio is computed per sample against that sample's *absolute*
    pressure. Using a standard sea-level atmosphere instead would inflate every
    reading by about 12% at this altitude — uniformly, so the zone comparisons
    would survive, but the absolute values would be wrong.
    """
    stamps: list[dt.datetime] = []
    temp: dict[str, list[float]] = {z: [] for z in ZONE_ORDER}
    rh: dict[str, list[float]] = {z: [] for z in ZONE_ORDER}
    dew: dict[str, list[float]] = {z: [] for z in ZONE_ORDER}
    w: dict[str, list[float]] = {z: [] for z in ZONE_ORDER}
    solar: list[float] = []
    wind: list[float] = []
    rain: list[float] = []
    dropped = 0

    seen: dict[dt.datetime, dict[str, float]] = {}
    for path in _as_paths(source):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            present = {
                col: short
                for col, short in AWN_NUMERIC.items()
                if col in (reader.fieldnames or [])
            }
            for row in reader:
                sample: dict[str, float] = {}
                for col, short in present.items():
                    raw = row[col]
                    if not raw:
                        continue
                    try:
                        sample[short] = float(raw)
                    except ValueError:
                        continue
                seen[dt.datetime.fromisoformat(row["Simple Date"])] = sample

    rh_channel = {
        "outdoor": "rh", "shed": "rh_shed", "garage": "rh_garage",
        "patio": "rh_patio", "indoor": "rh_in",
    }
    for stamp in sorted(seen):
        sample = seen[stamp]
        pressure = sample.get("pressure_abs")
        readings: dict[str, tuple[float, float, float, float]] = {}
        for zone, (t_key, dew_key) in ZONE_CHANNELS.items():
            t, dp = sample.get(t_key), sample.get(dew_key)
            if t is None or dp is None or pressure is None:
                break
            readings[zone] = (
                t,
                sample.get(rh_channel[zone], float("nan")),
                dp,
                psychro.mixing_ratio(dp, psychro.inhg_to_hpa(pressure)),
            )
        else:
            stamps.append(stamp)
            for zone, (t, r, dp, m) in readings.items():
                temp[zone].append(t)
                rh[zone].append(r)
                dew[zone].append(dp)
                w[zone].append(m)
            solar.append(sample.get("solar", 0.0))
            wind.append(sample.get("wind", 0.0))
            rain.append(sample.get("rain_daily", 0.0))
            continue
        dropped += 1

    return ZoneSeries(
        stamps=stamps, temp=temp, rh=rh, dew=dew, w=w,
        solar=solar, wind=wind, rain=rain, dropped=dropped,
    )


# ---------------------------------------------------------------------------
# Joined daily record
# ---------------------------------------------------------------------------


def load_water_samples(
    source,
) -> dict[dt.date, list[tuple[dt.datetime, float, float, float]]]:
    """Native 5-minute samples of the water probe, with solar and outdoor temp.

    Kept separate from the daily aggregate because the questions this answers —
    what switched on at 15:15, was the sun up when the water hit 110°F — live
    entirely below the daily grain.
    """
    seen: dict[dt.datetime, tuple[dt.datetime, float, float, float]] = {}
    for path in _as_paths(source):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if "Pool Temperature (°F)" not in (reader.fieldnames or []):
                continue
            for row in reader:
                try:
                    stamp = dt.datetime.fromisoformat(row["Date"])
                    seen[stamp] = (
                        stamp,
                        float(row["Pool Temperature (°F)"]),
                        float(row["Solar Radiation (W/m^2)"] or 0.0),
                        float(row["Outdoor Temperature (°F)"]),
                    )
                except (ValueError, KeyError, TypeError):
                    continue
    out: dict[dt.date, list[tuple[dt.datetime, float, float, float]]] = defaultdict(list)
    for stamp in sorted(seen):
        out[stamp.date()].append(seen[stamp])
    return dict(out)


def load_solar_slots(source) -> dict[tuple[dt.date, int], float]:
    """Mean irradiance (W/m2) per 15-minute slot, keyed by (date, slot).

    Binned to 15 minutes so it lines up exactly with the electric meter, which
    is what lets generation and consumption be compared slot for slot rather
    than through a daily average that hides the timing mismatch entirely.
    """
    seen: dict[dt.datetime, float] = {}
    for path in _as_paths(source):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if "Solar Radiation (W/m^2)" not in (reader.fieldnames or []):
                continue
            for row in reader:
                try:
                    stamp = dt.datetime.fromisoformat(row["Date"])
                    seen[stamp] = float(row["Solar Radiation (W/m^2)"] or 0.0)
                except (ValueError, KeyError, TypeError):
                    continue
    buckets: dict[tuple[dt.date, int], list[float]] = defaultdict(list)
    for stamp, value in seen.items():
        buckets[(stamp.date(), stamp.hour * 4 + stamp.minute // 15)].append(value)
    return {k: statistics.fmean(v) for k, v in buckets.items() if v}


def load_irradiance_samples(source) -> list[tuple[dt.datetime, float, float]]:
    """Native 5-minute (timestamp, global horizontal irradiance, outdoor temp)."""
    seen: dict[dt.datetime, tuple[dt.datetime, float, float]] = {}
    for path in _as_paths(source):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if "Solar Radiation (W/m^2)" not in (reader.fieldnames or []):
                continue
            for row in reader:
                try:
                    stamp = dt.datetime.fromisoformat(row["Date"])
                    seen[stamp] = (
                        stamp,
                        float(row["Solar Radiation (W/m^2)"] or 0.0),
                        float(row["Outdoor Temperature (°F)"]),
                    )
                except (ValueError, KeyError, TypeError):
                    continue
    return [seen[k] for k in sorted(seen)]


@dataclass
class Day:
    """One local calendar day with every source that covers it."""

    date: dt.date
    weather: WeatherDay
    utility: UtilityDay | None
    electric: ElectricDay | None = None

    @property
    def water_gal(self) -> float | None:
        return self.utility.water_gal if self.utility else None

    @property
    def gas_cf(self) -> float | None:
        return self.utility.gas_cf if self.utility else None

    @property
    def kwh(self) -> float | None:
        return self.electric.kwh if self.electric else None

    @property
    def peak_kw(self) -> float | None:
        return self.electric.peak_kw if self.electric else None

    @property
    def baseload_kw(self) -> float | None:
        return self.electric.baseload_kw if self.electric else None

    @property
    def variable_kwh(self) -> float | None:
        return self.electric.variable_kwh if self.electric else None

    @property
    def weekday(self) -> int:
        return self.date.weekday()


def join_days(
    weather: list[WeatherDay],
    utilities: list[UtilityDay],
    electric: list[ElectricDay] | None = None,
) -> list[Day]:
    """Join on local calendar date, anchored to the days the station covers.

    The weather station is the anchor because every model here is weather-driven;
    a utility day with no matching weather cannot be analysed anyway.
    """
    util_by_date = {u.date: u for u in utilities}
    elec_by_date = {e.date: e for e in (electric or [])}
    return [
        Day(
            date=w.date,
            weather=w,
            utility=util_by_date.get(w.date),
            electric=elec_by_date.get(w.date),
        )
        for w in weather
    ]


def station_agreement(days: list[Day]) -> dict[str, float]:
    """How closely the backyard station tracks UtilityHawk's weather source.

    Reported in the dashboard so the station's authority is earned rather than
    assumed — if a future export drifts, this number moves first.
    """
    highs_a, highs_b, lows_a, lows_b = [], [], [], []
    for d in days:
        u = d.utility
        if not u or u.ref_high_f is None or u.ref_low_f is None:
            continue
        highs_a.append(d.weather.t_max)
        highs_b.append(u.ref_high_f)
        lows_a.append(d.weather.t_min)
        lows_b.append(u.ref_low_f)
    if not highs_a:
        return {}
    return {
        "n": len(highs_a),
        "high_r": _pearson(highs_a, highs_b),
        "high_bias": statistics.fmean(a - b for a, b in zip(highs_a, highs_b)),
        "low_r": _pearson(lows_a, lows_b),
        "low_bias": statistics.fmean(a - b for a, b in zip(lows_a, lows_b)),
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)
