"""The same meter at hourly resolution, which is what finds the leak.

Hour resolution is what makes the fault claim admissible: two zones run inside
one hourly bucket, so the meter can size a loss and never name the valve.
"""

from __future__ import annotations

import datetime as dt
import statistics

from src import charts, model, tariff
from src.analysis import Analysis
from src.house import (IRRIGATION_SUMMER_MIN, IRRIGATION_WINTER_MIN,
                       LEAK_FOUND_ZONE,
                       POOL_SURFACE_SQFT, REFILL_WINDOW)
from src.prose import money, spell
from src.report import Callout, Formula, Section, formula, frac, var


def build(data: Analysis) -> Section | None:
    """The same meter at hourly resolution, which is what finds the leak."""
    # Everything this section reads from the analysis layer.
    big_water = data.big_water
    clock_slips = data.clock_slips
    cut_days = data.cut_days
    cut_gallons = data.cut_gallons
    cycle_summer = data.cycle_summer
    cycle_winter = data.cycle_winter
    days = data.days
    dst_slips = data.dst_slips
    era_cause = data.era_cause
    eras = data.eras
    evap = data.evap
    fault = data.fault
    flow_rows = data.flow_rows
    hourly = data.hourly
    hourly_series = data.hourly_series
    normal_day_names = data.normal_day_names
    power_cuts = data.power_cuts
    rest_fit = data.rest_fit
    season_switches = data.season_switches
    set_hour = data.set_hour
    section: Section | None = None

    if hourly and hourly.periods:
        # Seasons, not sampled weeks. Five weeks pulled months apart could fix
        # the schedule and bound a leak; they could not tell a season's level
        # from a season's scatter, which is exactly what the irrigation question
        # turned on. The whole year is now here, so every figure below is an
        # aggregate over months rather than a reading off one week.
        SEASONS = [
            ("Winter", {12, 1, 2}),
            ("Spring", {3, 4, 5}),
            ("Summer", {6, 7, 8}),
            ("Autumn", {9, 10, 11}),
        ]
        hour_of_day: dict[str, list[float]] = {}
        season_days: dict[str, int] = {}
        for name, months in SEASONS:
            buckets: list[list[float]] = [[] for _ in range(24)]
            n = 0
            for period in hourly.periods:
                for day, hours in period.by_day.items():
                    if day.month not in months or day in big_water:
                        continue
                    n += 1
                    for hour, gallons in hours.items():
                        buckets[hour].append(gallons)
            hour_of_day[name] = [
                statistics.fmean(b) if b else 0.0 for b in buckets
            ]
            season_days[name] = n
        # The overnight channel, season by season, from every night of the year
        # rather than a sampled week of each. Hours 01–04: past any evening
        # activity, before any morning, and never touched by the controller.
        overnight: dict[str, float] = {}
        season_temp: dict[str, float] = {}
        t_lookup = {d.date: d.weather.t_mean for d in days}
        for name, months in SEASONS:
            nights = [
                statistics.fmean([hours[h] for h in (1, 2, 3, 4)])
                for period in hourly.periods
                for day, hours in period.by_day.items()
                if day.month in months and day not in big_water
            ]
            temps = [
                t_lookup[day]
                for period in hourly.periods
                for day in period.by_day
                if day.month in months and day in t_lookup
            ]
            if nights:
                overnight[name] = statistics.median(nights) * 24.0
            if temps:
                season_temp[name] = statistics.fmean(temps)
    
    
        # The live fault. It closes the hourly-water section rather than standing
        # alone, because the hour-resolution argument above it is what makes the
        # claim admissible in the first place.
        leak_blocks: list[object] = []
        if fault:
            leak_blocks.extend([
                        Callout(
                            kind="caution",
                            title=(
                                f"A cycle that delivered {fault.baseline_gal:.0f} gallons "
                                f"now delivers {fault.recent_gal:.0f}"
                            ),
                            body=(
                                f"<p>The drip controller opens two valves in series at "
                                f"{fault.hour:02d}:00 on Tuesday, Thursday and Saturday, "
                                f"and everything it delivers lands inside that one hour. "
                                f"That makes each cycle directly measurable — and through "
                                f"April and May it measured "
                                f"<strong>{fault.baseline_gal:.0f} gallons</strong>, cycle "
                                f"after cycle.</p>"
                                f"<p>On <strong>{fault.break_date:%A %-d %B %Y}</strong> it "
                                f"stepped to {fault.cycles[[c.date for c in fault.cycles].index(fault.break_date)].gallons:.0f}, "
                                f"and it has climbed every week since — about "
                                f"<strong>{fault.growth_per_week:+.0f} gallons a cycle per "
                                f"week</strong>. The most recent cycles run "
                                f"<strong>{fault.recent_gal:.0f} gallons</strong>: "
                                f"{fault.excess_gal:.0f} more than the clean figure, "
                                f"<strong>{fault.excess_share:.0%} above it</strong>. "
                                f"Across {fault.cycles_since} cycles and "
                                f"{fault.days_since} days that is "
                                f"<strong>{fault.excess_total:,.0f} gallons</strong>, and it "
                                f"is currently running about {fault.weekly_gal:.0f} gallons "
                                f"a week.</p>"
                                f"<p>The money is not the point, and the numbers make that "
                                f"plain: at "
                                f"{money(tariff.water_marginal_per_kgal(6000.0))} per thousand "
                                f"gallons the excess has cost about "
                                f"<strong>{money(fault.excess_total / 1000 * tariff.water_marginal_per_kgal(6000.0))}</strong> "
                                f"so far — too little to notice on a bill, which is exactly "
                                f"why it ran for {spell(fault.days_since // 7)} weeks. The point is the "
                                f"<strong>{fault.excess_total:,.0f} gallons</strong>. This is "
                                f"the Chihuahuan Desert, the aquifer under it is not being "
                                f"refilled at the rate anyone is drawing on it, and putting "
                                f"that much drinking water into the ground through a split "
                                f"pipe is the kind of waste worth fixing whatever it "
                                f"costs.</p>"
                            ),
                        ),
                        charts.event_series(
                            "leak",
                            "Every irrigation cycle in the record",
                            f"Gallons through the meter in the {fault.hour:02d}:00 hour, "
                            f"on each night the controller ran.",
                            [
                                (
                                    c.date,
                                    c.gallons,
                                    f"{c.date:%a %-d %b %Y}: {c.gallons:,.0f} gal",
                                )
                                for c in fault.cycles
                            ],
                            "water",
                            "gallons per cycle",
                            baseline=fault.baseline_gal,
                            baseline_label=f"clean cycle, {fault.baseline_gal:.0f} gal",
                            baseline_span=fault.baseline_span,
                            break_date=fault.break_date,
                            break_label=f"{fault.break_date:%-d %b}",
                            note=(
                                f"The winter block in the middle is the controller doing "
                                f"what it was told — {IRRIGATION_WINTER_MIN:.0f} minutes "
                                f"of valve-open time against "
                                f"{IRRIGATION_SUMMER_MIN:.0f} in summer. The rise on the "
                                f"right is not that. Note where the record starts: the "
                                f"same season a year earlier sat at "
                                f"{fault.prior_year_gal:.0f} gallons."
                                if fault.prior_year_gal else ""
                            ),
                        ),
                        formula(Formula(
                            caption="The climb, as a straight line through the cycles",
                            lhs=f'{var("V")}({var("t")})',
                            rhs=f'{var("V","0")} + {var("k")} · {var("t")}',
                            where=[
                                (f'{var("V")}({var("t")})',
                                 "gallons in one cycle, t weeks after the break"),
                                (var("V","0"),
                                 f"{fault.growth_at_break:.0f} gal — the fitted volume at "
                                 f"the break itself, already "
                                 f"{fault.growth_at_break - fault.baseline_gal:.0f} above "
                                 f"the clean {fault.baseline_gal:.0f}"),
                                (var("k"),
                                 f"{fault.growth_per_week:+.1f} gal per week, fitted by "
                                 f"least squares on all {fault.cycles_since} cycles since "
                                 f"the break"),
                            ],
                            note=(
                                f"R² {fault.growth_r2:.2f}. The intercept is the useful "
                                f"part: the fault did not start at nothing and grow — it "
                                f"arrived as a step of "
                                f"{fault.growth_at_break - fault.baseline_gal:.0f} gallons "
                                f"and <em>then</em> began climbing. The line reads "
                                f"{fault.growth_at_break + fault.growth_per_week * ((fault.cycles[-1].date - fault.break_date).days / 7):.0f} "
                                f"gal at the latest cycle against "
                                f"{fault.recent_gal:.0f} measured, so it slightly "
                                f"over-runs the recent weeks — it describes the climb "
                                f"rather than forecasting it."
                            ),
                        )),
                        Callout(
                            kind="finding",
                            title="Four things it is not",
                            body=(
                                f"<p>Each of these would leave a different fingerprint on "
                                f"the meter, and the record carries none of them.</p>"
                                '<div class="table-scroll"><table><thead><tr>'
                                '<th>Could it be…</th><th>Then the meter would show</th>'
                                '<th>What it actually shows</th></tr></thead><tbody>'
                                f"<tr><td>The season</td>"
                                f"<td>the same weeks last year at the same level</td>"
                                f"<td>{fault.prior_year_gal:.0f} → "
                                f"<strong>{fault.recent_gal:.0f} gal</strong> a cycle, "
                                f"{fault.recent_gal / fault.prior_year_gal:.1f}× the "
                                f"water on the same program</td></tr>"
                                f"<tr><td>The timer</td>"
                                f"<td>one step to a new level, then a hold</td>"
                                f"<td>climbing for <strong>{fault.days_since // 7} "
                                f"weeks</strong>, and the "
                                f"{(fault.hour + 1) % 24:02d}:00 hour after it still only "
                                f"carries {fault.spill_now:.0f} gal, so nothing runs "
                                f"over</td></tr>"
                                f"<tr><td>A leak elsewhere in the house</td>"
                                f"<td>the quiet hours rising too</td>"
                                f"<td>{fault.overnight_prior:.2f} → "
                                f"<strong>{fault.overnight_now:.2f} gal/h</strong> on the "
                                f"nights the controller sleeps — unchanged, so it only "
                                f"moves water while a valve is open</td></tr>"
                                f"<tr><td>A measurement artifact</td>"
                                f"<td>the billed total unmoved</td>"
                                f"<td>July billed "
                                f"{sum(g for st, g in zip(hourly_series.stamps, hourly_series.gallons) if st.year == 2025 and st.month == 7):,.0f} → "
                                f"<strong>{sum(g for st, g in zip(hourly_series.stamps, hourly_series.gallons) if st.year == 2026 and st.month == 7):,.0f} gal</strong></td></tr>"
                                "</tbody></table></div>"
                                + (
                                    f"<p><strong>And it was there.</strong> What the "
                                    f"meter could say was that a valve somewhere was "
                                    f"losing {fault.excess_gal:.0f} gallons a cycle and "
                                    f"getting worse. Walking the zones during a run found "
                                    f"it in <strong>{charts.esc(LEAK_FOUND_ZONE)}</strong>. "
                                    f"That last step is the one the data could not take: "
                                    f"the two zones run back-to-back inside the same "
                                    f"hourly bucket, so the meter can say how much a cycle "
                                    f"lost and never which valve was open when it "
                                    f"did.</p>"
                                    if LEAK_FOUND_ZONE
                                    else
                                    f"<p>What is left is a fault downstream of a valve "
                                    f"that is getting worse — a cracked fitting or a split "
                                    f"line that only loses water while that zone is "
                                    f"running. It is worth walking the zones during a "
                                    f"cycle: it runs {fault.hour:02d}:00 Tuesday, Thursday "
                                    f"and Saturday, and at {fault.excess_gal:.0f} extra "
                                    f"gallons in half an hour there should be something to "
                                    f"see.</p>"
                                )
                            ),
                        ),
                        Callout(
                            kind="note",
                            title="What the repair should look like on the meter",
                            body=(
                                f"<p>The same measurement that found this will confirm the "
                                f"fix, and it is worth writing the numbers down now rather "
                                f"than deciding afterwards what would have counted.</p>"
                                f"<p><strong>A repaired line puts the "
                                f"{fault.hour:02d}:00 cycle back to about "
                                f"{fault.baseline_gal:.0f} gallons</strong> — not lower. "
                                f"That is what April and May delivered on this same "
                                f"program, and what the previous summer delivered before "
                                f"that. Anything landing near {fault.recent_gal:.0f} means "
                                f"the loss is still there; anything in between means part "
                                f"of it is.</p>"
                                f"<p>Two cycles are enough to tell, so a single week's "
                                f"export answers it. The one thing not to read as success "
                                f"is a fall in the <em>daily</em> total — that moves for a "
                                f"dozen reasons, which is how this went unnoticed from "
                                f"{fault.break_date:%B} to {fault.cycles[-1].date:%B}. "
                                f"Read the hour.</p>"
                                f"<p>Worth carrying forward as a standing check rather "
                                f"than a one-off: this whole fault sat "
                                f"{fault.excess_gal / max(fault.baseline_gal, 1) * 100:.0f}% "
                                f"above a level the meter had held for two seasons, and "
                                f"nothing else on this page noticed. The alarm is one "
                                f"number — the {fault.hour:02d}:00 hour on a watering "
                                f"night — and it is already in every export.</p>"
                            ),
                        ),
            ])
    
        section = (
            Section(
                id="hourly-water",
                emoji="💧",
                title="Water, by the hour — and the one thing that is broken",
                lede=(
                    f"The daily meter could say which days water moved. "
                    f"{sum(p.days for p in hourly.periods):,} days at hourly resolution "
                    f"say at what hour, how fast, and — on the night one cycle stopped "
                    f"matching every cycle before it — exactly when something broke. "
                    f"That fault closes the section: it is the only live problem on this "
                    f"page, and the only one the daily meter is structurally blind to."
                ),
                blocks=[
                    charts.zone_multiples(
                        "hourly-water",
                        "The shape of a day, season by season",
                        f"Mean gallons in each hour of the day, across every complete day "
                        f"of the year bar the two the pool refill occupies. Every panel on "
                        f"the same scale, each against the annual mean for reference.",
                        [
                            charts.ZonePanel(
                                label=f"{name} — {season_days[name]} days",
                                values=hour_of_day[name],
                                caption=(
                                    f"{sum(hour_of_day[name]):.0f} gal on an average day"
                                ),
                            )
                            for name, _ in SEASONS
                            if season_days[name]
                        ],
                        # The reference is the whole year, so no season is drawn
                        # against itself.
                        ("Whole year", [
                            statistics.fmean(
                                [hour_of_day[n][h] for n, _ in SEASONS if season_days[n]]
                            )
                            for h in range(24)
                        ]),
                        "gal/hour",
                        [f"{h:02d}:00" for h in range(24)],
                        accent="var(--stream-water)",
                        series_label="Season",
                        note=(
                            f"One spike, in every season, at "
                            f"{hourly.irrigation_hour:02d}:00 — the controller, which "
                            f"never moves. What changes is its height. Each line averages "
                            f"every day of the season including the four a week the "
                            f"controller sleeps, so the peak here is roughly "
                            f"three-sevenths of a cycle. The rest of the day is flat and "
                            f"low: this household's water is a schedule with a little "
                            f"noise on top, which is why a change in that one hour is "
                            f"visible at all."
                        ),
                    ),
                    Callout(
                        kind="finding",
                        title=(
                            f"Hour by hour, the refill comes to "
                            f"{hourly.refill_net:,.0f} gallons — the daily meter said "
                            f"{hourly.assumed_volume:,.0f}"
                        ),
                        body=(
                            f"<p>Pool volume is the keystone here: the per-degree costs, "
                            f"the spa volume and every turnover count derive from it. It "
                            f"comes from the March drain and refill, by subtracting an "
                            f"<em>estimated</em> daily baseline from two days of billing — "
                            f"<strong>{hourly.assumed_volume:,.0f} gallons</strong>.</p>"
                            f"<p>The hourly register measures it directly. The fill ran "
                            f"{hourly.refill_hours} hours from "
                            f"{REFILL_WINDOW[0]:%-H:%M on %A}, holding a steady "
                            f"<strong>{hourly.refill_rate:.0f} gallons an hour "
                            f"({hourly.refill_rate / 60:.1f} a minute)</strong> for fourteen "
                            f"hours straight — a hose, left on overnight. Net of baseline "
                            f"that is <strong>{hourly.refill_net:,.0f} gallons</strong>.</p>"
                            f"<p>The two land "
                            f"<strong>{abs(hourly.refill_net - hourly.assumed_volume):,.0f} "
                            f"gallons apart</strong> on {hourly.assumed_volume:,.0f} — "
                            f"closer than either method deserves, and closer than the "
                            f"drain-and-refill assumption underneath both of them. The check "
                            f"is worth having because it could have gone the other way: the "
                            f"daily figure rests on an estimated baseline, and an hour-by-"
                            f"hour read owes it nothing.</p>"
                        ),
                    ),
                    Callout(
                        kind="finding",
                        title=(
                            f"The weather over the pool predicts the water going into it"
                        ),
                        body=(
                            f"<p>The strongest check does not measure volume at all — it "
                            f"measures the <em>surface</em>, and it comes from instruments "
                            f"that have nothing to do with the water meter. The pool has a "
                            f"float valve, so evaporation is replaced automatically and "
                            f"shows up as flow in the small hours. Carrier's evaporation "
                            f"relation predicts that flow from three measured quantities: "
                            f"the pool probe's water temperature, the outdoor dew point, "
                            f"and the anemometer.</p>"
                            + formula(Formula(
                                caption="Evaporation from an open water surface",
                                lhs=var("w"),
                                rhs=f'{frac(f"(95 + 0.425·{var("V")}) · ({var("P","w")} − {var("P","a")})", var("Y"))}',
                                where=[
                                    (var("w"), "water lost, lb per hour per ft² of surface"),
                                    (var("V"), "air speed over the water, mph — measured"),
                                    (var("P","w"), "saturation vapour pressure at the water "
                                                   "temperature, inHg — from the pool probe"),
                                    (var("P","a"), "vapour pressure of the air, inHg — the "
                                                   "saturation pressure at the outdoor dew point"),
                                    (var("Y"), f"latent heat of vaporisation, "
                                               f"{model.LATENT_HEAT_BTU_LB:,.0f} BTU/lb"),
                                ],
                            ))
                            + f"<p>Run across the year at the measured "
                            f"{POOL_SURFACE_SQFT:.0f} ft² of surface, and set beside what "
                            f"the meter actually passed in the small hours:</p>"
                        ),
                    ),
                    charts.profile_lines(
                        "pool-evap",
                        "What the weather asks for, and what the meter delivered",
                        "Monthly means. The prediction uses no water data; the "
                        "measurement uses no weather data.",
                        [
                            ("Predicted", "var(--zone-accent)",
                             [p for _, p, _ in evap.monthly]),
                            ("Metered", "var(--stream-water)",
                             [m for _, _, m in evap.monthly]),
                        ],
                        "gal/day",
                        x_labels=[
                            dt.datetime.strptime(k, "%Y-%m").strftime("%b")
                            for k, _, _ in evap.monthly
                        ],
                        note=(
                            f"Two instrument chains with nothing in common — a pool "
                            f"thermometer, a dew point and an anemometer on one side, a "
                            f"water meter on the other — tracing the same four-fold "
                            f"seasonal swing. The gap between them is close to constant, "
                            f"which is the giveaway: it is the household's own overnight "
                            f"draw, {evap.intercept:.0f} gal/day, sitting under the "
                            f"evaporation the whole year."
                        ),
                    ),
                    Callout(
                        kind="finding",
                        title="What that agreement is worth",
                        body=(
                            f"<p><strong>The two track each other across a four-fold "
                            f"seasonal swing</strong> — slope {evap.slope:.2f}, "
                            f"R² {evap.r2:.2f} over {evap.n} months, with nothing fitted to "
                            f"make it happen: every term is a sensor reading and the only "
                            f"free choice was the surface area.</p>"
                            f"<p>The slope is {evap.slope:.2f} rather than 1, and this fit "
                            f"cannot say why. The pool's surface area might be smaller than "
                            f"the {POOL_SURFACE_SQFT:.0f} ft² measured; Carrier's relation is "
                            f"documented to run high on still water with nobody in it; or "
                            f"the anemometer on its mast reads a breeze the sheltered pool "
                            f"never feels. Only the first is about the pool.</p>"
                        ) + (
                            f"<p>Widened from the pool to <em>all</em> the water this house "
                            f"cannot account for, the same shape holds at a steeper slope — "
                            f"<strong>{rest_fit[1]:.2f}</strong>, R² {rest_fit[2]:.2f}. "
                            f"Which puts evaporation at about <strong>{1 / rest_fit[1]:.0%} "
                            f"of the seasonal swing</strong> rather than all of it; the rest "
                            f"is what Carrier's relation excludes — swimmers, hoses and "
                            f"longer showers, all leaning the same way the weather does. "
                            f"That fit's own intercept, {rest_fit[0]:.0f} gal/day, is the "
                            f"indoor water underneath both.</p>"
                            if rest_fit else ""
                        ) + (
                            f"<p><strong>None of this measures the pool.</strong> Inverting "
                            f"the fit implies {evap.implied_sqft:.0f} ft² against the "
                            f"{POOL_SURFACE_SQFT:.0f} ft² measured, which would assume the "
                            f"model exactly right in order to prove the tape wrong. What it "
                            f"establishes is that two instrument chains sharing no hardware "
                            f"reproduce one seasonal shape to R² {evap.r2:.2f} — and that "
                            f"either was free to fail.</p>"
                        ),
                    ),
                    Callout(
                        kind="finding",
                        title=(
                            f"Two programs, one flow rate — and the pipe is the "
                            f"honest witness"
                        ),
                        body=(
                            f"<p>Every cycle fires on the same schedule — "
                            f"{hourly.irrigation_hour:02d}:00, Tuesday, Thursday and "
                            f"Saturday — inside a single hour, in all "
                            f"{len(hourly.periods)} months of the record. Only the volume "
                            f"moves: <strong>{cycle_winter:.0f} gallons a cycle on the "
                            f"winter program against {cycle_summer:.0f} on the "
                            f"summer</strong>.</p>"
                            f"<p>Dividing each by the runtime it was set to gives the one "
                            f"thing the controller does not control — how fast the pipe "
                            f"delivers.</p>"
                            + '<div class="table-scroll"><table><thead><tr>'
                            '<th>Month</th><th>Program</th><th>Gallons a cycle</th>'
                            '<th>Implied flow</th></tr></thead><tbody>'
                            + "".join(
                                f"<tr><td>{charts.esc(p.label)}</td>"
                                f"<td>{mins:.0f} min</td><td>{gal:.0f}</td>"
                                f"<td>{gpm:.2f} GPM</td></tr>"
                                for p, gal, mins, gpm in flow_rows
                            )
                            + "</tbody></table></div>"
                            + (
                                f"<p>Both programs land between "
                                f"{min(r[3] for r in flow_rows):.2f} and "
                                f"{max(r[3] for r in flow_rows):.2f} GPM — the same "
                                f"plumbing, moving water at the same rate, whichever "
                                f"runtime it was given. <strong>That is what makes the "
                                f"runtimes credible</strong> without anything here being "
                                f"able to measure them: an hourly bucket records volume "
                                f"and never duration, so the two figures are the owner's "
                                f"account, and their only corroboration is that dividing "
                                f"by them produces one flow rate instead of two.</p>"
                                if flow_rows else ""
                            )
                            + f"<p>These months are the clean ones. From "
                            f"{fault.break_date:%B} the same arithmetic returns "
                            f"{fault.recent_gal / IRRIGATION_SUMMER_MIN:.2f} GPM, which no "
                            f"pipe does on its own — that is the leak, and it has its own "
                            f"section above.</p>"
                            if fault else ""
                        ),
                    ),
                    Callout(
                        kind="finding",
                        title=(
                            f"The controller has lost track of the time "
                            f"{spell(len(clock_slips))} times"
                            if clock_slips else "The controller keeps its own clock"
                        ),
                        body=(
                            f"<p>Reading every cycle at the hour it actually ran, rather "
                            f"than at the hour the controller is supposed to use, turns up "
                            f"something the daily meter could never show: the start time "
                            f"is not fixed. Every dot off the line below is a controller "
                            f"that lost the time.</p>"
                            if clock_slips else ""
                        ),
                    ),
                    charts.schedule_clock(
                        "clock",
                        "When the controller actually fired",
                        f"One dot per cycle, placed at the hour the meter recorded it "
                        f"— against the {set_hour:02d}:00 it was programmed to use.",
                        [
                            (c.date, c.hour, f"{c.date:%a %-d %b %Y}: {c.hour:02d}:00")
                            for c in model.detect_cycles(hourly_series)
                        ],
                        [
                            (e.start, e.end, e.hour, e.cycles, era_cause.get(e.start, ""))
                            for e in eras
                        ],
                        set_hour,
                        "water",
                        note=(
                            "The record holds no cycle at a wrong hour that is also a "
                            "wrong volume, which is what separates a lost clock from a "
                            "changed program."
                        ),
                    ),
                    Callout(
                        kind="note",
                        title="Why a controller loses the time",
                        body=(
                            f"<p><strong>The weekdays tell the two causes apart.</strong> "
                            f"A controller keeping its own schedule badly and a controller "
                            f"that has lost the schedule entirely both look like a moved "
                            f"start time, but only one of them also moves the days.</p>"
                            f"<p><strong>{spell(len(power_cuts)).capitalize()} are power "
                            f"cuts.</strong> The controller has a backup battery and it had "
                            f"never been connected — the insulating tab was still in it, "
                            f"straight from the factory. An outage takes the clock with it "
                            f"and the controller comes back knowing neither the hour nor "
                            f"the day, which is why these fire on {cut_days} instead of "
                            f"{normal_day_names}. "
                            f"What did <em>not</em> change is the volume: the midday cycles "
                            f"delivered {cut_gallons:.0f} "
                            f"gallons against {cycle_summer:.0f} either side. The program "
                            f"survived; only the clock was lost, which is why the volume "
                            f"evidence elsewhere on this page is undisturbed by it.</p>"
                            f"<p><strong>{spell(len(dst_slips)).capitalize()} is daylight "
                            f"saving.</strong> The controller runs its own clock and does "
                            f"not observe it, so local time slides underneath a schedule it "
                            f"is still keeping perfectly: the hour moves by exactly one and "
                            f"the weekdays do not move at all. The meter sees that as a "
                            f"schedule change because, from the pipe's point of view, that "
                            f"is precisely what it is.</p>"
                            + (
                                f"<p><strong>And the seasonal setting rides along with "
                                f"the clock.</strong> The winter program is not a "
                                f"different program — it is the same fifteen minutes a "
                                f"zone with the seasonal-adjust dial turned to 50%, which "
                                f"the controller rounds to seven. The meter catches both "
                                f"times it was moved, and neither lands on anything "
                                f"horticultural:</p>"
                                + "".join(
                                    f"<p>Cycles ran {lo:.0f} gallons up to "
                                    f"{prev.end:%-d %B %Y} at {prev.hour:02d}:00, and "
                                    f"{hi:.0f} from {nxt.start:%-d %B %Y} at "
                                    f"{nxt.hour:02d}:00 — both changed inside the same "
                                    f"{(nxt.start - prev.end).days}-day gap, which is one "
                                    f"trip to the controller.</p>"
                                    for prev, nxt, lo, hi in season_switches
                                )
                                + f"<p>Which makes the whole thing one habit rather than "
                                f"two: the trip to fix a clock that cannot fix itself is "
                                f"also the only reliable prompt to change the watering. It "
                                f"works — but it binds the irrigation season to whenever "
                                f"the clock next goes wrong, and it is why summer began on "
                                f"{season_switches[-1][1].start:%-d %B} this year rather "
                                f"than whenever the garden wanted it.</p>"
                                if season_switches else ""
                            )
                            + f"<p>The cost of the August episode is not the water — the "
                            f"cycles were the same size. It is <em>when</em> they ran. "
                            f"Midday in Las Cruces in August is the worst hour of the worst "
                            f"month to water: most of it evaporates before it reaches a "
                            f"root. And with no working battery it will happen again at the "
                            f"next outage, which is a two-dollar fix.</p>"
                            if clock_slips else ""
                        ),
                    ),
                ] + leak_blocks,
            )
        )
    
    return section
