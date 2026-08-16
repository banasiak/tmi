#!/usr/bin/env python3
"""Everything the dashboard knows about the house, computed once.

This module is the whole measurement and inference layer: it finds the raw
exports, refuses to continue if a transcribed tariff or nameplate fails its own
arithmetic, joins the sources on local calendar date, fits every model, and
prices the result from the tariffs. It renders nothing and knows nothing about
HTML.

The split matters for a page that is mostly argument. `Analysis` is the contract
between what was measured and what is claimed about it: a section can only say
something the analysis layer has already established, and any figure appearing
on the page can be traced to exactly one field here. Presentation cannot quietly
introduce a number of its own.

Fields are grouped by subject rather than by the order they happen to be
computed in. Optional fields are genuinely optional — a source that is absent or
too short to fit yields `None`, and every consumer is expected to handle it.
"""

from __future__ import annotations

import csv
import datetime as dt
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src import (costs, datafiles, equipment, model, noaa, solar, sources,
                 tariff, zones)
from src.house import (IRRIGATION_SETTLED_SUMMER, IRRIGATION_SUMMER_MIN,
                       IRRIGATION_SUMMER_MONTHS, IRRIGATION_WINTER_MIN,
                       POOL_SURFACE_SQFT, REFILL_DATES, REFILL_WINDOW,
                       ROOF_AZIMUTHS, ROOF_TILT, SYSTEM_GALLONS)
from src.sources import (join_days, load_billing, load_irradiance_samples,
                         load_solar_slots, load_water_samples,
                         station_agreement)


def load_source(paths: list[Path], kind: str):
    """Load one kind of source, failing with a useful message, not a traceback."""
    loader = {
        "weather": sources.load_weather,
        "utilities": sources.load_utilities,
        "electric": sources.load_electric,
    }[kind]
    data = loader(paths)
    if not data:
        names = ", ".join(p.name for p in paths)
        sys.exit(f"Parsed no rows from {names} — is it the export you expected?")
    return data


def verify_transcriptions() -> list[tariff.Check]:
    """Refuse to build on a mistyped rate or a mistyped nameplate.

    Both bodies of numbers were copied off paper by hand, and both can be
    checked against themselves. A tariff reproduces the total printed on the
    bill it came from; the MCA printed on a nameplate is derivable from the
    currents printed beside it. A typo in either shows up as an arithmetic
    contradiction, and every dollar downstream depends on neither existing.

    Exits rather than raising: a dashboard that is confidently wrong is worse
    than one that does not appear.
    """
    tariff_checks = tariff.validate()
    if failed := [c for c in tariff_checks if not c.ok]:
        for c in failed:
            print(f"  tariff FAIL: {c.label}: "
                  f"expected {c.expected:.2f}, got {c.actual:.2f}")
        sys.exit("Tariff self-check failed — refusing to build.")

    plate_checks = equipment.validate() + equipment.check_against_derived(
        costs.POOL_HEATER_BTU_PER_HOUR
    )
    if failed := [c for c in plate_checks if not c.ok]:
        for c in failed:
            print(f"  nameplate FAIL: {c.label}: "
                  f"expected {c.expected}, got {c.actual}")
        sys.exit("Nameplate self-check failed — refusing to build.")

    return tariff_checks


@dataclass(frozen=True)
class Analysis:
    """One house, one year, every figure the page is allowed to quote."""

    # --- What was loaded, and what the loaders could say about it ----------
    weather: list[sources.WeatherDay]
    utilities: list[sources.UtilityDay]
    electric: list[sources.ElectricDay]
    bills: list[sources.BillingPeriod]
    hourly_series: sources.HourlyWater | None
    days: list[sources.Day]
    with_elec: list[sources.Day]
    with_util: list[sources.Day]
    span: str
    bill_files: list[Path]
    weather_channels: int
    noaa_station_count: int
    tariff_checks: list[tariff.Check]
    tariff_worst_delta: float

    # --- Electricity -------------------------------------------------------
    elec_model: model.ElectricModel | None
    elec_pool: list[sources.Day]
    baseload: model.BaseloadStats | None
    scheduled: model.ScheduledLoad | None
    pump_options: list[costs.PumpScenario]
    vs_options: list[costs.PumpScenario]
    minisplit: costs.MiniSplit | None
    meter_check: model.MeterCheck | None
    system_cf: float
    system_winter: float
    system_summer: float

    # --- Gas, and the envelope it heats ------------------------------------
    gas_sig: model.Signature | None
    gas_split: costs.GasSplit
    envelope: model.EnvelopeStats | None
    glazing: solar.GlazingSeason
    glazing_pm_am: float
    glazing_bias: float
    irradiance: dict[tuple[int, int], float]
    warm_gas: model.WarmDayGas | None
    gas_series: dict[dt.date, float]
    pyranometer: solar.PyranometerCheck | None
    shortfall: solar.ShortfallSplit | None
    planes: dict[float, solar.PVWattsRun | None]
    pv_flat: solar.PVWattsRun | None
    pv_south: solar.PVWattsRun | None
    zone_series: sources.ZoneSeries
    couplings: dict[tuple[str, str], zones.Coupling]
    cooling_check: model.CoolingCheck | None

    # --- Water: the meter, and what the hourly record adds to it -----------
    hourly: model.HourlyWater | None
    water_anoms: list[model.Anomaly]
    water_events: list[model.WaterFeature]
    leak_sens: model.LeakSensitivity | None
    big_water: set[dt.date]
    anomalies: list[model.Anomaly]
    attributions: list[model.Attribution]
    resolved: list[model.Attribution]
    still_open: list[model.Attribution]
    gas_identified_phrase: str
    water_series: dict[dt.date, float]

    # --- Irrigation: a two-state schedule, and its faults ------------------
    irrigation: list[model.IrrigationMonth]
    irrigation_changes: list[tuple[str, str, str]]
    irrigation_health: model.IrrigationConsistency | None
    irr_event: dict[str, float]
    irr_monthly: dict[str, float]
    fault: model.IrrigationFault | None
    eras: list[model.ScheduleEra]
    era_cause: dict[dt.date, str]
    clock_slips: list[model.ScheduleEra]
    power_cuts: list[model.ScheduleEra]
    dst_slips: list[model.ScheduleEra]
    set_hour: int
    cut_days: str
    cut_gallons: float
    normal_day_names: str
    season_switches: list[tuple[str, float, float]]
    cycle_winter: float
    cycle_winter_lo: float
    cycle_winter_hi: float
    cycle_summer: float
    cycle_summer_lo: float
    cycle_summer_hi: float
    rest_fit: tuple[float, float, float, int] | None
    flow_rows: list[tuple]

    # --- The pool, which crosses all three meters --------------------------
    evap: model.PoolEvaporation | None
    pump_proof: model.PumpConfirmation | None
    slot_delta: list[float]
    slot_solar: list[float]
    spa_rate: list[costs.SpaFromRate]
    refill_water: float
    refill_gas: float
    refill_gallons: float
    refill_lower_bound: bool

    # --- Weather -----------------------------------------------------------
    storms: list[model.StormDay]
    agreement: dict[str, int]
    normalised: noaa.Normalisation | None
    yoy: list[model.YearOverYear]

    # --- Money. Every figure recomputed from the tariffs on each build -----
    total_kwh: float
    total_water: int
    total_gas: int
    total_cost: float
    water_cost: float
    gas_cost: float
    fixed_other: float
    household_cost: float
    water_above_tier: list[str]
    cool_kwh: float
    cool_cost: float
    heat_kwh: float
    heat_elec_cost: float
    floor_cost: float
    pump_cost: float
    irr_volume: float
    irr_cost: float
    leak_volume: float
    leak_cost: float
    evap_volume: float
    evap_cost: float
    refill_volume: float
    refill_water_cost: float
    use_irrigation: dict[str, float]
    use_leak: dict[str, float]


def analyse() -> Analysis:
    """Find the exports, check the transcriptions, fit the models, price the year.

    Exits rather than returns on a failed self-check: a mistyped tariff rate or
    nameplate makes every dollar downstream wrong, and a dashboard that is
    confidently wrong is worse than one that refuses to build.
    """

    # Nothing is addressed by an exact filename — see src/datafiles.py. Each
    # kind is whatever currently matches its pattern under data/, so dropping in
    # a newer export needs no code change and no renaming of the old one.
    print("inputs:")
    print(datafiles.describe())
    print()

    try:
        weather_files = datafiles.find("weather")
        utility_files = datafiles.find("utilities")
        electric_files = datafiles.find("electric")
    except FileNotFoundError as exc:
        sys.exit(str(exc))

    weather = load_source(weather_files, "weather")
    utilities = load_source(utility_files, "utilities")
    electric = load_source(electric_files, "electric")

    # Optional: the billing summary carries cost and three years of history,
    # where the interval export carries neither.
    billing_files = datafiles.find("billing", required=False)
    bills = load_billing(billing_files) if billing_files else []

    tariff_checks = verify_transcriptions()
    # The page quotes this bound in three places. Derived once, and to the
    # tenth of a cent: rounding the error to a whole cent flatters the
    # transcription, which is the one direction an accuracy claim must not
    # round. 2.3 displayed as "2" is how "within two cents" survived a
    # check that misses by 2.3.
    tariff_worst_delta = max((abs(c.delta) for c in tariff_checks), default=0.0)

    bill_files = datafiles.bills()
    with open(weather_files[0], encoding="utf-8", newline="") as fh:
        weather_channels = len(next(csv.reader(fh)))
    noaa_station_count = len(list(datafiles.NOAA.glob("*.json")))
    hourly_files = datafiles.find("hourly_water", required=False)
    hourly = None
    hourly_series = None
    if hourly_files:
        hourly_series = sources.load_hourly_water(hourly_files)
        hourly = model.analyse_hourly_water(
            hourly_series, SYSTEM_GALLONS,
            refill_window=REFILL_WINDOW,
        )

    # The one fault daily metering cannot see, watched at the hour the valves
    # open. Runs on the whole hourly record rather than the sampled weeks.
    fault = (
        model.irrigation_fault(
            hourly_series, hourly.irrigation_hour, IRRIGATION_SETTLED_SUMMER
        )
        if hourly_series and hourly
        else None
    )
    # The charger's own log. Only ever a rolling window, so its annual figure is
    # a rate held across the year rather than a year's worth of observation.
    days = join_days(weather, utilities, electric)
    if not days:
        sys.exit("No overlapping days across the three sources — nothing to build.")

    with_elec = [d for d in days if d.electric]
    with_util = [d for d in days if d.utility]
    span = f"{days[0].date:%-d %b %Y} – {days[-1].date:%-d %b %Y}"

    # --- models ------------------------------------------------------------
    elec_model, elec_pool = model.fit_electric(days)
    baseload = model.analyse_baseload(days)
    scheduled = model.detect_scheduled_load(days)
    gas_sig = model.fit_signature(days, "gas_cf", "heating", "cf")
    envelope = model.fit_envelope(days)
    agreement = station_agreement(days)
    meter_check = model.validate_against_billing(bills, days) if bills else None
    yoy = model.decompose_year_over_year(bills) if bills else []

    # The water probe sits in the pool circulation loop, which makes it an
    # independent witness to what the pump and the gas heater were doing.
    water_samples = load_water_samples(weather_files)
    flat_samples = [s for day in sorted(water_samples) for s in water_samples[day]]
    pump_proof = (
        model.confirm_pump(flat_samples, scheduled.start_slot)
        if scheduled and flat_samples
        else None
    )
    slot_delta, slot_solar, _slot_outdoor = (
        model.slot_means(flat_samples) if flat_samples else ([], [], [])
    )

    gas_anoms = model.detect_gas_anomalies(days, gas_sig) if gas_sig else []
    water_anoms = model.detect_water_anomalies(days)
    leak_sens = model.leak_sensitivity(days)
    water_events = (
        model.classify_water_events(days, water_samples) if water_samples else []
    )
    # The pool drain would swamp a monthly median, so it is held out.
    irrigation = model.detect_irrigation(
        days, exclude={a.date for a in water_anoms if a.actual > 1000}
    )
    irrigation_changes = model.schedule_changes(irrigation)
    # Cross-examined against the hour the valves actually open, where available.
    # The daily detector reads the schedule off weekday medians, and on a partial
    # month it can rank the wrong three: it reported a September 2025
    # reprogramming from Wed/Fri/Sun that the hourly record flatly denies —
    # every cycle from July 2025 to August 2026 ran Tuesday, Thursday, Saturday.
    # A claim that someone changed a setting should not survive a measurement
    # saying nobody did.
    # The schedule's own history, read off the hour each cycle actually ran at.
    # The daily detector reports weekday changes and it was right that they
    # happened — but wrong about why, and it cannot see the half of the story
    # that matters: the start time moved too. Both are the same event, and it is
    # not somebody reprogramming anything.
    eras = model.schedule_eras(model.detect_cycles(hourly_series)) if hourly_series else []
    set_hour = hourly.irrigation_hour if hourly else 20
    clock_slips = [e for e in eras if e.hour != set_hour]
    # Why each slip happened, told apart by what it lost rather than by its date.
    # A power cut takes the whole clock, so the controller comes back with the
    # wrong weekday as well as the wrong hour. Daylight saving moves nothing on
    # the controller at all — it keeps its schedule perfectly and local time
    # slides underneath, so only the hour appears to change.
    _kept_days = [e.weekdays for e in eras if e.hour == set_hour]
    normal_days = max(_kept_days, key=_kept_days.count) if _kept_days else set()
    era_cause = {
        e.start: (
            "" if e.hour == set_hour
            else "power cut" if e.weekdays != normal_days
            else "daylight saving"
        )
        for e in eras
    }
    power_cuts = [e for e in eras if era_cause.get(e.start) == "power cut"]
    dst_slips = [e for e in eras if era_cause.get(e.start) == "daylight saving"]
    _DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def _days(weekdays: set[int]) -> str:
        return "/".join(_DOW[i] for i in sorted(weekdays))

    cut_days = " and ".join(_days(e.weekdays) for e in power_cuts)
    normal_day_names = _days(normal_days)
    # The volume through the first outage, which is the evidence that an outage
    # costs the clock and nothing else.
    cut_gallons = (
        statistics.median(
            [c.gallons for c in model.detect_cycles(hourly_series)
             if power_cuts[0].start <= c.date <= power_cuts[0].end]
        )
        if power_cuts and hourly_series else 0.0
    )
    # Where the seasonal-adjust percentage was moved, found from the cycles
    # rather than from a calendar: adjacent runs whose volume changes by half or
    # more. The interesting part is not that it happens but when — see below.
    # Does the seasonal dial move when the clock does? Test it where the claim
    # lives — at the boundary between one start-hour era and the next — by
    # comparing the cycle volume either side of it. Scanning the cycle series for
    # level changes instead finds the leak onset in June and calls that a
    # seasonal change, which is both wrong and a contradiction of the section
    # above; a boundary test structurally cannot, because the leak began
    # mid-era with the clock untouched.
    season_switches: list[tuple[model.ScheduleEra, model.ScheduleEra, float, float]] = []
    if eras:
        cycles_by_era = [
            [c for c in model.detect_cycles(hourly_series)
             if e.start <= c.date <= e.end]
            for e in eras
        ]
        for i in range(1, len(eras)):
            before = [c.gallons for c in cycles_by_era[i - 1]]
            after = [c.gallons for c in cycles_by_era[i]]
            if len(before) < 2 or len(after) < 2:
                continue
            # Only the cycles adjacent to the boundary. The whole-era median
            # on the far side runs to August and so carries the leak, which
            # would report the spring dial change as taking cycles to 149
            # gallons when it took them to 113.
            lo = statistics.median(before[-4:])
            hi = statistics.median(after[:4])
            if lo and abs(hi / lo - 1.0) >= 0.4:
                season_switches.append((eras[i - 1], eras[i], lo, hi))
    # Pool events are excluded so a refill or a heating day cannot masquerade
    # as an irrigation fault.
    irrigation_health = model.irrigation_consistency(
        days,
        irrigation,
        exclude={a.date for a in water_anoms if a.actual > 1000}
        | {a.date for a in gas_anoms},
    )
    # One irrigation volume per month, used by the cost row, the annual total and
    # the stacked chart alike. Typical event × how many ran, rather than the sum
    # of the events: September carried four enormous Thursdays and Saturdays
    # (455, 285, 283, 259 gal) that the controller did not deliver, and a sum
    # hands all of them to it. The earlier route — monthly medians reconstructed
    # as `weekly_gal * 52/12` — disagreed with both the meter and the
    # event-by-event series the prose quotes.
    irr_monthly: dict[str, float] = {}
    irr_event: dict[str, float] = {}
    if irrigation_health:
        by_month: dict[str, list[float]] = defaultdict(list)
        for e in irrigation_health.events:
            by_month[f"{e.date:%Y-%m}"].append(max(0.0, e.gallons))
        irr_event = {k: statistics.median(v) for k, v in by_month.items()}
        irr_monthly = {k: irr_event[k] * len(v) for k, v in by_month.items()}

    # Solar: the station's own pyranometer, binned to the meter's 15 minutes.
    irradiance = load_solar_slots(weather_files)
    storms = model.monsoon_days(days)

    # NOAA stands in for the two years the station's export cannot reach. The
    # station itself has been on the roof far longer; AmbientWeather simply will
    # not hand back more than a rolling year, so the earlier record exists and is
    # not retrievable. Cached by tools/fetch_noaa.py so the build never touches
    # the network.
    station_days = {d.date: d.weather for d in days}
    calibrations = noaa.load_calibrations(
        datafiles.NOAA, station_days, elec_model.cool_base_f, elec_model.heat_base_f
    )
    normalised = (
        noaa.normalise_billing(
            bills, station_days, calibrations[0],
            elec_model.cool_base_f, elec_model.heat_base_f,
            elec_model.cooling_slope, elec_model.heating_slope,
        )
        if calibrations and bills
        else None
    )

    # Two large sliding doors, due south, dual pane low-E. Projecting the
    # station's horizontal readings onto that surface is the only way to get
    # the seasonal split right.
    glazing = solar.glazing_insolation(
        load_irradiance_samples(weather_files), cool_setpoint=74.0, heat_setpoint=71.0
    )
    # How much the station's blocked eastern sky costs this window. A due-south
    # surface should collect symmetrically about solar noon, so whatever
    # asymmetry survives here is the roof ridge, not the weather — and half the
    # gap is what the annual total is missing.
    glazing_pm_am, glazing_bias = solar.vertical_symmetry(
        load_irradiance_samples(weather_files), calibration=1.349
    )
    minisplit = costs.minisplit_estimate(days, elec_model, gas_sig, glazing)
    pump_options = costs.pump_scenarios(days, scheduled.magnitude_kw, SYSTEM_GALLONS)
    vs_options = costs.variable_speed_scenarios(days, scheduled.magnitude_kw, SYSTEM_GALLONS)

    # --- costs, all recomputed from the tariffs on every build ---------------
    big_water = {a.date for a in water_anoms if a.actual > 1000}

    # What the weather says the pool should be losing, against what the float
    # valve actually put back. Two instrument chains with nothing in common: the
    # prediction comes from the pool thermometer, the outdoor dew point and the
    # anemometer; the measurement is the water meter in the small hours.
    makeup: dict[dt.date, float] = {}
    if hourly_series and hourly:
        fired = {c.date for c in model.detect_cycles(hourly_series)}
        for period in hourly.periods:
            for day, hours in period.by_day.items():
                if day in fired or day in big_water:
                    continue
                makeup[day] = statistics.fmean([hours[h] for h in (1, 2, 3, 4)]) * 24.0
    evap = model.pool_evaporation(days, POOL_SURFACE_SQFT, makeup) if makeup else None
    # And the same test against ALL the unattributed water, not just the sliver
    # of it visible overnight. This is the one the page kept asserting without
    # checking: that the seasonal swing in household water "is mostly the pool".
    rest_fit = None
    if evap:
        cyc_gal = {c.date: c.gallons for c in model.detect_cycles(hourly_series)}
        by_m: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for d in days:
            if d.water_gal is None or d.date in big_water or d.date not in evap.daily:
                continue
            row = by_m[f"{d.date:%Y-%m}"]
            row[0] += d.water_gal - cyc_gal.get(d.date, 0.0)
            row[1] += evap.daily[d.date]
            row[2] += 1
        pairs = [
            (v[1] / v[2], v[0] / v[2]) for v in by_m.values() if v[2] >= 25
        ]
        if len(pairs) >= 6:
            coef = model.solve_ols([[1.0, x] for x, _ in pairs], [y for _, y in pairs])
            ybar = statistics.fmean([y for _, y in pairs])
            sst = sum((y - ybar) ** 2 for _, y in pairs)
            ssr = sum((y - (coef[0] + coef[1] * x)) ** 2 for x, y in pairs)
            rest_fit = (coef[0], coef[1], 1 - ssr / sst if sst else 0.0, len(pairs))

    # The water year, split by end use and measured rather than inferred. Every
    # one of these is a line the daily meter could not have drawn: the hourly
    # record separates what the controller delivered from what leaked out of it,
    # from what the float valve replaced, from a one-off refill.
    use_cycles: dict[str, float] = defaultdict(float)
    use_leak: dict[str, float] = defaultdict(float)
    use_refill: dict[str, float] = defaultdict(float)
    use_evap: dict[str, float] = defaultdict(float)
    if hourly_series:
        for c in model.detect_cycles(hourly_series):
            key = f"{c.date:%Y-%m}"
            use_cycles[key] += c.gallons
            if fault and c.date >= fault.break_date:
                use_leak[key] += max(0.0, c.gallons - fault.baseline_gal)
        for d in big_water:
            day = next((p.by_day.get(d) for p in hourly.periods if d in p.by_day), None)
            if day:
                use_refill[f"{d:%Y-%m}"] += sum(day.values())
    if evap and evap.slope:
        # Scaled by the fitted slope, not taken raw: the model is the shape and
        # the meter is the size, and the meter says the shape runs about a fifth
        # high on this pool.
        for day, gallons in evap.daily.items():
            use_evap[f"{day:%Y-%m}"] += gallons * evap.slope
    # What the controller meant to deliver, with the split line taken back out.
    use_irrigation = {
        k: max(0.0, v - use_leak.get(k, 0.0)) for k, v in use_cycles.items()
    }

    # Onto the same twelve billing cycles as every other figure on this page.
    # The hourly record runs 400 days and reaches a month further back than the
    # daily one; left alone it reports a 400-day irrigation volume beside a
    # 364-day water bill, and prices it accordingly.
    util_months: dict[str, int] = defaultdict(int)
    for d in with_util:
        util_months[f"{d.date:%Y-%m}"] += 1
    stub = sorted(k for k, n in util_months.items() if n < 27)
    merge_from, merge_into = None, None
    if len(stub) == 2 and stub[0][5:] == stub[1][5:]:
        merge_into, merge_from = sorted(stub, key=lambda k: -util_months[k])

    def _billing_months(per_month: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for key, value in per_month.items():
            if key not in util_months:
                continue                     # outside the joined record entirely
            out[merge_into if key == merge_from else key] += value
        return dict(out)

    use_cycles = _billing_months(use_cycles)
    use_leak = _billing_months(use_leak)
    use_refill = _billing_months(use_refill)
    use_evap = _billing_months(use_evap)
    use_irrigation = _billing_months(use_irrigation)

    # What one cycle delivers on each program, measured at the hour the valves
    # open and taken only from months the fault has not touched. Computed once
    # here because three sections quote it and they must not disagree; taken from
    # clean months because averaging the leak in would report a pipe that got
    # wider rather than a pipe that split.
    cycle_winter = cycle_summer = 0.0
    cycle_winter_lo = cycle_winter_hi = 0.0
    cycle_summer_lo = cycle_summer_hi = 0.0
    if hourly:
        def _clean_cycles(period) -> list[float]:
            return [
                e.gallons
                for e in period.irrigation(hourly.irrigation_hour)
                if e.date not in big_water
            ]
        winter_vals: list[float] = []
        summer_vals: list[float] = []
        # Per-month medians, not every individual cycle: the spread that matters
        # is between months, and pooling raw cycles lets one odd night set the
        # range (a single 70-gallon January cycle stretched "winter" to 40–70).
        winter_months: list[float] = []
        summer_months: list[float] = []
        for period in hourly.periods:
            if fault and period.end >= fault.break_date:
                continue
            if period.start.month == 3:      # the changeover runs both
                continue
            vals = _clean_cycles(period)
            if not vals:
                continue
            summer = period.start.month in IRRIGATION_SETTLED_SUMMER
            (summer_vals if summer else winter_vals).extend(vals)
            if len(vals) >= 4:
                (summer_months if summer else winter_months).append(
                    statistics.median(vals)
                )
        cycle_winter = statistics.median(winter_vals) if winter_vals else 0.0
        cycle_summer = statistics.median(summer_vals) if summer_vals else 0.0
        # Quoted as ranges, because neither program delivers one number all
        # season: the summer cycle tapers from July to October and the leak
        # section's own clean baseline is the top of that range, not its middle.
        # A single median made two sections disagree by three gallons about the
        # same thing.
        cycle_winter_lo, cycle_winter_hi = (
            (min(winter_months), max(winter_months)) if winter_months else (0.0, 0.0)
        )
        cycle_summer_lo, cycle_summer_hi = (
            (min(summer_months), max(summer_months)) if summer_months else (0.0, 0.0)
        )
    gas_split = costs.gas_split(days, gas_sig, {a.date: a.excess for a in gas_anoms})
    cool_kwh, cool_cost = costs.cooling_cost(days, elec_model)
    heat_kwh, heat_elec_cost = costs.heating_electric_cost(days, elec_model)
    pump_cost, _pump_per_hour = costs.scheduled_cost(days, scheduled)
    floor_cost = costs.baseload_cost(days)
    # Each water end use priced the same way: the bill with it, less the bill
    # without. Marginal, so they do not sum to the water bill — every one of them
    # is the last 1,000 gallons of its month, and the "Other water" row absorbs
    # the difference.
    irr_volume, irr_cost = costs.water_end_use_cost(
        days, use_irrigation or irr_monthly, exclude=big_water
    )
    leak_volume, leak_cost = costs.water_end_use_cost(days, use_leak, exclude=big_water)
    evap_volume, evap_cost = costs.water_end_use_cost(days, use_evap, exclude=big_water)
    refill_volume, refill_water_cost = costs.water_end_use_cost(days, use_refill)
    spa_rate = costs.spa_volume_from_rate(
        water_samples, [e.date for e in water_events if e.kind == "spa"]
    )
    refill_water, refill_gas, refill_gallons, refill_lower_bound = costs.refill_cost(
        days, gas_sig,
        [dt.date(2026, 3, 29), dt.date(2026, 3, 30)],
        [dt.date(2026, 3, 31), dt.date(2026, 4, 4), dt.date(2026, 4, 5), dt.date(2026, 4, 6)],
    )
    anomalies = sorted(gas_anoms + water_anoms, key=lambda a: a.date, reverse=True)

    # --- headline figures --------------------------------------------------
    total_kwh = sum(d.kwh for d in with_elec)
    # Cost is computed per BILLING PERIOD, because the summer tier and the fixed
    # charges are period-level facts. Periods only partly covered by interval
    # data are scaled by the fraction of days present.
    elec_cost = 0.0
    billed_days = 0
    by_date = {d.date: d for d in with_elec}
    for b in bills:
        period_days = [b.start + dt.timedelta(days=i) for i in range(b.days)]
        present = [d for d in period_days if d in by_date]
        if not present:
            continue
        elec_cost += tariff.electric_bill(b.kwh, b.end).total * (len(present) / b.days)
        billed_days += len(present)
    # The interval export runs past the last bill, so some metered days sit in no
    # billing period at all — 12 of 359 here. Left alone that priced 347 days of
    # electricity against 359 days of kWh in the same tile. Stretch the total
    # over every metered day so the two halves of that sentence agree.
    if billed_days:
        elec_cost *= len(with_elec) / billed_days
    total_cost = elec_cost
    total_water = sum(d.water_gal for d in with_util)
    total_gas = sum(d.gas_cf for d in with_util)

    # Water and gas are billed monthly against tiered/commodity schedules, so
    # cost is accumulated per billing cycle rather than per day.
    #
    # A record starting mid-August and ending in early August spans thirteen
    # calendar months but only twelve cycles: the two August fragments are one
    # billing month cut in half by wherever the export happens to begin. Left
    # separate, neither clears the 27-day bar, so both were dropped — which
    # priced eleven months of water, gas and wastewater against twelve months of
    # volume, and put a twelve-month gas access fee inside an eleven-month gas
    # total. (`costs.gas_split` never had the bug; it counts `len(days)/30.44`.)
    # Merged, the pair also shares one 3,000-gallon free allowance instead of
    # being handed two, which is what the meter reader would have done.
    month_water: dict[str, float] = {}
    month_gas: dict[str, float] = {}
    month_days: dict[str, int] = {}
    for d in with_util:
        key = f"{d.date:%Y-%m}"
        month_water[key] = month_water.get(key, 0.0) + d.water_gal
        month_gas[key] = month_gas.get(key, 0.0) + d.gas_cf
        month_days[key] = month_days.get(key, 0) + 1

    # The merged cycle is priced at whichever fragment holds most of its days —
    # here 25 of 30 fall in 2025, and the wastewater allowance re-set makes that
    # choice worth $6.77.
    partial = sorted(k for k, n in month_days.items() if n < 27)
    if len(partial) == 2 and partial[0][5:] == partial[1][5:]:
        keep, drop = sorted(partial, key=lambda k: -month_days[k])
        month_water[keep] += month_water.pop(drop)
        month_gas[keep] += month_gas.pop(drop)
        month_days[keep] += month_days.pop(drop)
    full_months = [k for k, n in month_days.items() if n >= 27]

    water_cost = 0.0
    gas_cost = 0.0
    water_above_tier: list[str] = []
    for key in full_months:
        wb = tariff.water_bill(month_water[key])
        water_cost += wb.total
        if wb.above_observed:
            water_above_tier.append(key)
        mid = dt.date(int(key[:4]), int(key[5:]), 15)
        gas_cost += tariff.gas_bill(month_gas[key], mid).total
    # Wastewater is tiered and its allowance is re-set annually rather than
    # seasonally, so it is accumulated month by month against the date each
    # month actually fell on.
    fixed_other = sum(
        tariff.wastewater_bill(dt.date(int(key[:4]), int(key[5:]), 15))
        + tariff.SOLID_WASTE_TYPICAL
        for key in full_months
    )
    household_cost = total_cost + water_cost + gas_cost + fixed_other

    # --- Facts the page quotes in more than one place -------------------
    # Each of these was once computed inside the section that needed it
    # first, and read by name from a section further down. That made the
    # later section's output depend on the earlier one having run, which is
    # not a relationship presentation code should be able to express — and
    # it crashed outright on a dataset where the earlier section was skipped.

    # What a degree of pool-and-spa temperature costs. This is quoted beside the
    # volume it derives from rather than in the cost section, because it is only
    # meaningful once you know how much water is being heated — and because it is
    # the figure every later heating question reduces to.
    system_cf, system_winter = costs.degree_cost(SYSTEM_GALLONS, dt.date(2026, 1, 15))
    _, system_summer = costs.degree_cost(SYSTEM_GALLONS, dt.date(2026, 7, 15))

    warm_gas = (
        model.analyse_warm_day_gas(days, gas_sig, gas_anoms) if gas_sig else None
    )
    attributions = (
        model.attribute_anomalies(
            days, gas_sig, gas_anoms, water_anoms, water_events, REFILL_DATES,
            water_samples=water_samples, pool_gallons=SYSTEM_GALLONS,
        )
        if gas_sig
        else []
    )
    resolved = [a for a in attributions if a.resolved]
    still_open = [a for a in attributions if not a.resolved]
    # The provenance summary quotes how many gas days got a cause. Derive it from
    # the same attributions that render the list rather than restating a subtotal,
    # so the two cannot drift apart — it previously claimed 7 of 10 while listing
    # all 10 as explained.
    gas_identified = sum(1 for a in resolved if a.anomaly.stream == "gas")
    gas_identified_phrase = (
        f"all {len(gas_anoms)} gas anomalies"
        if gas_identified == len(gas_anoms)
        else f"{gas_identified} of the {len(gas_anoms)} gas anomalies"
    )

    water_series = {d.date: d.water_gal for d in with_util}
    gas_series = {d.date: d.gas_cf for d in with_util}

    zone_series = sources.load_zone_series(weather_files)
    couplings = {(c.zone, c.channel): c for c in zones.coupling(zone_series)}

    # Nameplate cross-check for the air conditioner, quoted by the equipment
    # section.
    cooling_check = model.check_cooling(
        days, equipment.rated_draw_kw(), equipment.FURNACE_BLOWER_WATTS / 1000.0
    )

    pyranometer = solar.check_pyranometer(irradiance) if irradiance else None

    # Plane-of-array comes from PVWatts rather than the station. The station's
    # own sky is blocked to ~21 degrees in the east by the ridge its sensor sits
    # below, which is invisible on a south plane and fatal on an east one.
    pv_runs = solar.load_pvwatts(datafiles.find("pvwatts", required=False))
    planes = {az: pv_runs.get((ROOF_TILT, az)) for az in ROOF_AZIMUTHS}
    pv_flat = pv_runs.get((0.0, 180.0))
    pv_south = pv_runs.get((ROOF_TILT, 180.0))
    # A flat PVWatts plane is global horizontal, so it doubles as the outside
    # check on the sensor — and as the way to tell a low sensor from a blocked one.
    shortfall = (
        solar.split_shortfall(irradiance, pv_flat, pyranometer.shortfall)
        if pyranometer and pv_flat else None
    )

    # Irrigation flow rate per sampled period, clean months only. Bound
    # unconditionally: the provenance section quotes its range, and used to
    # raise NameError if the hourly export was missing.
    flow_rows: list[tuple] = []
    if hourly and hourly.periods:
        def _events(w: object) -> list:
            """The controller's own cycles: right hour, right weekday, no refill."""
            return [
                e for e in w.irrigation(hourly.irrigation_hour)
                if e.date not in big_water
            ]
    
        def _irr_mean(w: object) -> float:
            ev = _events(w)
            return statistics.fmean(e.gallons for e in ev) if ev else 0.0
    
        def _program_min(period: object) -> float:
            return (
                IRRIGATION_SUMMER_MIN
                if period.start.month in IRRIGATION_SUMMER_MONTHS
                else IRRIGATION_WINTER_MIN
            )
    
        # Flow rate by program, from the CLEAN months only. Including the
        # months after the break would price the leak as though the pipe had got
        # wider, which is the reading a year of data exists to refuse.
        clean = [
            p for p in hourly.periods
            if _events(p)
            and (fault is None or p.end < fault.break_date)
            and p.start.month != 3        # the changeover runs both programs
        ]
        flow_rows = sorted(
            ((p, _irr_mean(p), _program_min(p), _irr_mean(p) / _program_min(p))
             for p in clean),
            key=lambda r: r[0].start,
        )

    return Analysis(
        system_cf=system_cf,
        system_winter=system_winter,
        system_summer=system_summer,
        warm_gas=warm_gas,
        gas_series=gas_series,
        pyranometer=pyranometer,
        shortfall=shortfall,
        planes=planes,
        pv_flat=pv_flat,
        pv_south=pv_south,
        zone_series=zone_series,
        couplings=couplings,
        cooling_check=cooling_check,
        attributions=attributions,
        resolved=resolved,
        still_open=still_open,
        gas_identified_phrase=gas_identified_phrase,
        water_series=water_series,
        flow_rows=flow_rows,
        # What was loaded, and what the loaders could say about it
        weather=weather,
        utilities=utilities,
        electric=electric,
        bills=bills,
        hourly_series=hourly_series,
        days=days,
        with_elec=with_elec,
        with_util=with_util,
        span=span,
        bill_files=bill_files,
        weather_channels=weather_channels,
        noaa_station_count=noaa_station_count,
        tariff_checks=tariff_checks,
        tariff_worst_delta=tariff_worst_delta,
        # Electricity
        elec_model=elec_model,
        elec_pool=elec_pool,
        baseload=baseload,
        scheduled=scheduled,
        pump_options=pump_options,
        vs_options=vs_options,
        minisplit=minisplit,
        meter_check=meter_check,
        # Gas, and the envelope it heats
        gas_sig=gas_sig,
        gas_split=gas_split,
        envelope=envelope,
        glazing=glazing,
        glazing_pm_am=glazing_pm_am,
        glazing_bias=glazing_bias,
        irradiance=irradiance,
        # Water: the meter, and what the hourly record adds to it
        hourly=hourly,
        water_anoms=water_anoms,
        water_events=water_events,
        leak_sens=leak_sens,
        big_water=big_water,
        anomalies=anomalies,
        # Irrigation: a two-state schedule, and its faults
        irrigation=irrigation,
        irrigation_changes=irrigation_changes,
        irrigation_health=irrigation_health,
        irr_event=irr_event,
        irr_monthly=irr_monthly,
        fault=fault,
        eras=eras,
        era_cause=era_cause,
        clock_slips=clock_slips,
        power_cuts=power_cuts,
        dst_slips=dst_slips,
        set_hour=set_hour,
        cut_days=cut_days,
        cut_gallons=cut_gallons,
        normal_day_names=normal_day_names,
        season_switches=season_switches,
        cycle_winter=cycle_winter,
        cycle_winter_lo=cycle_winter_lo,
        cycle_winter_hi=cycle_winter_hi,
        cycle_summer=cycle_summer,
        cycle_summer_lo=cycle_summer_lo,
        cycle_summer_hi=cycle_summer_hi,
        rest_fit=rest_fit,
        # The pool, which crosses all three meters
        evap=evap,
        pump_proof=pump_proof,
        slot_delta=slot_delta,
        slot_solar=slot_solar,
        spa_rate=spa_rate,
        refill_water=refill_water,
        refill_gas=refill_gas,
        refill_gallons=refill_gallons,
        refill_lower_bound=refill_lower_bound,
        # Weather
        storms=storms,
        agreement=agreement,
        normalised=normalised,
        yoy=yoy,
        # Money. Every figure recomputed from the tariffs on each build
        total_kwh=total_kwh,
        total_water=total_water,
        total_gas=total_gas,
        total_cost=total_cost,
        water_cost=water_cost,
        gas_cost=gas_cost,
        fixed_other=fixed_other,
        household_cost=household_cost,
        water_above_tier=water_above_tier,
        cool_kwh=cool_kwh,
        cool_cost=cool_cost,
        heat_kwh=heat_kwh,
        heat_elec_cost=heat_elec_cost,
        floor_cost=floor_cost,
        pump_cost=pump_cost,
        irr_volume=irr_volume,
        irr_cost=irr_cost,
        leak_volume=leak_volume,
        leak_cost=leak_cost,
        evap_volume=evap_volume,
        evap_cost=evap_cost,
        refill_volume=refill_volume,
        refill_water_cost=refill_water_cost,
        use_irrigation=use_irrigation,
        use_leak=use_leak,
    )
