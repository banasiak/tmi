"""The transcribed tariffs — the one place a typo makes every dollar wrong."""

from __future__ import annotations

import datetime as dt
import unittest

from src import tariff


class TariffSelfCheck(unittest.TestCase):
    """The build refuses to run when these fail; so should the test suite."""

    def test_every_transcribed_rate_reproduces_its_source_bill(self):
        checks = tariff.validate()
        self.assertTrue(checks, "no tariff checks are defined at all")
        for check in checks:
            with self.subTest(check.label):
                self.assertTrue(
                    check.ok,
                    f"{check.label}: expected {check.expected:.4f}, "
                    f"got {check.actual:.4f}",
                )

    def test_worst_deviation_stays_where_it_is(self):
        """A tolerance loose enough to pass anything proves nothing.

        `Check.ok` allows `max(2 cents, 0.5%)`, which on a $300 electricity bill
        is $1.50 — wide enough to hide a real transcription error. Pin the worst
        deviation actually observed so that widening the tolerance to make a
        failure go away trips this test instead.

        The page quotes this bound rather than asserting one, and to a tenth
        of a cent: displaying 2.3 as a whole "2" made "within two cents" look
        true when the worst check misses by 2.3.
        """
        checks = tariff.validate()
        worst = max(checks, key=lambda c: abs(c.delta))
        self.assertLessEqual(
            abs(worst.delta), 0.03,
            f"worst check drifted: {worst.label} off by {worst.delta:+.4f}")
        over = [c.label for c in checks if abs(c.delta) > 0.02]
        self.assertEqual(
            len(over), 1,
            f"number of checks outside two cents changed: {over}")


class SeasonBoundary(unittest.TestCase):
    """Summer is billed differently, and the boundary is a cliff, not a ramp."""

    def test_summer_months_are_june_through_september(self):
        for month in (6, 7, 8, 9):
            self.assertTrue(tariff.is_summer_period(dt.date(2026, month, 15)))
        for month in (1, 2, 3, 4, 5, 10, 11, 12):
            self.assertFalse(tariff.is_summer_period(dt.date(2026, month, 15)))

    def test_summer_energy_costs_more_than_winter_for_the_same_kwh(self):
        summer = tariff.electric_bill(900, dt.date(2026, 7, 20))
        winter = tariff.electric_bill(900, dt.date(2026, 1, 20))
        self.assertGreater(summer.energy_charge, winter.energy_charge)


class ElectricBill(unittest.TestCase):
    def test_components_sum_to_the_total(self):
        bill = tariff.electric_bill(1234.5, dt.date(2026, 7, 20))
        parts = (bill.energy_charge + bill.rider_charge + bill.fixed_charge
                 + bill.franchise + bill.tax)
        self.assertAlmostEqual(bill.total, parts, places=6)

    def test_zero_usage_still_bills_the_fixed_charge(self):
        bill = tariff.electric_bill(0.0, dt.date(2026, 7, 20))
        self.assertEqual(bill.energy_charge, 0.0)
        self.assertGreater(bill.fixed_charge, 0.0)
        self.assertGreater(bill.total, 0.0)

    def test_cost_is_monotonic_in_usage(self):
        day = dt.date(2026, 7, 20)
        totals = [tariff.electric_bill(kwh, day).total
                  for kwh in (0, 100, 500, 600, 601, 1000, 2000)]
        self.assertEqual(totals, sorted(totals))

    def test_summer_tier_raises_the_marginal_rate(self):
        """Above 600 kWh in summer, the next kWh costs more than the last."""
        day = dt.date(2026, 7, 20)
        below = tariff.marginal_rate(day, above_tier=False)
        above = tariff.marginal_rate(day, above_tier=True)
        self.assertGreater(above, below)

    def test_marginal_rate_matches_a_finite_difference_of_the_bill(self):
        """The rate quoted on the page has to be the rate the bill charges."""
        day = dt.date(2026, 7, 20)
        base = tariff.electric_bill(1000.0, day).total
        stepped = tariff.electric_bill(1001.0, day).total
        self.assertAlmostEqual(stepped - base, tariff.marginal_rate(day), places=4)


class WaterBill(unittest.TestCase):
    def test_the_first_3000_gallons_are_free_of_volumetric_charge(self):
        bill = tariff.water_bill(3000.0)
        self.assertEqual(bill.volumetric, 0.0)
        self.assertGreater(bill.access, 0.0)

    def test_volumetric_charge_starts_above_the_free_allowance(self):
        free = tariff.water_bill(3000.0)
        over = tariff.water_bill(4000.0)
        self.assertGreater(over.volumetric, free.volumetric)

    def test_cost_is_monotonic_in_gallons(self):
        totals = [tariff.water_bill(g).total
                  for g in (0, 1000, 3000, 3001, 6000, 12000)]
        self.assertEqual(totals, sorted(totals))


class FixedCharges(unittest.TestCase):
    def test_wastewater_is_billed_with_no_usage_at_all(self):
        self.assertGreater(tariff.wastewater_bill(dt.date(2026, 7, 15)), 0.0)

    def test_wastewater_allowance_is_positive_year_round(self):
        for month in range(1, 13):
            self.assertGreater(
                tariff.wastewater_allowance(dt.date(2026, month, 15)), 0.0)


if __name__ == "__main__":
    unittest.main()
