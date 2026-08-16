"""Moist-air properties.

Every zone comparison on this page runs on **mixing ratio** — grams of water
vapour per kilogram of dry air — rather than relative humidity. RH is a ratio to
a temperature-dependent denominator, so comparing the garage's RH with the
house's mostly restates that the garage is colder. Mixing ratio is absolute: if
two rooms read the same, they hold the same water, whatever their thermometers
say, and a difference means moisture actually moved.

Altitude matters here. The station sits near 3,900 ft, where the air is about
12% thinner than at sea level, so mixing ratio is computed against the measured
*absolute* pressure rather than a standard atmosphere.
"""

from __future__ import annotations

# Magnus coefficients over water (Bolton 1980), good to ~0.3% across the
# -30..50 °C range these sensors report.
MAGNUS_A = 17.67
MAGNUS_B = 243.5
E0_HPA = 6.112

# Ratio of the molar masses of water vapour and dry air.
EPSILON = 0.622


def f_to_c(deg_f: float) -> float:
    return (deg_f - 32.0) / 1.8


def saturation_vapour_pressure(temp_c: float) -> float:
    """Saturation vapour pressure over liquid water, hPa."""
    return E0_HPA * 2.718281828459045 ** (MAGNUS_A * temp_c / (temp_c + MAGNUS_B))


def vapour_pressure(dew_point_f: float) -> float:
    """Actual vapour pressure, hPa.

    The vapour pressure of a parcel *is* the saturation pressure at its dew
    point — that is what a dew point means — so no humidity term is needed.
    """
    return saturation_vapour_pressure(f_to_c(dew_point_f))


def mixing_ratio(dew_point_f: float, pressure_hpa: float) -> float:
    """Grams of water vapour per kilogram of dry air."""
    e = vapour_pressure(dew_point_f)
    # Guard the degenerate case where a bad pressure reading would otherwise
    # drive the denominator through zero.
    return 1000.0 * EPSILON * e / max(pressure_hpa - e, 1.0)


def inhg_to_hpa(inhg: float) -> float:
    return inhg * 33.8639
