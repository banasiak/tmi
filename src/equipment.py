"""Nameplate data, transcribed from photographs of the equipment.

Same rule as `tariff`: typed in by hand from the source, never inferred from
consumption. Everything here is a manufacturer's rating, so where a figure below
disagrees with one derived from the meters, the meters are describing what the
machine *did* and this file is describing what it was *built to do* — both are
real, and the gap between them is usually the interesting part.

The single most consequential line in this file is the model prefix of the
condenser. Carrier numbers cooling-only condensers `24…` and heat pumps `25…`,
and the UL block on this one reads CENTRAL COOLING AIR CONDITIONER. The house
therefore has no central heat pump: all central heat is the gas furnace, and the
only heat pump on the property is the patio mini-split.

**This module is a record, not a library.** Several constants here are read by
nothing — the refrigerant charge, the locked-rotor amps, the furnace blower's
ratings, the garage wall and door dimensions. They are kept deliberately. A
label reading is expensive to reacquire and impossible to reconstruct: getting
it back means a flashlight, a ladder, and the machine still being there. Code
that no longer runs can always be rewritten from the logic around it, so it goes
the moment it stops being called; a measurement cannot, so it stays whether or
not anything currently computes with it. Do not treat an unreferenced constant
in this file as dead code.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Nameplate:
    role: str
    maker: str
    model: str
    # None where no date is printed on the label. Never guess one: a fabricated
    # build date would be indistinguishable from a transcribed one everywhere it
    # is displayed.
    made: dt.date | None
    # Short form for a tile; `detail` is the fuller line. Kept as its own field
    # because splitting `detail` on punctuation truncates "88,000 BTU/h" to "88".
    headline: str
    detail: str
    # Only where it is actually known. `made` comes off the label; an install
    # date has to come from somebody's memory, so most of these stay None rather
    # than being guessed from the manufacture date.
    installed: dt.date | None = None
    # Why `made` is None, when it is. The default is the common case — the label
    # simply carries no date. But "the label has no date" and "the label defers
    # to an encoded serial nobody has decoded" are different claims, and printing
    # the first when the second is true would be a small lie in the one place
    # this file exists to prevent them.
    undated_reason: str = "no date on the label"

    @property
    def age_years(self) -> float | None:
        return (dt.date.today() - self.made).days / 365.25 if self.made else None

    @property
    def vintage(self) -> str:
        """How old this thing is, where the label says."""
        if self.made:
            return f"built {self.made:%b %Y}, {self.age_years:.0f} years old"
        return self.undated_reason

    @property
    def shelf_days(self) -> int | None:
        """Days between leaving the factory and going into service."""
        if self.installed is None or self.made is None:
            return None
        return (self.installed - self.made).days


# --- central cooling --------------------------------------------------------
# Carrier 24ABB3, "Comfort 13" — a cooling-only condenser. 42 = 42,000 BTU/h
# nominal, i.e. 3.5 tons. TXV metering at the indoor coil.
CONDENSER = Nameplate(
    role="Central air conditioning",
    maker="Carrier",
    model="24ABB342A300",
    made=dt.date(2009, 10, 1),
    headline="3.5 ton",
    detail="13 SEER, R-410A, cooling only",
)
COOLING_BTU = 42000.0
COOLING_TONS = COOLING_BTU / 12000.0
CONDENSER_SEER = 13.0
COMPRESSOR_RLA = 17.9       # amps, rated load
COMPRESSOR_LRA = 112.0      # amps, locked rotor
CONDENSER_FAN_FLA = 1.1     # amps
NAMEPLATE_VOLTS = 230.0
NAMEPLATE_MCA = 23.5        # amps, minimum circuit ampacity
REFRIGERANT_LB = 5.84

# Power factor for a single-phase hermetic compressor under load. Assumed — it
# is the one number in the electrical estimate below that is not on the label.
ASSUMED_POWER_FACTOR = 0.90


def minimum_circuit_amps() -> float:
    """NEC 440.33: 125% of the largest motor, plus the rest.

    Reproducing the printed MCA from the printed RLA is a check on the
    transcription, not on the equipment — if this disagrees with `NAMEPLATE_MCA`
    then a number above was typed wrong.
    """
    return 1.25 * COMPRESSOR_RLA + CONDENSER_FAN_FLA


def rated_draw_kw(power_factor: float = ASSUMED_POWER_FACTOR) -> float:
    """Ceiling on the outdoor unit's draw, from rated-load current."""
    amps = COMPRESSOR_RLA + CONDENSER_FAN_FLA
    return amps * NAMEPLATE_VOLTS * power_factor / 1000.0


# --- central heating --------------------------------------------------------
# Carrier 58DLA090, an 80%-class induced-draft furnace. Input and output are
# both printed, so its efficiency is read rather than assumed.
FURNACE = Nameplate(
    role="Central heating",
    maker="Carrier",
    model="58DLA090-16",
    made=dt.date(2009, 11, 1),
    headline="88,000 BTU/h",
    detail="80.7% efficient, 71,000 BTU/h out",
)
FURNACE_INPUT_BTU = 88000.0
FURNACE_OUTPUT_BTU = 71000.0
FURNACE_BLOWER_HP = 0.5
FURNACE_BLOWER_WATTS = 373.0
FURNACE_MAX_AMPS = 10.0
FURNACE_VOLTS = 115.0

# Measured, not assumed: both sides of the ratio are on the label.
FURNACE_EFFICIENCY = FURNACE_OUTPUT_BTU / FURNACE_INPUT_BTU


# --- domestic hot water -----------------------------------------------------
WATER_HEATER = Nameplate(
    role="Water heater",
    maker="Rheem",
    model="XG50T12HE40U0",
    made=dt.date(2024, 3, 15),
    headline="50 gal",
    detail="40,000 BTU/h, natural draft",
    # 28 March 2024. The year was uncertain from memory alone, but it was a
    # Thursday, and 28 March falls on a Thursday only in 2024 across the years
    # the label admits — 2023 predates manufacture, 2025 was a Friday.
    installed=dt.date(2024, 3, 28),
)
WATER_HEATER_GALLONS = 50.0
WATER_HEATER_INPUT_BTU = 40000.0

# --- pool plant ------------------------------------------------------------
# Sta-Rite Max-E-Therm SR333NA. The label prints the input rating only, so the
# heater's efficiency is still assumed — it is now the sole remaining user of
# `costs.APPLIANCE_EFFICIENCY`.
POOL_HEATER = Nameplate(
    role="Pool heater",
    maker="Sta-Rite",
    model="SR333NA",
    made=dt.date(2009, 12, 4),
    headline="333,000 BTU/h",
    detail="natural gas, input rating",
)
POOL_HEATER_INPUT_BTU = 333000.0

# Pentair FNS Plus 36, a 36 sq ft DE filter. The flow figure is the
# manufacturer's private-pool rating: a ceiling on what may be pushed through
# it, not a measurement of what is.
POOL_FILTER = Nameplate(
    role="Pool filter",
    maker="Pentair",
    model="FNS Plus 36",
    made=dt.date(2022, 7, 19),
    headline="36 ft²",
    detail="DE, rated 90 GPM for a private pool",
)
FILTER_AREA_SQFT = 36.0
FILTER_MAX_GPM_PRIVATE = 90.0
FILTER_MAX_GPM_PUBLIC = 72.0
FILTER_DE_LB = 3.6

# The pool tops itself up through a float valve, so evaporation is replaced
# automatically and shows in the water meter as overnight flow in summer and
# none in winter. Anything reading the small hours for a leak has to account
# for it first.
POOL_HAS_FLOAT_VALVE = True

# Pentair Max-E-Pro, 1 HP energy-efficient. This is the *wet end*; the A.O.
# Smith SQ1102 whose nameplate predicts the measured 1.65 kW is the square-flange
# motor bolted to it. The two labels describe the same pump, not two pumps.
POOL_PUMP = Nameplate(
    role="Pool pump",
    maker="Pentair",
    model="P6E6E-206L",
    made=dt.date(2009, 11, 20),
    headline="1 HP",
    detail="Max-E-Pro EE, single speed",
)

# --- the patio mini-split ---------------------------------------------------
# The property's only heat pump, and the one machine here that is two labelled
# units: indoor PIAW121790A, outdoor PIAW121800B. The model recorded below is the
# outdoor unit, which is where the compressor and the ratings live.
#
# The value column on this label sits one row below its heading, so the currents
# have to be assigned before they can be transcribed. Physics settles it rather
# than judgement: read as printed, the compressor draws 0.45 A — 104 W for
# 12,000 BTU/h, which is 116 BTU/Wh and impossible. Shifted up a row it draws
# 6.8 A, or 7.7 BTU/Wh at full load, which is what a 12k inverter should do.
MINISPLIT_INDOOR_MODEL = "PIAW121790A"
MINISPLIT_COMPRESSOR_A = 6.80
MINISPLIT_OUTDOOR_FAN_A = 0.45
MINISPLIT_INDOOR_FAN_A = 0.25
MINISPLIT_VOLTS = 230.0
MINISPLIT_BTU_COOLING = 12000.0
MINISPLIT_BTU_HEATING = 12000.0
MINISPLIT_REFRIGERANT_OZ = 29.63
# Printed, but not derivable from the currents above the way the Carrier's is —
# see the note in `validate`.
MINISPLIT_MCA_OUTDOOR = 15.0

MINISPLIT = Nameplate(
    role="Patio mini-split",
    maker="Premium Levella",
    model="PIAW121800B",
    # The label prints no date. It says SEE THE BAR CODE FOR THE PRODUCED DATE,
    # and the serial does not decode without the manufacturer's key — so this
    # stays None rather than becoming a plausible-looking guess.
    made=None,
    undated_reason="date encoded in the serial, not decoded",
    headline="12,000 BTU/h",
    detail="heat pump, both ways · R-410A · the only one on the property",
)


def minisplit_max_amps() -> float:
    """Every motor on the unit running at once — the ceiling on its draw."""
    return (
        MINISPLIT_COMPRESSOR_A + MINISPLIT_OUTDOOR_FAN_A + MINISPLIT_INDOOR_FAN_A
    )


def minisplit_max_kw() -> float:
    return minisplit_max_amps() * MINISPLIT_VOLTS / 1000.0


# --- measured geometry ------------------------------------------------------
# Tape-measure figures, not estimates. Kept here rather than in `costs` because
# they are facts about the building in the same way a nameplate is a fact about
# a machine: measured once, then used wherever a model needs them.


def feet(ft: float, inches: float = 0.0) -> float:
    return ft + inches / 12.0


# The wall between the house and the garage, and the door in it. The door is
# worth keeping separate: a hollow-core interior door is a far worse insulator
# than the wall around it, so a single area would misstate the conductance.
GARAGE_WALL_FT = (feet(19), feet(9))
GARAGE_DOOR_FT = (feet(2, 8), feet(6, 8))
GARAGE_WALL_SQFT = GARAGE_WALL_FT[0] * GARAGE_WALL_FT[1]
GARAGE_DOOR_SQFT = GARAGE_DOOR_FT[0] * GARAGE_DOOR_FT[1]
GARAGE_WALL_OPAQUE_SQFT = GARAGE_WALL_SQFT - GARAGE_DOOR_SQFT

# The patio's south-facing sliding glass — *both* doors together, which is the
# figure the solar model wants. This replaces a long-standing assumption of
# 110 sq ft inferred from the phrase "two large sliders": the real opening is
# 31% smaller than that, so every solar-gain figure for the patio moves with it.
PATIO_GLAZING_FT = (feet(11, 8), feet(6, 6))
PATIO_GLAZING_SQFT = PATIO_GLAZING_FT[0] * PATIO_GLAZING_FT[1]

# The fixed plant: what is bolted to the house. The equipment section tiles these.
ALL = (
    CONDENSER, FURNACE, WATER_HEATER, POOL_HEATER, POOL_FILTER, POOL_PUMP,
    MINISPLIT,
)
# Everything whose label has been transcribed. The electric motorcycle's plate was
# here too, and came out with the rest of its analysis: the only data behind it was
# a charger log covering eight summer weeks on a rolling window, which is not a
# year and cannot be made into one. Its energy now sits in the residual with the
# other loads too small or too irregular to separate.
TRANSCRIBED = ALL


@dataclass
class Check:
    label: str
    expected: float
    actual: float
    unit: str
    tolerance: float

    @property
    def ok(self) -> bool:
        return abs(self.expected - self.actual) <= self.tolerance


def heater_duty_cycle(derived_btu_per_hour: float) -> float:
    """What share of a heating window the burner must have been lit.

    The ramp analysis measures heat delivered over a window of wall-clock time,
    which is the firing rate multiplied by however much of that window the
    burner was actually lit. The label gives the firing rate. Their ratio is
    therefore a duty cycle, and it is a genuine one-sided test: a burner cannot
    exceed its own input rating, so a derived figure above 100% would mean the
    ramp analysis is wrong, not that the heater is remarkable.
    """
    return derived_btu_per_hour / POOL_HEATER_INPUT_BTU


def validate() -> list[Check]:
    """Internal consistency of the transcription itself."""
    return [
        Check(
            "Condenser MCA from RLA (NEC 440.33)",
            NAMEPLATE_MCA, minimum_circuit_amps(), "A", 0.05,
        ),
        Check(
            "Furnace efficiency within the 80% class",
            0.80, FURNACE_EFFICIENCY, "", 0.02,
        ),
        # The mini-split's ampacity is *not* derivable from its printed currents:
        # NEC 440.33 would give 1.25 x 6.8 + 0.45 + 0.25 = 9.2 A against the 15.0
        # printed, because the maker has simply specified a 15 A circuit. So
        # there is no MCA test here like the Carrier's. What can be checked is
        # that the sum of the three motor loads still reproduces the full-draw
        # figure the patio model runs on — the number that sets its duty cycle.
        Check(
            "Mini-split full draw from its three printed motor loads",
            1.725, minisplit_max_kw(), "kW", 0.005,
        ),
        # A guard against the row alignment, not a precision test: the band is
        # wide enough to admit any real inverter unit and narrow enough that
        # reading the compressor off the wrong row (0.45 A, implying 116 BTU/Wh)
        # fails immediately.
        Check(
            "Mini-split full-load efficiency is physically possible",
            7.7,
            MINISPLIT_BTU_COOLING
            / (MINISPLIT_COMPRESSOR_A * MINISPLIT_VOLTS),
            "BTU/Wh", 4.0,
        ),
    ]


def check_against_derived(pool_heater_btu_per_hour: float) -> list[Check]:
    """One-sided tests of figures the meters produced, against the labels.

    Separate from `validate()` because these compare two different kinds of
    knowledge rather than checking a transcription against itself. Expressed as
    a duty cycle so the admissible range is stated: anywhere in 0–100% is
    consistent, and only a value above 100% is a contradiction.
    """
    duty = heater_duty_cycle(pool_heater_btu_per_hour)
    return [
        Check(
            "Pool heater burn rate at or below its input rating",
            # Midpoint of the admissible band, with a tolerance that admits all
            # of it — this fails only if the derived rate exceeds the nameplate.
            0.5, min(duty, 1.0) if duty <= 1.0 else duty, "duty", 0.5,
        ),
    ]
