"""What everything costs, priced from the transcribed tariffs.

Two kinds of number live here and they answer different questions:

  Annual operating cost   What a load actually adds to the year's bills. Priced
                          at the *marginal* rate, because every load discussed
                          here sits on top of the others — remove it and you
                          stop paying the top-tier rate, not the average.

  Unit cost               What one more degree, or one more refill, costs. The
                          useful form for a decision.

Nothing is hardcoded: every figure is recomputed from the joined record and the
tariff module on each build, so a corrected rate or a fresh export propagates
everywhere at once.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from . import equipment, solar, tariff
from .model import (
    ElectricModel,
    ScheduledLoad,
    Signature,
)
from .sources import Day

# Water: 8.34 lb/gal, and one BTU raises one pound by one degree F.
LB_PER_GAL = 8.34
# Gas appliance efficiency. This now has exactly one job: converting the pool
# heater's gas into heat in the water. Its nameplate prints an input rating and
# no efficiency, so the figure stays assumed.
#
# The furnace left this bucket when its label turned up printing both input and
# output (88,000 and 71,000 BTU/h) — see `equipment.FURNACE_EFFICIENCY`. That it
# landed within 0.7 points of the guess below is the only independent evidence
# that 80% is fair for the pool heater too. The water heater never needed a
# figure at all: its share of the gas meter is counted in cubic feet and priced
# directly, with no conversion to delivered heat in between.
APPLIANCE_EFFICIENCY = 0.80



@dataclass
class GasSplit:
    space_heating_cf: float
    water_heater_cf: float
    pool_spa_cf: float
    space_heating_cost: float
    water_heater_cost: float
    pool_spa_cost: float
    fixed_access: float
    metered_cf: float

    @property
    def accounted(self) -> float:
        return self.space_heating_cf + self.water_heater_cf + self.pool_spa_cf

    @property
    def coverage(self) -> float:
        return self.accounted / self.metered_cf if self.metered_cf else 0.0

    @property
    def total(self) -> float:
        return (
            self.space_heating_cost
            + self.water_heater_cost
            + self.pool_spa_cost
            + self.fixed_access
        )


def gas_split(days: list[Day], sig: Signature, anomaly_excess: dict[dt.date, float]) -> GasSplit:
    """Divide the gas meter into heating, the standing baseline, and the pool.

    The signature supplies the split: its slope against heating degree-days is
    space heating, its intercept is the appliance floor, and what the model
    cannot explain on a mild day is the pool or spa.
    """
    pool = [d for d in days if d.gas_cf is not None]
    heat_cf = heat_cost = 0.0
    base_cf = base_cost = 0.0
    spa_cf = spa_cost = 0.0

    for d in pool:
        rate = tariff.gas_marginal_per_kcf(d.date) / 1000.0
        h = sig.slope * d.weather.hdd(sig.base_f)
        heat_cf += h
        heat_cost += h * rate
        base_cf += sig.baseline
        base_cost += sig.baseline * rate
        excess = anomaly_excess.get(d.date, 0.0)
        spa_cf += excess
        spa_cost += excess * rate

    # Count whole months, not distinct (year, month) pairs: a record starting
    # mid-August and ending in early August spans 13 partial months but only
    # twelve billing cycles.
    months = round(len(pool) / 30.44)
    return GasSplit(
        space_heating_cf=heat_cf,
        water_heater_cf=base_cf,
        pool_spa_cf=spa_cf,
        space_heating_cost=heat_cost,
        water_heater_cost=base_cost,
        pool_spa_cost=spa_cost,
        fixed_access=tariff.GAS_ACCESS_FEE * months,
        metered_cf=sum(d.gas_cf for d in pool),
    )


def cooling_cost(days: list[Day], model: ElectricModel) -> tuple[float, float]:
    """Annual cooling energy and what it costs at marginal rates."""
    kwh = cost = 0.0
    for d in days:
        if not d.electric:
            continue
        k = model.cooling_slope * d.weather.cdd(model.cool_base_f)
        kwh += k
        cost += k * tariff.marginal_rate(d.date)
    return kwh, cost


def heating_electric_cost(days: list[Day], model: ElectricModel) -> tuple[float, float]:
    """The electric side of heating — blower and anything else tracking cold."""
    kwh = cost = 0.0
    for d in days:
        if not d.electric:
            continue
        k = model.heating_slope * d.weather.hdd(model.heat_base_f)
        kwh += k
        cost += k * tariff.marginal_rate(d.date)
    return kwh, cost


def scheduled_cost(days: list[Day], sched: ScheduledLoad) -> tuple[float, float]:
    """The timer load's annual cost, and what one hour of daily runtime is worth."""
    with_elec = [d for d in days if d.electric]
    total = sum(tariff.marginal_rate(d.date) * sched.daily_kwh for d in with_elec)
    return total, total / sched.hours if sched.hours else 0.0


def baseload_cost(days: list[Day]) -> float:
    return sum(
        tariff.marginal_rate(d.date) * d.electric.baseload_kw * 24.0
        for d in days
        if d.electric
    )


def water_end_use_cost(
    days: list[Day],
    monthly_gal: dict[str, float],
    exclude: set[dt.date] | None = None,
) -> tuple[float, float]:
    """Marginal water cost of one end use: the bill with it, minus the bill without.

    Generic in the end use. Irrigation was the first caller and the only one for a
    long time, which is why this was called `irrigation_cost` — but the hourly
    record now separates the controller's own water from the pool's evaporation
    make-up, from a refill, from the leak, and each wants pricing the same way.

    Marginal rather than average because the first 3,000 gallons each month are
    free — so what irrigation costs depends entirely on where in the tier it
    lands, not on how many gallons it is.

    `monthly_gal` is the measured irrigation volume per calendar month, keyed
    "YYYY-MM" — the events the controller actually ran, which is the basis the
    chart and the sensitivity figures use. This used to rebuild the volume from
    monthly medians instead (`weekly_gal * 52/12`) and subtract a modeled
    baseline, which agreed with neither the meter nor the event series.
    """
    # One-off events such as a pool refill must come out of the monthly volume,
    # or the tier they push the month into gets charged to irrigation.
    exclude = exclude or set()
    counts: dict[str, int] = {}
    volumes: dict[str, float] = {}
    for d in days:
        if d.water_gal is None or d.date in exclude:
            continue
        key = f"{d.date:%Y-%m}"
        counts[key] = counts.get(key, 0) + 1
        volumes[key] = volumes.get(key, 0.0) + d.water_gal

    cost = 0.0
    priced_volume = 0.0
    for key, irrigated in sorted(monthly_gal.items()):
        n = counts.get(key, 0)
        # A partial month cannot be priced: the free allowance and the tier are
        # month-level facts, so a 25-day month would land in the wrong tier.
        if n < 27:
            continue
        with_irr = tariff.water_bill(volumes[key]).total
        # The counterfactual is this month's own meter reading less the water the
        # controller put through it — not a modeled baseline, which was a second
        # estimate of the same thing and did not have to agree with the first.
        without = tariff.water_bill(max(0.0, volumes[key] - irrigated)).total
        cost += with_irr - without
        priced_volume += irrigated

    # The row this feeds is an annual figure, so report a year. Skipping the
    # partial months left the volume describing 11 while the section beside it
    # described 12. Scale the cost with the volume rather than by 12/n:
    # irrigation cost is close to proportional to volume inside a tier, and the
    # months that go unpriced are high-use ones.
    volume = sum(monthly_gal.values())
    if priced_volume > 0:
        cost *= volume / priced_volume
    return volume, cost


# ---------------------------------------------------------------------------
# The patio mini-split
# ---------------------------------------------------------------------------

# Both read off the label — see equipment.MINISPLIT. Held there rather than here
# so the transcription sits with the other nameplates and gets checked on every
# build; the full-draw figure used to be the magic number `7.5 * 230 / 1000`,
# with the three currents it came from recorded only in a comment.
MINISPLIT_BTU = equipment.MINISPLIT_BTU_COOLING
MINISPLIT_MAX_KW = equipment.minisplit_max_kw()
# Seasonal efficiencies in BTU per Wh. Conservative for an inverter unit.
COOLING_EER = 11.0
HEATING_HSPF = 8.0
# Superseded by real solar geometry — see solar.py. A due-south vertical window
# does not scale from horizontal by any fixed factor: the ratio runs 1.01 in
# December and 0.39 in June.
# Two large sliding patio doors, dual pane with low-E. Southern-climate low-E
# coatings run SHGC 0.25-0.35; clear dual pane would be about 0.70, so the
# coating is roughly halving the solar gain on this zone.
GLAZING_SHGC = 0.30
# Measured, both doors together — see equipment.PATIO_GLAZING_SQFT. Previously
# assumed at 110 sq ft, which was 45% too much glass.
GLAZING_SQFT = equipment.PATIO_GLAZING_SQFT
CLEAR_GLASS_SHGC = 0.70


@dataclass
class MiniSplit:
    """The patio zone's share of the two HVAC lines.

    Solved from the measured side rather than assumed. The furnace's own gas
    consumption fixes how many hours it ran, which fixes its blower energy —
    and whatever cold-weather electricity is left over must be the mini-split.
    That pins the zone's heat-loss coefficient, which then prices the cooling
    season too.
    """

    ua: float  # BTU/h/degF, effective — what the mini-split has to cover
    ua_envelope: float  # BTU/h/degF, true — adding back free winter solar
    blower_kwh: float
    heating_kwh: float
    cooling_kwh: float
    heating_share: float  # of the measured cold-weather line
    cooling_share: float  # of the measured cooling line
    duty_at_full_draw: float
    cost: float
    solar_kwh: float = 0.0
    solar_kwh_if_clear: float = 0.0
    winter_gain_kwh: float = 0.0
    winter_gain_if_clear: float = 0.0

    @property
    def lowe_saving_kwh(self) -> float:
        """Cooling avoided by the coating."""
        return self.solar_kwh_if_clear - self.solar_kwh

    @property
    def lowe_heating_penalty_kwh(self) -> float:
        """Winter heat the coating also blocks — the other side of the ledger."""
        extra = self.winter_gain_if_clear - self.winter_gain_kwh
        return extra * 3412.0 / HEATING_HSPF / 1000.0

    @property
    def solar_share_of_winter_load(self) -> float:
        return (
            (self.ua_envelope - self.ua) / self.ua_envelope if self.ua_envelope else 0.0
        )

    @property
    def total_kwh(self) -> float:
        return self.heating_kwh + self.cooling_kwh

    @property
    def design_load(self) -> float:
        return self.ua * 44.0

    @property
    def oversize_factor(self) -> float:
        return MINISPLIT_BTU / self.design_load if self.design_load else 0.0


def minisplit_estimate(
    days: list[Day],
    elec: ElectricModel,
    gas_sig: Signature,
    glazing: "solar.GlazingSeason",
    heat_setpoint: float = 71.0,
    cool_setpoint: float = 74.0,
    glazing_sqft: float = GLAZING_SQFT,
    # Both were round-number guesses until the furnace label turned up; they are
    # now its printed input rating and blower wattage.
    furnace_btu: float = equipment.FURNACE_INPUT_BTU,
    blower_watts: float = equipment.FURNACE_BLOWER_WATTS,
) -> MiniSplit | None:
    """Separate the patio mini-split from the main HVAC."""
    with_elec = [d for d in days if d.electric]
    if not with_elec:
        return None

    cold_line = sum(elec.heating_slope * d.weather.hdd(elec.heat_base_f) for d in with_elec)
    cool_line = sum(elec.cooling_slope * d.weather.cdd(elec.cool_base_f) for d in with_elec)

    # Furnace runtime is fixed by the gas it burned, which fixes blower energy.
    gas_cf = sum(gas_sig.slope * d.weather.hdd(gas_sig.base_f) for d in days if d.gas_cf is not None)
    # The furnace's own efficiency, off its label — not the assumed figure the
    # pool heater still has to use.
    delivered = gas_cf * tariff.MCF_TO_DTH * 1000.0 * equipment.FURNACE_EFFICIENCY
    blower_kwh = delivered / furnace_btu * blower_watts / 1000.0
    heating_kwh = max(cold_line - blower_kwh, 0.0)

    # Degree-hours at the zone's own setpoints, integrated from daily aggregates.
    heat_dh = sum(d.weather.hdd(heat_setpoint) for d in days) * 24.0
    cool_dh = sum(d.weather.cdd(cool_setpoint) for d in days) * 24.0
    if heat_dh <= 0:
        return None

    area_m2 = glazing_sqft / 10.76
    winter_gain = glazing.while_heating * area_m2 * GLAZING_SHGC
    summer_gain = glazing.while_cooling * area_m2 * GLAZING_SHGC

    # The measured heating energy is what the mini-split had to supply *after*
    # the south glass had already contributed. Adding that gain back recovers
    # the envelope's true heat-loss coefficient.
    ua_effective = heating_kwh * 1000.0 * HEATING_HSPF / heat_dh
    delivered_btu = heating_kwh * HEATING_HSPF * 1000.0 + winter_gain * 3412.0
    ua_envelope = delivered_btu / heat_dh

    conduction = ua_envelope * cool_dh / COOLING_EER / 1000.0
    solar_kwh = summer_gain * 3412.0 / COOLING_EER / 1000.0
    cooling_kwh = conduction + solar_kwh
    ua = ua_effective

    hours_above = sum(1 for d in days if d.weather.t_max > cool_setpoint) * 9.0
    duty = (
        cooling_kwh * 1000.0 / (MINISPLIT_MAX_KW * 1000.0) / hours_above
        if hours_above
        else 0.0
    )
    cost = (
        heating_kwh * tariff.marginal_rate(dt.date(2026, 1, 15))
        + cooling_kwh * tariff.marginal_rate(dt.date(2026, 7, 15))
    )
    return MiniSplit(
        ua=ua,
        ua_envelope=ua_envelope,
        blower_kwh=blower_kwh,
        heating_kwh=heating_kwh,
        cooling_kwh=cooling_kwh,
        heating_share=heating_kwh / cold_line if cold_line else 0.0,
        cooling_share=cooling_kwh / cool_line if cool_line else 0.0,
        duty_at_full_draw=duty,
        cost=cost,
        solar_kwh=solar_kwh,
        solar_kwh_if_clear=(
            glazing.while_cooling * area_m2 * CLEAR_GLASS_SHGC * 3412.0 / COOLING_EER / 1000.0
        ),
        winter_gain_kwh=winter_gain,
        winter_gain_if_clear=glazing.while_heating * area_m2 * CLEAR_GLASS_SHGC,
    )


# ---------------------------------------------------------------------------
# The pool pump
# ---------------------------------------------------------------------------

# A.O. Smith SQ1102: 1 HP nameplate, service factor 1.65, 3450 RPM, 48Y frame,
# capacitor start. Single speed — there is no modulation to exploit, so runtime
# is the only variable without changing hardware.
PUMP_HP = 1.0
PUMP_SERVICE_FACTOR = 1.65
PUMP_RPM = 3450
WATTS_PER_HP = 746.0
PUMP_MOTOR_EFFICIENCY = 0.75
# A 1 HP square-flange pump on typical residential head. The turnover figures
# scale inversely with this, so it is quoted as a range wherever it is used.
PUMP_FLOW_GPM = 60.0
# One turnover a day is the usual guidance, two if you want margin.
TURNOVERS_TARGET = 2.0


@dataclass
class PumpScenario:
    hours: float
    kw: float
    turnovers: float
    annual_kwh: float
    annual_cost: float
    label: str = ""


def pump_nameplate_watts(efficiency: float = PUMP_MOTOR_EFFICIENCY) -> float:
    """What the motor should draw at full load, from the nameplate alone."""
    return PUMP_HP * PUMP_SERVICE_FACTOR * WATTS_PER_HP / efficiency


def turnover_hours(volume_gal: float, gpm: float = PUMP_FLOW_GPM) -> float:
    return volume_gal / gpm / 60.0


def pump_scenarios(
    days: list[Day],
    measured_kw: float,
    volume_gal: float,
    hours_options: tuple[float, ...] = (6.75, 5.0, 4.0, 3.0),
) -> list[PumpScenario]:
    """Cost of running the existing single-speed motor for various daily hours."""
    with_elec = [d for d in days if d.electric]
    one = turnover_hours(volume_gal)
    out = []
    for hours in hours_options:
        cost = sum(tariff.marginal_rate(d.date) * measured_kw * hours for d in with_elec)
        out.append(
            PumpScenario(
                hours=hours,
                kw=measured_kw,
                turnovers=hours / one,
                annual_kwh=measured_kw * hours * len(with_elec),
                annual_cost=cost,
            )
        )
    return out


def variable_speed_scenarios(
    days: list[Day],
    measured_kw: float,
    volume_gal: float,
    speeds: tuple[float, ...] = (0.75, 0.5, 0.4),
    turnovers: float = TURNOVERS_TARGET,
) -> list[PumpScenario]:
    """What a variable-speed replacement would cost at the same filtration.

    Affinity laws: flow scales with speed, power with its cube. Halving the
    speed therefore moves half the water for an eighth of the power, so the
    same daily volume takes twice as long at a quarter of the energy.
    """
    with_elec = [d for d in days if d.electric]
    one = turnover_hours(volume_gal)
    out = []
    for frac in speeds:
        kw = measured_kw * frac**3
        hours = turnovers * one / frac
        cost = sum(tariff.marginal_rate(d.date) * kw * hours for d in with_elec)
        out.append(
            PumpScenario(
                hours=hours,
                kw=kw,
                turnovers=turnovers,
                annual_kwh=kw * hours * len(with_elec),
                annual_cost=cost,
                label=f"{frac:.0%} speed",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Unit costs
# ---------------------------------------------------------------------------


def degree_cost(gallons: float, day: dt.date) -> tuple[float, float]:
    """Gas needed, and its cost, to raise a body of water one degree F."""
    # One BTU raises one pound of water one degree F. The bill's own conversion
    # factor gives the heat content: 1 Mcf = 0.896 Dth, so 896 BTU per cubic foot.
    btu_per_cf = tariff.MCF_TO_DTH * 1000.0
    cf = gallons * LB_PER_GAL / APPLIANCE_EFFICIENCY / btu_per_cf
    return cf, cf * tariff.gas_marginal_per_kcf(day) / 1000.0


# Heater input while running, inferred from the October ramp: 879 cf burned
# over a 2.9 hour rise.
POOL_HEATER_BTU_PER_HOUR = 270000.0


@dataclass
class SpaFromRate:
    """Spa volume from how fast the heater raises it, not from a total.

    The probe is moved into the spa while it heats, which gives a clean linear
    ramp to work from. Rate beats energy accounting here: it needs no starting
    temperature, and it does not care how much of the day's gas went to the pool
    or to losses before and after the soak.
    """

    date: dt.date
    rate_f_per_hour: float
    gallons: float


def spa_volume_from_rate(
    samples: dict[dt.date, list[tuple[dt.datetime, float, float, float]]],
    dates: list[dt.date],
    burn_btu_per_hour: float = POOL_HEATER_BTU_PER_HOUR,
    efficiency: float = APPLIANCE_EFFICIENCY,
    step_threshold: float = 6.0,
    ceiling: float = 105.0,
) -> list[SpaFromRate]:
    """Measure the heating ramp on each soak and invert it for volume."""
    out: list[SpaFromRate] = []
    for date in dates:
        series = [(t, p) for t, p, _, _ in samples.get(date, [])]
        if len(series) < 20:
            continue
        # The move shows as a single-sample step from a flat, cooler reading.
        move = next(
            (
                i
                for i in range(1, len(series))
                if series[i][1] - series[i - 1][1] > step_threshold
                and series[i - 1][1] < 90.0
            ),
            None,
        )
        if move is None:
            continue
        end = move
        while (
            end + 1 < len(series)
            and series[end + 1][1] > series[end][1]
            and series[end][1] < ceiling
        ):
            end += 1
        hours = (series[end][0] - series[move][0]).total_seconds() / 3600.0
        if hours <= 0:
            continue
        rate = (series[end][1] - series[move][1]) / hours
        if rate <= 0:
            continue
        out.append(
            SpaFromRate(
                date=date,
                rate_f_per_hour=rate,
                gallons=burn_btu_per_hour * efficiency / (rate * LB_PER_GAL),
            )
        )
    return out


def refill_cost(
    days: list[Day],
    sig: Signature,
    refill_dates: list[dt.date],
    reheat_dates: list[dt.date],
) -> tuple[float, float, float, bool]:
    """Water plus gas for a complete drain and refill."""
    by_date = {d.date: d for d in days}
    month = f"{refill_dates[0]:%Y-%m}"
    actual = sum(d.water_gal for d in days if f"{d.date:%Y-%m}" == month and d.water_gal)
    normal = statistics.median(
        [d.water_gal for d in days if d.water_gal is not None and d.date not in refill_dates]
    )
    refilled = sum(by_date[d].water_gal for d in refill_dates if d in by_date) - normal * len(
        refill_dates
    )
    with_bill = tariff.water_bill(actual)
    without = tariff.water_bill(actual - refilled)

    gas_cf = sum(
        by_date[d].gas_cf - sig.predict(by_date[d].weather.hdd(sig.base_f))
        for d in reheat_dates
        if d in by_date and by_date[d].gas_cf is not None
    )
    gas = gas_cf * tariff.gas_marginal_per_kcf(reheat_dates[0]) / 1000.0
    return with_bill.total - without.total, gas, refilled, with_bill.above_observed
