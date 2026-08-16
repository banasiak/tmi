"""Where the money actually went, ranked.

Every figure priced from the transcribed tariffs rather than a bill total, so
the ranking survives a rate change.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from src import charts, costs, tariff
from src.analysis import Analysis
from src.prose import money, spell
from src.report import Callout, Section


def build(data: Analysis) -> Section:
    """Where the money actually went, ranked."""
    # Everything this section reads from the analysis layer.
    baseload = data.baseload
    cool_cost = data.cool_cost
    cool_kwh = data.cool_kwh
    evap_cost = data.evap_cost
    evap_volume = data.evap_volume
    fault = data.fault
    fixed_other = data.fixed_other
    floor_cost = data.floor_cost
    gas_cost = data.gas_cost
    gas_split = data.gas_split
    heat_elec_cost = data.heat_elec_cost
    heat_kwh = data.heat_kwh
    household_cost = data.household_cost
    irr_cost = data.irr_cost
    irr_volume = data.irr_volume
    leak_cost = data.leak_cost
    leak_volume = data.leak_volume
    minisplit = data.minisplit
    pump_cost = data.pump_cost
    refill_volume = data.refill_volume
    refill_water_cost = data.refill_water_cost
    scheduled = data.scheduled
    total_cost = data.total_cost
    water_cost = data.water_cost

    summer_rate = tariff.marginal_rate(dt.date(2026, 7, 15))
    winter_rate = tariff.marginal_rate(dt.date(2026, 1, 15))
    tier1_rate = tariff.marginal_rate(dt.date(2026, 7, 15), above_tier=False)
    
    
    ranked = sorted(
        [
            ("Always-on floor", floor_cost, "electric",
             f"{baseload.median_kw:.2f} kW that never switches off"),
            ("Cooling", cool_cost, "electric",
             f"{cool_kwh:,.0f} kWh — main HVAC plus about {minisplit.cooling_share:.0%} "
             f"from the patio mini-split" if minisplit else f"{cool_kwh:,.0f} kWh"),
            ("Pool pump", pump_cost, "electric",
             f"{scheduled.annual_kwh:,.0f} kWh on a {scheduled.hours:.2f} h timer"),
            ("Gas access fee", gas_split.fixed_access, "gas",
             f"${tariff.GAS_ACCESS_FEE:.2f}/month before a single cubic foot"),
            ("Wastewater + refuse", fixed_other, "water",
             f"wastewater is tiered on an allowance re-set yearly; refuse is flat"),
            ("Space heating, electric", heat_elec_cost, "electric",
             f"{heat_kwh:,.0f} kWh — {minisplit.heating_share:.0%} of it the mini-split, "
             f"only {minisplit.blower_kwh:.0f} kWh the furnace blower"
             if minisplit else f"{heat_kwh:,.0f} kWh"),
            ("Water heating + cooking", gas_split.water_heater_cost, "gas",
             f"{gas_split.water_heater_cf:,.0f} cf standing baseline"),
            ("Irrigation", irr_cost, "water",
             f"{irr_volume:,.0f} gal the controller meant to deliver"),
            ("Pool evaporation", evap_cost, "water",
             f"{evap_volume:,.0f} gal the float valve replaced, unasked"),
            ("Zone 1 leak", leak_cost, "water",
             f"{leak_volume:,.0f} gal since {fault.break_date:%-d %B} and still rising"
             if fault else f"{leak_volume:,.0f} gal"),
            ("Pool refill (one-off)", refill_water_cost, "water",
             f"{refill_volume:,.0f} gal over two days in March — not an annual cost"),
            ("Space heating, gas", gas_split.space_heating_cost, "gas",
             f"{gas_split.space_heating_cf:,.0f} cf — the furnace alone"),
            ("Pool + spa heating", gas_split.pool_spa_cost, "gas",
             f"{gas_split.pool_spa_cf:,.0f} cf on days with no heating demand"),
        ],
        key=lambda r: -r[1],
    )
    # The chart is titled with the household total, so it has to sum to it, and
    # the identified loads leave a residue. That residue is not one thing: it is
    # a separate gap on each meter, and it used to be charted as a single bar
    # painted water-green while its own caption talked about vehicle charging.
    # Colour on this chart means the meter, so a bar that spans three of them is
    # the one thing it must not draw. Split per stream instead — each gap then
    # has a real meter behind it, and the size of each says how much of that
    # utility the rest of this page failed to account for.
    identified = defaultdict(float)
    for _, amount, stream, _ in ranked:
        identified[stream] += amount
    stream_total = {
        "electric": total_cost,
        "gas": gas_cost,
        # Wastewater and refuse arrive on the city bill alongside the water
        # commodity, and are already itemised above.
        "water": water_cost + fixed_other,
    }
    for stream, label, detail in (
        ("electric", "Other electricity",
         "every electric load too small or too irregular to separate from the "
         "meter — vehicle charging among them, plus the customer charge no load "
         "can shed"),
        ("water", "Other water",
         "indoor use — showers, laundry, dishes, the tap. Metered, never "
         "separately, so it is a remainder rather than a measurement"),
        ("gas", "Other gas",
         "what the heating signature could not assign to space heating, the "
         "water heater or the pool"),
    ):
        gap = stream_total[stream] - identified[stream]
        # Below a dollar this is rounding in the tariff arithmetic, not a load.
        if gap >= 1.0:
            ranked.append((label, gap, stream, detail))
    ranked.sort(key=lambda r: -r[1])
    

    cost_blocks: list[object] = [
        Callout(
            kind="finding",
            title="Use the marginal rate, never the average",
            body=(
                f"<p>Every load on this page sits on top of the others, so removing one "
                f"saves the <em>top</em> rate you pay, not the blended one. Those rates are "
                f"far apart:</p>"
                f"<ul>"
                f"<li>Summer electricity above the {tariff.SUMMER_TIER_KWH} kWh tier: "
                f"<strong>${summer_rate:.4f}/kWh</strong></li>"
                f"<li>Summer electricity, first {tariff.SUMMER_TIER_KWH} kWh: "
                f"${tier1_rate:.4f}/kWh</li>"
                f"<li>Winter electricity: <strong>${winter_rate:.4f}/kWh</strong></li>"
                f"<li>Gas: ${tariff.gas_marginal_per_kcf(dt.date(2026, 1, 15)) / 1000:.5f}/cf in "
                f"winter, ${tariff.gas_marginal_per_kcf(dt.date(2026, 7, 16)) / 1000:.5f} in "
                f"summer — the commodity charge is a pass-through and moves with the market</li>"
                f"<li>Water above the free allowance: "
                f"${tariff.water_marginal_per_kgal(4000):.2f} per 1,000 gal all-in — the "
                f"${tariff.WATER_RATE_PER_KGAL:.2f} commodity rate plus the franchise fee and "
                f"tax that ride on it. The first "
                f"{tariff.WATER_TIERS[0][0]:,.0f} gallons each month cost nothing</li>"
                f"</ul>"
                f"<p>A summer kilowatt-hour costs "
                f"<strong>{summer_rate / winter_rate:.2f}×</strong> a winter one. Every dollar "
                f"below is computed at whichever rate applied on the day.</p>"
            ),
        ),
        charts.ranked_bars(
            "cost-rank",
            "Where the money goes",
            f"Every line recomputed from the transcribed tariffs, priced at the rate that "
            f"applied on the day. {money(household_cost)} in total.",
            ranked,
            note=(
                # The colour is the argument: two electric bars at the top, and the
                # third-longest bar a stream nothing you do can move.
                f"Color is the meter, not the category. The top of this chart is "
                f"{spell(sum(1 for r in ranked[:2] if r[2] == 'electric'))} electric bars, "
                f"and the third is the one stream that answers to nothing you do. "
                f"The three <em>Other</em> bars are each meter's own remainder — what it "
                f"measured that the rest of this page could not assign to a named load. "
                f"They are split by meter rather than pooled, because a single bar "
                f"spanning three of them would be the one thing this chart's colors "
                f"cannot say."
            ),
            legend=[
                ("var(--stream-electric)", "Electricity"),
                ("var(--stream-gas)", "Natural gas"),
                ("var(--stream-water)", "Water, wastewater and refuse"),
            ],
        ),
        Callout(
            kind="note",
            title="What that ordering says",
            body=(
                # Named from the sorted table rather than asserted. "The three largest
                # items are all electricity" had stopped being true — wastewater and
                # refuse sit third.
                f"<p>The ordering is the point. The two largest items — "
                f"{charts.esc(ranked[0][0].lower())} and {charts.esc(ranked[1][0].lower())} — "
                f"are both electricity and between them are "
                f"{(ranked[0][1] + ranked[1][1]) / household_cost:.0%} of the bill, and the "
                f"third, wastewater and refuse, is the one line here that responds to nothing "
                f"you do at all. Everything gas-fired "
                f"combined — heating the house, heating the water, heating the pool — comes to "
                f"{money(gas_split.space_heating_cost + gas_split.water_heater_cost + gas_split.pool_spa_cost)}, "
                f"less than the {money(gas_split.fixed_access)} you pay just to have a gas meter.</p>"
            ),
        ),
        Callout(
            kind="note",
            title="The patio is a third conditioned zone, and it pays its own way",
            body=(
                f"<p>The house is not one thermal zone. The enclosed patio has its own "
                f"mini-split — a 12,000 BTU/h Premium Levella heat pump, "
                f"{costs.MINISPLIT_MAX_KW:.2f} kW at full draw — and neither of the two "
                f"lines above is wholly the central system. Its share is recoverable "
                f"without a submeter: the furnace's own gas consumption fixes how many "
                f"hours it ran, which fixes its blower energy at about "
                f"<strong>{minisplit.blower_kwh:.0f} kWh</strong>, so the remaining "
                f"<strong>{minisplit.heating_kwh:,.0f} kWh</strong> of the cold-weather "
                f"line has to be the mini-split — and the heat-loss coefficient that "
                f"implies prices its cooling season at {minisplit.cooling_kwh:,.0f} kWh, "
                f"{minisplit.cooling_share:.0%} of the cooling line.</p>"
                f"<p><strong>Total: {minisplit.total_kwh:,.0f} kWh, roughly "
                f"{money(minisplit.cost)} a year.</strong> The heating line is almost "
                f"entirely this unit; the cooling line is mostly the main system. How that "
                f"zone actually behaves — its glazing, what the low-E coating costs and "
                f"saves, and why a 12,000 BTU/h unit is five times the size it needs to "
                f"be — is measured alongside the other three buildings in "
                f"<a href=\"#zones\">Four boxes in the same weather</a>.</p>"
            ),
        ),
    ]
    
    section = (
        Section(
            id="costs",
            emoji="💵",
            title="What things cost",
            lede=(
                "Every figure here is recomputed from the transcribed tariffs on each build, "
                "and priced at the rate that actually applied on the day."
            ),
            blocks=cost_blocks,
        )
    )
    
    return section
