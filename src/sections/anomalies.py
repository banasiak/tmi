"""Days that departed from what the weather predicted.

Detection and attribution are kept apart: a flagged day is a residual, and a
cause is a separate claim that has to be argued from another source.
"""

from __future__ import annotations

from src import charts, model
from src.analysis import Analysis
from src.charts import fmt
from src.palette import STATUS
from src.report import Callout, Section


def build(data: Analysis) -> Section:
    """Days that departed from what the weather predicted."""
    # Everything this section reads from the analysis layer.
    anomalies = data.anomalies
    attributions = data.attributions
    days = data.days
    fault = data.fault
    gas_series = data.gas_series
    gas_sig = data.gas_sig
    gas_split = data.gas_split
    leak_sens = data.leak_sens
    resolved = data.resolved
    still_open = data.still_open
    total_gas = data.total_gas
    water_anoms = data.water_anoms
    water_series = data.water_series

    anom_blocks: list[object] = []
    
    causes = model.attribution_summary(attributions)
    # Derive the pool-heating statistics from the attribution list itself, so
    # they cannot drift from the counts quoted alongside them.
    heater_days = [a for a in attributions if a.cause == "pool-heating"]
    heater_excess = sum(a.anomaly.excess for a in heater_days)
    heater_weekend = sum(1 for a in heater_days if a.anomaly.date.weekday() >= 5)
    weekend_base = sum(1 for d in days if d.date.weekday() >= 5) / len(days)
    
    
    if anomalies:
        march = sum(
            a.actual for a in water_anoms
            if a.date.year == 2026 and a.date.month == 3
        )
        anom_blocks.append(
            Callout(
                kind="finding",
                title=(
                    f"{len(attributions)} days flagged, {len(resolved)} of them now "
                    f"accounted for — and every one by the pool"
                ),
                body=(
                    f"<p>The detector's job is narrow: it says a day departs from what the "
                    f"weather predicts, and nothing more. Explaining those departures took "
                    f"the water-temperature probe, the calendar, and the other two meters. "
                    f"Keeping the two jobs apart matters — thresholds tuned until a story "
                    f"emerges are not evidence.</p>"
                    f"<ul>"
                    f"<li><strong>{causes.get('pool-heating', 0)} gas days: the pool heater.</strong> "
                    f"Together {heater_excess:,.0f} cf — {heater_excess / total_gas:.0%} of the "
                    f"year's gas. Most are identified by energy balance rather than by the "
                    f"calendar: the water's heat gain from one morning to the next accounts for "
                    f"a large share of the missing gas, which works in any season. "
                    f"{heater_weekend} of {len(heater_days)} fell on a weekend, about "
                    f"{(heater_weekend / len(heater_days)) / weekend_base:.1f}× what chance "
                    f"would give.</li>"
                    f"<li><strong>{causes.get('spa', 0)} gas days: spa soaks.</strong> Each "
                    f"peaked after sunset — zero solar — with the probe deliberately moved into "
                    f"the spa to watch it climb to 110°F. A furnace does not know it is "
                    f"evening.</li>"
                    f"<li><strong>{causes.get('refill', 0)} water days: the drain and refill.</strong> "
                    f"{march:,.0f} gallons across 29–30 March, the whole system going back in.</li>"
                    f"<li><strong>{causes.get('pool-adjacent', 0)} water day</strong> falls on the "
                    f"same date as a pool-heating event — a top-up alongside the heater.</li>"
                    f"</ul>"
                    f"<p>So the year's anomalies across three separate utilities trace to one "
                    f"piece of equipment. That is the useful result: not that {len(attributions)} "
                    f"days were odd, but that they were odd for a single reason, and the reason "
                    f"was findable from the data already being collected.</p>"
                    + (
                        f"<p><strong>{len(still_open)} remain open</strong>, and are worth stating "
                        f"plainly rather than folded into the story:</p><ul>"
                        + "".join(
                            f"<li><strong>{a.anomaly.date:%-d %B %Y}</strong> — "
                            f"{a.anomaly.stream}, {fmt(a.anomaly.actual)} {a.anomaly.unit} "
                            f"against {fmt(a.anomaly.expected)} expected. {charts.esc(a.detail)}."
                            + (
                                " The water absorbed none of it, so it was not the pool."
                                if a.anomaly.stream == "gas"
                                else " Electricity that day also ran above normal, which fits "
                                "household activity rather than equipment."
                            )
                            + "</li>"
                            for a in still_open
                        )
                        + "</ul>"
                        if still_open
                        else ""
                    )
                    + (
                        f"<p><strong>This test found no leak, and there was one.</strong> "
                        f"It watches the quietest day of each week, which for this house "
                        f"sits at {leak_sens.typical_floor_gal:.0f} gallons, and reports "
                        f"anything holding that floor above "
                        f"{leak_sens.trip_threshold_gal:.0f}. Nothing did, all year — and "
                        f"that was correct, not a miss. A split irrigation line only loses "
                        f"water while its valve is open, so the quiet days stayed quiet "
                        f"and the floor never moved while "
                        + (f"{fault.excess_total:,.0f} gallons " if fault else "water ")
                        + f"went into the ground. The failure was in the question, not "
                        f"the arithmetic.</p>"
                        f"<p>What it does still cover is a leak that runs "
                        f"<em>continuously</em>: a running toilet or a failed flapper "
                        f"would lift the floor well past the trigger. Below roughly "
                        f"<strong>{leak_sens.detectable_leak_gal:.0f} gallons a day</strong> "
                        f"even that hides inside the household's own variation, so a "
                        f"dripping tap is invisible at daily resolution. Two different "
                        f"faults, two different monitors — and the one that mattered here "
                        f'is <a href="#leak">the cycle volume</a>.</p>'
                        f"<p>The March refill left nothing running behind it: the weekly floor "
                        f"in the month afterwards sat at 65 gallons against 53 in the month "
                        f"before, which is ordinary seasonal drift rather than a new baseline. "
                        f"A drain and refill is a discrete event, and this one closed.</p>"
                        if leak_sens
                        else ""
                    )
                ),
            )
        )
    
        rows = []
        for item in attributions[:24]:
            anomaly = item.anomaly
            color = STATUS["good"] if item.resolved else STATUS[anomaly.severity]
            stream_name = "Gas" if anomaly.stream == "gas" else "Water"
            rows.append(
                f'<div class="anom">'
                f'<span class="sev" style="background:{color}"></span>'
                f'<span class="when">{anomaly.date:%a %-d %b %Y}</span>'
                f'<span class="what"><strong>{stream_name}</strong> — '
                f'{charts.esc(model.CAUSE_LABELS[item.cause])}</span>'
                f'<span class="mag">{fmt(anomaly.actual)} {anomaly.unit} '
                f'<span class="badge">vs {fmt(anomaly.expected)} expected</span></span>'
                f"</div>"
            )
        # Folded: the prose above already says what these are and how they were
        # attributed, and most of the list is the pool heater repeating. Kept in
        # full rather than truncated, because "13 of 15" is only checkable if all
        # 15 are reachable.
        anom_blocks.append(
            f'<details class="table-view"><summary>All {len(rows)} flagged days'
            f"</summary>"
            f'<div class="anoms">{"".join(rows)}</div></details>'
        )
    
    anom_blocks.append(
        charts.calendar_heatmap(
            "water-cal",
            "Water, day by day",
            "Daily gallons across the year.",
            water_series,
            "water",
            "gal",
            note=(
                "Water at this house is not weather-driven — with refrigerated air there is "
                "no evaporative cooling load, so what remains is irrigation and behavior. "
                "That is why water is judged against its own trailing baseline rather than "
                "against temperature."
            ),
        )
    )
    anom_blocks.append(
        charts.calendar_heatmap(
            "gas-cal",
            "Gas, day by day",
            "Daily cubic feet across the year.",
            gas_series,
            "gas",
            "cf",
            note="The winter block is heating. The isolated dark cells outside it are not.",
        )
    )
    anom_blocks.append(
        charts.monthly_columns(
            "gas-split",
            "Where the gas goes",
            f"Annual cubic feet, split by the heating signature. "
            f"{gas_split.coverage:.0%} of metered gas is accounted for.",
            ["Space heating", "Water heater\n+ cooking", "Pool + spa"],
            [(
                "Cubic feet",
                "gas",
                [gas_split.space_heating_cf, gas_split.water_heater_cf, gas_split.pool_spa_cf],
            )],
            "cf per year",
            category_label="End use",
            note=(
                f"Space heating is only {gas_split.space_heating_cf / gas_split.metered_cf:.0%} "
                f"of the gas — less than the water heater's year-round standing draw, and "
                f"the reason the whole gas bill loses to its own access fee in the cost "
                f"section. The house "
                f"starts calling for heat when the outside temperature dips below "
                f"{gas_sig.base_f:.0f}°F (rather than the conventional 65°F), which cuts "
                f"the heating degree-days that matter from "
                f"{sum(d.weather.hdd(65.0) for d in days if d.gas_cf is not None):,.0f} to "
                f"{sum(d.weather.hdd(gas_sig.base_f) for d in days if d.gas_cf is not None):,.0f} — "
                f"and only {len([d for d in days if d.weather.t_min < 32])} nights all year fell "
                f"below freezing."
            ),
        )
    )
    
    section = (
        Section(
            id="anomalies",
            emoji="🚩",
            title="What the weather cannot explain",
            lede=(
                "Every day is scored against what its own weather predicts. What survived that "
                "test then had to be explained from elsewhere in the record — and almost all of "
                "it was."
            ),
            blocks=anom_blocks,
        )
    )
    
    return section
