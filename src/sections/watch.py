"""One threshold worth carrying forward, and one failure nothing here would catch.

Returns None when the record is too short to set a threshold honestly.
"""

from __future__ import annotations

import datetime as dt

from src import equipment, model, report, tariff
from src.analysis import Analysis
from src.palette import STREAM_COLORS
from src.prose import money
from src.report import Callout, Formula, Section, formula, var


def build(data: Analysis) -> Section | None:
    """One threshold worth carrying forward, and one failure nothing here would catch."""
    # Everything this section reads from the analysis layer.
    baseload = data.baseload
    days = data.days
    elec_model = data.elec_model
    evap = data.evap
    floor_cost = data.floor_cost
    hourly = data.hourly
    section: Section | None = None

    winter_day = dt.date(2026, 1, 15)
    # Price a new always-on load the same way the existing floor is priced in the
    # cost table — the effective rate the floor actually paid across the year, not
    # the winter marginal rate alone. The two sections valued the same continuous
    # kilowatt at $0.084 and $0.103 respectively.
    floor_effective_rate = (
        floor_cost / baseload.annual_kwh
        if baseload.annual_kwh
        else tariff.marginal_rate(winter_day)
    )
    tripwire = model.baseload_tripwire(days, floor_effective_rate)
    # Split at the turn of the year: the record holds one cooling season either
    # side of it, which is the only comparison this span supports.
    cooling_watch = model.cooling_watch(days, elec_model, dt.date(2026, 1, 1))
    if tripwire and cooling_watch:
        fan_watts = (
            equipment.CONDENSER_FAN_FLA
            * equipment.NAMEPLATE_VOLTS
            * equipment.ASSUMED_POWER_FACTOR
        )
        # The bands where both seasons are populated are the honest comparison;
        # the outermost ones are where the two seasons stop overlapping.
        paired = [b for b in cooling_watch.bands if b[2] is not None and b[3] is not None]
        interior = paired[1:-1] or paired
        middle_gap = max(abs(b[2] - b[3]) for b in interior)
        middle_bands = (
            f"{interior[0][0]:.0f}–{interior[-1][1]:.0f} degree-day range"
            if interior else "matched range"
        )
        watch_blocks: list[object] = [
            report.tile_row(
                [
                    # Distinguished from the "Always-on floor" tile in the electricity
                    # section: that one is the median day's floor, this is the median of
                    # the twelve monthly medians. They differ by 0.02 kW, and sharing a
                    # label made that look like a contradiction.
                    report.Tile(
                        label="Floor, month by month",
                        value=f"{tripwire.median_kw:.2f}",
                        unit="kW",
                        detail=(
                            f"median of {len(tripwire.monthly)} monthly medians — the "
                            f"same floor as above, aggregated for watching rather than "
                            f"for costing"
                        ),
                        accent=STREAM_COLORS["electric"]["light"],
                    ),
                    report.Tile(
                        label="Month-to-month wobble",
                        value=f"±{tripwire.month_sd:.3f}",
                        unit="kW",
                        detail=f"full range {tripwire.spread_kw:.2f} kW across the year",
                    ),
                    report.Tile(
                        label="Smallest new load it would catch",
                        value=f"{tripwire.detectable_kw * 1000:.0f}",
                        unit="W",
                        detail=(
                            f"{tripwire.detectable_kwh:,.0f} kWh/yr — about "
                            f"{money(tripwire.detectable_cost)} a year left running"
                        ),
                    ),
                ]
            ),
            Callout(
                kind="finding",
                title=f"Watch the floor: {tripwire.median_kw:.2f} kW, ±{tripwire.month_sd:.3f}",
                body=(
                    f"<p>Most numbers on this page describe a year that has already "
                    f"happened. This one is for the next export. The always-on floor is "
                    f"equipment that never switches off, so unlike everything weather-driven "
                    f"it has no business moving at all — which makes its ordinary wobble a "
                    f"usable alarm threshold.</p>"
                    f"<p>Over {len(tripwire.monthly)} months it held "
                    f"<strong>{tripwire.median_kw:.2f} kW</strong> with a month-to-month "
                    f"standard deviation of {tripwire.month_sd:.3f} kW and no trend "
                    f"(t = {tripwire.trend_t:+.2f}). Two standard deviations is "
                    f"<strong>{tripwire.detectable_kw * 1000:.0f} W</strong>. Anything new "
                    f"that runs continuously and draws more than that — a second "
                    f"refrigerator, a failing pump seal, a device that stopped sleeping — "
                    f"would clear the noise and show up as a step in this series.</p>"
                    f"<p>Put in money, {tripwire.detectable_kw * 1000:.0f} W left running is "
                    f"{money(tripwire.detectable_cost)} a year. So the floor catches any "
                    f"new always-on load costing more than roughly that, and cannot see one "
                    f"costing much less.</p>"
                ),
            ),
            formula(Formula(
                caption="Where the alarm threshold comes from",
                lhs=var("P","min"),
                rhs=f'2 · &sigma;({var("F","m")})',
                where=[
                    (var("F","m"), "each month's median always-on floor, kW"),
                    ("&sigma;", f"its month-to-month standard deviation, "
                                f"{tripwire.month_sd:.3f} kW"),
                    (var("P","min"), f"smallest new continuous load that would clear the "
                                     f"noise — {tripwire.detectable_kw * 1000:.0f} W"),
                ],
                note="Two standard deviations rather than three: this is a prompt to go "
                     "and look, not a claim that something is wrong.",
            )),
            Callout(
                kind="caution",
                title="The blind spot between the two alarms",
                body=(
                    f"<p>There is a real failure in this house's recent history that neither "
                    f"the floor above nor anything else on this page would have caught. "
                    f"Shortly before this record starts, the air conditioner's outdoor fan "
                    f"motor was found drawing too much current and was replaced. A "
                    f"technician with a clamp meter found it; the whole-house meter could "
                    f"not have.</p>"
                    f"<p>The arithmetic says why. That fan is rated "
                    f"{equipment.CONDENSER_FAN_FLA:.1f} A, or about "
                    f"{fan_watts:.0f} W. A fan drawing <em>double</em> its rating therefore "
                    f"adds only another {fan_watts:.0f} W, and only while the compressor "
                    f"runs — which works out near 6% of the cooling slope. Comparing "
                    f"cooling efficiency across the two summers in "
                    f"this record — matched on how hot the days were, since an air "
                    f"conditioner is less efficient the hotter it gets — resolves a step of "
                    f"<strong>{cooling_watch.detectable_pct:.0%}</strong> "
                    f"({cooling_watch.detectable:.2f} kWh per degree-day). The fault is "
                    f"five times smaller than the smallest thing the method can see.</p>"
                    f"<p>So the two alarms bracket a gap. The always-on floor catches "
                    f"anything new that runs <em>continuously</em> above "
                    f"{tripwire.detectable_kw * 1000:.0f} W. Cooling efficiency catches "
                    f"degradation above {cooling_watch.detectable_pct:.0%}. A part that is "
                    f"small, intermittent and only draws when the weather says so falls "
                    f"between them. The pool pump was found here precisely because it is "
                    f"the opposite of that — large, long-running, and on a fixed "
                    f"schedule.</p>"
                    f"<p>Worth recording that the naive version of this test fails badly. An "
                    f"unmatched changepoint scan over the cooling season reports a large, "
                    f"confident break at the start of June — and in the wrong direction, "
                    f"cooling apparently getting <em>worse</em>. It is not an event at all, "
                    f"but the curve of efficiency against outdoor temperature being fitted "
                    f"as a step. Matching on degree-days makes it vanish: across the "
                    f"{middle_bands} the two seasons agree to within "
                    f"{middle_gap:.2f} kWh per degree-day.</p>"
                ),
            ),
            Callout(
                kind="note",
                title=(
                    f"A {evap.intercept:.0f} gal/day overnight residue, recorded and "
                    f"not chased"
                    if evap else "An unexplained overnight flow"
                ),
                body=(
                    f"<p>Fitting the pool's make-up water against the weather leaves a "
                    f"constant behind: <strong>{evap.intercept:.0f} gallons a day</strong> "
                    f"in the small hours that does not vary with evaporation. Splitting "
                    f"the record in half puts it between 10 and 14, so it is a range.</p>"
                    f"<p>It is <strong>stable</strong> — the first half of the record and "
                    f"the second give the same figure, so nothing started during the year "
                    f"— and it is not the Zone 1 leak, which only flows on watering "
                    f"nights. Beyond that the meter cannot help: at one-gallon resolution "
                    f"a steady 0.6 gal/h and a couple of gallons every three hours are the "
                    f"same reading, and only "
                    f"{sum(1 for p_ in hourly.periods for _d, h in p_.by_day.items() for x in (1, 2, 3, 4) if h[x] >= 10)} "
                    f"overnight hours in the year exceed ten gallons, so no appliance "
                    f"cycle stands out to be identified.</p>"
                    f"<p><strong>Which is why it is written down rather than "
                    f"investigated.</strong> A softener regenerating, an RO filter, an ice "
                    f"maker, a fill valve settling — any of them produces this, and the "
                    f"whole thing is "
                    f"{money(evap.intercept * 365 / 1000 * tariff.water_marginal_per_kgal(6000.0))} "
                    f"a year. The number is here so a future export has something to "
                    f"compare against: if it doubles, that is worth a look, and a single "
                    f"night with the pool's float valve shut would settle what it is. "
                    f"Neither is worth doing today.</p>"
                    if evap else ""
                ),
            ),
        ]
        section = Section(
            id="watch",
            emoji="👀",
            title="What to check the next export against",
            lede=(
                "One number here is worth carrying forward as an alarm — and one "
                "real failure that neither it nor anything else on this page would "
                "have caught. Both are worth writing down."
            ),
            blocks=watch_blocks,
            collapsed=True,
            fold_label="Show the threshold, and what it cannot see",
        )
    
    return section
