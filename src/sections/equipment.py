"""The nameplates every derived figure above was checked against.

Transcribed from photographs, and cross-checked arithmetically — the MCA on a
label is derivable from the currents printed beside it.
"""

from __future__ import annotations

from src import costs, equipment, report
from src.analysis import Analysis
from src.house import SYSTEM_GALLONS
from src.prose import spell
from src.report import Callout, Formula, Section, formula, var


def build(data: Analysis) -> Section:
    """The nameplates every derived figure above was checked against."""
    # Everything this section reads from the analysis layer.
    cooling_check = data.cooling_check
    scheduled = data.scheduled

    plate_blocks: list[object] = [
        report.tile_row(
            [
                report.Tile(
                    label=n.role,
                    value=n.headline,
                    detail=(
                        f"{n.maker} {n.model} — {n.detail}"
                        + f"<br>{n.vintage}"
                        + (
                            f"<br>installed {n.installed:%-d %b %Y}"
                            if n.installed else ""
                        )
                    ),
                )
                for n in equipment.TRANSCRIBED
            ]
        ),
        Callout(
            kind="note",
            title="How the house actually heats and cools",
            body=(
                f"<p>The condenser is a <strong>{equipment.CONDENSER.model}</strong> — "
                f"Carrier numbers cooling-only condensers <code>24…</code> and heat pumps "
                f"<code>25…</code>, and its UL block reads <em>central cooling air "
                f"conditioner</em>. So the split is clean: <strong>all central heat is the "
                f"{equipment.FURNACE_INPUT_BTU:,.0f} BTU/h gas furnace, and all central "
                f"cooling is the {equipment.COOLING_TONS:.1f}-ton air conditioner.</strong> "
                f"The only heat pump on the property is the "
                f"{costs.MINISPLIT_BTU:,.0f} BTU/h mini-split serving the patio.</p>"
                f"<p>That matters for reading the winter electric line. The electricity "
                f"that tracks cold is not a heat pump warming the house — it is the "
                f"furnace's own {equipment.FURNACE_BLOWER_WATTS:.0f} W blower, the "
                f"mini-split heating one room, and whatever else a dark cold evening turns "
                f"on. It also explains why the two fuels could not be ranked against each "
                f"other elsewhere on this page: <strong>they were never alternatives for "
                f"the same space.</strong></p>"
            ),
        ),
        Callout(
            kind="finding",
            title=(
                f"The furnace's efficiency is printed on it: "
                f"{equipment.FURNACE_EFFICIENCY:.1%}, within "
                f"{abs(equipment.FURNACE_EFFICIENCY - costs.APPLIANCE_EFFICIENCY) * 100:.1f} "
                f"of a point of the figure assumed for the pool heater"
            ),
            body=(
                f"<p>Every gas-to-heat conversion here runs through an assumed "
                f"{costs.APPLIANCE_EFFICIENCY:.0%} appliance efficiency, and the caveats "
                f"have said all year that a real appliance between 70% and 85% moves those "
                f"figures by about a fifth either way. The furnace label prints both sides "
                f"of that ratio: <strong>{equipment.FURNACE_INPUT_BTU:,.0f} BTU/h in, "
                f"{equipment.FURNACE_OUTPUT_BTU:,.0f} out</strong>. Its efficiency is "
                f"therefore <strong>{equipment.FURNACE_EFFICIENCY:.1%}</strong> — read, "
                f"not guessed.</p>"
                f"<p>The furnace's own conversions use that figure, and the mini-split "
                f"model takes its blower wattage and input rating from the same label — "
                f"{equipment.FURNACE_BLOWER_WATTS:.0f} W and "
                f"{equipment.FURNACE_INPUT_BTU:,.0f} BTU/h.</p>"
                f"<p>The pool heater and water heater labels are both here too, and "
                f"neither prints an efficiency — only an input rating "
                f"({equipment.POOL_HEATER_INPUT_BTU:,.0f} and "
                f"{equipment.WATER_HEATER_INPUT_BTU:,.0f} BTU/h). So the assumed figure now "
                f"has exactly one job left: converting the pool heater's gas into heat in "
                f"the water. The water heater never needed it — its share of the meter is "
                f"counted as cubic feet and priced directly, with no conversion in "
                f"between.</p>"
                f"<p>That the one appliance with a printed efficiency was guessed correctly is the "
                f"only independent reason to think {costs.APPLIANCE_EFFICIENCY:.0%} is "
                f"fair for the pool heater as well. It is weak evidence, but it is more "
                f"than the figure had before.</p>"
            ),
        ),
    ]
    plate_blocks.append(formula(Formula(
        caption="A nameplate that checks its own transcription (NEC 440.33)",
        lhs=var("MCA"),
        rhs=f'1.25 · {var("RLA")} + {var("FLA")}',
        where=[
            (var("RLA"), f"compressor rated-load amps, {equipment.COMPRESSOR_RLA:.1f} A"),
            (var("FLA"), f"condenser fan full-load amps, "
                         f"{equipment.CONDENSER_FAN_FLA:.1f} A"),
            (var("MCA"), f"computes to {equipment.minimum_circuit_amps():.2f} A against "
                         f"the {equipment.NAMEPLATE_MCA:.1f} A printed"),
        ],
        note="The largest motor is taken at 125%, the rest at nameplate. Reproducing the "
             "printed figure from the printed currents tests the typing, not the "
             "equipment — and the build refuses to run if it stops agreeing.",
    )))
    if cooling_check:
        plate_blocks.append(
            Callout(
                kind="finding",
                title=(
                    f"The air conditioner runs at {cooling_check.load_factor:.0%} of "
                    f"what its label allows"
                ),
                body=(
                    f"<p>The same trick that identified the pool pump works on the air "
                    f"conditioner: take the median load profile of the "
                    f"{cooling_check.hot_days} hottest days of the year (mean high "
                    f"{cooling_check.hot_max_f:.0f}°F) and subtract the median profile of "
                    f"{cooling_check.mild_days} mild ones. Everything that ignores the "
                    f"weather cancels — the pool pump runs the same 15:15 block on both "
                    f"kinds of day — and what is left is cooling.</p>"
                    f"<p>It comes to <strong>{cooling_check.measured_kw:.2f} kW</strong> "
                    f"sustained through the afternoon, peaking at "
                    f"{cooling_check.peak_hour:02d}:00. The label allows "
                    f"{cooling_check.rated_kw:.2f} kW — compressor at its rated "
                    f"{equipment.COMPRESSOR_RLA:.1f} A plus the condenser fan, at "
                    f"{equipment.NAMEPLATE_VOLTS:.0f} V, at an assumed power factor of "
                    f"{equipment.ASSUMED_POWER_FACTOR:.2f}. That last figure is the only "
                    f"one here not printed on the label, and it matters: at unity the "
                    f"ceiling would be "
                    f"{equipment.rated_draw_kw(1.0):.2f} kW and the ratio below would read "
                    f"{cooling_check.measured_kw / equipment.rated_draw_kw(1.0):.0%} instead. "
                    f"Measured against rated is "
                    f"<strong>{cooling_check.load_factor:.0%}</strong>, which is where a "
                    f"compressor should sit on the hottest days of its year: rated load "
                    f"amps is a ceiling, not an operating point.</p>"
                    f"<p>Two further things fall out. On those same days the unit ran about "
                    f"<strong>{cooling_check.runtime_fraction:.0%} of the twenty-four "
                    f"hours</strong> — so at 106°F it is still cycling rather than running "
                    f"flat out, and {equipment.COOLING_TONS:.1f} tons is enough for this "
                    f"house. And overnight the hot-day premium collapses to "
                    f"{cooling_check.overnight_kw:.2f} kW: once the sun is down the house "
                    f"coasts, which is the same envelope the zone section measured from the "
                    f"other side.</p>"
                    f"<p>As a check on the transcription rather than the equipment, the "
                    f"minimum circuit ampacity computes from the currents printed beside it "
                    f"— 1.25 × {equipment.COMPRESSOR_RLA:.1f} + "
                    f"{equipment.CONDENSER_FAN_FLA:.1f} = "
                    f"{equipment.minimum_circuit_amps():.1f} A against the "
                    f"{equipment.NAMEPLATE_MCA:.1f} A printed. The build refuses to run if "
                    f"that stops being true.</p>"
                ),
            )
        )
    heater_duty = equipment.heater_duty_cycle(costs.POOL_HEATER_BTU_PER_HOUR)
    plate_blocks.append(
        Callout(
            kind="finding",
            title=(
                f"The pool heater's rating checks a number this page worked out, "
                f"rather than one it assumed"
            ),
            body=(
                f"<p>Most of what a label settles here is an assumption. This one tests a "
                f"<em>derivation</em>. The spa's volume was inferred from how fast the "
                f"heater raised it, which needed the heater's burn rate — and that was "
                f"reverse-engineered from the October ramp at "
                f"<strong>{costs.POOL_HEATER_BTU_PER_HOUR:,.0f} BTU/h</strong>, with no way "
                f"to check it. The label reads "
                f"<strong>{equipment.POOL_HEATER_INPUT_BTU:,.0f} BTU/h</strong>.</p>"
                f"<p>The derived figure is <strong>{heater_duty:.0%}</strong> of the rated "
                f"one, and that is the right shape of answer. A burner cannot beat its own "
                f"input rating, so the test is one-sided: anything from 0 to 100% is "
                f"consistent and only a figure above 100% would mean the ramp analysis was "
                f"broken. What the remaining {1 - heater_duty:.0%} represents is the part "
                f"of the window the burner was not lit — purge and ignition at the start, "
                f"and cycling as the water approaches setpoint.</p>"
                f"<p>The spa volume keeps the derived rate rather than the nameplate, and "
                f"deliberately so: the ramp needs the <em>average</em> rate actually "
                f"delivered across the window, and substituting the nameplate would assume "
                f"continuous firing and inflate the spa by about "
                f"{1 / heater_duty - 1:.0%}. The label's job here was to bound the "
                f"derivation, and it does.</p>"
                f"<p>Note what the label does <em>not</em> give: an efficiency. Only the "
                f"input rating is printed, so the pool heater stays on the assumed "
                f"{costs.APPLIANCE_EFFICIENCY:.0%} along with the water heater.</p>"
            ),
        )
    )
    plate_blocks.append(
        Callout(
            kind="finding",
            title=f"The filter puts a ceiling on the pump's flow, and the pool conclusion survives it",
            body=(
                f"<p>Pump flow has been the other load-bearing guess on this page — "
                f"{costs.PUMP_FLOW_GPM:.0f} GPM, assumed, with turnover counts scaling "
                f"inversely with it. The filter is a "
                f"<strong>{equipment.POOL_FILTER.maker} {equipment.POOL_FILTER.model}</strong>, "
                f"{equipment.FILTER_AREA_SQFT:.0f} ft² of DE rated at "
                f"<strong>{equipment.FILTER_MAX_GPM_PRIVATE:.0f} GPM</strong> for a private "
                f"pool. That is a design ceiling, not a measurement — but a ceiling is "
                f"exactly what an open-ended assumption was missing.</p>"
                f"<p>At the assumed {costs.PUMP_FLOW_GPM:.0f} GPM the pump turns the water "
                f"over {scheduled.hours * 60 * costs.PUMP_FLOW_GPM / SYSTEM_GALLONS:.1f} "
                f"times a day. Push it all the way to the filter's rating and it becomes "
                f"{scheduled.hours * 60 * equipment.FILTER_MAX_GPM_PRIVATE / SYSTEM_GALLONS:.1f}. "
                f"<strong>Every value the plumbing admits leaves the pump running several "
                f"times the one-to-two turnovers that is standard</strong>, so the "
                f"recommendation to cut the runtime does not depend on the guess at all — "
                f"only the precise saving does.</p>"
                f"<p>The pump carries two labels because it is two parts. The wet end is a "
                f"<strong>{equipment.POOL_PUMP.maker} "
                f"{equipment.POOL_PUMP.model}</strong>, a 1 HP Max-E-Pro; the A.O. Smith "
                f"SQ1102 whose nameplate predicted the measured 1.65 kW is the square-flange "
                f"motor bolted to it. One pump, two labels — and the power prediction stands "
                f"either way, because it was the motor that did the predicting.</p>"
            ),
        )
    )
    section = (
        Section(
            id="equipment",
            emoji="🏷️",
            title="What the labels say",
            lede=(
                f"{len(equipment.TRANSCRIBED)} nameplates, read off the machines "
                "and typed in by hand — the one source here with no file behind it. "
                "They settle one "
                "assumption, correct another outright, and give the meters something to "
                "be checked against."
            ),
            blocks=plate_blocks,
            collapsed=True,
            fold_label=(f"Show the {spell(len(equipment.TRANSCRIBED))} nameplates "
                        f"and what they settle"),
        )
    )


    return section
