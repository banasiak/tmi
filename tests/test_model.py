"""The models, checked against planted answers rather than against fixtures.

`model.py` is where readings become claims, and it was the largest thing here
with nothing checking it. The transcription layers self-check on every build —
a mistyped rate or nameplate stops the build — but the arithmetic that turns a
year of meter readings into a balance point, an anomaly or a null result had no
equivalent, which is the wrong way round: a wrong tariff is at least a wrong
number, while a wrong signature is a wrong *argument* the page then states in
prose.

Nothing here reads `data/`. Every input is generated from a known answer — a
balance point chosen in advance, an excess planted on a named date, a rate
change with an arithmetic identity behind it — so a test failure names the
quantity that drifted rather than reporting that some real day changed shape.
That also means these run on a clean checkout, which is the constraint the rest
of the suite is built to.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
import unittest

from src import model, sources

DAY_ZERO = dt.date(2025, 1, 1)


def weather_day(date: dt.date, temps: list[float]) -> sources.WeatherDay:
    """A station day carrying `temps` as its sample record.

    Only `_temps` matters to anything under test: `hdd`/`cdd` integrate over the
    samples rather than taking (Tmax+Tmin)/2, so the sample list *is* the
    weather as far as every fit here is concerned. The rest are plausible desert
    constants, present because the dataclass requires them.
    """
    return sources.WeatherDay(
        date=date, samples=288,
        t_min=min(temps), t_max=max(temps), t_mean=statistics.fmean(temps),
        dew_mean=30.0, rh_mean=25.0, wind_mean=4.0, gust_max=12.0,
        solar_mean=200.0, solar_peak=800.0, pressure_mean=29.9,
        rain_in=0.0, rain_rate_max=0.0, strikes=0.0,
        t_in_mean=72.0, t_in_min=70.0, t_in_max=74.0, rh_in_mean=30.0,
        t_pool_mean=None, t_garage_mean=None, t_garage_min=None,
        t_garage_max=None, t_patio_mean=None,
        _temps=list(temps),
    )


def day(
    offset: int, temp: float = 70.0, *,
    water: float | None = None, gas: float | None = None,
    kwh: float | None = None, baseload_kw: float = 0.5,
) -> sources.Day:
    """One joined day, `offset` days after DAY_ZERO, held at a flat `temp`.

    A flat day makes the degree-day integral exact — hdd(base) is simply
    max(0, base - temp) — so a planted balance point stays plantable.
    """
    date = DAY_ZERO + dt.timedelta(days=offset)
    utility = None
    if water is not None or gas is not None:
        utility = sources.UtilityDay(
            date=date, water_gal=0.0 if water is None else water,
            gas_cf=0.0 if gas is None else gas,
        )
    electric = None
    if kwh is not None:
        electric = sources.ElectricDay(
            date=date, kwh=kwh, peak_kw=5.0, baseload_kw=baseload_kw,
            intervals=96, profile=[],
        )
    return sources.Day(date=date, weather=weather_day(date, [temp] * 24),
                       utility=utility, electric=electric)


# The answer every signature test is asked to recover.
PLANTED_BASE = 60.0
PLANTED_BASELINE = 10.0
PLANTED_SLOPE = 8.0
SPIKE_OFFSET = 40


def gas_day(offset: int, temp: float, gas_from) -> sources.Day:
    """A day whose gas is a function of its own weather.

    `gas_from` receives the built WeatherDay, so the planted usage is generated
    through the same integrated `hdd`/`cdd` the fit will read it back with —
    a test that reimplemented the degree-day integral could agree with itself
    while both were wrong.
    """
    date = DAY_ZERO + dt.timedelta(days=offset)
    weather = weather_day(date, [temp] * 24)
    return sources.Day(
        date=date, weather=weather,
        utility=sources.UtilityDay(date=date, water_gal=0.0,
                                   gas_cf=gas_from(weather)),
        electric=None,
    )


def heating_days(spike_cf: float = 0.0) -> list[sources.Day]:
    """120 days of gas generated from the planted signature, straddling the base.

    Temperatures run 25°F to 84.5°F so the record holds both the heating limb
    and the flat summer that has to be told apart from it. `spike_cf` plants a
    single day of gas the signature cannot explain.
    """
    return [
        gas_day(i, 25.0 + i * 0.5,
                lambda w: PLANTED_BASELINE + PLANTED_SLOPE * w.hdd(PLANTED_BASE)
                + (spike_cf if i == SPIKE_OFFSET else 0.0))
        for i in range(120)
    ]


class LeastSquares(unittest.TestCase):
    """`model.py` implements its own OLS so the build runs without numpy."""

    def test_recovers_the_line_it_was_given(self):
        rows = [[1.0, x] for x in (0.0, 1.0, 2.0, 3.0)]
        intercept, slope = model.solve_ols(rows, [3.0, 5.0, 7.0, 9.0])
        self.assertAlmostEqual(intercept, 3.0)
        self.assertAlmostEqual(slope, 2.0)

    def test_recovers_a_multiple_regression(self):
        points = ((0, 0), (1, 0), (0, 1), (1, 1), (2, 1))
        rows = [[1.0, float(a), float(b)] for a, b in points]
        targets = [1.0 + 2.0 * a + 3.0 * b for a, b in points]
        coef = model.solve_ols(rows, targets)
        for got, want in zip(coef, (1.0, 2.0, 3.0)):
            self.assertAlmostEqual(got, want)

    def test_a_singular_system_returns_zeros_rather_than_dividing_by_zero(self):
        """A degenerate predictor must not take the build down with it.

        Every caller here treats an all-zero fit as "no relationship", which is
        the honest reading of a column that never varies.
        """
        self.assertEqual(model.solve_ols([[1.0, 5.0]] * 3, [1.0, 2.0, 3.0]),
                         [0.0, 0.0])


class GoodnessOfFit(unittest.TestCase):
    def test_a_perfect_fit_scores_one(self):
        self.assertEqual(model.r_squared([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)

    def test_no_variance_to_explain_scores_zero_rather_than_dividing_by_zero(self):
        self.assertEqual(model.r_squared([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]), 0.0)


class RobustScale(unittest.TestCase):
    """Utility residuals are not homoscedastic; the scale estimators say so."""

    def test_robust_sigma_is_the_scaled_median_absolute_deviation(self):
        self.assertAlmostEqual(model.robust_sigma([-1.0, 0.0, 1.0]),
                               model.MAD_TO_SIGMA)

    def test_robust_sigma_ignores_the_outlier_it_exists_to_survive(self):
        """One wild value must not move the scale — that is the whole job.

        Replaced rather than appended, so the list length stays odd and the
        median does not shift on parity instead of on the outlier. The standard
        deviation is shown alongside as the thing this replaces.
        """
        quiet = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        wild = quiet[:-1] + [10_000.0]
        self.assertAlmostEqual(model.robust_sigma(quiet), model.robust_sigma(wild))
        self.assertGreater(statistics.stdev(wild), 100 * statistics.stdev(quiet))

    def test_the_noise_model_widens_where_the_data_is_noisy(self):
        """The whole point: a furnace day is judged against furnace-sized noise.

        A single pooled sigma, dominated by flat summer days, would declare the
        entire heating season anomalous.
        """
        scale = model.proportional_scale(
            predicted=[0.0, 10.0, 100.0], residuals=[0.0, 5.0, 50.0], floor=5.0)
        self.assertGreater(scale(100.0), scale(10.0))
        self.assertGreater(scale(10.0), 0.0)

    def test_the_floor_holds_where_there_is_no_noise_at_all(self):
        scale = model.proportional_scale([0.0, 1.0, 2.0], [0.0, 0.0, 0.0], floor=5.0)
        self.assertEqual(scale(0.0), 5.0)


class BalancePointIsFitted(unittest.TestCase):
    """The decision the README asks not to undo, checked rather than described.

    The conventional 65°F base is wrong for most houses. These days were built
    from a base of 60, and the scan has to find it without being told.
    """

    def setUp(self):
        self.sig = model.fit_signature(heating_days(), "gas_cf", "heating", "cf")

    def test_the_scan_recovers_the_planted_balance_point(self):
        self.assertEqual(self.sig.base_f, PLANTED_BASE)

    def test_it_recovers_the_baseline_and_the_slope_with_it(self):
        self.assertAlmostEqual(self.sig.baseline, PLANTED_BASELINE, places=6)
        self.assertAlmostEqual(self.sig.slope, PLANTED_SLOPE, places=6)

    def test_a_noiseless_record_keeps_every_day(self):
        self.assertEqual(self.sig.n, self.sig.n_all)
        self.assertEqual(self.sig.excluded, [])

    def test_predict_and_degree_days_agree_with_the_fit(self):
        cold = day(0, 40.0, gas=0.0)
        self.assertAlmostEqual(self.sig.degree_days(cold), 20.0)
        self.assertAlmostEqual(self.sig.predict(20.0),
                               PLANTED_BASELINE + PLANTED_SLOPE * 20.0, places=6)

    def test_a_negative_slope_is_not_a_signature(self):
        """Heating load that falls as it gets colder is noise finding a base."""
        inverted = [
            gas_day(i, 25.0 + i * 0.5,
                    lambda w: 10.0 - 5.0 * w.hdd(PLANTED_BASE))
            for i in range(120)
        ]
        self.assertIsNone(
            model.fit_signature(inverted, "gas_cf", "heating", "cf"))


class OutlierTrimmingReportsWhatItCost(unittest.TestCase):
    """Both R² values are reported, and the gap between them is the finding."""

    def setUp(self):
        self.sig = model.fit_signature(
            heating_days(spike_cf=2000.0), "gas_cf", "heating", "cf")

    def test_the_planted_spike_is_the_day_that_gets_held_out(self):
        self.assertEqual(self.sig.excluded,
                         [DAY_ZERO + dt.timedelta(days=SPIKE_OFFSET)])
        self.assertEqual(self.sig.n, self.sig.n_all - 1)

    def test_the_signature_survives_the_spike_intact(self):
        """Trimming exists so one pool-heater week cannot drag the balance point."""
        self.assertEqual(self.sig.base_f, PLANTED_BASE)
        self.assertAlmostEqual(self.sig.slope, PLANTED_SLOPE, places=6)

    def test_the_trimmed_score_flatters_itself_and_the_honest_one_shows_it(self):
        """A fit scored only on the days it kept is not the whole story.

        Here the retained fit is perfect and the all-days fit is not, which is
        exactly the gap that must never be reported as a single number.
        """
        self.assertAlmostEqual(self.sig.r2, 1.0, places=6)
        self.assertLess(self.sig.r2_all, self.sig.r2)


class GasAnomaliesNeedBothGates(unittest.TestCase):
    """A proportional z-score *and* an absolute floor, both required."""

    SIG = model.Signature(
        mode="heating", base_f=PLANTED_BASE, baseline=PLANTED_BASELINE,
        slope=PLANTED_SLOPE, r2=1.0, r2_all=1.0, n=100, n_all=100,
        unit="cf", excluded=[])

    def days_with(self, planted: dict[int, float]) -> list[sources.Day]:
        return [
            gas_day(i, 30.0 + i * 0.5,
                    lambda w: self.SIG.predict(w.hdd(PLANTED_BASE))
                    + planted.get(i, 0.0))
            for i in range(60)
        ]

    def test_a_day_the_signature_cannot_explain_is_flagged(self):
        found = model.detect_gas_anomalies(self.days_with({10: 1000.0}), self.SIG)
        self.assertEqual([a.date for a in found],
                         [DAY_ZERO + dt.timedelta(days=10)])
        self.assertAlmostEqual(found[0].excess, 1000.0, places=6)
        self.assertEqual(found[0].stream, "gas")

    def test_a_small_excess_is_not_a_story_however_significant(self):
        """The floor stops a 6 cf day being "300% of expected" on a mild one."""
        self.assertEqual(model.detect_gas_anomalies(
            self.days_with({20: 50.0}), self.SIG), [])

    def test_a_record_the_signature_explains_flags_nothing(self):
        self.assertEqual(model.detect_gas_anomalies(self.days_with({}), self.SIG), [])

    def test_severity_climbs_with_the_size_of_the_departure(self):
        big = model.detect_gas_anomalies(self.days_with({10: 5000.0}), self.SIG)
        self.assertEqual(big[0].severity, "critical")

    def test_the_detector_never_names_a_cause(self):
        """Detection and attribution are kept separate on purpose.

        The note may describe the departure and the weather it departed from;
        naming a cause requires a different source.
        """
        found = model.detect_gas_anomalies(self.days_with({10: 1000.0}), self.SIG)
        for banned in ("pool", "heater", "leak", "furnace", "because"):
            self.assertNotIn(banned, found[0].note.lower())


class WaterAnomaliesTrackTheirOwnBaseline(unittest.TestCase):
    """Water has no weather driver here, so the baseline has to drift with use."""

    def test_a_step_change_is_flagged(self):
        days = [day(i, water=300.0) for i in range(60)]
        days[50] = day(50, water=550.0)
        found = model.detect_water_anomalies(days)
        self.assertEqual([a.date for a in found],
                         [DAY_ZERO + dt.timedelta(days=50)])
        self.assertAlmostEqual(found[0].expected, 300.0)
        self.assertAlmostEqual(found[0].excess, 250.0)

    def test_an_excess_under_the_floor_is_left_alone(self):
        days = [day(i, water=300.0) for i in range(60)]
        days[50] = day(50, water=450.0)
        self.assertEqual(model.detect_water_anomalies(days), [])

    def test_a_dramatic_relative_jump_on_a_small_base_is_still_not_a_story(self):
        """Isolates the absolute floor from the z-score gate.

        On a 30 gal/day household a 180 gal day is six times normal and scores a
        z of 30 — the statistical gate waves it straight through. Only the floor
        stops it, which is what keeps a quiet week from manufacturing a leak out
        of one load of laundry.
        """
        days = [day(i, water=30.0) for i in range(60)]
        days[50] = day(50, water=180.0)
        self.assertEqual(model.detect_water_anomalies(days), [])

    def test_a_refill_in_the_trailing_window_does_not_blind_the_detector(self):
        """Isolates the median from a mean.

        A pool refill is a genuine 5,000 gal day. Averaged into the next four
        weeks of baseline it lifts the expectation by ~180 gal/day and hides
        every real step change behind it; a median shrugs it off and the later
        step is still caught.
        """
        days = [day(i, water=300.0) for i in range(60)]
        days[35] = day(35, water=5000.0)
        days[50] = day(50, water=550.0)
        flagged = {a.date for a in model.detect_water_anomalies(days)}
        self.assertIn(DAY_ZERO + dt.timedelta(days=50), flagged)

    def test_summer_arriving_is_not_an_anomaly(self):
        """The regression this design exists for.

        A season's worth of irrigation ramp moves water use by more than any
        single flagged step, and a fixed baseline would have called all of it a
        leak. The trailing median tracks the drift instead.
        """
        ramp = [day(i, water=200.0 + i * 6.7) for i in range(60)]
        self.assertGreater(ramp[-1].water_gal - ramp[0].water_gal, 250.0)
        self.assertEqual(model.detect_water_anomalies(ramp), [])


class NullResultsCarryTheirSensitivity(unittest.TestCase):
    """"No leak found" means nothing without the smallest leak the test could see."""

    def test_a_clean_record_still_reports_what_would_have_tripped_it(self):
        quiet = [day(i, water=100.0 + (i % 7) * 20.0) for i in range(60)]
        sens = model.leak_sensitivity(quiet)
        self.assertEqual(sens.windows_flagged, 0)
        self.assertAlmostEqual(sens.typical_floor_gal, 100.0)
        self.assertAlmostEqual(sens.trip_threshold_gal, 250.0)
        self.assertAlmostEqual(sens.detectable_leak_gal, 150.0)

    def test_a_lifted_floor_reports_as_one_event_not_eight_sliding_windows(self):
        days = [day(i, water=100.0) for i in range(60)]
        for i in range(30, 44):
            days[i] = day(i, water=400.0)
        windows = model.detect_leak_windows(days)
        self.assertEqual(len(windows), 1)
        self.assertAlmostEqual(windows[0].typical_floor_gal, 100.0)
        self.assertLessEqual(windows[0].start,
                             DAY_ZERO + dt.timedelta(days=30))
        self.assertGreaterEqual(windows[0].end,
                                DAY_ZERO + dt.timedelta(days=43))


class CostDecompositionBalances(unittest.TestCase):
    """Splitting a bill's change into usage and rate must not lose a dollar."""

    @staticmethod
    def three_years() -> list[sources.BillingPeriod]:
        periods = []
        for year, kwh, cost in ((2024, 1000.0, 120.0), (2025, 1200.0, 168.0)):
            for month in range(1, 13):
                start = dt.date(year, month, 1)
                periods.append(sources.BillingPeriod(
                    start=start, end=start + dt.timedelta(days=29),
                    kwh=kwh + month, cost=cost + month))
        return periods

    def test_the_two_effects_add_up_to_the_whole_change(self):
        """The identity behind the split, which is the only thing making it a
        decomposition rather than two loosely related numbers."""
        rows = [r for r in model.decompose_year_over_year(self.three_years())
                if r.prev_kwh is not None]
        self.assertEqual(len(rows), 12)
        for row in rows:
            with self.subTest(row.label):
                self.assertAlmostEqual(row.usage_effect + row.rate_effect,
                                       row.cost - row.prev_cost, places=6)

    def test_using_more_at_a_steady_rate_is_all_usage_effect(self):
        rate = 0.12
        periods = [
            sources.BillingPeriod(start=dt.date(2024, 6, 1),
                                  end=dt.date(2024, 6, 30),
                                  kwh=1000.0, cost=1000.0 * rate),
            sources.BillingPeriod(start=dt.date(2025, 6, 1),
                                  end=dt.date(2025, 6, 30),
                                  kwh=1500.0, cost=1500.0 * rate),
        ]
        row = [r for r in model.decompose_year_over_year(periods)
               if r.prev_kwh is not None][0]
        self.assertAlmostEqual(row.usage_effect, 500.0 * rate, places=6)
        self.assertAlmostEqual(row.rate_effect, 0.0, places=6)

    def test_a_rate_rise_on_steady_usage_is_all_rate_effect(self):
        periods = [
            sources.BillingPeriod(start=dt.date(2024, 6, 1),
                                  end=dt.date(2024, 6, 30),
                                  kwh=1000.0, cost=120.0),
            sources.BillingPeriod(start=dt.date(2025, 6, 1),
                                  end=dt.date(2025, 6, 30),
                                  kwh=1000.0, cost=150.0),
        ]
        row = [r for r in model.decompose_year_over_year(periods)
               if r.prev_kwh is not None][0]
        self.assertAlmostEqual(row.usage_effect, 0.0, places=6)
        self.assertAlmostEqual(row.rate_effect, 30.0, places=6)

    def test_a_period_with_no_prior_year_declines_to_guess(self):
        rows = model.decompose_year_over_year(self.three_years())
        first = [r for r in rows if r.label.startswith("2024")]
        self.assertTrue(first)
        for row in first:
            self.assertIsNone(row.usage_effect)
            self.assertIsNone(row.rate_effect)


class AnomalyArithmetic(unittest.TestCase):
    def test_excess_and_ratio_read_off_the_pair(self):
        a = model.Anomaly(date=DAY_ZERO, stream="water", actual=500.0,
                          expected=200.0, unit="gal", severity="warning", note="")
        self.assertAlmostEqual(a.excess, 300.0)
        self.assertAlmostEqual(a.ratio, 2.5)

    def test_a_ratio_against_nothing_is_infinite_rather_than_an_error(self):
        a = model.Anomaly(date=DAY_ZERO, stream="gas", actual=50.0, expected=0.0,
                          unit="cf", severity="warning", note="")
        self.assertEqual(a.ratio, math.inf)


class Baseload(unittest.TestCase):
    """The always-on floor: equipment that never switches off, not behaviour."""

    def test_it_summarises_the_floor_and_what_share_of_the_year_it_is(self):
        days = [day(i, kwh=24.0, baseload_kw=0.5) for i in range(40)]
        stats = model.analyse_baseload(days)
        self.assertAlmostEqual(stats.median_kw, 0.5)
        self.assertAlmostEqual(stats.annual_kwh, 0.5 * 24.0 * 40)
        self.assertAlmostEqual(stats.share_of_total, 0.5)
        self.assertAlmostEqual(stats.seasonal_spread_kw, 0.0)

    def test_a_seasonal_floor_reports_its_spread(self):
        days = [day(i, kwh=24.0, baseload_kw=0.4 if i < 31 else 0.9)
                for i in range(62)]
        stats = model.analyse_baseload(days)
        self.assertAlmostEqual(stats.seasonal_spread_kw, 0.5)
        self.assertEqual(sorted(stats.by_month), ["2025-01", "2025-02", "2025-03"])


class TooLittleDataDeclinesRatherThanGuesses(unittest.TestCase):
    """Every one of these returns None so the section it feeds drops out.

    That is the contract the whole page rests on: a model that cannot be fitted
    returns nothing, `build()` returns None, and one section goes missing rather
    than the build dying or — worse — a figure being quoted from four days.
    """

    def test_a_signature_needs_thirty_days(self):
        self.assertIsNone(model.fit_signature(
            [day(i, 40.0, gas=10.0) for i in range(29)], "gas_cf", "heating", "cf"))

    def test_baseload_needs_thirty_days(self):
        self.assertIsNone(model.analyse_baseload(
            [day(i, kwh=24.0) for i in range(29)]))

    def test_leak_sensitivity_needs_four_windows(self):
        self.assertIsNone(model.leak_sensitivity(
            [day(i, water=100.0) for i in range(27)]))

    def test_leak_windows_need_four_windows(self):
        self.assertEqual(model.detect_leak_windows(
            [day(i, water=100.0) for i in range(27)]), [])

    def test_detectors_given_nothing_return_nothing(self):
        self.assertEqual(model.detect_water_anomalies([]), [])
        self.assertEqual(
            model.detect_gas_anomalies([], GasAnomaliesNeedBothGates.SIG), [])


if __name__ == "__main__":
    unittest.main()
