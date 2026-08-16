"""Published tariffs, transcribed from actual bills.

This module replaces the earlier `rates.py`, which inferred a single blended
rate by dividing cost by usage. That inference was wrong in two ways the bills
have now settled:

  1. The COST column in the Green Button billing export is *only* the
     "Total Energy Charges" line. The real bill adds riders, a customer charge,
     a franchise fee and taxes. Actual amounts due run 26-57% higher.
  2. EPE's summer rate IS tiered — 600 kWh at one rate, everything above it at
     another 55% higher. The blended rate therefore drifts with consumption,
     which is exactly the variation previously dismissed as noise.

Every rate below is transcribed from a PDF bill, not derived. Sources:

    electric1.pdf   EPE, 19 Jun - 21 Jul 2026, 2,358 kWh, $294.17 due
    electric2.pdf   EPE, 17 Dec 2025 - 20 Jan 2026, 1,560 kWh, $142.07 due
    electric3.pdf   EPE, 18 Sep - 20 Oct 2025, 1,608 kWh, $149.48 due
    electric4.pdf   EPE, 20 Mar - 21 Apr 2026, 1,495 kWh, $146.48 due
    utility1.pdf    Las Cruces, read 16 Jul 2026, $83.29 due
    utility2.pdf    Las Cruces, read 15 Jan 2025, $102.23 due
    utility3.pdf    Las Cruces, read 14 Apr 2026, 9,000 gal — the refill month
    utility4.pdf    Las Cruces, read 12 Dec 2025, $104.86 due
    utility5.pdf    Las Cruces, read 15 Jan 2026, $107.30 due
    utility6.pdf    Las Cruces, read 13 Feb 2026, $111.32 due

`validate()` reproduces all four totals from the rates alone; the build fails
loudly if any drifts. See KNOWN_GAPS for what the bills do not pin down.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Things a full year of bills still cannot determine, stated plainly
# ---------------------------------------------------------------------------

KNOWN_GAPS = [
    "Water has no second tier boundary anywhere in the record: 3,000 gallons "
    "free, then a flat $2.85 per 1,000 of commodity charge across every bill — "
    "$3.27 all-in once the franchise fee and tax that ride on it are added, which "
    "is the figure the cost section prices with — up to the largest ever "
    "billed at 9,000. Whether an escalating tier exists above that is unknown — "
    "no month has ever reached it, so no bill would have shown it.",
    "The gas commodity rate is a monthly pass-through and is known for every "
    "month of the record, spanning $0.40 to $3.37/Dth. Only days between two "
    "meter reads are interpolated, and never across more than one month.",
    "Wastewater is billed on a fixed allowance re-set annually, not on the "
    "month's own water use. A full year shows 4,000 gal holding through the "
    "February 2026 read and 2,000 from the March one. The date it re-sets is "
    "observed; the formula that chooses the number is not published.",
]



# ---------------------------------------------------------------------------
# Electricity — El Paso Electric, New Mexico Residential Service
# ---------------------------------------------------------------------------

SUMMER_TIER_KWH = 600
SUMMER_TIER1_RATE = 0.07035
SUMMER_TIER2_RATE = 0.10876
WINTER_RATE = 0.05816

# EPE's summer season, recovered empirically: a billing period is summer when
# it ENDS in June, July, August or September. That rule reproduces the season
# assignment of all 35 periods in the billing export.
SUMMER_END_MONTHS = {6, 7, 8, 9}

# Applied to everything except taxes; then tax on the lot. Both bills agree to
# three decimal places, so these are exact, not fitted.
FRANCHISE_PCT = 0.030
TAX_PCT = 0.065


@dataclass(frozen=True)
class ElectricRiders:
    """Per-kWh and fixed adders. These drift; each bill pins one date."""

    effective: dt.date
    fuel_adjustment: float  # $/kWh, negative when it is a credit
    renewable_standard: float  # $/kWh
    transport_electrification: float  # $/kWh
    efficient_use: float  # $/kWh
    metering_rider: float  # $/month
    customer_charge: float = 7.00

    @property
    def volumetric(self) -> float:
        """Total per-kWh adders, before franchise fee and tax."""
        return (
            self.fuel_adjustment
            + self.renewable_standard
            + self.transport_electrification
            + self.efficient_use
        )

    @property
    def fixed(self) -> float:
        return self.customer_charge + self.metering_rider


# Transcribed from the two EPE bills.
ELECTRIC_RIDERS = [
    # One entry per bill, a full year of them. The fuel adjustment is a monthly
    # pass-through and swings hard — it runs from +$0.0026 to -$0.0197 per kWh
    # across this year, changing sign in November — so nothing here is
    # interpolated: each bill month is priced with its own set.
    ElectricRiders(
        effective=dt.date(2025,1,20),
        fuel_adjustment=-0.003928,
        renewable_standard=0.015742,
        transport_electrification=0.000095,
        efficient_use=0.002695,  # $2.42 / 898 kWh
        metering_rider=1.60,
    ),
    ElectricRiders(
        effective=dt.date(2025,7,18),
        fuel_adjustment=0.004137,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.004628,  # $9.70 / 2,096 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2025,8,19),
        fuel_adjustment=0.002611,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.004576,  # $9.87 / 2,157 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2025,9,18),
        fuel_adjustment=0.000852,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.004042,  # $6.60 / 1,633 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2025,10,20),
        fuel_adjustment=0.000935,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.002799,  # $4.50 / 1,608 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2025,11,18),
        fuel_adjustment=-0.003107,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.002741,  # $3.19 / 1,164 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2025,12,17),
        fuel_adjustment=-0.010093,
        renewable_standard=0.015742,
        transport_electrification=0.000944,
        efficient_use=0.002492,  # $3.00 / 1,204 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2026,1,20),
        fuel_adjustment=-0.005404,
        renewable_standard=0.020215,
        transport_electrification=0.000944,
        efficient_use=0.002744,  # $4.28 / 1,560 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2026,2,18),
        fuel_adjustment=-0.004205,
        renewable_standard=0.020215,
        transport_electrification=0.000944,
        efficient_use=0.002834,  # $3.61 / 1,274 kWh
        metering_rider=2.92,
    ),
    ElectricRiders(
        effective=dt.date(2026,3,20),
        fuel_adjustment=0.000517,
        renewable_standard=0.020215,
        transport_electrification=0.001002,
        efficient_use=0.003042,  # $3.65 / 1,200 kWh
        metering_rider=3.82,
    ),
    ElectricRiders(
        effective=dt.date(2026,4,21),
        fuel_adjustment=-0.000247,
        renewable_standard=0.020215,
        transport_electrification=0.001002,
        efficient_use=0.002950,  # $4.41 / 1,495 kWh
        metering_rider=3.82,
    ),
    ElectricRiders(
        effective=dt.date(2026,5,20),
        fuel_adjustment=-0.019725,
        renewable_standard=0.020215,
        transport_electrification=0.001002,
        efficient_use=0.002293,  # $3.33 / 1,452 kWh
        metering_rider=3.82,
    ),
    ElectricRiders(
        effective=dt.date(2026,6,19),
        fuel_adjustment=-0.012249,
        renewable_standard=0.020215,
        transport_electrification=0.001002,
        efficient_use=0.003791,  # $6.79 / 1,791 kWh
        metering_rider=3.82,
    ),
    ElectricRiders(
        effective=dt.date(2026,7,21),
        fuel_adjustment=-0.014824,
        renewable_standard=0.020215,
        transport_electrification=0.001002,
        efficient_use=0.003757,  # $8.86 / 2,358 kWh
        metering_rider=3.82,
    ),
]



@dataclass
class ElectricBill:
    kwh: float
    summer: bool
    energy_charge: float
    rider_charge: float
    fixed_charge: float
    franchise: float
    tax: float

    @property
    def total(self) -> float:
        return (
            self.energy_charge
            + self.rider_charge
            + self.fixed_charge
            + self.franchise
            + self.tax
        )

    @property
    def effective_rate(self) -> float:
        return self.total / self.kwh if self.kwh else 0.0


def is_summer_period(end: dt.date) -> bool:
    return end.month in SUMMER_END_MONTHS


def riders_for(day: dt.date) -> ElectricRiders:
    """The rider set that governed a given day.

    Each entry is dated to the bill that printed it, and a bill states the rates
    for the period *ending* on that date. So the set in force is the first one
    dated on or after the day — not the nearest, which for a day early in a
    billing period would reach backwards to rates that had already lapsed.
    """
    for riders in ELECTRIC_RIDERS:
        if day <= riders.effective:
            return riders
    return ELECTRIC_RIDERS[-1]


def energy_charge(kwh: float, summer: bool) -> float:
    """The tiered energy charge — the only part the billing export records."""
    if not summer:
        return kwh * WINTER_RATE
    first = min(kwh, SUMMER_TIER_KWH)
    return first * SUMMER_TIER1_RATE + max(kwh - SUMMER_TIER_KWH, 0) * SUMMER_TIER2_RATE


def electric_bill(kwh: float, end: dt.date) -> ElectricBill:
    """Reconstruct a full bill from consumption and the period end date."""
    summer = is_summer_period(end)
    riders = riders_for(end)
    energy = energy_charge(kwh, summer)
    rider_charge = kwh * riders.volumetric
    fixed = riders.fixed
    subtotal = energy + rider_charge + fixed
    franchise = subtotal * FRANCHISE_PCT
    tax = (subtotal + franchise) * TAX_PCT
    return ElectricBill(
        kwh=kwh,
        summer=summer,
        energy_charge=energy,
        rider_charge=rider_charge,
        fixed_charge=fixed,
        franchise=franchise,
        tax=tax,
    )


def marginal_rate(day: dt.date, above_tier: bool = True) -> float:
    """What one more kWh actually costs, all-in.

    This is the number that matters for any decision about shifting or removing
    load — not the blended average, which is diluted by the customer charge and
    by the cheap first tier.
    """
    summer = is_summer_period(day)
    riders = riders_for(day)
    if summer:
        base = SUMMER_TIER2_RATE if above_tier else SUMMER_TIER1_RATE
    else:
        base = WINTER_RATE
    return (base + riders.volumetric) * (1 + FRANCHISE_PCT) * (1 + TAX_PCT)


# ---------------------------------------------------------------------------
# Water — City of Las Cruces, rate class 3000
# ---------------------------------------------------------------------------

WATER_ACCESS_FEE = 13.60
# Water is a free block and then a flat rate, with no second boundary anywhere
# in the record. Every bill prints the volumetric line as "First 3,000 at $0.00"
# plus "Next N at $2.85", and in every one of them N is simply that month's usage
# less 3,000 — 1,000 at 4,000 gallons, 6,000 at 9,000. The "Next" figure
# describes the bill, not the tariff, and reading it as a tier width is what
# previously put a phantom boundary there.
WATER_FREE_GAL = 3000.0
WATER_RATE_PER_KGAL = 2.8500
# The largest month ever billed. Nothing above it has been observed, so nothing
# above it is claimed: a higher tier could exist there and these bills would not
# show it.
WATER_MAX_OBSERVED_GAL = 9000.0
# Kept for callers that want the shape: free block, then everything else.
WATER_TIERS: list[tuple[float, float]] = [
    (WATER_FREE_GAL, 0.0000),
    (float("inf"), WATER_RATE_PER_KGAL),
]
WATER_RIGHTS_PER_KGAL = 0.1100
WATER_LITIGATION_PER_KGAL = 0.0900
WATER_DEVEL_PER_KGAL = 0.0000
WATER_FRANCHISE_PCT = 0.020
WATER_GGRT_PCT = 0.050

WASTEWATER_ACCESS = 8.26
WASTEWATER_TIERS: list[tuple[float, float]] = [(3000, 2.0000), (1000, 3.7900)]

# Wastewater is billed on a fixed allowance rather than on the month's own water
# use, and the allowance is re-set annually from the preceding winter's average.
# A full year of bills shows it holding at 4,000 gallons through the February
# 2026 read and dropping to 2,000 from the March one — an annual step, not the
# seasonal Dec-Feb pattern six bills had suggested. Each entry is the volume
# billed from that read date onward.
WASTEWATER_ALLOWANCE = [
    (dt.date(2025, 7, 15), 3000.0),
    (dt.date(2025, 1, 15), 3000.0),
    (dt.date(2025, 8, 14), 4000.0),
    (dt.date(2026, 3, 18), 2000.0),
]
WASTEWATER_FRANCHISE_PCT = 0.020
WASTEWATER_GGRT_PCT = 0.050
SOLID_WASTE_TYPICAL = 25.94  # mean of the bills ($26.27, $25.61)


def wastewater_allowance(day: dt.date) -> float:
    """Billed wastewater volume in force on a given date."""
    volume = WASTEWATER_ALLOWANCE[0][1]
    for effective, gallons in WASTEWATER_ALLOWANCE:
        if day >= effective:
            volume = gallons
    return volume


def wastewater_bill(day: dt.date) -> float:
    """Wastewater charge for a billing date."""
    gallons = wastewater_allowance(day)
    remaining = gallons
    volumetric = 0.0
    for size, rate in WASTEWATER_TIERS:
        used = min(remaining, size)
        volumetric += used / 1000.0 * rate
        remaining -= used
        if remaining <= 0:
            break
    subtotal = WASTEWATER_ACCESS + volumetric
    franchise = subtotal * WASTEWATER_FRANCHISE_PCT
    return subtotal + franchise + (subtotal + franchise) * WASTEWATER_GGRT_PCT



@dataclass
class WaterBill:
    gallons: float
    access: float
    volumetric: float
    riders: float
    franchise: float
    tax: float
    above_observed: bool

    @property
    def total(self) -> float:
        return self.access + self.volumetric + self.riders + self.franchise + self.tax


def water_bill(gallons: float) -> WaterBill:
    billable = max(gallons - WATER_FREE_GAL, 0.0)
    volumetric = billable / 1000.0 * WATER_RATE_PER_KGAL
    # Not "above the top tier" — there is no observed top tier. This flags usage
    # beyond the largest bill on file, where an escalating tier could exist and
    # this figure would then understate the cost.
    above = gallons > WATER_MAX_OBSERVED_GAL

    kgal = gallons / 1000.0
    riders = kgal * (
        WATER_RIGHTS_PER_KGAL + WATER_LITIGATION_PER_KGAL + WATER_DEVEL_PER_KGAL
    )
    subtotal = WATER_ACCESS_FEE + volumetric + riders
    franchise = subtotal * WATER_FRANCHISE_PCT
    tax = (subtotal + franchise) * WATER_GGRT_PCT
    return WaterBill(
        gallons=gallons,
        access=WATER_ACCESS_FEE,
        volumetric=volumetric,
        riders=riders,
        franchise=franchise,
        tax=tax,
        above_observed=above,
    )


def water_marginal_per_kgal(current_monthly_gal: float) -> float:
    """All-in cost of the next 1,000 gallons at the current monthly position."""
    base = 0.0 if current_monthly_gal < WATER_FREE_GAL else WATER_RATE_PER_KGAL
    base += WATER_RIGHTS_PER_KGAL + WATER_LITIGATION_PER_KGAL
    return base * (1 + WATER_FRANCHISE_PCT) * (1 + WATER_GGRT_PCT)


# ---------------------------------------------------------------------------
# Natural gas — City of Las Cruces, rate class 2000
# ---------------------------------------------------------------------------

# Flat at $14.50 across every bill on file.
GAS_ACCESS_FEE = 14.50
MCF_TO_DTH = 0.89600
GAS_SERVICE_PER_DTH = 1.3400
GAS_DECARB_PER_DTH = 0.1500
GAS_FRANCHISE_PCT = 0.020

# One point per bill, every meter read for a full year. Interpolation now only
# ever runs between adjacent months rather than across half-year gaps.
GAS_COMMODITY_POINTS = [
    (dt.date(2025, 7, 15), 2.1136),
    (dt.date(2025, 1, 15), 3.1300),
    (dt.date(2025, 8, 14), 2.1200),
    (dt.date(2025, 9, 15), 2.0700),
    (dt.date(2025, 10, 15), 2.0700),
    (dt.date(2025, 11, 14), 2.4200),
    (dt.date(2025, 12, 12), 3.3700),
    (dt.date(2026, 1, 15), 2.9000),
    (dt.date(2026, 2, 13), 2.8900),
    (dt.date(2026, 3, 18), 1.2500),
    (dt.date(2026, 4, 14), 0.5000),
    (dt.date(2026, 5, 14), 0.5000),
    (dt.date(2026, 6, 12), 0.4000),
    (dt.date(2026, 7, 16), 1.1000),
]
GAS_GRT_POINTS = [
    (dt.date(2025, 1, 15), 0.08056),
    (dt.date(2025, 12, 12), 0.08390),
    (dt.date(2026, 7, 16), 0.08390),
]


def _interpolate(points: list[tuple[dt.date, float]], day: dt.date) -> float:
    """Piecewise-linear between dated observations, flat outside their range."""
    ordered = sorted(points)
    if day <= ordered[0][0]:
        return ordered[0][1]
    if day >= ordered[-1][0]:
        return ordered[-1][1]
    for (d0, r0), (d1, r1) in zip(ordered, ordered[1:]):
        if d0 <= day <= d1:
            return r0 + (r1 - r0) * ((day - d0).days / (d1 - d0).days)
    return ordered[-1][1]


def gas_commodity_rate(day: dt.date) -> float:
    return _interpolate(GAS_COMMODITY_POINTS, day)


def gas_grt_rate(day: dt.date) -> float:
    return _interpolate(GAS_GRT_POINTS, day)


@dataclass
class GasBill:
    cubic_feet: float
    dekatherms: float
    access: float
    commodity: float
    service: float
    decarb: float
    franchise: float
    tax: float

    @property
    def total(self) -> float:
        return (
            self.access
            + self.commodity
            + self.service
            + self.decarb
            + self.franchise
            + self.tax
        )


def gas_bill(cubic_feet: float, day: dt.date, as_billed: bool = False) -> GasBill:
    """Cost of a volume of gas.

    The meter reads in whole Mcf and the bill charges whole dekatherms — 1 Mcf
    converts to 0.896 Dth but is billed as 1 Dth. `as_billed=True` reproduces
    that rounding, which is needed to match a paper bill. The default keeps the
    exact conversion, which is the right basis for daily figures, where rounding
    to whole units would be meaningless.
    """
    dth = cubic_feet / 1000.0 * MCF_TO_DTH
    if as_billed:
        dth = round(dth)
    commodity = dth * gas_commodity_rate(day)
    service = dth * GAS_SERVICE_PER_DTH
    decarb = dth * GAS_DECARB_PER_DTH
    subtotal = GAS_ACCESS_FEE + commodity + service + decarb
    franchise = subtotal * GAS_FRANCHISE_PCT
    tax = (subtotal + franchise) * gas_grt_rate(day)
    return GasBill(
        cubic_feet=cubic_feet,
        dekatherms=dth,
        access=GAS_ACCESS_FEE,
        commodity=commodity,
        service=service,
        decarb=decarb,
        franchise=franchise,
        tax=tax,
    )


def gas_marginal_per_kcf(day: dt.date) -> float:
    """All-in cost of the next 1,000 cubic feet."""
    per_dth = gas_commodity_rate(day) + GAS_SERVICE_PER_DTH + GAS_DECARB_PER_DTH
    return per_dth * MCF_TO_DTH * (1 + GAS_FRANCHISE_PCT) * (1 + gas_grt_rate(day))


# ---------------------------------------------------------------------------
# Self-check against the source bills
# ---------------------------------------------------------------------------


@dataclass
class Check:
    label: str
    expected: float
    actual: float

    @property
    def delta(self) -> float:
        return self.actual - self.expected

    @property
    def ok(self) -> bool:
        return abs(self.delta) <= max(0.02, abs(self.expected) * 0.005)


def validate() -> list[Check]:
    """Reproduce every bill total from the rates above.

    One entry per bill, a full year of each utility plus two older ones. Any
    drift means a transcription slipped, so the build treats a failure as fatal
    rather than shipping a dashboard full of confidently wrong money.
    """
    electric = [
        (dt.date(2025, 1, 20), 898, 81.12),
        (dt.date(2025, 7, 18), 2096, 294.18),
        (dt.date(2025, 8, 19), 2157, 299.43),
        (dt.date(2025, 9, 18), 1633, 219.08),
        (dt.date(2025, 10, 20), 1608, 149.48),
        (dt.date(2025, 11, 18), 1164, 105.98),
        (dt.date(2025, 12, 17), 1204, 99.69),
        (dt.date(2026, 1, 20), 1560, 142.07),
        (dt.date(2026, 2, 18), 1274, 119.81),
        (dt.date(2026, 3, 20), 1200, 121.03),
        (dt.date(2026, 4, 21), 1495, 146.48),
        (dt.date(2026, 5, 20), 1452, 110.52),
        (dt.date(2026, 6, 19), 1791, 225.32),
        (dt.date(2026, 7, 21), 2358, 294.17),
    ]
    gas = [
        (dt.date(2025, 7, 15), 1000, 20.01),
        (dt.date(2025, 1, 15), 4000, 36.35),
        (dt.date(2025, 8, 14), 0, 16.03),
        (dt.date(2025, 9, 15), 1000, 19.97),
        (dt.date(2025, 10, 15), 2000, 23.90),
        (dt.date(2025, 11, 14), 0, 16.03),
        (dt.date(2025, 12, 12), 2000, 26.77),
        (dt.date(2026, 1, 15), 3000, 30.59),
        (dt.date(2026, 2, 13), 4000, 35.40),
        (dt.date(2026, 3, 18), 1000, 19.07),
        (dt.date(2026, 4, 14), 3000, 22.63),
        (dt.date(2026, 5, 14), 1000, 18.23),
        (dt.date(2026, 6, 12), 0, 16.03),
        (dt.date(2026, 7, 16), 1000, 18.89),
    ]
    # Water has no dated rates, so one check per distinct volume is enough —
    # repeating a 3,000 gallon bill four times would test the same arithmetic.
    water = [(2000, 14.99), (3000, 15.20), (4000, 18.47), (5000, 21.74),
             (6000, 24.99), (9000, 34.79)]
    wastewater = [
        (dt.date(2025, 7, 15), 15.28),
        (dt.date(2025, 12, 12), 19.33),
        (dt.date(2026, 4, 14), 13.14),
    ]

    checks = [
        Check(f"EPE {end:%Y-%m}, {kwh:,} kWh", total, electric_bill(kwh, end).total)
        for end, kwh, total in electric
    ]
    checks += [
        Check(f"Gas {day:%Y-%m}, {cf / 1000:.0f} Mcf @ ${gas_commodity_rate(day):.2f}/Dth",
              total, gas_bill(cf, day, as_billed=True).total)
        for day, cf, total in gas
    ]
    checks += [
        Check(f"Water, {gal:,} gal", total, water_bill(gal).total)
        for gal, total in water
    ]
    checks += [
        Check(f"Wastewater {day:%Y-%m}, {wastewater_allowance(day):,.0f} gal allowance",
              total, wastewater_bill(day))
        for day, total in wastewater
    ]
    checks += [
        Check("EPE summer energy charge only", 233.41, energy_charge(2358, summer=True)),
        Check("EPE winter energy charge only", 90.73, energy_charge(1560, summer=False)),
    ]
    return checks
