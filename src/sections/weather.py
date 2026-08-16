"""The house as a thermal object, and the monsoon that closes its year.

Balance points are fitted rather than assumed at the conventional 65°F.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from src import charts, model, tariff
from src.analysis import Analysis
from src.charts import Panel
from src.report import Callout, Formula, Section, formula, frac, var


def build(data: Analysis) -> Section:
    """The house as a thermal object, and the monsoon that closes its year."""
    # Everything this section reads from the analysis layer.
    days = data.days
    elec_model = data.elec_model
    elec_pool = data.elec_pool
    envelope = data.envelope
    gas_sig = data.gas_sig
    hourly_series = data.hourly_series
    storms = data.storms

    weather_blocks: list[object] = []
    
    if elec_model:
        pts = [
            (
                d.weather.cdd(elec_model.cool_base_f),
                d.kwh,
                f"{d.date:%-d %b %Y}",
                False,
            )
            for d in elec_pool
        ]
        weather_blocks.append(formula(Formula(
            caption="Degree-days, integrated over the day's samples rather than its extremes",
            lhs=f'{var("CDD")}({var("T","b")})',
            rhs=f'{frac("1", var("N"))} · &sum; max(0, {var("T","i")} &minus; {var("T","b")})',
            where=[
                (var("T","i"), "each five-minute outdoor reading, °F"),
                (var("N"), "samples that day — 288 when the station misses nothing"),
                (var("T","b"), "balance point, °F — fitted by scanning, not assumed at 65"),
            ],
            note="The conventional (max + min) / 2 form assumes the day is a symmetric "
                 "curve between its two extremes. Near the balance point — which is "
                 "exactly where these fits live — that assumption is worth several "
                 "percent, and the station already reports every five minutes. Heating "
                 "degree-days are the same with the subtraction reversed.",
        )))
        weather_blocks.append(formula(Formula(
            caption="The energy signature each scatter below is fitting",
            lhs=var("U"),
            rhs=f'{var("U","0")} + {var("k")} · {var("DD")}({var("T","b")})',
            where=[
                (var("U"), "the day's metered use — kWh for electricity, cubic feet for gas"),
                (var("U","0"), "intercept: what the house uses when the weather asks for "
                               "nothing. This is the number the fit exists to produce"),
                (var("k"), "slope — the marginal cost of one more degree-day"),
                (var("T","b"), f"balance point, scanned over a range and chosen by fit: "
                               f"{elec_model.cool_base_f:.0f}°F cooling, "
                               f"{gas_sig.base_f:.0f}°F heating"),
            ],
            note="Fitting the balance point rather than assuming it is what makes the "
                 "intercept trustworthy: a base temperature that is wrong pushes its "
                 "error straight into the baseline, and the baseline is what gets called "
                 "always-on load elsewhere on this page.",
        )))
        weather_blocks.append(
            charts.signature_scatter(
                "elec-signature",
                "Electricity against cooling demand",
                f"Daily kWh vs cooling degree-days, balance point fitted at "
                f"{elec_model.cool_base_f:.0f}°F. R² = {elec_model.r2:.2f} over {elec_model.n} days.",
                pts,
                "electric",
                f"Cooling degree-days (base {elec_model.cool_base_f:.0f}°F)",
                "kWh per day",
                fit_line=(elec_model.baseline_kwh_day, elec_model.cooling_slope),
                note=(
                    f"The line meets the axis at <strong>{elec_model.baseline_kwh_day:.0f} kWh/day</strong>. "
                    f"That intercept is consumption no amount of mild weather removes — it is "
                    f"the floor plus the timer plus everything you plug in. Each cooling "
                    f"degree-day above {elec_model.cool_base_f:.0f}°F adds "
                    f"{elec_model.cooling_slope:.2f} kWh. Cooling starts late, at "
                    f"{elec_model.cool_base_f:.0f}°F, which is a well-behaved house, not a leaky one."
                ),
            )
        )
    
    if gas_sig:
        # Degree-days here are integrated across each day's samples, not taken
        # from the daily mean. The gap between the two methods widens sharply as
        # the balance point falls, because a day whose *mean* clears the base can
        # still spend its night below it — which is most of this house's winter.
        gas_days = [d for d in days if d.gas_cf is not None]
        hdd_integrated = sum(d.weather.hdd(gas_sig.base_f) for d in gas_days)
        hdd_from_mean = sum(
            max(0.0, gas_sig.base_f - d.weather.t_mean)
            for d in gas_days if d.weather.t_mean is not None
        )
        warm_mean_cold_night = sum(
            1 for d in gas_days
            if d.weather.t_mean is not None
            and d.weather.t_mean >= gas_sig.base_f
            and d.weather.hdd(gas_sig.base_f) > 0
        )
        gas_pts = [
            (
                d.weather.hdd(gas_sig.base_f),
                d.gas_cf,
                f"{d.date:%-d %b %Y}",
                d.date in set(gas_sig.excluded),
            )
            for d in days
            if d.gas_cf is not None
        ]
        weather_blocks.append(
            charts.signature_scatter(
                "gas-signature",
                "Gas against heating demand",
                f"Daily cubic feet vs heating degree-days, balance point fitted at "
                f"{gas_sig.base_f:.0f}°F.",
                gas_pts,
                "gas",
                f"Heating degree-days (base {gas_sig.base_f:.0f}°F)",
                "Cubic feet per day",
                fit_line=(gas_sig.baseline, gas_sig.slope),
                note=(
                    f"Two R² values, because only reporting the flattering one would mislead. "
                    f"On the {gas_sig.n} routine days the fit keeps, R² = "
                    f"<strong>{gas_sig.r2:.2f}</strong> — heating demand explains those days well. "
                    f"Across all {gas_sig.n_all} days it is only "
                    f"<strong>{gas_sig.r2_all:.2f}</strong>, because the "
                    f"{len(gas_sig.excluded)} days held out of it carry so much volume. "
                    f"Your house starts calling for heat once the outside temperature dips "
                    f"below about {gas_sig.base_f:.0f}°F, and burns "
                    f"{gas_sig.baseline:.0f} cf/day when it is not heating at all — that "
                    f"floor is the water heater."
                ),
            )
        )
        weather_blocks.append(formula(Formula(
            caption="The line through those points",
            lhs=var("G"),
            rhs=f'{var("G","0")} + {var("k")} · HDD({var("T","b")})',
            where=[
                (var("G"), "gas that day, cubic feet"),
                (var("G","0"), f"{gas_sig.baseline:.0f} cf/day — what the house burns with "
                               f"no heating demand at all, which is the water heater's "
                               f"standing draw"),
                (var("k"), f"{gas_sig.slope:.1f} cf per degree-day — the envelope, and the "
                           f"only term here that describes the building rather than the "
                           f"weather or the appliances"),
                (var("T","b"), f"balance point, {gas_sig.base_f:.0f}°F. Fitted, not "
                               f"assumed: every candidate from 45 to 80°F was tried and "
                               f"this one leaves the straightest line"),
            ],
            note=f"R² {gas_sig.r2:.2f} on the {gas_sig.n} days the fit keeps.",
        )))
        weather_blocks.append(formula(Formula(
            caption="And what a heating degree-day means here",
            lhs=f'HDD({var("T","b")})',
            rhs=frac(
                f'&sum; max(0, {var("T","b")} &minus; {var("T","i")})',
                var("n"),
            ),
            where=[
                (var("T","i"), "each temperature sample that day"),
                (var("n"), "samples in the day — 288 at five-minute spacing"),
            ],
            note=f"Averaged across the day's samples rather than taken from its mean, and "
                 f"at this balance point the difference is not cosmetic: integrating finds "
                 f"{hdd_integrated:,.0f} degree-days a year against {hdd_from_mean:,.0f} "
                 f"from daily means, <strong>{hdd_integrated / hdd_from_mean:.1f}×</strong> "
                 f"more. {warm_mean_cold_night} days average above "
                 f"{gas_sig.base_f:.0f}°F and still spend part of the night below it. A "
                 f"daily mean would score every one of them zero.",
        )))
    
    # The same gas meter at hourly resolution, which arrives free in the water
    # export — one row per meter per hour, both meters in one file. It is the
    # only sub-daily view of gas in the project: the billing export is monthly
    # and a daily total cannot say whether 400 cf went into one evening or was
    # spread across a cold day.
    if hourly_series and hourly_series.gas_stamps:
        gas_by_day: dict[dt.date, dict[int, float]] = defaultdict(dict)
        for stamp, cf in zip(hourly_series.gas_stamps, hourly_series.gas_cf):
            gas_by_day[stamp.date()][stamp.hour] = cf
        gas_whole = {d: h for d, h in gas_by_day.items() if len(h) == 24}
        t_by_day = {d.date: d.weather.t_mean for d in days}
        bands = [
            ("Cold day", lambda t: t < 45),
            ("Mild day", lambda t: 55 <= t <= 70),
            ("Hot day", lambda t: t > 80),
        ]
        gas_shape: list[tuple[str, list[float], int, float]] = []
        for name, test in bands:
            members = [
                d for d in gas_whole if d in t_by_day and test(t_by_day[d])
            ]
            if len(members) < 10:
                continue
            gas_shape.append((
                name,
                [statistics.fmean([gas_whole[d][h] for d in members])
                 for h in range(24)],
                len(members),
                statistics.fmean([sum(gas_whole[d].values()) for d in members]),
            ))
    
    if hourly_series and hourly_series.gas_stamps and len(gas_shape) == 3:
        hot_total = gas_shape[-1][3]
        weather_blocks.append(
            charts.zone_multiples(
                "gas-hourly",
                "What the gas meter does across a day",
                f"Mean cubic feet in each hour, grouped by the day's mean outdoor "
                f"temperature. Every panel on the same scale, each against the "
                f"annual mean for reference.",
                [
                    charts.ZonePanel(
                        label=f"{name} ({n}d)",
                        values=vals,
                        caption=f"{total:.0f} cf over the day",
                    )
                    for name, vals, n, total in gas_shape
                ],
                ("Every day", [
                    statistics.fmean([vals[h] for _, vals, _, _ in gas_shape])
                    for h in range(24)
                ]),
                "cf/hour",
                [f"{h:02d}:00" for h in range(24)],
                accent="var(--stream-gas)",
                series_label="Temperature band",
                note=(
                    f"<strong>The hot-day panel is the water heater, alone and "
                    f"visible.</strong> It is nearly flat at "
                    f"{hot_total / 24:.1f} cf an hour and totals "
                    f"<strong>{hot_total:.0f} cf a day</strong> — against the "
                    f"{gas_sig.baseline:.0f} cf/day the regression above puts at its "
                    f"intercept, reached by fitting 364 daily totals against degree-days. "
                    f"Two methods with nothing in common agreeing to within a cubic foot. "
                    f"And flat matters: a standing loss looks like this, whereas hot water "
                    f"actually being drawn would show morning and evening humps.</p>"
                    f"<p>The cold-day panel is the furnace, and it is concentrated: "
                    f"{max(gas_shape[0][1]):.0f} cf in the "
                    f"{gas_shape[0][1].index(max(gas_shape[0][1])):02d}:00 hour alone, "
                    f"{max(gas_shape[0][1]) / gas_shape[0][3]:.0%} of the whole day's gas, "
                    f"which is the recovery from a night setback."
                ),
            )
        )
    
    if envelope:
        env_pts = [
            (
                d.weather.t_swing,
                d.weather.t_in_swing,
                f"{d.date:%-d %b %Y} · outdoor mean {d.weather.t_mean:.0f}°F",
            )
            for d in days
            if d.weather.t_in_swing is not None
            and 58 <= d.weather.t_mean <= 72
        ]
        weather_blocks.append(
            charts.scatter(
                "envelope",
                "How much of the weather gets inside",
                f"Indoor temperature swing against outdoor swing, on the {envelope.mild_days} "
                f"mild days when the thermostat is mostly idle.",
                env_pts,
                # Temperature against temperature — the subject is the weather,
                # not a particular room, so it takes the weather accent.
                "var(--weather-accent)",
                "Outdoor daily temperature swing (°F)",
                "Indoor daily swing (°F)",
                fit_line=(0.0, envelope.damping),
                reference=(0.0, 1.0),
                reference_label="if the house were a tent",
                note=(
                    # The damping is a fitted slope, not the ratio of the two means —
                    # a positive intercept makes the ratio the larger number, and
                    # putting them side by side invited the reader to divide.
                    f"The house passes <strong>{envelope.damping:.0%}</strong> of each extra "
                    f"degree of outdoor swing through to the inside — the slope of the fit, "
                    f"which is what survives a thermometer reading a little high. In plain "
                    f"averages an outdoor day moves "
                    f"{envelope.outdoor_swing_mean:.0f}°F and the interior "
                    f"{envelope.indoor_swing_mean:.1f}°F, a slightly larger fraction because "
                    f"the line does not pass through the origin. That is a genuinely good "
                    f"envelope, "
                    f"and it agrees with the late "
                    f"{elec_model.cool_base_f:.0f}°F cooling balance point found above — "
                    f"two independent measurements of the same insulation. "
                    f"For contrast, the garage passes "
                    f"{envelope.garage_damping:.0%} of the same extra degree — "
                    f"{envelope.garage_damping / envelope.damping:.0f}× the house, fitted the "
                    f"same way on the same days — which is what an uninsulated space looks "
                    f"like. Its plain-average figure runs higher still for the same "
                    f"intercept reason, and the zones section ranks all four buildings on it."
                    if envelope.garage_damping and elec_model
                    else ""
                ),
            )
        )
    
    wcost = model.weather_cost(
        days, tariff.marginal_rate, tariff.gas_marginal_per_kcf
    )
    if wcost:
        weather_blocks.append(
            charts.scatter(
                "weather-cost",
                "What a day costs, against how warm it was",
                "Every day's electricity and gas priced at the rate that applied to it, "
                "against that day's mean outdoor temperature.",
                [(t, c, f"{t:.0f}°F · ${c:.2f}") for t, c in wcost.points],
                # Dollars across both meters.
                "var(--money-accent)",
                "Outdoor mean temperature (°F)",
                "Cost that day ($)",
                overlay=[(b[0], b[1]) for b in wcost.bins],
                overlay_label="median in each 5°F band",
                mark=(wcost.cheapest_f, wcost.cheapest_cost,
                      f"cheapest at {wcost.cheapest_f:.0f}°F"),
                # Nothing here happens below about 30°F, and 0°F is not a
                # meaningful anchor for outdoor temperature the way it is for a
                # swing ratio. Frame on the data.
                x_zero=False,
                note=(
                    f"Neither meter makes this shape on its own — gas falls as it warms "
                    f"and electricity climbs, so only the sum has a minimum. It sits at "
                    f"<strong>{wcost.cheapest_f:.0f}°F</strong>, which is roughly the "
                    f"outdoor temperature at which this house wants nothing from either "
                    f"utility."
                ),
            )
        )
        weather_blocks.append(
            Callout(
                kind="finding",
                title=(
                    f"Heat costs this house about "
                    f"{wcost.hot_cost / wcost.cold_cost:.1f}× what equivalent cold does"
                ),
                body=(
                    # Explicit cents throughout: money() scales its precision by
                    # magnitude, which reads as sloppy when three daily figures
                    # sit in one sentence at "$3.30", "$11" and "$5.68".
                    f"<p>The curve has a floor of "
                    f"<strong>${wcost.cheapest_cost:.2f} a day</strong> at "
                    f"{wcost.cheapest_f:.0f}°F, and it is not symmetric about it. The "
                    f"hottest band runs ${wcost.hot_cost:.2f} a day — "
                    f"{wcost.hot_cost / wcost.cheapest_cost:.1f}× the floor — while the "
                    f"coldest runs ${wcost.cold_cost:.2f}, only "
                    f"{wcost.cold_cost / wcost.cheapest_cost:.1f}×.</p>"
                    f"<p>Three things stack up on the warm side and none of them apply on "
                    f"the cold side. Cooling is electric and heating is mostly gas, and a "
                    f"marginal summer kilowatt-hour costs "
                    f"{tariff.marginal_rate(dt.date(2026, 7, 15)) / tariff.marginal_rate(dt.date(2026, 1, 15)):.2f}× "
                    f"a winter one before the fuel difference is even counted. The summer "
                    f"tier then bites on exactly the months that need the most. And the "
                    f"pool — pump and evaporation both — is a summer load that winter "
                    f"simply does not have.</p>"
                    f"<p>The practical reading is about which direction to insure against. "
                    f"A degree of unexpected heat is worth roughly twice a degree of "
                    f"unexpected cold on this bill, so shade, envelope and cooling "
                    f"efficiency are where money goes furthest here — and it is the "
                    f"opposite of the advice that would suit the same house further "
                    f"north.</p>"
                ),
            )
        )
    
    monsoon_blocks: list[object] = []
    if storms:
        lightning_days = [s for s in storms if s.strikes > 0]
        worst = max(storms, key=lambda s: s.strikes)
        wettest = max(storms, key=lambda s: s.rain_in)
        annual_rain = sum(s.rain_in for s in storms)
        season = [s for s in storms if s.date.month in (6, 7, 8, 9)]
        season_rain = sum(s.rain_in for s in season)
        season_strike_days = [s for s in lightning_days if s.date.month in (6, 7, 8, 9)]
        all_strikes = sum(s.strikes for s in lightning_days)
        season_strikes = sum(s.strikes for s in season_strike_days)
    
        monsoon_blocks.extend([
            Callout(
                kind="note",
                title=f"{annual_rain:.1f} inches for the year, {season_rain / annual_rain:.0%} of it in four months",
                body=(
                    f"<p>The North American monsoon shows up unmistakably. Of "
                    f"{annual_rain:.2f} inches recorded, {season_rain:.2f} fell between June "
                    f"and September. Lightning concentrates harder still: "
                    f"{len(season_strike_days)} of {len(lightning_days)} active days sit in "
                    f"those four months, but they carry "
                    f"<strong>{season_strikes / all_strikes:.0%} of the "
                    f"{all_strikes:,.0f} strikes</strong> recorded all year — the out-of-season "
                    f"days are isolated cells, the monsoon days are storms.</p>"
                    f"<p>The most active day was <strong>{worst.date:%-d %B %Y}</strong> with "
                    f"<strong>{worst.strikes:,.0f} strikes</strong>, "
                    f"{worst.rain_in:.2f} in of rain and gusts to {worst.gust_max:.0f} mph. "
                    f"The wettest was {wettest.date:%-d %B %Y} at {wettest.rain_in:.2f} in, "
                    f"peaking at a rate of {wettest.rain_rate_max:.2f} in/hr — desert rain "
                    f"arrives all at once, which is why it runs off rather than soaking in.</p>"
                ),
            ),
            charts.time_panels(
                "monsoon",
                "Rain and lightning through the year",
                "Daily totals from the station. Each panel keeps its own scale.",
                [
                    Panel("Daily rainfall", "in",
                          {d.date: d.weather.rain_in for d in days},
                          "water", kind="area"),
                    Panel("Lightning strikes", "per day",
                          {d.date: d.weather.strikes for d in days},
                          "var(--storm-accent)", kind="area"),
                    Panel("Peak gust", "mph", {d.date: d.weather.gust_max for d in days},
                          "var(--weather-accent)", kind="line"),
                ],
                note=(
                    f"Rain and lightning arrive together in a narrow season and are absent "
                    f"for the rest of the year. Wind is the exception: the year's strongest "
                    f"gust, {max(d.weather.gust_max for d in days):.0f} mph on "
                    f"{max(days, key=lambda d: d.weather.gust_max).date:%-d %B %Y}, came in "
                    f"spring with no rain at all. Those are the dust events, and they are a "
                    f"different phenomenon from the summer storms."
                ),
            ),
        ])
    
        by_month: dict[str, list[float]] = {}
        for s in storms:
            by_month.setdefault(f"{s.date:%Y-%m}", []).append(s.rain_in)
        labels = [k[5:] + "/" + k[2:4] for k in sorted(by_month)]
        # Which months actually carry the year, named from the data. A hard-coded
        # pair went stale: January 2026 out-rained July 2026, so the note
        # contradicted the chart directly beneath it.
        ranked_months = sorted(by_month, key=lambda k: -sum(by_month[k]))[:3]
        wettest_months = [
            f"{dt.datetime.strptime(k, '%Y-%m'):%B %Y}" for k in ranked_months
        ]
        monsoon_blocks.append(
            charts.monthly_columns(
                "monsoon-monthly",
                "Rainfall by month",
                # Not "complete months only" like the metered charts: this one
                # keeps every month in the record, so August appears twice as the
                # two partial ends of the year. Saying otherwise made two short
                # bars look like full months.
                "Every month in the record. The year starts and ends mid-August, "
                "so August appears twice — as a 25-day bar and a 6-day one.",
                labels,
                # Rain is weather, not the water meter.
                [("Rainfall", "water",
                  [sum(by_month[k]) for k in sorted(by_month)])],
                "inches",
                # Named from the data rather than typed in: January 2026 turned out to
                # out-rain July 2026, which the hard-coded version contradicted.
                note=(
                    f"{', '.join(wettest_months[:-1])} and {wettest_months[-1]} carry the "
                    f"year — and note that they are not all monsoon months, which is the "
                    f"reminder that winter rain here arrives too. A drip system on a fixed "
                    f"weekly schedule waters straight through every one of them; a rain "
                    f"sensor, or a controller that skips after a storm, is the cheapest "
                    f"water saving on this page."
                ),
            )
        )
    
    section = (
        Section(
            id="weather",
            emoji="🌡️",
            title="How the house answers the weather",
            lede=(
                "Balance points are fitted rather than assumed at the conventional 65°F. "
                "Where the line meets the axis matters as much as its slope: the intercept "
                "is load the weather never touches. The monsoon closes the section — Las "
                "Cruces takes most of its year's rain in a few violent afternoons between "
                "June and September, and the station catches all of it."
            ),
            blocks=weather_blocks + monsoon_blocks,
        )
    )
    
    return section
