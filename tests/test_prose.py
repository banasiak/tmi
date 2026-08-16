"""Formatting helpers, and the rounding bugs that made them necessary."""

from __future__ import annotations

import unittest

from src import charts, equipment, prose


class Money(unittest.TestCase):
    """Whole dollars are right for a bill and wrong for a rate."""

    def test_large_amounts_stay_clean(self):
        self.assertEqual(prose.money(1234.56), "$1,235")
        self.assertEqual(prose.money(10.0), "$10")

    def test_exact_zero_is_a_plain_zero(self):
        self.assertEqual(prose.money(0.0), "$0")

    def test_small_rates_keep_enough_places_to_stay_nonzero(self):
        """The regression this rule exists for.

        An open door costing 3.5 cents an hour rendered as "$0", and a 35-cent
        spa session as "$0 ($0-$0)". Anything the page is willing to print must
        stay distinguishable from nothing.
        """
        for value in (0.035, 0.35, 0.001, 0.0099):
            with self.subTest(value=value):
                self.assertNotEqual(prose.money(value), "$0")

    def test_the_boundaries_pick_the_documented_precision(self):
        self.assertEqual(prose.money(9.99), "$9.99")     # 1.0 <= x < 10
        self.assertEqual(prose.money(0.50), "$0.50")     # 0.10 <= x < 1.0
        self.assertEqual(prose.money(0.035), "$0.035")   # x < 0.10

    def test_negative_amounts_keep_their_sign(self):
        self.assertTrue(prose.money(-42.0).startswith("-$")
                        or prose.money(-42.0).startswith("$-"))


class Spell(unittest.TestCase):
    """Small counts read better as words, and come from the registries."""

    def test_small_counts_are_words(self):
        self.assertEqual(prose.spell(0), "no")
        self.assertEqual(prose.spell(1), "one")
        self.assertEqual(prose.spell(10), "ten")

    def test_large_counts_fall_back_to_grouped_digits(self):
        self.assertEqual(prose.spell(11), "11")
        self.assertEqual(prose.spell(1234), "1,234")

    def test_negative_counts_do_not_index_backwards_into_the_table(self):
        """`_SMALL[-1]` would silently return "ten" for a count of -1."""
        self.assertEqual(prose.spell(-1), "-1")


class Escaping(unittest.TestCase):
    """Everything on the page is hand-built HTML, so this is the only guard."""

    def test_angle_brackets_and_ampersands_are_escaped(self):
        self.assertEqual(charts.esc("<script>"), "&lt;script&gt;")
        self.assertEqual(charts.esc("a & b"), "a &amp; b")

    def test_quotes_are_escaped_for_attribute_context(self):
        self.assertIn("&quot;", charts.esc('say "hi"'))

    def test_non_strings_are_coerced_rather_than_crashing(self):
        self.assertEqual(charts.esc(42), "42")
        self.assertEqual(charts.esc(None), "None")


class Figures(unittest.TestCase):
    def test_missing_values_render_as_a_dash(self):
        self.assertEqual(charts.fmt(None), "—")

    def test_magnitude_picks_the_precision(self):
        self.assertEqual(charts.fmt(12345.0), "12,345")
        self.assertEqual(charts.fmt(123.4), "123")

    def test_a_unit_is_appended_when_given(self):
        self.assertIn("kWh", charts.fmt(500.0, "kWh"))


class QuantileEdges(unittest.TestCase):
    """A linear ramp puts 95% of days in the first colour; quantiles do not."""

    def test_edges_are_sorted(self):
        edges = charts.quantile_edges([float(v) for v in range(100)], bins=7)
        self.assertEqual(edges, sorted(edges))

    def test_a_degenerate_series_does_not_explode(self):
        for values in ([], [1.0], [2.0, 2.0, 2.0]):
            with self.subTest(values=values):
                charts.quantile_edges(values, bins=7)

    def test_a_long_tail_is_compressed_rather_than_dominating(self):
        """The reason for quantiles: utility usage is heavily right-skewed.

        On a cubic ramp the top edge must sit far below the maximum, so the one
        enormous day occupies the last bin instead of stretching a linear scale
        until every ordinary day shares the first colour.
        """
        values = [float(i) ** 3 for i in range(1, 101)]
        edges = charts.quantile_edges(values, bins=7)
        self.assertEqual(len(set(edges)), len(edges), "edges must be distinct")
        self.assertLess(max(edges), max(values) / 1.5)

    def test_every_bin_boundary_falls_inside_the_data(self):
        values = [float(i) ** 3 for i in range(1, 101)]
        edges = charts.quantile_edges(values, bins=7)
        self.assertGreaterEqual(min(edges), min(values))
        self.assertLessEqual(max(edges), max(values))


class Nameplates(unittest.TestCase):
    """Transcribed from photographs, so a typo is an arithmetic contradiction."""

    def test_transcription_is_internally_consistent(self):
        for check in equipment.validate():
            with self.subTest(check.label):
                self.assertTrue(
                    check.ok,
                    f"{check.label}: expected {check.expected}, got {check.actual}")

    def test_rated_draw_is_a_plausible_ceiling_for_a_domestic_condenser(self):
        self.assertGreater(equipment.rated_draw_kw(), 1.0)
        self.assertLess(equipment.rated_draw_kw(), 10.0)

    def test_a_worse_power_factor_lowers_the_ceiling(self):
        self.assertLess(equipment.rated_draw_kw(0.8), equipment.rated_draw_kw(1.0))


if __name__ == "__main__":
    unittest.main()
