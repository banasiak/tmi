"""What the electricity meter can separate.

A floor that never switches off, a load that runs to a timer, and what is left
answering the weather.
"""

from __future__ import annotations

import datetime as dt

from src import charts, costs, model, report, tariff
from src.analysis import Analysis
from src.house import SYSTEM_GALLONS
from src.palette import STREAM_COLORS
from src.prose import money
from src.report import Callout, Section, Tile


def build(data: Analysis) -> Section:
    """What the electricity meter can separate."""
    # Everything this section reads from the analysis layer.
    baseload = data.baseload
    days = data.days
    elec_model = data.elec_model
    pump_options = data.pump_options
    scheduled = data.scheduled
    total_kwh = data.total_kwh
    vs_options = data.vs_options
    with_elec = data.with_elec

    elec_blocks: list[object] = []
    # Built first but placed after the carpet plot:
    # the timer block is a horizontal band anyone can see in that chart, so the
    # finding reads as a confirmation rather than an assertion.
    timer_blocks: list[object] = []

    if scheduled and baseload:
        # Marginal, not blended: this load sits on top of everything else, so an
        # hour removed is priced at the top-tier rate, never the average.
        sched_cost = sum(
            tariff.marginal_rate(d.date) * scheduled.daily_kwh for d in with_elec
        )
        timer_blocks.append(
            Callout(
                kind="finding",
                title=f"Something runs on a timer from {scheduled.start_time} to {scheduled.end_time}",
                body=(
                    f"<p>A block of <strong>{scheduled.magnitude_kw:.2f} kW</strong> switches on "
                    f"at {scheduled.start_time} and off at {scheduled.end_time} — "
                    f"{scheduled.hours:.2f} hours, every day. That is "
                    f"<strong>{scheduled.daily_kwh:.1f} kWh/day</strong>, or "
                    f"<strong>{scheduled.annual_kwh:,.0f} kWh across the "
                    f"{len(with_elec)} metered days — "
                    f"{scheduled.share_of_total:.0%} of everything you use</strong>, "
                    f"about {money(sched_cost)} a year.</p>"
                    f"<p>It is equipment, not habit: mild-day consumption is "
                    f"{scheduled.weekday_kwh:.1f} kWh on weekdays and "
                    f"{scheduled.weekend_kwh:.1f} kWh at weekends — a difference of "
                    f"{abs(scheduled.weekend_kwh - scheduled.weekday_kwh):.1f} kWh. "
                    f"Nothing people do is that consistent. "
                    f"<strong>It is the pool pump</strong> — confirmed below by a second "
                    f"sensor that has nothing to do with the electricity meter.</p>"
                    f"<p>The motor is an <strong>A.O. Smith SQ1102</strong> — 1 HP nameplate, "
                    f"service factor {costs.PUMP_SERVICE_FACTOR}, {costs.PUMP_RPM} RPM, capacitor "
                    f"start. That rating predicts {costs.pump_nameplate_watts():,.0f} W at full "
                    f"load; the meter measured {scheduled.magnitude_kw * 1000:,.0f} W. Three "
                    f"independent confirmations now agree — the electrical step, the water "
                    f"temperature jumping at the same quarter-hour, and the nameplate.</p>"
                    f"<p><strong>It is single-speed</strong>, so runtime is the only variable "
                    f"without new hardware. And there is a great deal of runtime to give back. "
                    f"At around {costs.PUMP_FLOW_GPM:.0f} GPM this pump turns the "
                    f"{SYSTEM_GALLONS:,.0f} gallon system over once every "
                    f"{costs.turnover_hours(SYSTEM_GALLONS):.1f} hours, so "
                    f"{scheduled.hours:.2f} hours a day is about "
                    f"<strong>{pump_options[0].turnovers:.1f} turnovers</strong>. The usual "
                    f"guidance is one, two if you want margin.</p>"
                    + '<div class="table-scroll"><table><thead><tr><th>Daily runtime</th>'
                    + "<th>Turnovers</th><th>kWh/yr</th><th>Cost/yr</th><th>Saved</th>"
                    + "</tr></thead><tbody>"
                    + "".join(
                        f"<tr><td>{o.hours:.2f} h{' (today)' if i == 0 else ''}</td>"
                        f"<td>{o.turnovers:.1f}</td><td>{o.annual_kwh:,.0f}</td>"
                        f"<td>{money(o.annual_cost)}</td>"
                        f"<td>{'—' if i == 0 else money(pump_options[0].annual_cost - o.annual_cost)}</td></tr>"
                        for i, o in enumerate(pump_options)
                    )
                    + "</tbody></table></div>"
                    + f"<p><strong>Cutting to three hours still gives "
                    f"{pump_options[-1].turnovers:.1f} turnovers and saves "
                    f"{money(pump_options[0].annual_cost - pump_options[-1].annual_cost)} a year, "
                    f"at no cost.</strong> Before acting on that, check what else is tied to "
                    f"pump runtime: a salt chlorine generator only makes chlorine while the pump "
                    f"runs, the heater needs flow to fire, and surface skimming needs some hours. "
                    f"Any of those can set a floor that filtration alone does not.</p>"
                    f"<p>Replacing the motor with a variable-speed unit changes the arithmetic "
                    f"entirely, because power follows the cube of speed while flow follows the "
                    f"first power — half speed moves half the water for an eighth of the power:</p>"
                    + '<div class="table-scroll"><table><thead><tr><th>Speed</th><th>Draw</th>'
                    + f"<th>Hours for {costs.TURNOVERS_TARGET:.0f} turnovers</th><th>kWh/yr</th>"
                    + "<th>Cost/yr</th><th>Saved</th></tr></thead><tbody>"
                    + "".join(
                        f"<tr><td>{o.label}</td><td>{o.kw:.2f} kW</td><td>{o.hours:.1f} h</td>"
                        f"<td>{o.annual_kwh:,.0f}</td><td>{money(o.annual_cost)}</td>"
                        f"<td>{money(pump_options[0].annual_cost - o.annual_cost)}</td></tr>"
                        for o in vs_options
                    )
                    + "</tbody></table></div>"
                    + f"<p>At half speed the same filtration costs "
                    f"{money(vs_options[1].annual_cost)} instead of "
                    f"{money(pump_options[0].annual_cost)} — a saving of "
                    f"{money(pump_options[0].annual_cost - vs_options[1].annual_cost)} a year. "
                    f"Worth noting that US efficiency rules have barred new single-speed pumps "
                    f"above 0.711 total HP since July 2021, so a replacement would be "
                    f"variable-speed regardless, and utility rebates for the swap are common.</p>"
                    f"<p>Timing still matters as exposure rather than cost. The block runs "
                    f"straight through the late-afternoon system peak, and four months of it "
                    f"fall in the summer season where the marginal rate is "
                    f"${tariff.marginal_rate(dt.date(2026, 7, 15)):.4f}/kWh against "
                    f"${tariff.marginal_rate(dt.date(2026, 1, 15)):.4f} in winter — "
                    f"{tariff.marginal_rate(dt.date(2026, 7, 15)) / tariff.marginal_rate(dt.date(2026, 1, 15)):.2f}× more. "
                    f"If EPE introduces time-of-use pricing, this schedule is your largest "
                    f"exposure to it.</p>"
                ),
            )
        )
    
    if baseload:
        elec_blocks.append(
            report.tile_row(
                [
                    Tile(
                        "Always-on floor",
                        f"{baseload.median_kw:.2f}",
                        "kW",
                        f"the quietest sustained draw on a median day — "
                        f"{baseload.annual_kwh:,.0f} kWh/yr, {baseload.share_of_total:.0%} of total",
                        STREAM_COLORS["electric"]["light"],
                    ),
                    Tile(
                        "Floor, cost",
                        money(
                            sum(
                                tariff.marginal_rate(d.date) * d.electric.baseload_kw * 24
                                for d in with_elec
                            )
                        ),
                        "/yr",
                        "at marginal rates — what the house costs before anyone does anything",
                    ),
                    Tile(
                        "Seasonal drift in floor",
                        f"{baseload.seasonal_spread_kw:.2f}",
                        "kW",
                        f"between the lowest and highest month — "
                        f"{'largely weather-independent' if baseload.seasonal_spread_kw < 0.4 else 'meaningfully seasonal'}",
                    ),
                    Tile(
                        "Weather-independent load",
                        f"{elec_model.baseline_kwh_day:.0f}" if elec_model else "—",
                        "kWh/day",
                        f"regression intercept — {elec_model.baseline_kwh_day * len(with_elec) / total_kwh:.0%} "
                        f"of consumption survives with zero degree-days"
                        if elec_model
                        else "",
                    ),
                ]
            )
        )
    
    # Carpet plot: the whole year, every interval.
    columns = [
        (d.date, [(v * 4.0 if v is not None else None) for v in d.electric.profile])
        for d in with_elec
    ]
    elec_blocks.append(
        charts.carpet_plot(
            "carpet",
            "Every interval of the year",
            "Each column is one day; each row a 15-minute slot from midnight to midnight. "
            "Power in kW.",
            columns,
            "electric",
            note=(
                "The horizontal band across the afternoon and evening is the timer load — "
                "it holds the same clock position through every season, which is what "
                "distinguishes it from weather-driven use. The summer bulge above and below "
                "it is air conditioning. The pale strip across the small hours is the "
                "always-on floor."
            ),
        )
    )
    elec_blocks.extend(timer_blocks)
    
    bands = [
        ("Cold day (<50°F)", -20.0, 50.0),
        ("Mild day (58–72°F)", 58.0, 72.0),
        ("Hot day (>85°F)", 85.0, 200.0),
    ]
    profiles = model.profile_by_temp_band(days, bands)
    if len(profiles) >= 2:
        # All three curves are electricity; only the temperature band differs.
        # So they take three ordered steps of the electric hue rather than three
        # different hues — aqua and orange here read as water and gas.
        colors = ["var(--band-1)", "var(--band-2)", "var(--band-3)"]
        series = [
            (f"{p.label.split(' (')[0]} ({p.days}d)", colors[i % len(colors)], p.slots)
            for i, p in enumerate(profiles)
        ]
        highlight = (
            (scheduled.start_slot, scheduled.end_slot, "timer block")
            if scheduled
            else None
        )
        hot = next((p for p in profiles if p.mean_temp > 80), None)
        mild = next((p for p in profiles if 55 < p.mean_temp < 75), None)
        cooling_note = ""
        if hot and mild:
            diff = [h - m for h, m in zip(hot.slots, mild.slots)]
            peak_i = diff.index(max(diff))
            cooling_note = (
                f" Differencing the hot and mild shapes isolates the cooling load without a "
                f"submeter: about <strong>{sum(diff) / 4:.0f} kWh/day</strong>, peaking at "
                f"{max(diff):.2f} kW around {peak_i * 24 // len(diff):02d}:00."
            )
        elec_blocks.append(
            charts.profile_lines(
                "profiles",
                "The shape of a day, by how hot it was",
                "Median power at each 15-minute slot, grouped by the day's mean outdoor temperature.",
                series,
                "kW",
                highlight=highlight,
                note=(
                    "The timer block sits at the same clock position in all three curves, "
                    "cold days included — it does not care about the weather." + cooling_note
                ),
            )
        )
    
    duration = model.load_duration(days)
    if duration:
        elec_blocks.append(
            charts.duration_curve(
                "duration",
                "Every interval of the year, sorted by size",
                f"All {duration.intervals:,} fifteen-minute readings ranked from "
                f"largest to smallest. The x-axis is rank, not time.",
                duration.curve,
                "electric",
                "kW",
                markers=[
                    (0.25, f"{duration.percentiles[25]:.1f} kW"),
                    (0.90, f"{duration.percentiles[90]:.2f} kW"),
                ],
                percentiles=duration.percentiles,
                # Days of metered time the curve covers, from the interval count
                # rather than the calendar, so it matches the axis it labels: 96
                # quarter-hours a day, and gaps in the export are simply absent
                # from both.
                total_days=duration.intervals / 96.0,
                note=(
                    f"The same three loads the curves above separate, seen here as one "
                    f"shape. The cliff on the left is air conditioning — "
                    f"{duration.hours_above_3kw:,.0f} hours a year above 3 kW, "
                    f"{duration.hours_above_3kw / 8760:.0%} of the time. The long flat "
                    f"tail on the right is the floor, and it never reaches zero: the "
                    f"quietest quarter-hour of the entire year still drew "
                    f"{duration.min_kw:.2f} kW."
                ),
            )
        )
        elec_blocks.append(
            Callout(
                kind="note",
                title=(
                    f"Half the year is spent under {duration.percentiles[50]:.2f} kW, "
                    f"and the peak is {duration.peak_kw / duration.percentiles[50]:.0f}× that"
                ),
                body=(
                    f"<p>Ranking the readings instead of plotting them against the clock "
                    f"answers a different question: not when the house draws power, but how "
                    f"much of the year it spends at each level. The median quarter-hour is "
                    f"<strong>{duration.percentiles[50]:.2f} kW</strong> — barely more than "
                    f"the floor — while the peak reached "
                    f"<strong>{duration.peak_kw:.1f} kW</strong>.</p>"
                    f"<p>That gap is why the annual bill is so much flatter than the peaks "
                    f"suggest. The top 1% of intervals run above "
                    f"{duration.percentiles[1]:.2f} kW but there are only "
                    f"{duration.intervals * 0.01 * 0.25:,.0f} hours of them; the bottom "
                    f"{100 - 90}% sit below {duration.percentiles[90]:.2f} kW for "
                    f"{duration.intervals * 0.10 * 0.25:,.0f}. The area <em>beneath</em> the "
                    f"{duration.percentiles[90]:.2f} kW line — that draw sustained through "
                    f"every hour of the year, not just the hours that sit on it — is "
                    f"<strong>{duration.floor_share:.0%} of the year's energy</strong>: the "
                    f"house's own idling, paid for in full whatever the weather does.</p>"
                    f"<p>It also sizes any battery conversation before it starts. Carrying "
                    f"the house through the top 1% of intervals is a demand problem; "
                    f"carrying it through the flat tail is an energy problem, and they need "
                    f"very different hardware.</p>"
                ),
            )
        )
    
    section = (
        Section(
            id="electricity",
            emoji="⚡",
            title="Where the electricity goes",
            lede=(
                "Interval data separates three things a monthly bill blends together: what "
                "never turns off, what runs to a clock, and what responds to the weather."
            ),
            blocks=elec_blocks,
        )
    )
    
    return section
