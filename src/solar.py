"""Solar geometry, so irradiance can be projected onto real surfaces.

The weather station measures global horizontal irradiance. Almost nothing that
matters is horizontal: a window is vertical, a PV array is tilted. Projecting
one onto the other needs the sun's position and a split of the measured total
into its direct and diffuse parts.

The seasonal consequence is large and counter-intuitive. At this latitude a
DUE SOUTH vertical window receives slightly MORE energy in December than a
horizontal surface does, and barely a third as much in June — the summer sun is
too high to enter it, the winter sun strikes it nearly square. Any estimate that
scales horizontal insolation by a fixed factor gets both seasons wrong, in
opposite directions.

Everything here is standard textbook solar position (Cooper's declination,
the equation of time) plus the Erbs correlation for the diffuse fraction.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

# Las Cruces, NM — deliberately the city, not the house.
#
# This is a committed file, unlike data/, and a precise home coordinate next to
# the utility name and tariff schedule is the sort of thing .gitignore exists to
# keep out. Resisting the urge to sharpen it costs almost nothing: the NSRDB grid
# cell PVWatts draws from sits 6.7 km away, which is 0.16 minutes of solar time and
# 0.05 degrees of sun altitude — worth under 0.06% on any plane-of-array figure
# here. Precision that cannot change a conclusion is not worth the disclosure.
#
# One decimal place, not two, and the rule above is what decided it rather than
# taste. Two places pin the house to about a square kilometre — roughly half a
# percent of the city, which the README already names. One place encloses the
# whole city. Rebuilt both ways before publishing: the entire dashboard moves by
# two numbers, the count of samples with the sun above 50 degrees (4,122 -> 4,124)
# and the low-E heating penalty (431 -> 430 kWh). No conclusion changes, so the
# extra digit was buying nothing and disclosing a neighbourhood.
LATITUDE = 32.3
LONGITUDE = -106.8
# Mountain Time's standard meridian; the station stamps local wall time with an
# explicit UTC offset, so DST is handled from that rather than assumed.
STANDARD_MERIDIAN = -105.0
LOCAL_ZONE = ZoneInfo("America/Denver")


def wall_clock(day: dt.date, minutes: float) -> dt.datetime:
    """Rebuild a local wall-clock stamp from a slot index, DST included.

    Slots are keyed by wall clock because that is the clock the electric meter
    keeps, and generation only lines up with consumption slot for slot if both
    use it. But sun position is a function of *solar* time, so the UTC offset
    has to be put back before any geometry runs. Attaching the zone is what
    lets `sun_position` read the offset instead of falling back to standard
    time — and that fallback is wrong for the two-thirds of the year on MDT,
    where it placed the sun a full 15 degrees too far west.

    That error was invisible on a due-south plane, which averages morning and
    afternoon symmetrically and cancels it. It is not invisible on an
    east-facing one.

    The hour that repeats each November collapses into one slot regardless;
    `fold=0` takes the daylight-time reading of it. One hour a year, either way.
    """
    naive = dt.datetime.combine(day, dt.time()) + dt.timedelta(minutes=minutes)
    return naive.replace(tzinfo=LOCAL_ZONE)

SOLAR_CONSTANT = 1367.0  # W/m2
SKY_VIEW_VERTICAL = 0.5  # a wall sees half the sky dome
GROUND_ALBEDO = 0.20  # desert gravel and concrete


@dataclass(frozen=True)
class SunPosition:
    altitude: float  # radians above the horizon
    azimuth: float  # radians from due south, positive toward west

    @property
    def is_up(self) -> bool:
        return self.altitude > 0.01


def sun_position(stamp: dt.datetime, latitude: float = LATITUDE,
                 longitude: float = LONGITUDE) -> SunPosition:
    day = stamp.timetuple().tm_yday
    b = math.radians(360 * (day - 81) / 364)
    equation_of_time = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)

    # `is not None` rather than a truth test: a zero offset is falsy, so a UTC
    # stamp would silently take the standard-time fallback instead of its own.
    utc = stamp.utcoffset()
    offset = utc.total_seconds() / 3600 if utc is not None else -7.0
    # Convert the local clock back to standard time, then to solar time.
    standard = stamp.hour + stamp.minute / 60 - (offset + 7.0)
    solar = standard + 4 * (STANDARD_MERIDIAN - longitude) / 60 + equation_of_time / 60

    hour_angle = math.radians(15 * (solar - 12))
    declination = math.radians(23.45 * math.sin(math.radians(360 * (284 + day) / 365)))
    lat = math.radians(latitude)

    sin_alt = (
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    altitude = math.asin(max(-1.0, min(1.0, sin_alt)))
    if math.cos(altitude) == 0:
        return SunPosition(altitude, 0.0)

    sin_az = math.cos(declination) * math.sin(hour_angle) / math.cos(altitude)
    cos_az = (
        math.sin(altitude) * math.sin(lat) - math.sin(declination)
    ) / (math.cos(altitude) * math.cos(lat))
    return SunPosition(
        altitude,
        math.atan2(max(-1.0, min(1.0, sin_az)), max(-1.0, min(1.0, cos_az))),
    )


def diffuse_fraction(clearness: float) -> float:
    """Erbs correlation: how much of the measured total arrived scattered."""
    if clearness <= 0.22:
        return 1.0 - 0.09 * clearness
    if clearness <= 0.80:
        return (
            0.9511
            - 0.1604 * clearness
            + 4.388 * clearness**2
            - 16.638 * clearness**3
            + 12.336 * clearness**4
        )
    return 0.165


def vertical_irradiance(
    stamp: dt.datetime, ghi: float, surface_azimuth: float = 0.0
) -> float:
    """Irradiance on a vertical surface, W/m2.

    `surface_azimuth` is radians from due south, positive toward west, so 0 is
    a due-south window. Returns beam plus the surface's share of diffuse sky
    and ground-reflected light.
    """
    if ghi <= 0:
        return 0.0
    sun = sun_position(stamp)
    if not sun.is_up:
        return 0.0

    day = stamp.timetuple().tm_yday
    eccentricity = 1 + 0.033 * math.cos(math.radians(360 * day / 365))
    extraterrestrial = SOLAR_CONSTANT * eccentricity * math.sin(sun.altitude)
    if extraterrestrial <= 0:
        return 0.0

    clearness = min(ghi / extraterrestrial, 1.0)
    diffuse = ghi * diffuse_fraction(clearness)
    # Clamp the sine so a low sun cannot inflate the beam component absurdly.
    direct_normal = (ghi - diffuse) / max(math.sin(sun.altitude), 0.05)

    cos_incidence = math.cos(sun.altitude) * math.cos(sun.azimuth - surface_azimuth)
    beam = direct_normal * cos_incidence if cos_incidence > 0 else 0.0
    return beam + diffuse * SKY_VIEW_VERTICAL + ghi * GROUND_ALBEDO * SKY_VIEW_VERTICAL


@dataclass
class GlazingSeason:
    """Insolation on a window, split by whether the zone wanted it."""

    total: float  # kWh/m2 over the period
    while_cooling: float
    while_heating: float

    @property
    def cooling_share(self) -> float:
        return self.while_cooling / self.total if self.total else 0.0


def glazing_insolation(
    samples: list[tuple[dt.datetime, float, float]],
    cool_setpoint: float,
    heat_setpoint: float,
    surface_azimuth: float = 0.0,
    interval_minutes: float = 5.0,
) -> GlazingSeason:
    """Integrate vertical irradiance, separating load from benefit.

    `samples` is (timestamp, ghi, outdoor_temp). Sun that arrives while the zone
    is already too warm is a cooling load; the same sun in winter is free heat,
    and the two need to be counted separately or the window looks worse than it is.
    """
    hours = interval_minutes / 60.0
    total = cooling = heating = 0.0
    for stamp, ghi, outdoor in samples:
        energy = vertical_irradiance(stamp, ghi, surface_azimuth) * hours / 1000.0
        if energy <= 0:
            continue
        total += energy
        if outdoor > cool_setpoint:
            cooling += energy
        elif outdoor < heat_setpoint:
            heating += energy
    return GlazingSeason(total=total, while_cooling=cooling, while_heating=heating)


def vertical_symmetry(
    samples: list[tuple[dt.datetime, float, float]],
    calibration: float = 1.0,
    surface_azimuth: float = 0.0,
) -> tuple[float, float]:
    """How lopsided a window's day looks, and what that costs its annual total.

    A due-south surface sees the sun's path symmetrically about solar noon, so
    on a clear horizon its morning and afternoon halves should come out close to
    equal. They do not here: the station that supplies the irradiance sits below
    the roof ridge and loses its eastern sky, which shows up as an afternoon
    surplus that no window orientation can explain.

    Returns the afternoon-to-morning ratio and, from it, the share of the annual
    total that is missing if the two halves ought to have matched. That second
    figure is a floor on the error rather than a correction — it assumes perfect
    symmetry, when real weather supplies some of its own.
    """
    morning = afternoon = 0.0
    for stamp, ghi, _ in samples:
        sun = sun_position(stamp)
        if not sun.is_up:
            continue
        energy = vertical_irradiance(stamp, ghi * calibration, surface_azimuth)
        if energy <= 0:
            continue
        if sun.azimuth < 0:
            morning += energy
        else:
            afternoon += energy
    if not morning or not afternoon:
        return 1.0, 0.0
    return afternoon / morning, (afternoon - morning) / (2 * (morning + afternoon))


def tilted_irradiance(
    stamp: dt.datetime,
    ghi: float,
    tilt: float,
    surface_azimuth: float = 0.0,
) -> float:
    """Irradiance on a surface at any tilt, W/m2 — the plane-of-array figure.

    Generalises `vertical_irradiance`, which is this with `tilt` fixed at 90
    degrees. `tilt` is radians from horizontal; `surface_azimuth` is radians
    from due south, positive toward west.

    A tilted plane sees less of the sky dome than a horizontal one and more of
    the ground, so the diffuse and reflected terms are weighted by their own
    view factors rather than by the single 0.5 a wall happens to have. At tilt
    zero this returns the horizontal irradiance it was given.
    """
    if ghi <= 0:
        return 0.0
    sun = sun_position(stamp)
    if not sun.is_up:
        return 0.0

    day = stamp.timetuple().tm_yday
    eccentricity = 1 + 0.033 * math.cos(math.radians(360 * day / 365))
    extraterrestrial = SOLAR_CONSTANT * eccentricity * math.sin(sun.altitude)
    if extraterrestrial <= 0:
        return 0.0

    clearness = min(ghi / extraterrestrial, 1.0)
    diffuse = ghi * diffuse_fraction(clearness)
    direct_normal = (ghi - diffuse) / max(math.sin(sun.altitude), 0.05)

    cos_incidence = (
        math.sin(sun.altitude) * math.cos(tilt)
        + math.cos(sun.altitude) * math.sin(tilt)
        * math.cos(sun.azimuth - surface_azimuth)
    )
    beam = direct_normal * cos_incidence if cos_incidence > 0 else 0.0
    sky_view = (1.0 + math.cos(tilt)) / 2.0
    ground_view = (1.0 - math.cos(tilt)) / 2.0
    return beam + diffuse * sky_view + ghi * GROUND_ALBEDO * ground_view


# ---------------------------------------------------------------------------
# How much to trust the station's own pyranometer
# ---------------------------------------------------------------------------

# NSRDB puts annual global horizontal irradiance for Las Cruces in this band.
# It is the only external number in this module, and it exists because the
# station's sensor cannot be checked against itself.
NSRDB_GHI_LOW = 2050.0
NSRDB_GHI_HIGH = 2150.0
# Clearness index a clear moment should reach at this altitude with the sun
# high. Anything well below it means the sensor is reading low, not that the
# desert is cloudy.
CLEAR_SKY_KT = 0.78


@dataclass
class PyranometerCheck:
    """Whether the solar sensor can be taken at face value. It cannot."""

    ghi_annual: float
    peak: float
    median_kt: float
    p99_kt: float
    samples: int
    scale_low: float
    scale_high: float

    @property
    def scale(self) -> float:
        return (self.scale_low + self.scale_high) / 2.0

    @property
    def shortfall(self) -> float:
        return 1.0 - 1.0 / self.scale


def check_pyranometer(
    slots: dict[tuple[dt.date, int], float], min_altitude: float = 50.0
) -> PyranometerCheck | None:
    """Compare the station's sensor against what the sky can physically deliver.

    A silicon photodiode — which is what a consumer weather station uses in
    place of a thermopile — has a poor cosine response and a narrow spectral
    window, and characteristically under-reads away from the peak. The test is
    the clearness index: the fraction of the extraterrestrial beam reaching the
    ground, restricted to moments with the sun high enough that the geometry is
    not doing the work. In a desert that should approach 0.78; a median far
    below it is an instrument problem, not a weather one.
    """
    kts: list[float] = []
    for (day, slot), ghi in slots.items():
        stamp = wall_clock(day, 15 * slot + 7)
        sun = sun_position(stamp)
        if not sun.is_up or math.degrees(sun.altitude) < min_altitude:
            continue
        eccentricity = 1 + 0.033 * math.cos(
            math.radians(360 * stamp.timetuple().tm_yday / 365)
        )
        extraterrestrial = SOLAR_CONSTANT * eccentricity * math.sin(sun.altitude)
        if extraterrestrial > 200:
            kts.append(ghi / extraterrestrial)
    if len(kts) < 200:
        return None
    kts.sort()
    annual = sum(slots.values()) * 0.25 / 1000.0
    return PyranometerCheck(
        ghi_annual=annual,
        peak=max(slots.values()),
        median_kt=kts[len(kts) // 2],
        p99_kt=kts[int(len(kts) * 0.99)],
        samples=len(kts),
        scale_low=NSRDB_GHI_LOW / annual,
        scale_high=NSRDB_GHI_HIGH / annual,
    )


def plane_of_array(
    slots: dict[tuple[dt.date, int], float],
    tilt_deg: float,
    calibration: float = 1.0,
    surface_azimuth: float = 0.0,
) -> dict[dt.date, float]:
    """Daily insolation on a tilted roof plane, kWh/m².

    Calibration is applied to the horizontal reading *before* the tilt geometry,
    not after: the beam-and-diffuse split depends on the clearness index, so
    scaling afterwards would keep the sensor's understated clearness and with it
    an overstated diffuse fraction — which is exactly the term that does not
    benefit from tilting.
    """
    daily: dict[dt.date, float] = defaultdict(float)
    for (day, _), kwh in plane_of_array_slots(
        slots, tilt_deg, calibration, surface_azimuth
    ).items():
        daily[day] += kwh
    return dict(daily)


def plane_of_array_slots(
    slots: dict[tuple[dt.date, int], float],
    tilt_deg: float,
    calibration: float = 1.0,
    surface_azimuth: float = 0.0,
) -> dict[tuple[dt.date, int], float]:
    """The same geometry, kept per 15-minute slot instead of summed by day.

    `plane_of_array` is this collapsed to daily totals. The slot-level form is
    what any question about *timing* needs — when generation arrives against
    when the house actually draws — and a daily total cannot answer that at all.
    """
    out: dict[tuple[dt.date, int], float] = {}
    tilt = math.radians(tilt_deg)
    for (day, slot), ghi in slots.items():
        # Mid-slot, so the sun position is the slot's average rather than its
        # leading edge — worth 7 minutes of solar angle near sunrise and sunset.
        stamp = wall_clock(day, 15 * slot + 7)
        out[(day, slot)] = (
            tilted_irradiance(stamp, ghi * calibration, tilt, surface_azimuth)
            * 0.25 / 1000.0
        )
    return out


@dataclass(frozen=True)
class ShortfallSplit:
    """How much of the sensor's deficit is the instrument and how much is its sky."""

    high_sun_ratio: float  # station / reference clear-sky ceiling, sun high
    total_shortfall: float  # the annual figure, from the NSRDB comparison
    samples: int

    @property
    def instrument(self) -> float:
        """The part that survives at high sun, where nothing is in the way."""
        return 1.0 - self.high_sun_ratio

    @property
    def obstruction(self) -> float:
        return max(self.total_shortfall - self.instrument, 0.0)


def split_shortfall(
    slots: dict[tuple[dt.date, int], float],
    reference: "PVWattsRun",
    total_shortfall: float,
    min_altitude: float = 50.0,
) -> ShortfallSplit | None:
    """Separate a low-reading sensor from a blocked one.

    A sensor that under-reads and a sensor with something in front of it look
    identical in an annual total. They separate by sun angle: an instrument
    fault is there at every altitude, while an obstruction runs out once the sun
    climbs above it. So the ratio of clear-sky ceilings measured with the sun
    high is the instrument alone, and whatever the annual figure has on top of
    that is the sky.

    Ceilings rather than medians, because the question is what the sensor reads
    when conditions are as good as they get — a median would fold in real cloud
    on both sides. The reference is a flat PVWatts plane, which is simply global
    horizontal from a source that shares none of this hardware.
    """
    def ceiling(pairs: list[tuple[dt.datetime, float]]) -> float | None:
        kts = []
        for stamp, ghi in pairs:
            sun = sun_position(stamp)
            if not sun.is_up or math.degrees(sun.altitude) < min_altitude:
                continue
            eccentricity = 1 + 0.033 * math.cos(
                math.radians(360 * stamp.timetuple().tm_yday / 365)
            )
            extraterrestrial = SOLAR_CONSTANT * eccentricity * math.sin(sun.altitude)
            if extraterrestrial > 200:
                kts.append(ghi / extraterrestrial)
        if len(kts) < 100:
            return None
        kts.sort()
        return kts[int(len(kts) * 0.9)]

    station = [(wall_clock(d, 15 * s + 7), g) for (d, s), g in slots.items()]
    # Mid-hour for the reference. At this altitude a few minutes either way moves
    # the sun's height by too little to matter, which is exactly why the test is
    # restricted to high sun in the first place.
    ref = [
        (
            dt.datetime(2025, m, d, h, 30, tzinfo=PVWATTS_STANDARD),
            w,
        )
        for (m, d, h), w in reference.poa.items()
    ]
    a, b = ceiling(station), ceiling(ref)
    if not a or not b:
        return None
    return ShortfallSplit(
        high_sun_ratio=a / b,
        total_shortfall=total_shortfall,
        samples=len(station),
    )


# ---------------------------------------------------------------------------
# PVWatts — the one modeled input on this page, and why it had to be brought in
# ---------------------------------------------------------------------------
#
# Everything else here is measured at the house. This is not: it is NREL's model
# run against the nearest NSRDB grid cell. It earns its place because the
# station's pyranometer physically cannot answer the question the roof asks.
# (No range quoted, for the reason given beside LATITUDE above: a distance to a
# published grid point is a ring drawn around the house.)
#
# The sensor sits on an old satellite mount about 3 ft above the eave on the
# northwest corner, on the west slope and below the ridge — so the ridge stands
# between it and every sunrise. Measured against sun position, its eastern sky
# is blocked to roughly 21 degrees of elevation while its western sky is clear.
# On the due-south plane the page used to assume, that cancelled: mornings and
# afternoons are symmetric about noon and the error divided out. On an
# east-west roof it does not cancel, it *is* the measurement. The station put
# west 7.4% ahead of east; PVWatts, from a clear horizon, puts them within 2.3%.
#
# So plane-of-array comes from here, and the station keeps the jobs its siting
# does not compromise: consumption timing, and the case against itself.

# PVWatts stamps hours in local *standard* time year-round, with no daylight
# saving — unlike the house's own meters, which keep wall time. Converting
# between them is the same trap that made the station's own numbers wrong for
# two thirds of the year, so it is done explicitly here rather than assumed.
PVWATTS_STANDARD = dt.timezone(dt.timedelta(hours=-7))


@dataclass(frozen=True)
class PVWattsRun:
    """One PVWatts hourly run: a single roof plane, a typical year."""

    tilt_deg: float
    azimuth_deg: float  # PVWatts convention: 0 north, 90 east, 180 south, 270 west
    dc_kw: float
    poa: dict[tuple[int, int, int], float]  # (month, day, standard hour) -> W/m2
    ac_w: dict[tuple[int, int, int], float]  # same key -> AC watts

    @property
    def annual_poa(self) -> float:
        """kWh/m2 a year. Hourly samples, so each watt-figure is a watt-hour."""
        return sum(self.poa.values()) / 1000.0

    @property
    def annual_ac(self) -> float:
        return sum(self.ac_w.values()) / 1000.0

    @property
    def per_kw(self) -> float:
        return self.annual_ac / self.dc_kw if self.dc_kw else 0.0

    @property
    def compass(self) -> str:
        return {0: "north", 90: "east", 180: "south", 270: "west"}.get(
            round(self.azimuth_deg), f"{self.azimuth_deg:.0f}°"
        )


def load_pvwatts(source) -> dict[tuple[float, float], PVWattsRun]:
    """Every PVWatts hourly export, keyed by the (tilt, azimuth) it was run at.

    Tilt and azimuth are read from each file's own header rather than parsed out
    of its filename, so a mislabelled file is a wrong number in the open rather
    than a silently wrong plane.
    """
    paths = (
        [Path(source)] if isinstance(source, (str, Path))
        else [Path(p) for p in source]
    )
    runs: dict[tuple[float, float], PVWattsRun] = {}
    for path in paths:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            lines = fh.read().splitlines()
        header: dict[str, str] = {}
        start = None
        for i, line in enumerate(lines):
            if line.startswith('"Month"'):
                start = i
                break
            parts = next(csv.reader([line]), [])
            if len(parts) >= 2 and parts[0]:
                header.setdefault(parts[0], parts[1])
        if start is None:
            continue
        poa: dict[tuple[int, int, int], float] = {}
        ac: dict[tuple[int, int, int], float] = {}
        for row in csv.DictReader(lines[start:]):
            try:
                key = (int(row["Month"]), int(row["Day"]), int(row["Hour"]))
                poa[key] = float(row["Plane of Array Irradiance (W/m2)"])
                ac[key] = float(row["AC System Output (W)"])
            except (ValueError, KeyError, TypeError):
                continue
        if not poa:
            continue
        # Fail loudly on a header this cannot read. The quiet alternative is
        # worse than a crash: an unparsed tilt becomes NaN, NaN never matches
        # the plane the build asks for, and the entire solar section disappears
        # from the page with nothing to say it was ever meant to be there.
        try:
            tilt = float(header["Array Tilt (deg)"])
            azimuth = float(header["Array Azimuth (deg)"])
            dc_kw = float(header["DC System Size (kW)"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"{path.name}: cannot read the PVWatts header. Expected "
                f"'Array Tilt (deg)', 'Array Azimuth (deg)' and "
                f"'DC System Size (kW)' among its opening lines. Re-export the "
                f"run rather than editing the file by hand."
            ) from exc
        run = PVWattsRun(
            tilt_deg=tilt, azimuth_deg=azimuth, dc_kw=dc_kw, poa=poa, ac_w=ac
        )
        runs[(run.tilt_deg, run.azimuth_deg)] = run
    return runs


def pvwatts_daily(run: PVWattsRun, dates) -> dict[dt.date, float]:
    """Project a typical year onto real calendar dates, kWh/m2 per day.

    This trades measured weather for typical weather, and the trade is worth
    naming: a month that was genuinely overcast gets a typical month's sun, so
    the month-by-month view answers "what would an array do in a normal year"
    rather than "what would it have done in this one". For sizing an array
    against a tariff that is exactly the question worth asking, but it means
    these months cannot be read as a record of anything.

    February 29th borrows the 28th; a typical year has no leap day.
    """
    by_md: dict[tuple[int, int], float] = defaultdict(float)
    for (month, day, _), watts in run.poa.items():
        by_md[(month, day)] += watts
    return {
        d: by_md.get((2, 28) if (d.month, d.day) == (2, 29) else (d.month, d.day), 0.0)
        / 1000.0
        for d in dates
    }


def pvwatts_slots(run: PVWattsRun, dates) -> dict[tuple[dt.date, int], float]:
    """The same run at 15-minute grain, on the wall clock the meters keep.

    Two conversions happen here and both matter. PVWatts hours are local
    standard time, so during daylight saving each one lands an hour later on the
    wall clock than its label suggests. And an hourly figure has to be spread
    across four slots to sit beside 15-minute consumption; it is spread evenly,
    which is honest at this grain but means nothing inside an hour should be
    read closely.
    """
    out: dict[tuple[dt.date, int], float] = {}
    for day in dates:
        md = (2, 28) if (day.month, day.day) == (2, 29) else (day.month, day.day)
        for hour in range(24):
            watts = run.poa.get((md[0], md[1], hour))
            if not watts:
                continue
            # Built from the real date so the daylight-saving offset is the one
            # actually in force, while the value comes from the typical day —
            # which is what lets February 29th borrow the 28th's sun without
            # also borrowing its calendar.
            stamp = dt.datetime(
                day.year, day.month, day.day, hour, tzinfo=PVWATTS_STANDARD
            ).astimezone(LOCAL_ZONE)
            if stamp.date() != day:
                continue
            for quarter in range(4):
                slot = stamp.hour * 4 + stamp.minute // 15 + quarter
                if slot < 96:
                    out[(day, slot)] = watts * 0.25 / 1000.0
    return out
