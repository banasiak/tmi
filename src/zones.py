"""What the five sensed volumes say about the building.

The house, patio, garage and shed are four boxes sitting in the same weather,
built to four different standards. Comparing them turns the weather into an
instrument: outdoors supplies the forcing, and each zone's response measures how
well that zone is separated from it.

Two rules run through everything here.

**Moisture is compared as mixing ratio, never relative humidity.** RH divides by
a temperature-dependent denominator, so an RH comparison between a 50F garage
and a 74F house mostly restates their thermometers. Mixing ratio is grams of
water per kilogram of air: equal readings mean equal water.

**Between-zone offsets are reported as slopes wherever possible.** Five
independent hygrometers do not agree to better than about a gram per kilogram,
which is the same size as some of the effects worth measuring. A constant
calibration error moves the *intercept* of a regression and leaves the *slope*
untouched, so a slope against a driving gradient is a claim the instruments can
actually support, and a bare difference of means often is not.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

from .model import r_squared, solve_ols
from .sources import ZONE_LABELS, ZONE_ORDER, Day, ZoneSeries

# A day needs this many of the 288 five-minute samples before its extremes are
# trusted; a partial day understates the swing it is being asked to report.
MIN_DAY_SAMPLES = 250


def _corr(a: list[float], b: list[float]) -> float:
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da and db else 0.0


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Ordinary least squares through (intercept, slope, R²)."""
    coef = solve_ols([[1.0, x] for x in xs], ys)
    pred = [coef[0] + coef[1] * x for x in xs]
    return coef[0], coef[1], r_squared(ys, pred)


def _full_days(series: ZoneSeries) -> dict[dt.date, list[int]]:
    return {
        day: idx
        for day, idx in series.by_day().items()
        if len(idx) >= MIN_DAY_SAMPLES
    }


# ---------------------------------------------------------------------------
# The ladder: how much of the outdoor swing each zone lets through
# ---------------------------------------------------------------------------


@dataclass
class Rung:
    zone: str
    label: str
    swing: float          # mean daily max - min, °F
    swing_ratio: float    # that swing as a fraction of the outdoor swing
    max_offset: float     # mean daily max, relative to the outdoor daily max
    min_offset: float     # mean daily min, relative to the outdoor daily min
    lag_hours: int        # hours behind outdoors, by peak cross-correlation
    corr: float           # correlation with outdoors at that lag
    t_mean: float
    t_min: float
    t_max: float


def ladder(series: ZoneSeries, max_lag: int = 12) -> list[Rung]:
    """Rank the zones by how much weather gets through them.

    Damping and phase lag are the two numbers that characterise a wall. Damping
    says how much of the daily swing survives; lag says how long the wall takes
    to pass it on. Reporting the daily maximum and minimum offsets separately
    matters because insulation is not symmetric — a zone can be much better at
    holding heat in than at keeping it out.
    """
    days = _full_days(series)
    if not days:
        return []

    hourly: dict[str, dict[dt.datetime, list[float]]] = {
        z: defaultdict(list) for z in ZONE_ORDER
    }
    for i, stamp in enumerate(series.stamps):
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        for zone in ZONE_ORDER:
            hourly[zone][hour].append(series.temp[zone][i])
    hours = sorted(hourly["outdoor"])
    hourly_mean = {
        z: [statistics.fmean(hourly[z][h]) for h in hours] for z in ZONE_ORDER
    }
    outdoor_hourly = hourly_mean["outdoor"]

    out_swing = statistics.fmean(
        max(series.temp["outdoor"][i] for i in idx)
        - min(series.temp["outdoor"][i] for i in idx)
        for idx in days.values()
    )

    rungs: list[Rung] = []
    for zone in ZONE_ORDER:
        temps = series.temp[zone]
        swing = statistics.fmean(
            max(temps[i] for i in idx) - min(temps[i] for i in idx)
            for idx in days.values()
        )
        max_offset = statistics.fmean(
            max(temps[i] for i in idx)
            - max(series.temp["outdoor"][i] for i in idx)
            for idx in days.values()
        )
        min_offset = statistics.fmean(
            min(temps[i] for i in idx)
            - min(series.temp["outdoor"][i] for i in idx)
            for idx in days.values()
        )
        zone_hourly = hourly_mean[zone]
        lag = max(
            range(max_lag + 1),
            key=lambda k: _corr(
                outdoor_hourly[: len(outdoor_hourly) - k] if k else outdoor_hourly,
                zone_hourly[k:],
            ),
        )
        best = _corr(
            outdoor_hourly[: len(outdoor_hourly) - lag] if lag else outdoor_hourly,
            zone_hourly[lag:],
        )
        rungs.append(
            Rung(
                zone=zone,
                label=ZONE_LABELS[zone],
                swing=swing,
                swing_ratio=swing / out_swing if out_swing else 0.0,
                max_offset=max_offset,
                min_offset=min_offset,
                lag_hours=lag,
                corr=best,
                t_mean=statistics.fmean(temps),
                t_min=min(temps),
                t_max=max(temps),
            )
        )
    return rungs


# ---------------------------------------------------------------------------
# Coupling: how much of the house reaches the zones next to it
# ---------------------------------------------------------------------------


@dataclass
class Coupling:
    zone: str
    label: str
    channel: str        # "temperature" or "moisture"
    unit: str
    slope: float        # fraction of the house's gradient that arrives
    intercept: float
    r2: float
    n: int
    reference: str      # the zone the target is measured against
    points: list[tuple[float, float]]


def coupling(series: ZoneSeries) -> list[Coupling]:
    """Measure the garage and patio against the gradient driving them.

    The garage is compared with the **shed**, not with outdoors. Both are
    unconditioned boxes on the same property carrying the same model of sensor;
    the difference between them is that one shares a wall with the house. So
    `garage - shed` isolates the wall, and regressing it on `house - outdoors`
    gives the fraction of the house's gradient that arrives next door.

    The slope is the load-bearing number. A hygrometer reading half a gram high
    all year shifts the intercept of that line and leaves its slope alone, which
    is why the slope is quoted and the offset is not.
    """
    days = _full_days(series)
    out: list[Coupling] = []
    plans = [
        ("garage", "shed", "shed"),
        ("patio", "outdoor", "outdoors"),
    ]
    for channel, unit, chan in (
        ("temperature", "°F", "temp"),
        ("moisture", "g/kg", "w"),
    ):
        data = getattr(series, chan)
        for zone, against, ref_label in plans:
            pts: list[tuple[float, float]] = []
            for idx in days.values():
                drive = statistics.fmean(
                    data["indoor"][i] - data["outdoor"][i] for i in idx
                )
                response = statistics.fmean(
                    data[zone][i] - data[against][i] for i in idx
                )
                pts.append((drive, response))
            if len(pts) < 30:
                continue
            a, b, r2 = _fit([p[0] for p in pts], [p[1] for p in pts])
            out.append(
                Coupling(
                    zone=zone,
                    label=ZONE_LABELS[zone],
                    channel=channel,
                    unit=unit,
                    slope=b,
                    intercept=a,
                    r2=r2,
                    n=len(pts),
                    reference=ref_label,
                    points=pts,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Moisture through the year
# ---------------------------------------------------------------------------


@dataclass
class MoistureMonth:
    month: str
    outdoor: float
    excess: dict[str, float]   # zone -> mixing ratio above outdoors, g/kg


def moisture_months(series: ZoneSeries) -> list[MoistureMonth]:
    """Monthly mixing ratio for each zone, relative to outdoors.

    The sign of the excess is the finding: a house that adds water to its air in
    winter and takes water out of it in summer is running two different
    machines. Because each zone is compared with itself across the year, a fixed
    calibration error cannot manufacture the reversal — it can only shift every
    month by the same amount.
    """
    buckets: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for i, stamp in enumerate(series.stamps):
        key = stamp.strftime("%Y-%m")
        for zone in ZONE_ORDER:
            buckets[key][zone].append(series.w[zone][i])

    months: list[MoistureMonth] = []
    for key in sorted(buckets):
        outdoor = statistics.fmean(buckets[key]["outdoor"])
        months.append(
            MoistureMonth(
                month=key,
                outdoor=outdoor,
                excess={
                    z: statistics.fmean(buckets[key][z]) - outdoor
                    for z in ZONE_ORDER
                    if z != "outdoor"
                },
            )
        )
    return months


# ---------------------------------------------------------------------------
# Condensation
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Latent load: what humidity costs at the meter
# ---------------------------------------------------------------------------


@dataclass
class LatentLoad:
    base: float
    n: int
    intercept: float
    per_cdd: float
    per_gram: float          # extra kWh per g/kg of outdoor moisture
    r2: float
    r2_without: float
    t_stat: float
    vif: float               # collinearity between the two regressors
    dry_w: float
    humid_w: float
    dry_days: int
    humid_days: int
    extra_kwh_day: float
    extra_cost_day: float
    season_kwh: float
    season_cost: float


def latent_load(
    days: list[Day],
    series: ZoneSeries,
    rate: float,
    base: float = 72.0,
) -> LatentLoad | None:
    """Separate the cost of humid air from the cost of hot air.

    Cooling a desert house is mostly a sensible load — the air conditioner
    fights temperature. During the monsoon it also has to condense water, and
    that work does not show up in degree-days at all. Regressing daily kWh on
    degree-days *and* outdoor mixing ratio splits the two, provided the two
    regressors are not measuring the same thing; the reported VIF is what says
    whether that assumption held.
    """
    per_day = defaultdict(list)
    for i, stamp in enumerate(series.stamps):
        per_day[stamp.date()].append(series.w["outdoor"][i])
    counts = {d: len(v) for d, v in per_day.items()}

    pts = [
        (d.weather.cdd(base), statistics.fmean(per_day[d.date]), d.kwh)
        for d in days
        if d.kwh is not None
        and counts.get(d.date, 0) >= MIN_DAY_SAMPLES
        and d.weather.cdd(base) >= 1.0
    ]
    if len(pts) < 40:
        return None

    cdds = [p[0] for p in pts]
    ws = [p[1] for p in pts]
    kwh = [p[2] for p in pts]
    w_mean = statistics.fmean(ws)

    rows = [[1.0, c, w - w_mean] for c, w in zip(cdds, ws)]
    coef = solve_ols(rows, kwh)
    pred = [sum(a * b for a, b in zip(coef, row)) for row in rows]
    r2 = r_squared(kwh, pred)

    plain = solve_ols([[1.0, c] for c in cdds], kwh)
    r2_without = r_squared(kwh, [plain[0] + plain[1] * c for c in cdds])

    resid = [a - b for a, b in zip(kwh, pred)]
    sxx = sum((w - w_mean) ** 2 for w in ws)
    se = math.sqrt(sum(r * r for r in resid) / (len(pts) - 3))
    t_stat = coef[2] / (se / math.sqrt(sxx)) if sxx and se else 0.0
    rho = _corr(cdds, ws)

    dry = [p for p in pts if p[1] < 5]
    humid = [p for p in pts if p[1] > 11]
    dry_w = statistics.fmean(p[1] for p in dry) if dry else 0.0
    humid_w = statistics.fmean(p[1] for p in humid) if humid else 0.0
    gap = humid_w - dry_w

    # Season total is measured against the driest quarter of cooling days rather
    # than against zero moisture, which never happens here.
    floor = sorted(ws)[len(ws) // 4]
    season = sum(coef[2] * max(0.0, w - floor) for w in ws)

    return LatentLoad(
        base=base,
        n=len(pts),
        intercept=coef[0],
        per_cdd=coef[1],
        per_gram=coef[2],
        r2=r2,
        r2_without=r2_without,
        t_stat=t_stat,
        vif=1.0 / (1.0 - rho * rho) if abs(rho) < 1 else float("inf"),
        dry_w=dry_w,
        humid_w=humid_w,
        dry_days=len(dry),
        humid_days=len(humid),
        extra_kwh_day=coef[2] * gap,
        extra_cost_day=coef[2] * gap * rate,
        season_kwh=season,
        season_cost=season * rate,
    )


# ---------------------------------------------------------------------------
# Monsoon: how far the wet air gets, and how long it stays
# ---------------------------------------------------------------------------


@dataclass
class MonsoonResponse:
    zone: str
    label: str
    profile: list[float]     # mixing ratio change from the day before, d-1..d+4
    peak: float
    retained: float          # fraction of the peak still present on d+4


def monsoon_response(
    series: ZoneSeries, threshold: float = 0.05, span: int = 4
) -> tuple[list[MonsoonResponse], int]:
    """Track moisture into each zone across a rain event and back out again.

    Onsets only — a rain day preceded by another rain day is part of the same
    event, and counting it again would blur the arrival. What the profile shows
    is not just how much wet air gets in but how long each zone takes to give it
    back, which is a property of what the zone is made of rather than of how it
    is sealed.
    """
    days = _full_days(series)
    daily: dict[dt.date, dict[str, float]] = {
        day: {z: statistics.fmean(series.w[z][i] for i in idx) for z in ZONE_ORDER}
        for day, idx in days.items()
    }
    rain_days = sorted(
        day for day, idx in days.items() if max(series.rain[i] for i in idx) > threshold
    )
    rain_set = set(rain_days)
    onsets = [d for d in rain_days if (d - dt.timedelta(days=1)) not in rain_set]

    out: list[MonsoonResponse] = []
    for zone in ZONE_ORDER:
        profile: list[float] = []
        for offset in range(-1, span + 1):
            deltas = []
            for onset in onsets:
                before = onset - dt.timedelta(days=1)
                target = onset + dt.timedelta(days=offset)
                if before in daily and target in daily:
                    deltas.append(daily[target][zone] - daily[before][zone])
            profile.append(statistics.fmean(deltas) if deltas else 0.0)
        peak = max(profile)
        out.append(
            MonsoonResponse(
                zone=zone,
                label=ZONE_LABELS[zone],
                profile=profile,
                peak=peak,
                retained=profile[-1] / peak if peak > 0 else 0.0,
            )
        )
    return out, len(onsets)


# ---------------------------------------------------------------------------
# Diurnal shapes, for the small multiples
# ---------------------------------------------------------------------------


def diurnal(
    series: ZoneSeries, channel: str, dates: set[dt.date] | None = None
) -> dict[str, list[float]]:
    """Mean value in each hour of the day, per zone."""
    data = getattr(series, channel)
    buckets: dict[str, list[list[float]]] = {
        z: [[] for _ in range(24)] for z in ZONE_ORDER
    }
    for i, stamp in enumerate(series.stamps):
        if dates is not None and stamp.date() not in dates:
            continue
        for zone in ZONE_ORDER:
            buckets[zone][stamp.hour].append(data[zone][i])
    return {
        z: [statistics.fmean(h) if h else 0.0 for h in buckets[z]]
        for z in ZONE_ORDER
    }


def hottest_days(series: ZoneSeries, count: int = 30) -> set[dt.date]:
    days = _full_days(series)
    ranked = sorted(
        days,
        key=lambda d: max(series.temp["outdoor"][i] for i in days[d]),
        reverse=True,
    )
    return set(ranked[:count])
