"""A two-state controller, solved from the meter rather than read off the schedule.

The controller has two programs and a seasonal scaler, so anything drifting
smoothly across the year is something else drawing water.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from src import charts
from src.analysis import Analysis
from src.house import IRRIGATION_SUMMER_MIN, IRRIGATION_WINTER_MIN
from src.palette import STATUS
from src.prose import spell
from src.report import Callout, Section


def build(data: Analysis) -> Section | None:
    """A two-state controller, solved from the meter rather than read off the schedule."""
    # Everything this section reads from the analysis layer.
    big_water = data.big_water
    cycle_summer = data.cycle_summer
    cycle_summer_hi = data.cycle_summer_hi
    cycle_summer_lo = data.cycle_summer_lo
    cycle_winter = data.cycle_winter
    cycle_winter_hi = data.cycle_winter_hi
    cycle_winter_lo = data.cycle_winter_lo
    evap = data.evap
    fault = data.fault
    hourly = data.hourly
    irr_event = data.irr_event
    irr_monthly = data.irr_monthly
    irr_volume = data.irr_volume
    irrigation = data.irrigation
    irrigation_changes = data.irrigation_changes
    irrigation_health = data.irrigation_health
    total_water = data.total_water
    use_irrigation = data.use_irrigation
    use_leak = data.use_leak
    with_util = data.with_util
    section: Section | None = None

    if len(irrigation) >= 6:
        warm = [m for m in irrigation if m.mean_temp >= 72]
        cold = [m for m in irrigation if m.mean_temp <= 56]
    
        # Weekly delivery on the measured-event basis, so this callout, the
        # chart, the annual total and the cost row all quote one estimator.
        # Event count per week rather than per month, so a partial August is not
        # read as a quiet one.
        def weekly(m: model.IrrigationMonth) -> float:
            return irr_event.get(m.month, m.per_event_gal) * len(m.watering_days)
    
        warm_weekly = statistics.fmean(weekly(m) for m in warm) if warm else 0.0
        cold_weekly = statistics.fmean(weekly(m) for m in cold) if cold else 0.0
        ratio = cold_weekly / warm_weekly if warm_weekly else 0.0
        annual_irr = irr_volume
    
        # The stacked chart below is built from the meter, not from the monthly
        # medians the callouts above quote. Those medians are a robust estimator
        # and a poor accountant: `per_event × 3 × 52/12` plus `baseline × 30`
        # summed to 43,167 gallons against 52,444 actually metered, and put
        # September at 154 gal an event where the event-by-event series — the one
        # the "smooth seasonal curve" sentence describes — says 98. Stacking real
        # monthly totals split by the measured events makes the chart agree with
        # both the meter and the prose.
        split_skipped = {d for d in big_water}
        month_metered: dict[str, float] = defaultdict(float)
        month_covered: dict[str, int] = defaultdict(int)
        for d in with_util:
            if d.date in split_skipped:
                continue
            month_metered[f"{d.date:%Y-%m}"] += d.water_gal
            month_covered[f"{d.date:%Y-%m}"] += 1
        # Measured cycles, and the leak split out of them. The chart used to plot
        # the daily-derived estimate, which put a smooth climb through June and
        # July into the irrigation series and so contradicted its own caption:
        # the controller has two settings and cannot ramp. What ramps is the
        # leak, and separating it makes both series say what they mean.
        month_events = {
            k: v for k, v in use_irrigation.items()
        } if use_irrigation else irr_monthly
        month_leak = use_leak if use_leak else {}
        # Partial months are dropped rather than stretched, the same rule every
        # other monthly chart on this page follows. March keeps its two held-out
        # days in the day count so it is not disqualified for them.
        split_months = [
            k for k in sorted(month_metered)
            if month_covered[k] + sum(1 for d in split_skipped if f"{d:%Y-%m}" == k) >= 27
        ]
        split_labels = [k[5:] + "/" + k[2:4] for k in split_months]
        split_irrigation = [month_events.get(k, 0.0) for k in split_months]
        split_leak = [month_leak.get(k, 0.0) for k in split_months]
        split_rest = [
            max(0.0, month_metered[k] - month_events.get(k, 0.0)
                - month_leak.get(k, 0.0))
            for k in split_months
        ]
        rest_rate = {
            k: (month_metered[k] - month_events.get(k, 0.0)
                - month_leak.get(k, 0.0)) / max(1, month_covered[k])
            for k in split_months
        }
        rest_warm = [rest_rate[k] for k in split_months if k[5:] in ("06", "07", "08", "09")]
        rest_cold = [rest_rate[k] for k in split_months if k[5:] in ("12", "01", "02")]
    
        irr_blocks: list[object] = [
            Callout(
                kind="finding",
                title="The drip controller is legible from daily meter reads alone",
                body=(
                    f"<p>Three weekdays sit far above the other four, every week, for a "
                    f"year: <strong>{irrigation[-1].schedule}</strong>. Daily resolution "
                    f"cannot see a valve open, but a controller running to a weekly "
                    f"schedule cannot hide from it either — the gap between the two groups "
                    f"is the water the controller delivered.</p>"
                    f"<p>In the warmest months it puts out about "
                    f"<strong>{warm_weekly:,.0f} gallons a "
                    f"week</strong>; in the coldest, "
                    f"<strong>{cold_weekly:,.0f}</strong> — "
                    f"<strong>{ratio:.0%}</strong> of the summer rate, on the same three "
                    f"days. Across the year irrigation accounts for roughly "
                    f"{annual_irr:,.0f} gallons, "
                    f"{annual_irr / total_water:.0%} of everything metered.</p>"
                    + (
                        f"<p><strong>The watering days are not quite fixed, and the "
                        f"reason is not horticultural.</strong> The daily meter reports "
                        f"them changing "
                        f"{spell(len(irrigation_changes))} time"
                        f"{'' if len(irrigation_changes) == 1 else 's'} across the year. "
                        f"It is right that they moved and wrong about why — read at the "
                        f"hour each cycle actually ran, the start <em>time</em> moved with "
                        f"them, which no reprogramming would do. That is a clock, not a "
                        f"gardener, and it has its own note in the hourly section.</p>"
                        if irrigation_changes
                        else ""
                    )
                ),
            ),
            Callout(
                kind="note",
                title="A burst line hides from the leak test",
                body=(
                    f"<p>The leak test elsewhere on this page watches the floor — the "
                    f"quietest hours of the week — and a broken irrigation line will never "
                    f"move it. A burst downstream of the valve leaks only <em>while the "
                    f"valve is open</em>, so the quiet days stay quiet and the weekly "
                    f"minimum holds steady. All the damage lands in how much each cycle "
                    f"delivers, which needs a monitor of its own.</p>"
                ),
            ),
            Callout(
                kind="finding",
                title=(
                    f"The controller delivers {cycle_winter:.0f} gallons a cycle in winter "
                    f"and {cycle_summer:.0f} in summer — the runtime, and nothing else"
                    if hourly and cycle_summer else
                    "The controller has two settings, and holds them"
                ),
                body=(
                    (
                        f"<p>Each cycle can be read straight off the meter, because the "
                        f"controller owns the {hourly.irrigation_hour:02d}:00 hour outright "
                        f"— {sum(len(p.irrigation(hourly.irrigation_hour)) for p in hourly.periods):,} "
                        f"of them across {len(hourly.periods)} months. No baseline to "
                        f"subtract, no household noise to argue with.</p>"
                        f"<p><strong>The seasonal step is the runtime.</strong> The X-Core "
                        f"holds two settings rather than a seasonal curve — "
                        f"{IRRIGATION_WINTER_MIN:.0f} minutes of valve-open time in winter "
                        f"against {IRRIGATION_SUMMER_MIN:.0f} in summer — and the water "
                        f"follows: a clean winter cycle is "
                        f"{cycle_winter / cycle_summer:.0%} of a summer one, against "
                        f"{IRRIGATION_WINTER_MIN / IRRIGATION_SUMMER_MIN:.0%} of the "
                        f"runtime. The small remainder is a slightly slower winter flow.</p>"
                        f"<p>Neither figure is one number all season. Winter cycles run "
                        f"{cycle_winter_lo:.0f}–{cycle_winter_hi:.0f} gallons and clean "
                        f"summer ones {cycle_summer_lo:.0f}–{cycle_summer_hi:.0f}, drifting "
                        f"down through the autumn as the ground cools and the line with "
                        f"it. That drift is why the fault below takes its reference from "
                        f"the weeks immediately before the break rather than from a "
                        f"season-wide average.</p>"
                        if hourly and cycle_summer else
                        f"<p>Measured against a household baseline across "
                        f"{len(irrigation_health.events)} watering events, the controller "
                        f"holds two settings rather than a seasonal curve — "
                        f"{IRRIGATION_WINTER_MIN:.0f} minutes in winter, "
                        f"{IRRIGATION_SUMMER_MIN:.0f} in summer — so what it delivers "
                        f"should step twice a year and hold flat in between. It does.</p>"
                    )
                    + (
                        f"<p><strong>Steady enough to catch a fault.</strong> Across the "
                        f"clean months a cycle holds its level to within a few gallons. "
                        f"That is what made a {fault.excess_gal:.0f}-gallon rise "
                        f"unmistakable, and why this is the only channel on the page that "
                        f"could have caught it.</p>"
                        if hourly and fault else ""
                    )
                    + (
                        f"<p>The same events estimated from daily totals scatter about "
                        f"{irrigation_health.typical_scatter:.0f} gallons, so only a "
                        f"sustained step of roughly "
                        f"{irrigation_health.detectable_step:.0f} gallons would show — "
                        f"obvious in summer, but in winter a fault would have to nearly "
                        f"double the cycle first. Subtracting a household baseline also "
                        f"charges anything landing on a watering night to the controller, "
                        f"so smooth seasonal drift in that estimate is the pool and the "
                        f"hose, never a controller that ramps.</p>"
                        if hourly and cycle_summer else
                        f"<p>The method has limits worth naming. It subtracts a "
                        f"non-watering day from a watering day, so anything rising through "
                        f"summer on both — the pool's float valve, hose work — cancels, "
                        f"while anything landing on a watering night is charged to "
                        f"irrigation. Scatter of about "
                        f"{irrigation_health.typical_scatter:.0f} gallons means only a "
                        f"step near {irrigation_health.detectable_step:.0f} would show.</p>"
                    )
                ),
            ),
            charts.monthly_columns(
                "irrigation",
                "Irrigation versus everything else",
                f"Complete months only, and the {spell(len(split_skipped))} refill days of "
                f"29–30 March held out. Each month's metered water, split into the "
                f"controller's own events and everything left over.",
                split_labels,
                [
                    ("Irrigation", "water", split_irrigation),
                    ("Leak", STATUS["serious"], split_leak),
                    ("Everything else", "var(--ink-muted)", split_rest),
                ],
                "gallons per month",
                stacked=True,
                note=(
                    f"Meter readings, not a model: the three series sum to the "
                    f"{sum(split_irrigation) + sum(split_leak) + sum(split_rest):,.0f} "
                    f"gallons actually billed across these "
                    f"{spell(len(split_months))} months.</p>"
                    f"<p><strong>The irrigation series steps and the gray one drifts, "
                    f"and those are different things.</strong> A cycle has two sizes and "
                    f"changes between them on the day somebody moves the dial — the "
                    f"winter block from November to February is unmistakable. The "
                    f"monthly totals are less tidy than the cycles because they also "
                    f"carry how many watering nights fell in the month, and because a "
                    f"summer cycle tapers through the autumn as the ground cools. The "
                    f"gray series has no settings at all: it runs "
                    f"{statistics.fmean(rest_warm):.0f} gal/day across the summer months "
                    f"against {statistics.fmean(rest_cold):.0f} in the depths of winter, "
                    f"and it slides between the two because that is what evaporation "
                    f"does. Most of that "
                    f"{statistics.fmean(rest_warm) - statistics.fmean(rest_cold):.0f} "
                    f"gal/day gap is the pool topping itself up through the float valve "
                    f"— <a href=\"#pool\">the pool section</a> "
                    f"predicts it from the weather and gets the seasonal shape right to "
                    f"an R² of {evap.r2:.2f}. The rest is hose work and washing "
                    f"vehicles.</p>"
                    f"<p><strong>The third series is the split line in Zone 1</strong>, "
                    f"which is what a controller that cannot ramp looks like when "
                    f"something downstream of it can. It appears in June, it grows, and "
                    f"it is the subject of its own section. Folded into the irrigation "
                    f"series — where "
                    f"a daily meter has no way to separate it — it reads as an "
                    f"irrigation program doing something no irrigation program "
                    f"does.</p>"
                    f"<p>March is short two days here: 29–30 March put "
                    f"{sum(d.water_gal for d in with_util if d.date in split_skipped):,.0f} "
                    f"gallons through the meter refilling the pool, which would have "
                    f"dwarfed every other bar on the chart."
                    if evap else ""
                ),
            ),
        ]
        section = (
            Section(
                id="irrigation",
                emoji="💦",
                title="The sprinkler saga",
                lede=(
                    "Water is the one stream with no weather signature worth fitting: it "
                    "answers to a clock rather than a thermometer. The meter recovers that "
                    "clock on its own — the schedule it keeps, the two seasonal settings it "
                    "steps between, and the volume each cycle delivers."
                ),
                blocks=irr_blocks,
            )
        )
    
    return section
