"""Psychrometrics and solar geometry — checked against physics, not fixtures."""

from __future__ import annotations

import datetime as dt
import math
import unittest

from src import psychro, solar


class Psychrometrics(unittest.TestCase):
    """Every zone comparison on the page runs on mixing ratio, so these matter."""

    def test_saturation_pressure_at_known_temperatures(self):
        """Magnus over water, against the textbook values it approximates."""
        for temp_c, expected_hpa in ((0.0, 6.11), (10.0, 12.28),
                                     (20.0, 23.39), (30.0, 42.47)):
            with self.subTest(temp_c=temp_c):
                self.assertAlmostEqual(
                    psychro.saturation_vapour_pressure(temp_c),
                    expected_hpa, delta=expected_hpa * 0.005)

    def test_saturation_pressure_rises_with_temperature(self):
        values = [psychro.saturation_vapour_pressure(t)
                  for t in range(-30, 51, 5)]
        self.assertEqual(values, sorted(values))

    def test_f_to_c_at_the_fixed_points(self):
        self.assertAlmostEqual(psychro.f_to_c(32.0), 0.0)
        self.assertAlmostEqual(psychro.f_to_c(212.0), 100.0)
        self.assertAlmostEqual(psychro.f_to_c(-40.0), -40.0)

    def test_mixing_ratio_rises_with_dew_point(self):
        pressure = psychro.inhg_to_hpa(25.0)
        values = [psychro.mixing_ratio(dp, pressure) for dp in range(0, 80, 5)]
        self.assertEqual(values, sorted(values))

    def test_thinner_air_holds_more_vapour_per_kilogram(self):
        """The station sits near 3,900 ft; that is why pressure is a parameter.

        At a fixed dew point, the same vapour pressure is a larger share of a
        lower total pressure, so mixing ratio goes up as the air thins. Getting
        this backwards would bias every zone comparison in the same direction.
        """
        sea_level = psychro.mixing_ratio(50.0, 1013.25)
        altitude = psychro.mixing_ratio(50.0, psychro.inhg_to_hpa(25.9))
        self.assertGreater(altitude, sea_level)

    def test_degenerate_pressure_does_not_divide_by_zero(self):
        self.assertGreater(psychro.mixing_ratio(50.0, 0.0), 0.0)
        self.assertGreater(psychro.mixing_ratio(120.0, 1.0), 0.0)

    def test_inhg_conversion(self):
        self.assertAlmostEqual(psychro.inhg_to_hpa(29.92), 1013.2, delta=0.5)


class SolarGeometry(unittest.TestCase):
    def test_sun_is_below_the_horizon_at_midnight(self):
        pos = solar.sun_position(dt.datetime(2026, 6, 21, 0, 0))
        self.assertLess(pos.altitude, 0.0)
        self.assertFalse(pos.is_up)

    def test_summer_noon_sun_is_higher_than_winter_noon_sun(self):
        summer = solar.sun_position(dt.datetime(2026, 6, 21, 12, 0))
        winter = solar.sun_position(dt.datetime(2026, 12, 21, 12, 0))
        self.assertGreater(summer.altitude, winter.altitude)
        self.assertTrue(summer.is_up and winter.is_up)

    def test_solstice_noon_altitude_matches_the_declination_identity(self):
        """At solar noon, altitude = 90 - |latitude - declination|.

        An independent check on the whole ephemeris: it uses the published
        latitude and the textbook solstice declination, and touches none of the
        code's own intermediate terms.
        """
        for day, declination in ((dt.date(2026, 6, 21), 23.44),
                                 (dt.date(2026, 12, 21), -23.44)):
            with self.subTest(day=day):
                # Solar noon is where the altitude peaks, by definition — found
                # rather than assumed, so the test does not depend on the clock
                # offset or on daylight saving being in force.
                peak = max(
                    solar.sun_position(
                        dt.datetime(day.year, day.month, day.day)
                        + dt.timedelta(minutes=m)).altitude
                    for m in range(0, 24 * 60, 2))
                expected = 90.0 - abs(solar.LATITUDE - declination)
                self.assertAlmostEqual(math.degrees(peak), expected, delta=1.0)

    def test_diffuse_fraction_is_a_fraction(self):
        for clearness in (0.0, 0.1, 0.22, 0.5, 0.8, 0.9, 1.0):
            with self.subTest(clearness=clearness):
                self.assertGreaterEqual(solar.diffuse_fraction(clearness), 0.0)
                self.assertLessEqual(solar.diffuse_fraction(clearness), 1.0)

    def test_a_clear_sky_scatters_less_than_an_overcast_one(self):
        self.assertGreater(solar.diffuse_fraction(0.05),
                           solar.diffuse_fraction(0.75))

    def test_a_flat_plane_returns_the_horizontal_irradiance_it_was_given(self):
        """Documented in `tilted_irradiance`: at tilt zero it is the identity."""
        stamp = dt.datetime(2026, 6, 21, 12, 0)
        self.assertAlmostEqual(
            solar.tilted_irradiance(stamp, 900.0, tilt=0.0), 900.0, delta=1.0)

    def test_plane_of_array_is_never_negative(self):
        for hour in range(24):
            for tilt_deg in (0, 22.6, 45, 90):
                stamp = dt.datetime(2026, 3, 21, hour, 0)
                with self.subTest(hour=hour, tilt=tilt_deg):
                    self.assertGreaterEqual(
                        solar.tilted_irradiance(
                            stamp, 500.0, tilt=math.radians(tilt_deg)), 0.0)

    def test_no_irradiance_produces_no_plane_of_array(self):
        stamp = dt.datetime(2026, 3, 21, 12, 0)
        self.assertEqual(
            solar.tilted_irradiance(stamp, 0.0, tilt=math.radians(22.6)), 0.0)

    def test_east_and_west_planes_swap_advantage_across_the_day(self):
        """The whole roof argument rests on this asymmetry being real."""
        tilt = math.radians(22.6)
        east, west = math.radians(-90.0), math.radians(90.0)
        morning = dt.datetime(2026, 6, 21, 8, 0)
        afternoon = dt.datetime(2026, 6, 21, 16, 0)
        self.assertGreater(solar.tilted_irradiance(morning, 500.0, tilt, east),
                           solar.tilted_irradiance(morning, 500.0, tilt, west))
        self.assertGreater(solar.tilted_irradiance(afternoon, 500.0, tilt, west),
                           solar.tilted_irradiance(afternoon, 500.0, tilt, east))


if __name__ == "__main__":
    unittest.main()
