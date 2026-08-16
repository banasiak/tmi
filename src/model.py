"""Statistical models over the joined daily record.

Deliberately dependency-free: the regressions here have two or three parameters,
so normal equations plus a small Gaussian elimination beat pulling in numpy and
let `python3 build.py` run anywhere.

Three families of model live here:

  Energy signature   Usage against degree-days, with the balance point *fitted*
                     rather than assumed at 65F. The balance point is the real
                     output — it says at what outdoor temperature the house
                     starts asking for heat or cooling.

  Anomaly detection  Robust residuals against the signature for gas, and a
                     rolling-baseline test for water (which has no strong
                     weather driver). Both are tuned to flag events worth a
                     phone call, not statistical curiosities.

  Cost decomposition Splits a change in a bill into the part you caused and the
                     part the rate schedule caused.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import psychro
from .sources import BillingPeriod, Day

# Robust scale estimator: for normally distributed residuals, 1.4826*MAD
# converges to the standard deviation but ignores the outliers we are hunting.
MAD_TO_SIGMA = 1.4826


# ---------------------------------------------------------------------------
# Small least-squares helper
# ---------------------------------------------------------------------------


def solve_ols(rows: list[list[float]], targets: list[float]) -> list[float]:
    """Least-squares fit via normal equations. `rows` includes the intercept."""
    k = len(rows[0])
    # Build X'X and X'y.
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * t for r, t in zip(rows, targets)) for i in range(k)]

    # Gaussian elimination with partial pivoting.
    aug = [row[:] + [rhs] for row, rhs in zip(xtx, xty)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return [0.0] * k
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for r in range(k):
            if r == col:
                continue
            factor = aug[r][col] / aug[col][col]
            for c in range(col, k + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][k] / aug[i][i] for i in range(k)]


def r_squared(actual: list[float], predicted: list[float]) -> float:
    mean = statistics.fmean(actual)
    ss_tot = sum((a - mean) ** 2 for a in actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - ss_res / ss_tot if ss_tot else 0.0


def robust_sigma(residuals: list[float]) -> float:
    med = statistics.median(residuals)
    mad = statistics.median([abs(r - med) for r in residuals])
    return MAD_TO_SIGMA * mad


# sqrt(pi/2): converts a mean absolute deviation into the equivalent sigma for
# normally distributed noise.
MAD_MEAN_TO_SIGMA = 1.2533


def proportional_scale(
    predicted: list[float], residuals: list[float], floor: float
) -> callable:
    """Build a noise model whose width grows with the predicted level.

    Utility meters are not homoscedastic. A furnace running 8 hours produces
    residuals an order of magnitude larger than one that never fires, so a
    single pooled sigma — dominated by 200 flat summer days — declares the
    entire heating season anomalous. Regressing |residual| on the prediction
    recovers a scale that widens where the data actually is noisy.
    """
    coef = solve_ols(
        [[1.0, max(p, 0.0)] for p in predicted], [abs(r) for r in residuals]
    )
    intercept, slope = coef[0], max(coef[1], 0.0)

    def scale(pred: float) -> float:
        return max(floor, MAD_MEAN_TO_SIGMA * (intercept + slope * max(pred, 0.0)))

    return scale


# ---------------------------------------------------------------------------
# Energy signature
# ---------------------------------------------------------------------------


@dataclass
class Signature:
    """A fitted usage-vs-degree-days relationship."""

    mode: str  # "heating" or "cooling"
    base_f: float  # fitted balance point
    baseline: float  # usage per day with zero degree-days
    slope: float  # usage per degree-day
    r2: float  # on the days the fit retained
    r2_all: float  # on every day, outliers included — the honest number
    n: int
    n_all: int
    unit: str
    excluded: list[dt.date]  # days held out of the fit as outliers

    def predict(self, degree_days: float) -> float:
        return self.baseline + self.slope * degree_days

    def degree_days(self, day: Day) -> float:
        return (
            day.weather.hdd(self.base_f)
            if self.mode == "heating"
            else day.weather.cdd(self.base_f)
        )


def fit_signature(
    days: list[Day],
    usage: str,
    mode: str,
    unit: str,
    base_range: tuple[int, int] = (45, 80),
    trim_iterations: int = 3,
    trim_k: float = 4.0,
    scale_floor: float = 5.0,
) -> Signature | None:
    """Fit usage ~ baseline + slope * degree_days, scanning for the balance point.

    The scan is the point: assuming 65F (the US convention) systematically
    misplaces the intercept for a well-insulated house or one with a large
    non-weather baseline, and that intercept is what we later call "baseline
    load".

    Outliers are trimmed against a *proportional* noise model, so a cold January
    day is judged against January-sized noise rather than against the flatness
    of August. Trimming keeps one pool-heater week from dragging the balance
    point; the proportional scale keeps it from eating the heating season.
    """
    pool = [d for d in days if getattr(d, usage) is not None]
    if len(pool) < 30:
        return None

    best: Signature | None = None
    for base_int in range(base_range[0], base_range[1] + 1):
        base = float(base_int)

        all_dd = [
            d.weather.hdd(base) if mode == "heating" else d.weather.cdd(base)
            for d in pool
        ]
        all_y = [float(getattr(d, usage)) for d in pool]
        if len({round(v, 6) for v in all_dd}) < 2:
            continue

        active = list(range(len(pool)))
        coef = [0.0, 0.0]

        for iteration in range(trim_iterations + 1):
            dd = [all_dd[i] for i in active]
            y = [all_y[i] for i in active]
            coef = solve_ols([[1.0, x] for x in dd], y)
            pred = [coef[0] + coef[1] * x for x in dd]
            resid = [a - p for a, p in zip(y, pred)]

            if iteration == trim_iterations:
                break

            scale = proportional_scale(pred, resid, scale_floor)
            keep = [i for i, p, r in zip(active, pred, resid) if abs(r) <= trim_k * scale(p)]
            if len(keep) == len(active) or len(keep) < 30:
                break
            active = keep

        # Score the surviving fit against every day, so a flattering trimmed R2
        # can never be reported on its own.
        pred_all = [coef[0] + coef[1] * x for x in all_dd]
        fit = Signature(
            mode=mode,
            base_f=base,
            baseline=coef[0],
            slope=coef[1],
            r2=r_squared([all_y[i] for i in active], [pred_all[i] for i in active]),
            r2_all=r_squared(all_y, pred_all),
            n=len(active),
            n_all=len(pool),
            unit=unit,
            excluded=sorted(pool[i].date for i in set(range(len(pool))) - set(active)),
        )
        # Select on the retained R2, not the all-days one: the balance point
        # describes routine heating behavior, and the excluded days are by
        # definition not heating. (Empirically r2_all is flat across the whole
        # base range here, so it carries no signal about the base anyway.)
        # A negative slope means "heating" load falls as it gets colder, which is
        # not a signature — it is noise finding a convenient base temperature.
        if fit.slope > 0 and (best is None or fit.r2 > best.r2):
            best = fit

    return best


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


@dataclass
class Anomaly:
    date: dt.date
    stream: str  # "water" | "gas"
    actual: float
    expected: float
    unit: str
    severity: str  # "critical" | "serious" | "warning"
    note: str

    @property
    def excess(self) -> float:
        return self.actual - self.expected

    @property
    def ratio(self) -> float:
        return self.actual / self.expected if self.expected > 0 else math.inf


def detect_gas_anomalies(
    days: list[Day], sig: Signature, min_excess_cf: float = 60.0, z_threshold: float = 4.0
) -> list[Anomaly]:
    """Flag days whose gas use the heating signature cannot account for.

    Two gates, both required. The proportional z-score catches the statistical
    outlier at whatever scale that day operates on; the absolute floor stops a
    6 cf day from being "300% of expected" on a mild day when expected was 2 cf.
    """
    pool = [d for d in days if d.gas_cf is not None]
    if not pool:
        return []
    pred = [sig.predict(sig.degree_days(d)) for d in pool]
    resid = [d.gas_cf - p for d, p in zip(pool, pred)]
    scale = proportional_scale(pred, resid, floor=5.0)

    out: list[Anomaly] = []
    for d, p, r in zip(pool, pred, resid):
        if r < min_excess_cf:
            continue
        z = r / scale(p)
        if z < z_threshold:
            continue
        severity = "critical" if z > 12 else "serious" if z > 7 else "warning"
        out.append(
            Anomaly(
                date=d.date,
                stream="gas",
                actual=d.gas_cf,
                expected=max(p, 0.0),
                unit="cf",
                severity=severity,
                note=(
                    f"{r:,.0f} cf beyond what a {d.weather.t_mean:.0f}°F day predicts"
                ),
            )
        )
    return out


def detect_water_anomalies(
    days: list[Day],
    window: int = 28,
    z_threshold: float = 5.0,
    min_excess_gal: float = 200.0,
) -> list[Anomaly]:
    """Flag water days against a trailing local baseline.

    Water has no usable weather driver at this house (refrigerated air, so no
    evaporative cooling load), and irrigation shifts the baseline seasonally.
    A trailing median tracks that drift, so what survives is a genuine step
    change rather than "summer arrived".
    """
    pool = [d for d in days if d.water_gal is not None]
    out: list[Anomaly] = []

    for i, d in enumerate(pool):
        history = [p.water_gal for p in pool[max(0, i - window) : i]]
        if len(history) < window // 2:
            continue
        baseline = statistics.median(history)
        sigma = robust_sigma(history)
        # A perfectly steady baseline gives sigma 0; fall back to a
        # proportional floor so the z-score stays finite and meaningful.
        sigma = max(sigma, 0.15 * baseline, 5.0)

        excess = d.water_gal - baseline
        if excess < min_excess_gal or excess / sigma < z_threshold:
            continue
        z = excess / sigma
        severity = "critical" if z > 20 else "serious" if z > 10 else "warning"
        out.append(
            Anomaly(
                date=d.date,
                stream="water",
                actual=d.water_gal,
                expected=baseline,
                unit="gal",
                severity=severity,
                note=f"{excess:,.0f} gal above the trailing {window}-day median",
            )
        )
    return out


@dataclass
class WarmDayGas:
    """Gas burned on days with no heating demand at all.

    Separating these out matters because they are a different phenomenon from a
    cold snap the model underestimated. If they cluster on weekends, the cause
    is recreational rather than mechanical — a heater someone switches on, not
    an appliance stuck open.
    """

    events: list[Anomaly]
    total_events: int
    weekend_events: int
    weekend_rate: float
    baseline_weekend_rate: float
    excess_cf: float
    share_of_annual: float

    @property
    def over_representation(self) -> float:
        if not self.baseline_weekend_rate:
            return 0.0
        return self.weekend_rate / self.baseline_weekend_rate


def analyse_warm_day_gas(
    days: list[Day], sig: Signature, anomalies: list[Anomaly], hdd_cutoff: float = 1.0
) -> WarmDayGas | None:
    """Split gas anomalies into 'the house was cold' and 'something else ran'."""
    by_date = {d.date: d for d in days}
    warm = [
        a
        for a in anomalies
        if a.stream == "gas"
        and a.date in by_date
        and by_date[a.date].weather.hdd(sig.base_f) < hdd_cutoff
    ]
    if not warm:
        return None

    annual = sum(d.gas_cf for d in days if d.gas_cf is not None)
    weekend = sum(1 for a in warm if a.date.weekday() >= 5)
    baseline = sum(1 for d in days if d.date.weekday() >= 5) / len(days)
    excess = sum(a.excess for a in warm)
    return WarmDayGas(
        events=sorted(warm, key=lambda a: a.date),
        total_events=len(warm),
        weekend_events=weekend,
        weekend_rate=weekend / len(warm),
        baseline_weekend_rate=baseline,
        excess_cf=excess,
        share_of_annual=excess / annual if annual else 0.0,
    )






@dataclass
class StormDay:
    """A day the weather station recorded convective activity."""

    date: dt.date
    strikes: float
    rain_in: float
    rain_rate_max: float
    gust_max: float
    pressure_min: float


def monsoon_days(days: list[Day], min_strikes: float = 1.0) -> list[StormDay]:
    return [
        StormDay(
            date=d.date,
            strikes=d.weather.strikes,
            rain_in=d.weather.rain_in,
            rain_rate_max=d.weather.rain_rate_max,
            gust_max=d.weather.gust_max,
            pressure_min=d.weather.pressure_mean,
        )
        for d in days
        if d.weather.strikes >= min_strikes or d.weather.rain_in > 0.0
    ]


@dataclass
class IrrigationMonth:
    """One month's irrigation schedule and volume, recovered from daily meter data.

    Daily resolution cannot see a valve open, but a controller running to a
    weekly schedule leaves the pattern anyway: three weekdays sit far above the
    other four, every week, for months. The gap between them is the water the
    controller delivered.
    """

    month: str
    watering_days: list[int]  # weekday indices, Monday = 0
    baseline_gal: float  # a non-watering day
    per_event_gal: float  # the surplus on a watering day
    mean_temp: float
    rain_in: float
    day_medians: dict[int, float] = field(default_factory=dict, repr=False)

    @property
    def weekly_gal(self) -> float:
        return self.per_event_gal * len(self.watering_days)

    @property
    def schedule(self) -> str:
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return "/".join(names[i] for i in sorted(self.watering_days))


def detect_irrigation(
    days: list[Day], events_per_week: int = 3, exclude: set[dt.date] | None = None
) -> list[IrrigationMonth]:
    """Recover the irrigation schedule and volume, month by month.

    The schedule is re-detected each month rather than assumed, because
    controllers get reprogrammed — and when that happens, the change is itself
    a finding.
    """
    exclude = exclude or set()
    buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    weather: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for d in days:
        if d.water_gal is None or d.date in exclude:
            continue
        key = f"{d.date:%Y-%m}"
        buckets[key][d.weekday].append(d.water_gal)
        weather[key].append((d.weather.t_mean, d.weather.rain_in))

    out: list[IrrigationMonth] = []
    for key in sorted(buckets):
        by_day = buckets[key]
        # Need every weekday represented before a schedule can be read off.
        if len(by_day) < 7 or any(not v for v in by_day.values()):
            continue
        medians = {i: statistics.median(v) for i, v in by_day.items()}
        ranked = sorted(medians, key=lambda i: -medians[i])
        watering = sorted(ranked[:events_per_week])
        rest = ranked[events_per_week:]

        baseline = statistics.median([medians[i] for i in rest])
        per_event = statistics.median([medians[i] for i in watering]) - baseline
        if per_event <= 0:
            continue

        temps = weather[key]
        out.append(
            IrrigationMonth(
                month=key,
                watering_days=watering,
                baseline_gal=baseline,
                per_event_gal=per_event,
                mean_temp=statistics.fmean(t for t, _ in temps),
                rain_in=sum(r for _, r in temps),
                day_medians=medians,
            )
        )
    return out


@dataclass
class IrrigationEvent:
    date: dt.date
    weekday: int
    gallons: float  # surplus over the local non-watering baseline


@dataclass
class IrrigationConsistency:
    """Event-to-event steadiness, and what a fault would have to do to show.

    This matters because the weekly-floor leak test cannot see an irrigation
    fault at all. A burst downstream of the valve only leaks while the valve is
    open, so the quiet days stay quiet and the floor never moves — the damage
    shows up entirely in how much each cycle delivers. Watching event volume is
    a different monitor from watching the baseline, and only one of them can
    catch a broken line.
    """

    events: list[IrrigationEvent]
    monthly_median: dict[str, float]
    monthly_cv: dict[str, float]
    typical_scatter: float  # gallons, 1 sd within a month
    detectable_step: float  # gallons per event
    largest_jump: tuple[str, float] | None  # month, change from the month before


def irrigation_consistency(
    days: list[Day],
    months: list[IrrigationMonth],
    exclude: set[dt.date] | None = None,
    window: int = 10,
) -> IrrigationConsistency | None:
    """Measure each watering event against its own local baseline."""
    exclude = exclude or set()
    schedule = {m.month: set(m.watering_days) for m in months}
    pool = [d for d in days if d.water_gal is not None and d.date not in exclude]

    events: list[IrrigationEvent] = []
    for i, d in enumerate(pool):
        sched = schedule.get(f"{d.date:%Y-%m}")
        if not sched or d.weekday not in sched:
            continue
        quiet = [
            p.water_gal
            for p in pool[max(0, i - window) : i + window + 1]
            if p.weekday not in schedule.get(f"{p.date:%Y-%m}", set())
        ]
        if len(quiet) < 5:
            continue
        events.append(
            IrrigationEvent(d.date, d.weekday, d.water_gal - statistics.median(quiet))
        )
    if len(events) < 24:
        return None

    grouped: dict[str, list[float]] = defaultdict(list)
    for e in events:
        grouped[f"{e.date:%Y-%m}"].append(e.gallons)
    usable = {k: v for k, v in grouped.items() if len(v) >= 6}
    if not usable:
        return None

    medians = {k: statistics.median(v) for k, v in usable.items()}
    cvs = {
        k: statistics.stdev(v) / statistics.fmean(v)
        for k, v in usable.items()
        if statistics.fmean(v)
    }
    scatter = statistics.median([statistics.stdev(v) for v in usable.values()])

    jump = None
    keys = sorted(usable)
    for a, b in zip(keys, keys[1:]):
        change = medians[b] - medians[a]
        if jump is None or abs(change) > abs(jump[1]):
            jump = (b, change)

    return IrrigationConsistency(
        events=events,
        monthly_median=medians,
        monthly_cv=cvs,
        typical_scatter=scatter,
        detectable_step=2 * scatter,
        largest_jump=jump,
    )


def schedule_changes(
    months: list[IrrigationMonth], margin: float = 0.25
) -> list[tuple[str, str, str]]:
    """Months where the watering days genuinely changed.

    A bare set comparison reports a change whenever two days are nearly tied for
    third place, which is noise rather than a reprogrammed controller. A swap
    only counts when the day gained stands clearly above the day dropped, in
    both months.
    """
    out = []
    for prev, cur in zip(months, months[1:]):
        gained = set(cur.watering_days) - set(prev.watering_days)
        dropped = set(prev.watering_days) - set(cur.watering_days)
        if not gained or not dropped:
            continue
        # Judge the swap in the month that claims it, and confirm in the other.
        def separated(month: IrrigationMonth, high: set[int], low: set[int]) -> bool:
            # Compare medians rather than the extremes: one non-watering day that
            # happens to run high should not veto a real reprogramming.
            if not month.day_medians:
                return False
            hi = statistics.median([month.day_medians[i] for i in high])
            lo = statistics.median([month.day_medians[i] for i in low])
            return hi > lo * (1 + margin)

        if separated(cur, gained, dropped) and separated(prev, dropped, gained):
            out.append((cur.month, prev.schedule, cur.schedule))
    return out


@dataclass
class Attribution:
    """A flagged day, and what the rest of the record says caused it."""

    anomaly: Anomaly
    cause: str  # "pool-heating" | "spa" | "refill" | "pool-adjacent" | "open"
    detail: str

    @property
    def resolved(self) -> bool:
        return self.cause != "open"


# Heat content of the gas (from the bill's own Mcf-to-Dth factor) times a
# typical heater efficiency, in BTU per cubic foot delivered to the water.
DELIVERED_BTU_PER_CF = 896.0 * 0.80
WATER_BTU_PER_GAL_DEGF = 8.34
# A day counts as pool heating when at least this share of the unexplained gas
# turns up as stored heat in the water the next morning. Overnight losses in a
# desert winter are large, so the bar is deliberately well under 1.
POOL_ENERGY_SHARE = 0.20


def pool_energy_ratio(
    date: dt.date,
    excess_cf: float,
    samples: dict[dt.date, list[tuple[dt.datetime, float, float, float]]],
    volume_gal: float,
    hour: int = 6,
) -> float | None:
    """How much of a day's excess gas ended up as heat in the water.

    Anchored at 06:00 on consecutive mornings, when the water is best mixed and
    solar gain is zero. A ratio near or above the threshold means the heater
    ran, whatever the air temperature was doing — which is what makes this test
    work in January, where a heated pool goes from 48F to 61F and never
    approaches the spa temperatures a threshold test looks for.
    """
    def morning(day: dt.date) -> float | None:
        vals = [p for t, p, _, _ in samples.get(day, []) if t.hour == hour]
        return statistics.fmean(vals) if vals else None

    start = morning(date)
    end = morning(date + dt.timedelta(days=1))
    if start is None or end is None or excess_cf <= 0:
        return None
    stored = (end - start) * volume_gal * WATER_BTU_PER_GAL_DEGF
    delivered = excess_cf * DELIVERED_BTU_PER_CF
    return stored / delivered if delivered else None


CAUSE_LABELS = {
    "pool-heating": "Pool heater — the water absorbed the missing gas",
    "spa": "Spa soak — probe moved into the spa, reached 110°F after dark",
    "refill": "Drain and refill of the whole pool and spa",
    "pool-adjacent": "Same day as a pool-heating event",
    "open": "Not accounted for",
}


def attribute_anomalies(
    days: list[Day],
    sig: Signature,
    gas_anomalies: list[Anomaly],
    water_anomalies: list[Anomaly],
    water_events: list[WaterFeature],
    refill_dates: set[dt.date],
    water_samples: dict | None = None,
    pool_gallons: float = 5000.0,
    hdd_cutoff: float = 1.0,
) -> list[Attribution]:
    """Match each flagged day against everything else the record knows.

    Detection and explanation are separate jobs. The detector only says a day
    departs from what the weather predicts; deciding *why* needs the water
    probe, the calendar, and the other meters. Keeping the two apart means the
    thresholds never get quietly tuned to make a story come out.
    """
    by_date = {d.date: d for d in days}
    spa_days = {e.date for e in water_events if e.kind == "spa"}
    gas_days = {a.date for a in gas_anomalies}
    out: list[Attribution] = []

    for a in gas_anomalies:
        day = by_date.get(a.date)
        warm = day is not None and day.weather.hdd(sig.base_f) < hdd_cutoff
        ratio = (
            pool_energy_ratio(a.date, a.excess, water_samples, pool_gallons)
            if water_samples
            else None
        )

        # Order matters. The spa test is the most specific — the probe is moved
        # into the spa during a soak, so a hot reading after dark is deliberate
        # placement rather than inference. The energy test is the general one
        # and works in any season.
        # The no-heating-demand rule is the weakest and comes last, because it
        # argues from what the weather did rather than from what the water did.
        if a.date in spa_days:
            out.append(Attribution(a, "spa", "probe in the spa, 110°F reached after sunset"))
        elif ratio is not None and ratio >= POOL_ENERGY_SHARE:
            out.append(
                Attribution(a, "pool-heating", f"{ratio:.0%} of it stored in the water by morning")
            )
        elif warm:
            out.append(
                Attribution(a, "pool-heating", f"{day.weather.t_mean:.0f}°F mean, no heating demand")
            )
        else:
            out.append(
                Attribution(a, "open", f"{day.weather.t_mean:.0f}°F mean, no water-temperature response")
            )

    for a in water_anomalies:
        if a.date in refill_dates:
            out.append(Attribution(a, "refill", "the system going back in"))
        elif a.date in gas_days:
            out.append(Attribution(a, "pool-adjacent", "top-up alongside heating"))
        else:
            day = by_date.get(a.date)
            when = f"{a.date:%A}" if day else ""
            out.append(Attribution(a, "open", f"{when}, not an irrigation day"))

    out.sort(key=lambda x: x.anomaly.date, reverse=True)
    return out


def attribution_summary(items: list[Attribution]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.cause] = counts.get(item.cause, 0) + 1
    return counts


@dataclass
class LeakWindow:
    """A stretch where water use never returned to a plausible idle level.

    Daily meter data cannot see a dripping fixture directly, but a continuous
    leak lifts the *floor*: the quietest day of the week stops being quiet. That
    floor is the signal here.
    """

    start: dt.date
    end: dt.date
    floor_gal: float
    typical_floor_gal: float


@dataclass
class LeakSensitivity:
    """How large a leak this test could actually see.

    A null result is only worth as much as the test's sensitivity, so that
    sensitivity is reported alongside it. The floor is set by the household's
    own quietest days: a leak has to lift the weekly minimum past the trip
    multiple before anything registers, and at daily resolution that leaves a
    real band of small persistent leaks invisible.
    """

    typical_floor_gal: float
    trip_threshold_gal: float
    detectable_leak_gal: float
    windows_flagged: int


def leak_sensitivity(
    days: list[Day], window: int = 7, multiple: float = 2.5
) -> LeakSensitivity | None:
    pool = [d for d in days if d.water_gal is not None]
    if len(pool) < window * 4:
        return None
    floors = [
        min(c.water_gal for c in pool[i : i + window])
        for i in range(len(pool) - window + 1)
    ]
    typical = statistics.median(floors)
    return LeakSensitivity(
        typical_floor_gal=typical,
        trip_threshold_gal=typical * multiple,
        detectable_leak_gal=typical * (multiple - 1),
        windows_flagged=len(detect_leak_windows(days, window, multiple)),
    )


def detect_leak_windows(
    days: list[Day], window: int = 7, multiple: float = 2.5
) -> list[LeakWindow]:
    pool = [d for d in days if d.water_gal is not None]
    if len(pool) < window * 4:
        return []

    floors = []
    for i in range(len(pool) - window + 1):
        chunk = pool[i : i + window]
        floors.append((chunk[0].date, chunk[-1].date, min(c.water_gal for c in chunk)))

    typical = statistics.median([f[2] for f in floors])
    threshold = typical * multiple

    flagged: list[LeakWindow] = []
    for start, end, floor in floors:
        if floor <= threshold:
            continue
        # Merge into the previous window when they overlap, so a two-week leak
        # reports as one event rather than eight sliding windows.
        if flagged and start <= flagged[-1].end:
            prev = flagged[-1]
            flagged[-1] = LeakWindow(prev.start, end, max(prev.floor_gal, floor), typical)
        else:
            flagged.append(LeakWindow(start, end, floor, typical))
    return flagged


# ---------------------------------------------------------------------------
# Electric: rates and weather normalisation
# ---------------------------------------------------------------------------





@dataclass
class ElectricModel:
    baseline_kwh_day: float
    cooling_slope: float  # kWh per cooling degree-day
    heating_slope: float  # kWh per heating degree-day
    cool_base_f: float
    heat_base_f: float
    r2: float
    n: int

    def predict(self, day: Day) -> float:
        return (
            self.baseline_kwh_day
            + self.cooling_slope * day.weather.cdd(self.cool_base_f)
            + self.heating_slope * day.weather.hdd(self.heat_base_f)
        )


def fit_electric(
    days: list[Day],
    cool_range: tuple[int, int] = (55, 85),
    heat_range: tuple[int, int] = (45, 70),
) -> tuple[ElectricModel | None, list[Day]]:
    """Fit daily kWh against cooling and heating degree-days.

    With interval data this runs on ~364 daily observations rather than a dozen
    billing periods, so both balance points and the intercept are identified far
    more tightly. The intercept is the number that matters: it is consumption
    that no amount of weather explains.
    """
    pool = [d for d in days if d.kwh is not None]
    if len(pool) < 60:
        return None, []

    y = [d.kwh for d in pool]
    best: ElectricModel | None = None

    for cool_int in range(cool_range[0], cool_range[1] + 1):
        cdd = [d.weather.cdd(float(cool_int)) for d in pool]
        for heat_int in range(heat_range[0], heat_range[1] + 1):
            hdd = [d.weather.hdd(float(heat_int)) for d in pool]
            coef = solve_ols([[1.0, c, h] for c, h in zip(cdd, hdd)], y)
            # Both slopes must be physical: hotter means more AC, colder means
            # more furnace blower and resistance load. A negative slope is the
            # fit exploiting collinearity, not a discovery.
            if coef[1] <= 0 or coef[2] < 0:
                continue
            pred = [coef[0] + coef[1] * c + coef[2] * h for c, h in zip(cdd, hdd)]
            r2 = r_squared(y, pred)
            if best is None or r2 > best.r2:
                best = ElectricModel(
                    baseline_kwh_day=coef[0],
                    cooling_slope=coef[1],
                    heating_slope=coef[2],
                    cool_base_f=float(cool_int),
                    heat_base_f=float(heat_int),
                    r2=r2,
                    n=len(pool),
                )

    return best, pool


# ---------------------------------------------------------------------------
# Interval-level structure
# ---------------------------------------------------------------------------

SLOTS_PER_DAY = 96


@dataclass
class LoadProfile:
    """An average day's load shape, in kW per 15-minute slot."""

    label: str
    slots: list[float]
    days: int
    mean_temp: float

    @property
    def daily_kwh(self) -> float:
        return sum(self.slots) / 4.0

    def peak_slot(self) -> int:
        return max(range(len(self.slots)), key=lambda i: self.slots[i])


def profile_by_temp_band(
    days: list[Day], bands: list[tuple[str, float, float]]
) -> list[LoadProfile]:
    """Average load shape for each outdoor-temperature band.

    Differencing a hot band against a mild one isolates the cooling load by
    time of day without ever needing a submeter on the condenser.
    """
    out: list[LoadProfile] = []
    for label, lo, hi in bands:
        members = [
            d
            for d in days
            if d.electric and lo <= d.weather.t_mean < hi and d.electric.profile
        ]
        if len(members) < 5:
            continue
        slots: list[float] = []
        for i in range(SLOTS_PER_DAY):
            vals = [
                d.electric.profile[i] * 4.0
                for d in members
                if d.electric.profile[i] is not None
            ]
            slots.append(statistics.fmean(vals) if vals else 0.0)
        out.append(
            LoadProfile(
                label=label,
                slots=slots,
                days=len(members),
                mean_temp=statistics.fmean(d.weather.t_mean for d in members),
            )
        )
    return out


@dataclass
class BaseloadStats:
    """The always-on floor, and what it costs to leave running.

    Measured as each day's 5th-percentile power, then summarised across the
    year. A floor this stable is equipment that never turns off, not behavior.
    """

    median_kw: float
    min_kw: float
    p90_kw: float
    annual_kwh: float
    share_of_total: float
    seasonal_spread_kw: float
    by_month: dict[str, float]


def analyse_baseload(days: list[Day]) -> BaseloadStats | None:
    pool = [d for d in days if d.electric is not None]
    if len(pool) < 30:
        return None

    floors = [d.electric.baseload_kw for d in pool]
    by_month: dict[str, list[float]] = defaultdict(list)
    for d in pool:
        by_month[f"{d.date:%Y-%m}"].append(d.electric.baseload_kw)
    monthly = {k: statistics.median(v) for k, v in sorted(by_month.items())}

    median = statistics.median(floors)
    total = sum(d.kwh for d in pool)
    annual = median * 24.0 * len(pool)
    return BaseloadStats(
        median_kw=median,
        min_kw=min(floors),
        p90_kw=sorted(floors)[int(len(floors) * 0.9)],
        annual_kwh=annual,
        share_of_total=annual / total if total else 0.0,
        seasonal_spread_kw=max(monthly.values()) - min(monthly.values()),
        by_month=monthly,
    )



@dataclass
class ScheduledLoad:
    """A load that switches at the same clock time every day.

    Equipment on a timer leaves a signature nothing else does: a step in the
    *median* load profile, at a fixed slot, that survives averaging over
    hundreds of days. Occupant behavior smears across an hour or more and
    differs on weekends; a timer does not.
    """

    start_slot: int
    end_slot: int
    magnitude_kw: float
    daily_kwh: float
    annual_kwh: float
    share_of_total: float
    weekday_kwh: float
    weekend_kwh: float

    @staticmethod
    def _clock(slot: int) -> str:
        return f"{slot // 4 % 24:02d}:{15 * (slot % 4):02d}"

    @property
    def start_time(self) -> str:
        return self._clock(self.start_slot)

    @property
    def end_time(self) -> str:
        return self._clock(self.end_slot)

    @property
    def hours(self) -> float:
        return (self.end_slot - self.start_slot) / 4.0


def detect_scheduled_load(
    days: list[Day],
    mild_band: tuple[float, float] = (58.0, 72.0),
    step_kw: float = 0.35,
) -> ScheduledLoad | None:
    """Find a timer-driven block in the median mild-day load profile.

    Restricted to mild days on purpose: on hot days the air conditioner's own
    cycling swamps every other step in the profile. On mild days the HVAC is
    mostly idle, so whatever remains is equipment running to a clock.
    """
    mild = [
        d
        for d in days
        if d.electric and d.electric.profile and mild_band[0] <= d.weather.t_mean < mild_band[1]
    ]
    if len(mild) < 30:
        return None

    median_profile: list[float] = []
    for i in range(SLOTS_PER_DAY):
        vals = [d.electric.profile[i] * 4.0 for d in mild if d.electric.profile[i] is not None]
        median_profile.append(statistics.median(vals) if vals else 0.0)

    steps = [median_profile[i] - median_profile[i - 1] for i in range(1, SLOTS_PER_DAY)]

    # Largest sustained rise, then the largest fall after it.
    rise = max(range(len(steps)), key=lambda i: steps[i])
    if steps[rise] < step_kw:
        return None
    after = steps[rise + 1 :]
    if not after:
        return None
    fall = rise + 1 + min(range(len(after)), key=lambda i: after[i])
    if steps[fall] > -step_kw:
        return None

    start_slot, end_slot = rise + 1, fall + 1
    if end_slot - start_slot < 4:
        return None

    # Magnitude: how far the block sits above the surrounding shoulders. Using
    # the quieter shoulder keeps an evening cooking peak from inflating it.
    inside = median_profile[start_slot:end_slot]
    before = statistics.median(median_profile[max(0, start_slot - 8) : start_slot])
    behind = statistics.median(median_profile[end_slot : min(SLOTS_PER_DAY, end_slot + 8)])
    magnitude = statistics.median(inside) - max(before, behind)
    if magnitude <= 0:
        return None

    daily = magnitude * (end_slot - start_slot) / 4.0
    with_electric = [d for d in days if d.electric]
    total = sum(d.kwh for d in with_electric)
    annual = daily * len(with_electric)

    weekday = [d.kwh for d in mild if d.weekday < 5]
    weekend = [d.kwh for d in mild if d.weekday >= 5]

    return ScheduledLoad(
        start_slot=start_slot,
        end_slot=end_slot,
        magnitude_kw=magnitude,
        daily_kwh=daily,
        annual_kwh=annual,
        share_of_total=annual / total if total else 0.0,
        weekday_kwh=statistics.fmean(weekday) if weekday else 0.0,
        weekend_kwh=statistics.fmean(weekend) if weekend else 0.0,
    )


@dataclass
class PumpConfirmation:
    """Independent corroboration that the timer block moves water.

    The electric meter shows a block switching on at a fixed time. If that block
    is a circulation pump, a thermometer in the water loop must see a step at
    the same instant — and crucially, at a time when sun and air temperature are
    both falling, so neither can be the cause.
    """

    slot: int
    step_rate: float  # degF per 5-min sample in the switch-on slot
    neighbour_rate: float  # mean rate in the surrounding slots
    ratio: float
    solar_before: float
    solar_after: float
    outdoor_trend: float  # degF per 5-min sample, at the switch-on slot

    @property
    def clock(self) -> str:
        return f"{self.slot // 4:02d}:{15 * (self.slot % 4):02d}"


def confirm_pump(
    weather_samples: list[tuple[dt.datetime, float, float, float]], slot: int
) -> PumpConfirmation | None:
    """Test the water-temperature step at a given time-of-day slot.

    `weather_samples` is (timestamp, water_temp_f, solar, outdoor_f) at native
    5-minute resolution. Sorted ascending.
    """
    deltas: dict[int, list[float]] = defaultdict(list)
    solar: dict[int, list[float]] = defaultdict(list)
    outdoor: dict[int, list[float]] = defaultdict(list)

    for (t0, w0, _, o0), (t1, w1, s1, o1) in zip(weather_samples, weather_samples[1:]):
        if (t1 - t0).total_seconds() != 300:
            continue
        s = t1.hour * 4 + t1.minute // 15
        deltas[s].append(w1 - w0)
        solar[s].append(s1)
        outdoor[s].append(o1 - o0)

    if slot not in deltas or len(deltas[slot]) < 30:
        return None

    def mean_of(source, a: int, b: int) -> float:
        vals = [statistics.fmean(source[s]) for s in range(a, b) if s in source]
        return statistics.fmean(vals) if vals else 0.0

    step = statistics.fmean(deltas[slot])
    # Compare against the slots either side, skipping the switch-on slot itself.
    neighbours = [
        statistics.fmean(deltas[s])
        for s in (slot - 2, slot - 1, slot + 1, slot + 2)
        if s in deltas
    ]
    neighbour = statistics.fmean(neighbours) if neighbours else 0.0
    if neighbour <= 0 or step <= 0:
        return None

    return PumpConfirmation(
        slot=slot,
        step_rate=step,
        neighbour_rate=neighbour,
        ratio=step / neighbour,
        solar_before=mean_of(solar, max(slot - 4, 0), slot),
        solar_after=mean_of(solar, slot + 1, slot + 5),
        outdoor_trend=statistics.fmean(outdoor[slot]),
    )


def slot_means(
    weather_samples: list[tuple[dt.datetime, float, float, float]],
) -> tuple[list[float], list[float], list[float]]:
    """Per-slot mean water-temperature delta, solar, and outdoor temperature."""
    deltas: dict[int, list[float]] = defaultdict(list)
    solar: dict[int, list[float]] = defaultdict(list)
    outdoor: dict[int, list[float]] = defaultdict(list)
    for (t0, w0, _, _o0), (t1, w1, s1, o1) in zip(weather_samples, weather_samples[1:]):
        if (t1 - t0).total_seconds() != 300:
            continue
        s = t1.hour * 4 + t1.minute // 15
        deltas[s].append(w1 - w0)
        solar[s].append(s1)
        outdoor[s].append(o1)
    fill = lambda src: [  # noqa: E731
        statistics.fmean(src[s]) if s in src else 0.0 for s in range(SLOTS_PER_DAY)
    ]
    return fill(deltas), fill(solar), fill(outdoor)


@dataclass
class WaterFeature:
    """A day where the water-temperature probe reveals what the gas was doing."""

    date: dt.date
    kind: str  # "spa" | "dry" | "heater"
    peak_f: float
    window: str
    solar_at_peak: float
    gas_cf: float
    # Water temperature before the event began. Taken from the samples that
    # precede the hot window, since the day's mean is inflated by the event.
    start_f: float = 0.0
    minutes_hot: float = 0.0  # how long it stayed above the threshold
    # Largest single-sample rise leading into the event. Moving the probe by
    # hand produces one; nothing thermal does.
    step_f: float = 0.0


def classify_water_events(
    days: list[Day],
    samples_by_day: dict[dt.date, list[tuple[dt.datetime, float, float, float]]],
    hot_threshold: float = 100.0,
) -> list[WaterFeature]:
    """Separate spa soaks from a probe left dry.

    Both read far above pool temperature, but for opposite reasons and at
    opposite times. The probe is relocated into the spa while it heats, so a
    reading near 110F after sunset alongside a large gas draw is a soak, tracked
    deliberately. A probe left in air is hottest in the afternoon under full sun,
    and the gas meter stays quiet because nothing is being heated at all.

    110F is both the heater's setting and the alert threshold, which is why three
    separate evenings peak within a tenth of a degree of each other. The same
    alert catches the probe when it is accidentally pulled clear of the water —
    and how long it then stays out is itself informative, since an excursion that
    never quite reaches 110F raises no alarm and goes unnoticed for hours.
    """
    by_date = {d.date: d for d in days}
    out: list[WaterFeature] = []

    for day, samples in sorted(samples_by_day.items()):
        hot = [(t, w, s) for t, w, s, _ in samples if w > hot_threshold]
        if not hot:
            continue
        _peak_t, peak_w, peak_solar = max(hot, key=lambda r: r[1])
        gas = by_date[day].gas_cf if day in by_date and by_date[day].gas_cf else 0.0
        before = [w for t, w, _, _ in samples if t < hot[0][0]]
        start = statistics.median(before[-24:]) if before else peak_w
        minutes = (hot[-1][0] - hot[0][0]).total_seconds() / 60.0
        # Scan the hour before the excursion for a single-sample jump.
        run_up = [(t, wv) for t, wv, _, _ in samples if t <= hot[0][0]][-13:]
        step = max(
            (b[1] - a[1] for a, b in zip(run_up, run_up[1:])), default=0.0
        )

        if peak_solar > 200 and gas < 100:
            kind = "dry"
        elif peak_solar < 50:
            kind = "spa"
        else:
            kind = "heater"

        out.append(
            WaterFeature(
                date=day,
                kind=kind,
                peak_f=peak_w,
                window=f"{hot[0][0]:%H:%M}–{hot[-1][0]:%H:%M}",
                solar_at_peak=peak_solar,
                gas_cf=gas,
                start_f=start,
                minutes_hot=minutes,
                step_f=step,
            )
        )
    return out


def median_profile(days: list[Day], predicate=None) -> list[float]:
    """Median kW for each 15-minute slot across the selected days."""
    pool = [
        d
        for d in days
        if d.electric and d.electric.profile and (predicate is None or predicate(d))
    ]
    out: list[float] = []
    for i in range(SLOTS_PER_DAY):
        vals = [d.electric.profile[i] * 4.0 for d in pool if d.electric.profile[i] is not None]
        out.append(statistics.median(vals) if vals else 0.0)
    return out


@dataclass
class MeterCheck:
    """Agreement between the interval export and the billed meter reads.

    NOT two independent measurements. Both files are the utility's rendering of
    the same smart meter register, so agreement says nothing about whether the
    meter is accurate — a miscalibrated meter would be miscalibrated in both.

    What it does check is the pipeline between that meter and this code:
    a misaligned billing-period boundary, intervals dropped from the export,
    a unit or scaling error in parsing, or mishandled daylight saving would all
    break the sum. Those are the failure modes actually in play here, and this
    is the only end-to-end test available for them.
    """

    periods: int
    billed_kwh: float
    interval_kwh: float
    mean_deviation_pct: float
    worst_deviation_pct: float

    @property
    def total_deviation_pct(self) -> float:
        if not self.billed_kwh:
            return 0.0
        return 100.0 * (self.interval_kwh - self.billed_kwh) / self.billed_kwh


def validate_against_billing(periods: list[BillingPeriod], days: list[Day]) -> MeterCheck | None:
    """Sum interval readings over each fully covered billing period and compare."""
    by_date = {d.date: d for d in days if d.electric is not None}
    deviations: list[float] = []
    billed_total = 0.0
    interval_total = 0.0
    matched = 0

    for p in periods:
        span = [p.start + dt.timedelta(days=i) for i in range(p.days)]
        # Only fully covered periods; a partial one would always look short.
        if not all(d in by_date for d in span) or not p.kwh:
            continue
        total = sum(by_date[d].kwh for d in span)
        deviations.append(100.0 * (total - p.kwh) / p.kwh)
        billed_total += p.kwh
        interval_total += total
        matched += 1

    if not matched:
        return None
    return MeterCheck(
        periods=matched,
        billed_kwh=billed_total,
        interval_kwh=interval_total,
        mean_deviation_pct=statistics.fmean(deviations),
        worst_deviation_pct=max(abs(d) for d in deviations),
    )


@dataclass
class YearOverYear:
    label: str
    kwh: float
    cost: float
    prev_kwh: float | None
    prev_cost: float | None

    @property
    def usage_effect(self) -> float | None:
        """Dollars attributable to using more/less at last year's rate."""
        if self.prev_kwh is None or self.prev_cost is None or self.prev_kwh == 0:
            return None
        prev_rate = self.prev_cost / self.prev_kwh
        return (self.kwh - self.prev_kwh) * prev_rate

    @property
    def rate_effect(self) -> float | None:
        """Dollars attributable to the rate moving, holding usage at this year's."""
        if self.prev_kwh is None or self.prev_cost is None or self.kwh == 0:
            return None
        prev_rate = self.prev_cost / self.prev_kwh
        return self.cost - self.kwh * prev_rate


def decompose_year_over_year(periods: list[BillingPeriod]) -> list[YearOverYear]:
    """Split each bill's change from the same period last year into usage vs rate.

    Works across the full three-year history because it needs no weather data —
    which matters, since only the final year of station data can be exported.
    """
    by_month: dict[tuple[int, int], BillingPeriod] = {}
    for p in periods:
        # Attribute a period to the month containing most of its days.
        mid = p.start + dt.timedelta(days=p.days // 2)
        by_month[(mid.year, mid.month)] = p

    out: list[YearOverYear] = []
    for (year, month), p in sorted(by_month.items()):
        prev = by_month.get((year - 1, month))
        out.append(
            YearOverYear(
                label=f"{year}-{month:02d}",
                kwh=p.kwh,
                cost=p.cost,
                prev_kwh=prev.kwh if prev else None,
                prev_cost=prev.cost if prev else None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Building envelope
# ---------------------------------------------------------------------------


@dataclass
class EnvelopeStats:
    """How the house responds thermally to the weather outside it.

    `damping` is the headline: the fraction of the outdoor daily temperature
    swing that makes it indoors. Lower is a better envelope. It is measured on
    mild days only, because on days when the HVAC runs hard the thermostat —
    not the envelope — is setting indoor temperature.
    """

    damping: float
    mild_days: int
    indoor_mean: float
    indoor_swing_mean: float
    outdoor_swing_mean: float
    setpoint_cool: float | None
    setpoint_heat: float | None
    garage_damping: float | None


def fit_envelope(
    days: list[Day], mild_band: tuple[float, float] = (58.0, 72.0)
) -> EnvelopeStats | None:
    usable = [d for d in days if d.weather.t_in_swing is not None]
    if len(usable) < 30:
        return None

    mild = [d for d in usable if mild_band[0] <= d.weather.t_mean <= mild_band[1]]
    if len(mild) < 10:
        mild = usable

    coef = solve_ols(
        [[1.0, d.weather.t_swing] for d in mild],
        [d.weather.t_in_swing for d in mild],
    )

    # The thermostat reveals itself as the indoor temperature the house settles
    # at when the weather is pushing hardest in each direction.
    hot = sorted(usable, key=lambda d: d.weather.t_mean, reverse=True)[:30]
    cold = sorted(usable, key=lambda d: d.weather.t_mean)[:30]

    # Swing on swing, exactly as the house is measured above — an uninsulated
    # box is only a meaningful contrast if it is the same measurement. The
    # earlier version regressed garage *mean* on outdoor *mean* and got 88%,
    # which the page then printed beside the house's 11% swing slope as though
    # the two were comparable. They are not: on swing the garage passes 58%,
    # which is also what the zone ladder reports.
    garage = [d for d in mild if d.weather.t_garage_swing is not None]
    garage_damping = None
    if len(garage) >= 10:
        g = solve_ols(
            [[1.0, d.weather.t_swing] for d in garage],
            [d.weather.t_garage_swing for d in garage],
        )
        garage_damping = g[1]

    return EnvelopeStats(
        damping=coef[1],
        mild_days=len(mild),
        indoor_mean=statistics.fmean(d.weather.t_in_mean for d in usable),
        indoor_swing_mean=statistics.fmean(d.weather.t_in_swing for d in usable),
        outdoor_swing_mean=statistics.fmean(d.weather.t_swing for d in usable),
        setpoint_cool=statistics.fmean(d.weather.t_in_mean for d in hot),
        setpoint_heat=statistics.fmean(d.weather.t_in_mean for d in cold),
        garage_damping=garage_damping,
    )


# ---------------------------------------------------------------------------
# What a future export should be checked against
# ---------------------------------------------------------------------------


@dataclass
class Tripwire:
    monthly: dict[str, float]
    median_kw: float
    month_sd: float
    spread_kw: float
    trend_kw_year: float
    trend_t: float
    detectable_kw: float
    detectable_kwh: float
    detectable_cost: float


def baseload_tripwire(days: list[Day], rate: float) -> Tripwire | None:
    """Turn the always-on floor into a threshold worth watching.

    The floor is the one number here stable enough to serve as an alarm: it is
    equipment that never switches off, so it should not move at all. What makes
    it useful is knowing how much it wobbles when nothing is wrong — a new load
    has to clear that wobble before it can be called a new load.
    """
    pool = [d for d in days if d.electric is not None]
    if len(pool) < 60:
        return None

    by_month: dict[str, list[float]] = defaultdict(list)
    for d in pool:
        by_month[f"{d.date:%Y-%m}"].append(d.electric.baseload_kw)
    monthly = {
        k: statistics.median(v) for k, v in sorted(by_month.items()) if len(v) >= 15
    }
    if len(monthly) < 6:
        return None

    values = list(monthly.values())
    xs = list(range(len(values)))
    coef = solve_ols([[1.0, x] for x in xs], values)
    pred = [coef[0] + coef[1] * x for x in xs]
    resid = [a - b for a, b in zip(values, pred)]
    mx = statistics.fmean(xs)
    sxx = sum((x - mx) ** 2 for x in xs)
    se = math.sqrt(sum(r * r for r in resid) / (len(values) - 2))
    sd = statistics.stdev(values)

    detectable = 2.0 * sd
    return Tripwire(
        monthly=monthly,
        median_kw=statistics.median(values),
        month_sd=sd,
        spread_kw=max(values) - min(values),
        trend_kw_year=coef[1] * 12.0,
        trend_t=coef[1] / (se / math.sqrt(sxx)) if sxx and se else 0.0,
        detectable_kw=detectable,
        detectable_kwh=detectable * 24.0 * 365.0,
        detectable_cost=detectable * 24.0 * 365.0 * rate,
    )


# ---------------------------------------------------------------------------
# The air conditioner, against its own nameplate
# ---------------------------------------------------------------------------


@dataclass
class CoolingCheck:
    hot_days: int
    mild_days: int
    hot_max_f: float
    measured_kw: float        # sustained afternoon draw the AC adds
    overnight_kw: float       # the same comparison when the house is coasting
    rated_kw: float           # nameplate ceiling, outdoor unit at rated current
    blower_kw: float
    load_factor: float        # measured against that ceiling
    peak_hour: int
    runtime_fraction: float   # share of the hottest day the compressor ran


def check_cooling(
    days: list[Day],
    rated_kw: float,
    blower_kw: float,
    hot_count: int = 20,
    mild_range: tuple[float, float] = (68.0, 78.0),
) -> CoolingCheck | None:
    """Compare the cooling load in the meter with what the label allows.

    Same method as the pool pump: take the difference between two median load
    profiles rather than a single day, so cycling and one-off loads average out.
    Here the contrast is the twenty hottest days against mild ones, which
    subtracts everything that does not care about the weather — the pool pump
    runs the same 15:15 block on both.
    """
    pool = [d for d in days if d.electric and d.electric.profile]
    if len(pool) < 60:
        return None
    hot = sorted(pool, key=lambda d: -d.weather.t_max)[:hot_count]
    mild = [d for d in pool if mild_range[0] <= d.weather.t_max <= mild_range[1]]
    if len(hot) < 10 or len(mild) < 10:
        return None

    def profile(group: list[Day]) -> dict[int, float]:
        per: dict[int, list[float]] = defaultdict(list)
        for d in group:
            for i, v in enumerate(d.electric.profile):
                if v is not None:
                    per[i].append(v * 4.0)          # kWh per 15 min -> kW
        return {i: statistics.median(v) for i, v in per.items() if v}

    ph, pm = profile(hot), profile(mild)
    shared = sorted(set(ph) & set(pm))
    if len(shared) < 80:
        return None
    delta = {i: ph[i] - pm[i] for i in shared}

    afternoon = [delta[i] for i in shared if 11 * 4 <= i < 19 * 4]
    overnight = [delta[i] for i in shared if i < 5 * 4]
    measured = statistics.median(afternoon)
    peak_slot = max(delta, key=lambda i: delta[i])

    # Runtime is the day's extra energy divided by the draw while running: a
    # compressor is either on or off, so energy over power is hours.
    extra_kwh = sum(delta[i] for i in shared) / 4.0
    running_kw = measured + blower_kw
    return CoolingCheck(
        hot_days=len(hot),
        mild_days=len(mild),
        hot_max_f=statistics.fmean(d.weather.t_max for d in hot),
        measured_kw=measured,
        overnight_kw=statistics.median(overnight) if overnight else 0.0,
        rated_kw=rated_kw,
        blower_kw=blower_kw,
        load_factor=measured / rated_kw if rated_kw else 0.0,
        peak_hour=peak_slot // 4,
        runtime_fraction=(extra_kwh / running_kw / 24.0) if running_kw else 0.0,
    )


# ---------------------------------------------------------------------------
# What a whole-house meter can and cannot see in the cooling load
# ---------------------------------------------------------------------------


@dataclass
class CoolingWatch:
    base_f: float
    lo_cdd: float
    hi_cdd: float
    early_n: int
    late_n: int
    early: float          # kWh per cooling degree-day, first season
    late: float           # the same, second season
    shift: float
    standard_error: float
    t_stat: float
    detectable: float     # smallest step in kWh/CDD this could resolve
    detectable_pct: float
    bands: list[tuple[float, float, float | None, float | None, int, int]]


def cooling_watch(
    days: list[Day],
    elec: ElectricModel,
    split: dt.date,
    band: tuple[float, float] = (2.0, 9.0),
) -> CoolingWatch | None:
    """Compare cooling efficiency either side of a date, matched on how hot it was.

    Matching matters more than it looks. An air conditioner's efficiency falls as
    the outdoor temperature rises, so cooling energy per degree-day is not
    constant across the season — and two seasons that sample different
    temperature ranges will differ for that reason alone. A naive changepoint
    scan over this data duly finds a large, highly significant "step" at the
    start of June, which is nothing but that curvature being fitted as a break.

    Restricting both sides to a common degree-day window removes it, at the cost
    of most of the sample. The number this exists to produce is therefore the
    detection floor, not the estimate.
    """
    pool = [
        d for d in days
        if d.kwh is not None and d.weather.cdd(elec.cool_base_f) >= 2.0
    ]
    if len(pool) < 60:
        return None

    def efficiency(d: Day) -> float:
        return (d.kwh - elec.baseline_kwh_day) / d.weather.cdd(elec.cool_base_f)

    bands: list[tuple[float, float, float | None, float | None, int, int]] = []
    for lo, hi in ((2, 4), (4, 6), (6, 9), (9, 13), (13, 25)):
        early = [d for d in pool if lo <= d.weather.cdd(elec.cool_base_f) < hi and d.date < split]
        late = [d for d in pool if lo <= d.weather.cdd(elec.cool_base_f) < hi and d.date >= split]
        bands.append((
            lo, hi,
            statistics.fmean([efficiency(d) for d in early]) if len(early) >= 5 else None,
            statistics.fmean([efficiency(d) for d in late]) if len(late) >= 5 else None,
            len(early), len(late),
        ))

    lo, hi = band
    early = [efficiency(d) for d in pool
             if lo <= d.weather.cdd(elec.cool_base_f) < hi and d.date < split]
    late = [efficiency(d) for d in pool
            if lo <= d.weather.cdd(elec.cool_base_f) < hi and d.date >= split]
    if len(early) < 10 or len(late) < 10:
        return None

    se = math.sqrt(
        statistics.variance(early) / len(early) + statistics.variance(late) / len(late)
    )
    shift = statistics.fmean(late) - statistics.fmean(early)
    return CoolingWatch(
        base_f=elec.cool_base_f,
        lo_cdd=lo, hi_cdd=hi,
        early_n=len(early), late_n=len(late),
        early=statistics.fmean(early),
        late=statistics.fmean(late),
        shift=shift,
        standard_error=se,
        t_stat=shift / se if se else 0.0,
        detectable=2.0 * se,
        detectable_pct=2.0 * se / statistics.fmean(early) if early else 0.0,
        bands=bands,
    )


# ---------------------------------------------------------------------------
# A grid-tied, net-metered rooftop array
# ---------------------------------------------------------------------------

# What a panel is worth per watt installed, by system size. Small systems carry
# the same permit, design and scaffolding costs as large ones, so the curve
# falls steeply and then flattens. Market estimates, not quotes.
PRICE_PER_WATT = {4.0: 3.60, 6.0: 3.15, 7.0: 3.00, 8.0: 2.90, 10.0: 2.75}
PANEL_WATTS = 420.0
PANEL_SQFT = 21.5
FEDERAL_ITC = 0.30
STATE_CREDIT = 0.10
STATE_CREDIT_CAP = 6000.0
# Silicon degrades slowly and predictably; 0.5%/yr is a common warranty floor.
DEGRADATION = 0.005
LIFETIME_YEARS = 25


@dataclass
class RoofArray:
    kw: float
    panels: int
    roof_sqft: float
    produced: float
    share_of_use: float
    saved: float
    spilled: float
    price_per_w: float
    gross_cost: float
    net_cost: float

    @property
    def effective_rate(self) -> float:
        return self.saved / self.produced if self.produced else 0.0

    @property
    def payback_years(self) -> float:
        return self.net_cost / self.saved if self.saved else float("inf")

    @property
    def lifetime_net(self) -> float:
        return (
            sum(self.saved * (1 - DEGRADATION) ** y for y in range(LIFETIME_YEARS))
            - self.net_cost
        )


@dataclass
class RoofSolar:
    tilt_deg: float
    poa_annual: float
    annual_use: float
    irreducible: float
    excess_credit: float
    months: int
    scenarios: list[RoofArray]

    @property
    def recommended(self) -> RoofArray:
        """The largest size before exports start being given away.

        Payback keeps improving with size right up to the point where production
        overruns a month's consumption, because installed cost per watt falls
        and every kWh is worth the same. What stops it is spill, so the pick is
        the last size that stays essentially clear of it.
        """
        clean = [s for s in self.scenarios if s.spilled < 0.02 * s.produced]
        return clean[-1] if clean else self.scenarios[0]


def net_metered_solar(
    days: list[Day],
    daily_poa: dict[dt.date, float],
    bill_fn,
    sizes: list[float] | None = None,
    performance_ratio: float = 0.78,
    excess_credit: float = 0.035,
    min_days: int = 27,
) -> RoofSolar | None:
    """Price whole array sizes against the real tariff, month by month.

    Net metering nets *within a billing month*, so the saving is the difference
    between two real bills rather than production times a rate. That matters
    here because the summer tariff is tiered: the first kWh a panel displaces is
    worth the top-tier rate, and only once the array is large enough to push a
    month down into the cheap first tier does its marginal value fall. A flat
    rate would miss that, and would also miss the customer charge, which no
    array of any size can avoid.

    Production beyond a month's own consumption is credited at `excess_credit`
    rather than retail — the conservative reading of how a utility treats a
    surplus it did not agree to buy.
    """
    monthly_use: dict[str, float] = defaultdict(float)
    monthly_end: dict[str, dt.date] = {}
    monthly_days: dict[str, int] = defaultdict(int)
    for d in days:
        if d.kwh is None:
            continue
        key = f"{d.date:%Y-%m}"
        monthly_use[key] += d.kwh
        monthly_end[key] = d.date
        monthly_days[key] += 1
    months = [k for k in sorted(monthly_use) if monthly_days[k] >= min_days]
    if len(months) < 6:
        return None

    monthly_poa: dict[str, float] = defaultdict(float)
    for day, kwh in daily_poa.items():
        monthly_poa[f"{day:%Y-%m}"] += kwh

    scale = 12.0 / len(months)
    annual_use = sum(monthly_use[k] for k in months) * scale
    irreducible = sum(bill_fn(0.0, monthly_end[k]) for k in months) * scale

    sizes = sizes or sorted(PRICE_PER_WATT)
    scenarios: list[RoofArray] = []
    for kw in sizes:
        produced = saved = spilled = 0.0
        for key in months:
            gen = monthly_poa.get(key, 0.0) * kw * performance_ratio
            use = monthly_use[key]
            end = monthly_end[key]
            produced += gen
            over = max(gen - use, 0.0)
            spilled += over
            saved += bill_fn(use, end) - bill_fn(max(use - gen, 0.0), end)
            saved += over * excess_credit
        produced *= scale
        saved *= scale
        spilled *= scale

        price = PRICE_PER_WATT.get(kw, min(PRICE_PER_WATT.values()))
        gross = kw * 1000.0 * price
        net = gross - gross * FEDERAL_ITC - min(gross * STATE_CREDIT, STATE_CREDIT_CAP)
        panels = math.ceil(kw * 1000.0 / PANEL_WATTS)
        scenarios.append(
            RoofArray(
                kw=kw, panels=panels, roof_sqft=panels * PANEL_SQFT,
                produced=produced,
                share_of_use=produced / annual_use if annual_use else 0.0,
                saved=saved, spilled=spilled,
                price_per_w=price, gross_cost=gross, net_cost=net,
            )
        )

    return RoofSolar(
        tilt_deg=0.0, poa_annual=sum(daily_poa.values()),
        annual_use=annual_use, irreducible=irreducible,
        excess_credit=excess_credit, months=len(months), scenarios=scenarios,
    )


# ---------------------------------------------------------------------------
# Hourly water: what the daily meter could never show
# ---------------------------------------------------------------------------


@dataclass
class IrrigationEventHour:
    date: dt.date
    hour: int
    gallons: float


@dataclass
class HourlyWaterPeriod:
    label: str
    start: dt.date
    end: dt.date
    days: int
    total: float
    events: list[IrrigationEventHour]
    profile: list[float]          # mean gallons per hour of day
    dry_nights: int               # windows below the register's 10-gal rounding
    nights: int
    night_ticks: list[float]
    by_day: dict[dt.date, dict[int, float]] = field(default_factory=dict, repr=False)
    # Weekday indices the controller runs on, filled in once the whole record has
    # been read — a single month cannot establish a weekly schedule.
    scheduled: set[int] = field(default_factory=set)

    @property
    def event_mean(self) -> float:
        return statistics.fmean(e.gallons for e in self.events) if self.events else 0.0

    def quiet_hour(self, hour: int) -> list[float]:
        """That hour on the nights the controller did not run.

        The control for reading anything off the irrigation hour. If the 20:00
        bucket were catching evening hose work as well as the valves, the four
        unwatered nights of the same week would show it too — and they do not,
        which is what licenses treating that hour as the controller alone.
        """
        fired = {e.date for e in self.irrigation(hour)}
        return [
            hours[hour]
            for day, hours in sorted(self.by_day.items())
            if day not in fired and hour in hours
        ]

    def irrigation(self, hour: int) -> list[IrrigationEventHour]:
        """Only the controller's own cycles, not every large draw.

        A month contains hose work, backwashes and pool refills as well as
        irrigation, and those are far larger. Two filters separate them: the hour
        the controller fires, and the weekdays it fires on. The hour alone is not
        enough — a 5,229-gallon refill ran straight through 20:00 on a Sunday and
        read as the largest irrigation cycle of the year.
        """
        return [
            e for e in self.events
            if e.hour == hour
            and (not self.scheduled or e.date.weekday() in self.scheduled)
        ]

    def irrigation_mean(self, hour: int) -> float:
        ev = self.irrigation(hour)
        return statistics.fmean(e.gallons for e in ev) if ev else 0.0

    def irrigation_spread(self, hour: int) -> float:
        ev = [e.gallons for e in self.irrigation(hour)]
        return max(ev) - min(ev) if len(ev) >= 2 else 0.0


@dataclass
class HourlyWater:
    periods: list[HourlyWaterPeriod]
    irrigation_hour: int
    resolution_gal: float
    refill_gross: float | None
    refill_net: float | None
    refill_rate: float | None
    refill_hours: int
    assumed_volume: float
    dry_nights: int
    total_nights: int
    scheduled: set[int] = field(default_factory=set)

    @property
    def leak_bound(self) -> float:
        """Continuous flow ruled out by a register that does not move, gal/day."""
        return self.resolution_gal / 4.0 * 24.0


def analyse_hourly_water(
    series: "sources.HourlyWater",
    assumed_volume: float,
    event_floor: float = 40.0,
    refill_window: tuple[dt.datetime, dt.datetime] | None = None,
) -> HourlyWater | None:
    """Pull irrigation events, the refill, and a leak bound out of hourly reads.

    Two columns arrive from the vendor and they are the same measurement at
    different resolutions: the hourly `use` figure sums to within 0.1% of the
    cumulative register, but the register is *displayed* rounded to 10 gallons.
    So `use` is the one to read. Counting nights on which the register does not
    advance measures the rounding, not the flow — a "dry" night means only that
    fewer than ten gallons passed, which at one to five gallons an hour it
    frequently does.
    """
    if not series.stamps:
        return None
    index = {s: i for i, s in enumerate(series.stamps)}
    by_day: dict[dt.date, dict[int, float]] = defaultdict(dict)
    for stamp, gallons in zip(series.stamps, series.gallons):
        by_day[stamp.date()][stamp.hour] = gallons

    # Each export runs from midnight to midnight, and shifting the vendor's
    # hour-ending stamps back to hour-starting leaves a single stray hour of the
    # day before. Drop any day that is not complete: a partial day would drag the
    # hour-of-day profile down and pad the window's day count.
    by_day = defaultdict(dict, {d: h for d, h in by_day.items() if len(h) == 24})
    if not by_day:
        return None

    groups: dict[str, list[dt.date]] = defaultdict(list)
    for day in sorted(by_day):
        groups[f"{day:%Y-%m}"].append(day)

    periods: list[HourlyWaterPeriod] = []
    dry_total = night_total = 0
    for key, days in sorted(groups.items()):
        if len(days) < 4:
            continue
        hours: list[list[float]] = [[] for _ in range(24)]
        events: list[IrrigationEventHour] = []
        ticks: list[float] = []
        dry = 0
        for day in days:
            for hour, gallons in by_day[day].items():
                hours[hour].append(gallons)
                if gallons >= event_floor:
                    events.append(IrrigationEventHour(day, hour, gallons))
            a = dt.datetime.combine(day, dt.time(1))
            b = dt.datetime.combine(day, dt.time(5))
            # The register goes missing on a handful of rows. A night is only
            # counted when both ends of it were actually read — scoring it dry
            # off an absent reading would manufacture the very result this
            # statistic exists to report.
            moved = series.register_flow(a, b) if a in index and b in index else None
            if moved is not None:
                ticks.append(round(moved, 1))
                night_total += 1
                if moved < series.RESOLUTION_GAL / 2:
                    dry += 1
                    dry_total += 1
        periods.append(
            HourlyWaterPeriod(
                # Year included: a record spanning more than twelve months has
                # two Julys in it, and a bare month name silently merged them in
                # every lookup that went by label.
                label=dt.date(int(key[:4]), int(key[5:]), 1).strftime("%b %Y"),
                start=days[0], end=days[-1], days=len(days),
                total=sum(sum(v.values()) for d, v in by_day.items() if d in days),
                events=events,
                profile=[statistics.fmean(h) if h else 0.0 for h in hours],
                dry_nights=dry, nights=len(ticks), night_ticks=ticks,
                by_day={d: by_day[d] for d in days},
            )
        )

    gross = net = rate = None
    span = 0
    if refill_window:
        start, end = refill_window
        gross = series.register_flow(start, end)
        if gross is not None:
            hourly = [
                g for s, g in zip(series.stamps, series.gallons) if start <= s <= end
            ]
            span = len(hourly)
            quiet = [
                g for s, g in zip(series.stamps, series.gallons)
                if s.hour < 5 and not (start <= s <= end)
            ]
            baseline = statistics.median(quiet) if quiet else 0.0
            net = gross - baseline * span
            sustained = [g for g in hourly if g > 200]
            rate = statistics.median(sustained) if sustained else None

    # The hour the controller fires: the one carrying events in the most
    # periods, which no one-off hose job can outvote.
    hour_periods: dict[int, int] = defaultdict(int)
    for period in periods:
        for hour in {e.hour for e in period.events}:
            hour_periods[hour] += 1
    irrigation_hour = (
        max(hour_periods, key=lambda h: hour_periods[h]) if hour_periods else 21
    )
    # And the days it runs on, read off the whole record for the same reason the
    # hour is: the three weekdays carrying the most cycles outvote any one-off.
    weekday_counts: dict[int, int] = defaultdict(int)
    for period in periods:
        for e in period.events:
            if e.hour == irrigation_hour:
                weekday_counts[e.date.weekday()] += 1
    scheduled = {
        wd for wd, _ in sorted(weekday_counts.items(), key=lambda kv: -kv[1])[:3]
    }
    for period in periods:
        period.scheduled = scheduled

    return HourlyWater(
        periods=periods, irrigation_hour=irrigation_hour, scheduled=scheduled,
        resolution_gal=series.RESOLUTION_GAL,
        refill_gross=gross, refill_net=net, refill_rate=rate, refill_hours=span,
        assumed_volume=assumed_volume,
        dry_nights=dry_total, total_nights=night_total,
    )


# ---------------------------------------------------------------------------
# How much water an open pool loses, from the weather over it
# ---------------------------------------------------------------------------

# Carrier's evaporation relation, still the one ASHRAE prints. Evaporation from
# a still water surface is driven by the vapour-pressure difference between the
# water and the air above it, with a wind term because moving air carries the
# vapour away:
#
#     w = (95 + 0.425·V)·(P_w − P_a) / Y     lb of water per hour per ft²
#
# V is air speed in mph, P in inHg, Y the latent heat of vaporisation. Every
# input is measured here — water temperature by the pool probe, P_a from the
# outdoor dew point, V by the anemometer — which is what makes this a genuine
# prediction rather than a fitted curve.
CARRIER_STILL = 95.0
CARRIER_WIND = 0.425
LATENT_HEAT_BTU_LB = 1050.0
WATER_LB_PER_GAL = 8.34


@dataclass
class PoolEvaporation:
    """Predicted evaporation against the make-up water actually metered.

    The pool has a float valve, so evaporation is replaced automatically and
    appears in the water meter as overnight flow. That makes the comparison
    possible at all: one side is computed from the weather, the other is read
    off the meter, and nothing is shared between them.
    """

    daily: dict[dt.date, float]        # predicted gallons a day
    surface_sqft: float
    slope: float                       # metered make-up per predicted gallon
    intercept: float                   # gallons a day that are not evaporation
    r2: float
    n: int
    implied_sqft: float                # area the meter implies, given the model
    monthly: list[tuple[str, float, float]] = field(default_factory=list)


def pool_evaporation(
    days: list[Day], surface_sqft: float, measured: dict[dt.date, float] | None = None
) -> PoolEvaporation | None:
    """Evaporation per day from water temperature, dew point and wind."""
    daily: dict[dt.date, float] = {}
    for d in days:
        w = d.weather
        if w.t_pool_mean is None:
            continue
        # Saturation pressure at the water surface against actual vapour
        # pressure in the air. Both in inHg, since Carrier's constants are.
        p_w = psychro.saturation_vapour_pressure(psychro.f_to_c(w.t_pool_mean)) / 33.8639
        p_a = psychro.vapour_pressure(w.dew_mean) / 33.8639
        if p_w <= p_a:
            daily[d.date] = 0.0
            continue
        lb_per_hr_sqft = (
            (CARRIER_STILL + CARRIER_WIND * w.wind_mean)
            * (p_w - p_a)
            / LATENT_HEAT_BTU_LB
        )
        daily[d.date] = lb_per_hr_sqft * 24.0 * surface_sqft / WATER_LB_PER_GAL

    if not daily:
        return None

    slope = intercept = r2 = 0.0
    n = 0
    implied = surface_sqft
    monthly: list[tuple[str, float, float]] = []
    if measured:
        # Monthly, not daily. A float valve does not top up smoothly — it opens
        # when it opens — and the overnight window catches whatever else the
        # household did at 3 a.m. Against daily pairs the fit is R² 0.005, which
        # is not a failure of the model but of the grain: it predicts a slowly
        # varying seasonal quantity and is being asked about individual nights.
        by_month_pred: dict[str, list[float]] = defaultdict(list)
        by_month_meas: dict[str, list[float]] = defaultdict(list)
        for day, value in daily.items():
            by_month_pred[f"{day:%Y-%m}"].append(value)
        for day, value in measured.items():
            by_month_meas[f"{day:%Y-%m}"].append(value)
        monthly = [
            (k, statistics.fmean(by_month_pred[k]), statistics.median(by_month_meas[k]))
            for k in sorted(by_month_pred)
            if k in by_month_meas
            and len(by_month_pred[k]) >= 20
            and len(by_month_meas[k]) >= 10
        ]
        pairs = [(p, m) for _, p, m in monthly]
        if len(pairs) >= 6:
            coef = solve_ols([[1.0, x] for x, _ in pairs], [y for _, y in pairs])
            intercept, slope = coef[0], coef[1]
            ybar = statistics.fmean([y for _, y in pairs])
            ss_tot = sum((y - ybar) ** 2 for _, y in pairs)
            ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in pairs)
            r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
            n = len(pairs)
            # A slope of one says the assumed area is right. Anything else scales
            # it — the meter measuring the pool rather than the tape measure.
            implied = surface_sqft * slope

    return PoolEvaporation(
        daily=daily, surface_sqft=surface_sqft, slope=slope,
        intercept=intercept, r2=r2, n=n, implied_sqft=implied, monthly=monthly,
    )


# ---------------------------------------------------------------------------
# Watching the irrigation line for a fault
# ---------------------------------------------------------------------------


@dataclass
class IrrigationCycle:
    date: dt.date
    gallons: float
    summer_program: bool
    hour: int = 20


def detect_cycles(
    series: "sources.HourlyWater",
    floor: float = 35.0,
    spill_floor: float = 15.0,
    window_days: int = 10,
) -> list[IrrigationCycle]:
    """Every controller run in the record, wherever on the clock it was set.

    The start hour is not a constant of this house. For three weeks in August
    2025 the schedule moved to midday on Wed/Fri/Sun and then moved back, and a
    detector keyed to one global hour reads that as three weeks of no irrigation
    at all — a 24-day hole in the middle of the watering season, in a record with
    no missing days.

    So: take each day's peak hour, add the hour after it when the cycle straddles
    the boundary, then keep only days matching the schedule *in force around
    them* — the modal start hour and three weekdays over a rolling window. That
    admits a reprogramming without admitting a pool refill.
    """
    by_day: dict[dt.date, dict[int, float]] = defaultdict(dict)
    for stamp, gallons in zip(series.stamps, series.gallons):
        by_day[stamp.date()][stamp.hour] = gallons
    whole = {d: h for d, h in by_day.items() if len(h) == 24}

    peaks: dict[dt.date, tuple[int, float]] = {}
    for day, hours in whole.items():
        hour = max(hours, key=lambda h: hours[h])
        if hours[hour] < floor:
            continue
        spill = hours.get(hour + 1, 0.0) if hour < 23 else 0.0
        peaks[day] = (hour, hours[hour] + (spill if spill >= spill_floor else 0.0))

    cycles: list[IrrigationCycle] = []
    for day, (hour, gallons) in sorted(peaks.items()):
        lo = day - dt.timedelta(days=window_days)
        hi = day + dt.timedelta(days=window_days)
        near = [(d, h) for d, (h, _) in peaks.items() if lo <= d <= hi]
        if len(near) < 6:
            continue
        modal_hour = Counter(h for _, h in near).most_common(1)[0][0]
        weekdays = {
            wd for wd, _ in Counter(
                d.weekday() for d, h in near if h == modal_hour
            ).most_common(3)
        }
        if hour == modal_hour and day.weekday() in weekdays:
            cycles.append(IrrigationCycle(day, gallons, False, hour))
    return cycles


@dataclass
class ScheduleEra:
    """A stretch during which the controller fired at one hour on one set of days."""

    hour: int
    start: dt.date
    end: dt.date
    cycles: int
    weekdays: set[int]

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def schedule_eras(
    cycles: list[IrrigationCycle], gap_days: int = 8, min_cycles: int = 2
) -> list[ScheduleEra]:
    """Split the record wherever the controller's start hour moves.

    Each break is a clock event, not a change of intent: the program either
    side delivers the same volume, so what moved was the controller's idea of
    the time rather than what it was told to do.
    """
    eras: list[ScheduleEra] = []
    for c in cycles:
        if eras and eras[-1].hour == c.hour and (c.date - eras[-1].end).days <= gap_days:
            eras[-1].end = c.date
            eras[-1].cycles += 1
            eras[-1].weekdays.add(c.date.weekday())
        else:
            eras.append(
                ScheduleEra(c.hour, c.date, c.date, 1, {c.date.weekday()})
            )
    return [e for e in eras if e.cycles >= min_cycles]


@dataclass
class IrrigationFault:
    """A sustained change in what one irrigation cycle delivers.

    This is the fault the daily meter structurally cannot see. A burst
    downstream of a valve leaks only while that valve is open, so the quiet days
    stay quiet, the weekly floor never moves, and every leak test built on the
    baseline reports nothing wrong. What moves is the volume of the cycle
    itself — which needs the hour the controller runs, not the day.

    Everything here is measured against the controller's own two programs, so a
    seasonal step in runtime is not mistaken for a fault, and a fault is not
    excused as a season.
    """

    hour: int
    cycles: list[IrrigationCycle]
    baseline_gal: float
    baseline_span: tuple[dt.date, dt.date]
    break_date: dt.date
    recent_gal: float
    excess_gal: float                     # recent cycle, over baseline
    excess_total: float                   # cumulative since the break
    cycles_since: int
    growth_per_week: float                # gallons a cycle, per week since the break
    growth_at_break: float                # fitted intercept, gallons at the break
    growth_r2: float                      # how straight the climb is
    prior_year_gal: float | None          # same calendar window, a year earlier
    prior_year_span: tuple[dt.date, dt.date] | None
    # Both controls compare the fault window with the SAME calendar window a year
    # earlier, never with the months before it. Overnight flow tracks pool
    # evaporation, so a winter-against-summer comparison would show a rise that
    # is only the season and would wrongly implicate the plumbing.
    overnight_now: float                  # gal/h on quiet nights, fault window
    overnight_prior: float                # gal/h, same window a year earlier
    spill_now: float                      # gal in the hour AFTER the cycle
    spill_prior: float
    days_since: int

    @property
    def excess_share(self) -> float:
        return self.excess_gal / self.baseline_gal if self.baseline_gal else 0.0

    @property
    def weekly_gal(self) -> float:
        return self.excess_gal * 3.0      # three scheduled days a week

    @property
    def seasonal(self) -> bool:
        """True if a year earlier the same season ran at the current level."""
        if self.prior_year_gal is None:
            return False
        return self.prior_year_gal >= self.baseline_gal + 0.5 * self.excess_gal


def irrigation_fault(
    series: "sources.HourlyWater",
    hour: int,
    summer_months: set[int],
    event_floor: float = 35.0,
    min_side: int = 6,
) -> IrrigationFault | None:
    """Find the ONSET of a sustained rise in cycle volume, and try to explain it away.

    The scan runs over summer-program cycles only. Mixing the two programs would
    hand back the spring runtime change as the largest step in the record, which
    is a setting doing exactly what it was set to do — the question here is
    whether anything moved that *nobody* set.

    Onset, not the largest step. A fault that grows makes its widest gap long
    after it began, so maximising the difference between the two halves lands
    somewhere in the middle of the damage and reports it as the start. This
    instead establishes what a clean cycle looks like from the opening run of the
    current season, then walks forward for the first departure that *stays*
    departed.
    """
    by_day: dict[dt.date, dict[int, float]] = defaultdict(dict)
    for stamp, gallons in zip(series.stamps, series.gallons):
        by_day[stamp.date()][stamp.hour] = gallons
    whole = {d: h for d, h in by_day.items() if len(h) == 24}
    if not whole:
        return None

    # Every cycle the controller ran, wherever it was on the clock. Keying this
    # to one fixed hour dropped the three weeks in August 2025 when a power cut
    # reset the controller's clock and it watered at midday — leaving a 24-day
    # hole in the middle of the watering season, in a record with no missing
    # days, and quietly excluding those cycles from every level this fits.
    cycles = [
        IrrigationCycle(c.date, c.gallons, c.date.month in summer_months, c.hour)
        for c in detect_cycles(series, floor=event_floor)
    ]
    summer = [c for c in cycles if c.summer_program]
    if len(summer) < 2 * min_side:
        return None

    # Split into seasons: runs of summer-program cycles separated by a winter.
    # The current season supplies its own reference, so last year's flow rate —
    # which is not quite this year's — never enters the comparison.
    seasons: list[list[IrrigationCycle]] = [[summer[0]]]
    for prev, cur in zip(summer, summer[1:]):
        if (cur.date - prev.date).days > 60:
            seasons.append([])
        seasons[-1].append(cur)
    season = seasons[-1]
    if len(season) < 2 * min_side:
        return None

    baseline = statistics.median([c.gallons for c in season[:min_side]])
    spread = statistics.median(
        [abs(c.gallons - baseline) for c in season[:min_side]]
    )
    # A departure has to clear both the cycle-to-cycle noise and a floor set as a
    # share of the baseline, so a very steady system does not trip on rounding.
    threshold = baseline + max(3.0 * spread, 0.15 * baseline)

    onset = None
    for i in range(min_side, len(season) - 2):
        # Two conditions, and both are needed. The window alone straddles the
        # step and names the last clean cycle as the first bad one; the single
        # cycle alone promotes any loud night to a changepoint.
        if season[i].gallons > threshold and statistics.median(
            [c.gallons for c in season[i:i + 4]]
        ) > threshold:
            onset = i
            break
    if onset is None:
        return None

    before, after = season[:onset], season[onset:]
    span_start = before[0].date

    recent = statistics.median([c.gallons for c in after[-8:]])
    excess = recent - baseline
    total = sum(max(0.0, c.gallons - baseline) for c in after)

    # Growth since the break: gallons per week, fitted on days elapsed. The
    # intercept is kept alongside the slope so the fitted line can be written
    # out and checked, rather than only its steepness quoted.
    days = [(c.date - after[0].date).days for c in after]
    growth = 0.0
    growth_at_break = 0.0
    growth_r2 = 0.0
    if len(after) >= 3 and max(days) > 0:
        obs = [c.gallons for c in after]
        coef = solve_ols([[1.0, float(x)] for x in days], obs)
        growth = coef[1] * 7.0
        growth_at_break = coef[0]
        ybar = statistics.fmean(obs)
        ss_tot = sum((y - ybar) ** 2 for y in obs)
        ss_res = sum(
            (y - (coef[0] + coef[1] * x)) ** 2 for x, y in zip(days, obs)
        )
        growth_r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0

    # The same calendar window a year earlier, which is what separates a fault
    # from a season the record has simply not seen twice.
    lo = after[0].date - dt.timedelta(days=365)
    hi = after[-1].date - dt.timedelta(days=365)
    prior = [c for c in cycles if lo <= c.date <= hi]
    prior_gal = statistics.median([c.gallons for c in prior]) if prior else None
    prior_span = (prior[0].date, prior[-1].date) if prior else None

    # Two controls, both against the same calendar window a year earlier.
    # Overnight flow says whether anything leaks while every valve is shut — it
    # tracks pool evaporation, so it must be compared season to season or the
    # weather answers for the plumbing. The hour after the cycle says whether the
    # program simply runs longer than it used to.
    fired = {c.date for c in cycles}

    def overnight(lo_d: dt.date, hi_d: dt.date) -> float:
        vals = [
            whole[d][h]
            for d in whole
            if lo_d <= d <= hi_d and d not in fired
            for h in (1, 2, 3, 4)
        ]
        return statistics.median(vals) if vals else 0.0

    def spill(cs: list[IrrigationCycle]) -> float:
        vals = [whole[c.date][(hour + 1) % 24] for c in cs if c.date in whole]
        return statistics.median(vals) if vals else 0.0

    return IrrigationFault(
        hour=hour,
        cycles=cycles,
        baseline_gal=baseline,
        baseline_span=(span_start, before[-1].date),
        break_date=after[0].date,
        recent_gal=recent,
        excess_gal=excess,
        excess_total=total,
        cycles_since=len(after),
        growth_per_week=growth,
        growth_at_break=growth_at_break,
        growth_r2=growth_r2,
        prior_year_gal=prior_gal,
        prior_year_span=prior_span,
        overnight_now=overnight(after[0].date, after[-1].date),
        overnight_prior=overnight(lo, hi),
        spill_now=spill(after),
        spill_prior=spill(prior) if prior else spill(before),
        days_since=(after[-1].date - after[0].date).days,
    )


# ---------------------------------------------------------------------------
# Load duration, generation timing, and the cost of weather
# ---------------------------------------------------------------------------


@dataclass
class LoadDuration:
    """Every interval of the year, sorted by size rather than by clock.

    The classic utility view, and the one shape that shows this house's three
    loads at once: the steep left edge is air conditioning, the long flat right
    tail is the always-on floor, and the shoulder between them is the pool
    timer. A time series cannot show that because it interleaves all three.
    """

    curve: list[float]                 # kW, descending, downsampled for drawing
    intervals: int
    peak_kw: float
    min_kw: float
    percentiles: dict[int, float]      # share of the year -> kW exceeded
    hours_above_3kw: float
    floor_share: float                 # of total energy, below the p90 draw


def load_duration(days: list[Day], points: int = 240) -> LoadDuration | None:
    """Sort every 15-minute reading descending and sample the curve for drawing.

    Downsampled by rank rather than averaged: taking every nth value off the
    sorted list preserves the extremes, where averaging would clip the peak and
    lift the floor — the two features the chart exists to show.
    """
    kw: list[float] = []
    for d in days:
        if not d.electric:
            continue
        kw.extend(v * 4.0 for v in d.electric.profile if v is not None)
    if len(kw) < 1000:
        return None
    kw.sort(reverse=True)
    n = len(kw)

    step = max(1, n // points)
    curve = [kw[i] for i in range(0, n, step)]
    if curve[-1] != kw[-1]:
        curve.append(kw[-1])

    # Fractional steps below 1%, because that is where this curve does most of
    # its moving: the top percent spans more kW than the remaining ninety-nine
    # together. They have to come off the full sorted series — the drawn curve is
    # downsampled to ~240 points, so anything under about 0.4% reads back as the
    # peak itself. Float keys, and Python hashes 25 and 25.0 alike, so existing
    # integer lookups are unaffected.
    pct = {
        p: kw[min(n - 1, int(n * p / 100))]
        for p in (0.1, 0.25, 0.5, 1, 5, 10, 25, 50, 75, 90, 99)
    }
    floor_kw = pct[90]
    return LoadDuration(
        curve=curve,
        intervals=n,
        peak_kw=kw[0],
        min_kw=kw[-1],
        percentiles=pct,
        hours_above_3kw=sum(1 for v in kw if v > 3.0) * 0.25,
        floor_share=sum(min(v, floor_kw) for v in kw) / sum(kw),
    )


@dataclass
class ShiftableBlock:
    """A fixed load whose clock position is free, against available surplus.

    The pool pump is the only load here that is both large and arbitrary in
    timing, which makes it the one worth asking this question of: how much of it
    could be met by generation the house is not otherwise using?
    """

    kw: float
    slots: int
    now_slot: int
    now_covered: float        # share of the block met by surplus where it runs today
    best_slot: int
    best_covered: float       # ... and at the best start time available
    kwh_per_day: float

    @property
    def now_time(self) -> str:
        return f"{self.now_slot * 15 // 60:02d}:{self.now_slot * 15 % 60:02d}"

    @property
    def best_time(self) -> str:
        return f"{self.best_slot * 15 // 60:02d}:{self.best_slot * 15 % 60:02d}"


@dataclass
class GenerationTiming:
    """When an array would make power against when the house actually draws it."""

    load: list[float]                  # 96 slots, median kW — the base, see below
    generation: list[float]            # 96 slots, mean kW
    self_consumed: float               # share of generation used as it is made
    gen_peak_slot: int
    load_peak_slot: int
    surplus_kwh: float                 # generation exceeding load, per year
    deficit_kwh: float                 # load the base cannot cover from the array
    removed: ShiftableBlock | None = None


def generation_timing(
    days: list[Day],
    poa_slots: dict[tuple[dt.date, int], float],
    kw: float,
    performance_ratio: float,
    remove: tuple[int, int, float] | None = None,
) -> GenerationTiming | None:
    """Average day of generation against average day of load, slot by slot.

    Both are reduced to a single representative day before comparison, so this
    describes the *shape* of the mismatch rather than any particular day. The
    self-consumption figure is computed on the same paired slots: it is the
    share of generation that lands while the house is already drawing at least
    that much, which is exactly what net metering makes irrelevant and what an
    off-grid or battery scheme would have to buy back.
    """
    load_slots: dict[int, list[float]] = defaultdict(list)
    for d in days:
        if not d.electric:
            continue
        for i, v in enumerate(d.electric.profile):
            if v is not None:
                load_slots[i].append(v * 4.0)
    gen_slots: dict[int, list[float]] = defaultdict(list)
    for (_, slot), kwh in poa_slots.items():
        # kWh per 15 minutes on 1 m2 at STC -> kW from an array of this size.
        gen_slots[slot].append(kwh * 4.0 * kw * performance_ratio)
    if len(load_slots) < 90 or len(gen_slots) < 90:
        return None

    load = [statistics.median(load_slots[i]) if load_slots.get(i) else 0.0 for i in range(96)]
    gen = [statistics.fmean(gen_slots[i]) if gen_slots.get(i) else 0.0 for i in range(96)]

    block: ShiftableBlock | None = None
    if remove:
        a, b, magnitude = remove
        span = (b - a) % 96 or 96
        # Take the block out of the median profile. Clamped at zero rather than
        # allowed negative: the median in the block's window already contains it,
        # but the two are separate estimates and nothing guarantees the
        # subtraction lands above zero on every slot.
        for k in range(span):
            i = (a + k) % 96
            load[i] = max(0.0, load[i] - magnitude)

        def covered(start: int) -> float:
            """Share of the block met by generation the base load is not using."""
            got = sum(
                min(magnitude, max(0.0, gen[(start + k) % 96] - load[(start + k) % 96]))
                for k in range(span)
            )
            return got / (magnitude * span) if magnitude and span else 0.0

        best = max(range(96), key=covered)
        block = ShiftableBlock(
            kw=magnitude, slots=span, now_slot=a,
            now_covered=covered(a), best_slot=best, best_covered=covered(best),
            kwh_per_day=magnitude * span * 0.25,
        )

    total_gen = sum(gen)
    return GenerationTiming(
        load=load,
        generation=gen,
        self_consumed=sum(min(l, g) for l, g in zip(load, gen)) / total_gen if total_gen else 0.0,
        gen_peak_slot=max(range(96), key=lambda i: gen[i]),
        load_peak_slot=max(range(96), key=lambda i: load[i]),
        surplus_kwh=sum(max(0.0, g - l) for l, g in zip(load, gen)) * 0.25 * 365,
        deficit_kwh=sum(max(0.0, l - g) for l, g in zip(load, gen)) * 0.25 * 365,
        removed=block,
    )


@dataclass
class WeatherCost:
    """What a day costs, against how warm it was."""

    points: list[tuple[float, float]]      # (mean temp F, $ that day)
    bins: list[tuple[float, float, int]]   # (bin centre, median $, n)
    cheapest_f: float
    cheapest_cost: float
    hot_cost: float
    cold_cost: float


def weather_cost(
    days: list[Day],
    rate_fn,
    gas_rate_fn,
    bin_width: float = 5.0,
    min_bin: int = 5,
) -> WeatherCost | None:
    """Price every day at the rate that applied to it, then bin by temperature.

    Both meters together, because the answer is a U and neither fuel shows one
    on its own: gas falls as it warms and electricity climbs, so only the sum
    has a minimum. Priced at each day's own marginal rate rather than an annual
    average, or the summer tier would be smeared across the whole curve.
    """
    pts: list[tuple[float, float]] = []
    for d in days:
        if d.kwh is None or d.gas_cf is None or d.weather is None:
            continue
        pts.append((
            d.weather.t_mean,
            d.kwh * rate_fn(d.date) + d.gas_cf * gas_rate_fn(d.date) / 1000.0,
        ))
    if len(pts) < 100:
        return None

    grouped: dict[float, list[float]] = defaultdict(list)
    for t, c in pts:
        grouped[(t // bin_width) * bin_width + bin_width / 2].append(c)
    bins = sorted(
        (centre, statistics.median(v), len(v))
        for centre, v in grouped.items()
        if len(v) >= min_bin
    )
    if len(bins) < 4:
        return None
    cheapest = min(bins, key=lambda b: b[1])
    return WeatherCost(
        points=sorted(pts),
        bins=bins,
        cheapest_f=cheapest[0],
        cheapest_cost=cheapest[1],
        hot_cost=bins[-1][1],
        cold_cost=bins[0][1],
    )
