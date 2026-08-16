"""The system that crosses all three meters.

Volume settled from four instruments, the pump schedule confirmed, evaporation
fitted, and one complete drain and refill measured directly.
"""

from __future__ import annotations

import datetime as dt
import statistics

from src import charts, costs, equipment, model, tariff
from src.analysis import Analysis
from src.house import SPA_GALLONS, SYSTEM_GALLONS
from src.prose import money, spell
from src.report import Callout, Formula, Section, formula, frac, var


def build(data: Analysis) -> Section | None:
    """The system that crosses all three meters."""
    # Everything this section reads from the analysis layer.
    days = data.days
    evap = data.evap
    hourly = data.hourly
    pump_proof = data.pump_proof
    refill_gallons = data.refill_gallons
    refill_gas = data.refill_gas
    refill_lower_bound = data.refill_lower_bound
    refill_water = data.refill_water
    scheduled = data.scheduled
    slot_delta = data.slot_delta
    slot_solar = data.slot_solar
    spa_rate = data.spa_rate
    system_cf = data.system_cf
    system_summer = data.system_summer
    system_winter = data.system_winter
    water_events = data.water_events
    section: Section | None = None

    pool_blocks: list[object] = []
    
    if pump_proof:
        pool_blocks.append(
            Callout(
                kind="finding",
                title="Two unrelated instruments agree on the same timestamp",
                body=(
                    f"<p>The electricity meter says a 1.65 kW block switches on at "
                    f"<strong>{pump_proof.clock}</strong>. A thermometer in the pool says "
                    f"the water temperature jumps at <strong>{pump_proof.clock}</strong> — "
                    f"<strong>{pump_proof.step_rate:+.4f}°F per 5 minutes, "
                    f"{pump_proof.ratio:.1f}× the rate in the slots either side</strong>.</p>"
                    f"<p>Nothing in the environment can account for it. Across that same "
                    f"moment solar radiation is <em>falling</em> "
                    f"({pump_proof.solar_before:.0f} → {pump_proof.solar_after:.0f} W/m²) "
                    f"and outdoor temperature is <em>falling</em> too "
                    f"({pump_proof.outdoor_trend:+.4f}°F per sample). The sun is going down "
                    f"and the air is cooling, and the water gets warmer anyway — because a "
                    f"pump started moving it past the probe. At 22:00 the water's cooling "
                    f"rate abruptly flattens as the circulation stops.</p>"
                    f"<p>This is what upgrades the timer block from a plausible guess to a "
                    f"measurement. The pump is <strong>{scheduled.share_of_total:.0%} of the "
                    f"electricity this house uses</strong>.</p>"
                ),
            )
        )
    
    if slot_delta and slot_solar:
        load_profile = model.median_profile(days)
        pool_blocks.append(
            charts.profile_panels(
                "pump-step",
                "The moment the pump starts, seen three ways",
                "Every 5-minute sample of the year, averaged by time of day.",
                [
                    charts.SlotPanel(
                        "Water temperature, rate of change",
                        "°F / 5 min",
                        "var(--zone-accent)",
                        slot_delta,
                        zero_line=True,
                    ),
                    charts.SlotPanel(
                        "Household electrical load",
                        "kW",
                        "var(--stream-electric)",
                        load_profile,
                    ),
                    charts.SlotPanel(
                        "Solar radiation",
                        "W/m²",
                        "var(--solar-accent)",
                        slot_solar,
                    ),
                ],
                highlight=(scheduled.start_slot, scheduled.end_slot, "pump running")
                if scheduled
                else None,
                note=(
                    "Read the three panels down the same vertical line. The water spikes at "
                    "the exact quarter-hour the load steps up, while the sun is already on "
                    "its way down. Correlation this sharp, across sensors that share no "
                    "wiring, is about as close to proof as a house gets."
                ),
            )
        )
    
    if water_events:
        spa = [e for e in water_events if e.kind == "spa"]
        dry = [e for e in water_events if e.kind == "dry"]
        heated = [e for e in water_events if e.kind == "heater"]
        drained = [e for e in dry if e.date in (dt.date(2026, 3, 29), dt.date(2026, 3, 30))]
        # The alert fires at 110F, so excursions that reach it get fixed and
        # those that fall short do not — a split worth measuring.
        dry_alerted = [e for e in dry if e.peak_f >= 110.0]
        dry_quiet = [e for e in dry if e.peak_f < 110.0]
        pool_blocks.append(
            Callout(
                kind="finding",
                title="Spa or dry probe — the sun tells them apart",
                body=(
                    f"<p>The probe reads above 100°F on {len(water_events)} days, which pool "
                    f"water never does. {spell(len({e.kind for e in water_events})).capitalize()} "
                    f"different things cause it, and they separate cleanly on when they "
                    f"happen and on what the gas meter was doing at the time.</p>"
                    f"<p><strong>{len(spa)} are spa soaks.</strong> They peak after dark — "
                    f"zero solar — alongside a large gas draw, and they top out at "
                    f"{', '.join(f'{e.peak_f:.1f}' for e in spa)}°F. The heater is set to "
                    f"110°F and the alert is set to the same number, so the ceiling is both "
                    f"the thermostat arriving and the phone buzzing.</p>"
                    f"<p>The probe is lifted out of the pool and dropped into the spa while it "
                    f"heats, which the record shows plainly: a reading flat to a tenth of a "
                    f"degree for half an hour, then a single-sample step of "
                    f"{', '.join(f'+{e.step_f:.0f}' for e in sorted(spa, key=lambda e: e.date))}°F "
                    f"respectively, then a clean linear climb. It stays in the spa overnight and has "
                    f"equalised with the pool by morning — which is what lets the "
                    f"morning-anchored energy balance elsewhere on this page still work.</p>"
                    f"<p><strong>{len(dry)} are the probe out of the water and genuinely "
                    f"baking.</strong> They peak in the afternoon under "
                    f"{min(e.solar_at_peak for e in dry):.0f}–"
                    f"{max(e.solar_at_peak for e in dry):.0f} W/m² of sun while the "
                    f"gas meter stays idle — nothing is being heated, so the probe is out in "
                    f"the air rather than in the water.</p>"
                    + (
                        f"<p>The alert threshold shows up in how long each one lasts. The "
                        f"{len(dry_alerted)} that climbed past 110°F set the phone off and were "
                        f"back in the water within a mean of "
                        f"{statistics.fmean(e.minutes_hot for e in dry_alerted):.0f} minutes. The "
                        f"{len(dry_quiet)} that stopped short of it raised no alarm and sat out "
                        f"for {statistics.fmean(e.minutes_hot for e in dry_quiet):.0f} minutes on "
                        f"average — the worst reaching {max(e.peak_f for e in dry_quiet):.1f}°F, "
                        f"a tenth of a degree below the trigger, and going unnoticed for "
                        f"{max(e.minutes_hot for e in dry_quiet) / 60:.1f} hours. A threshold "
                        f"visible in the data purely through what it failed to catch.</p>"
                        if dry_alerted and dry_quiet
                        else ""
                    )
                    + (
                        f"<p><strong>{spell(len(drained)).capitalize()} of those "
                        f"{len(dry)} is not an accident.</strong> "
                        f"{', '.join(f'{e.date:%-d %B}' for e in drained)} is the hottest "
                        f"reading of the year at "
                        f"{max(e.peak_f for e in drained):.1f}°F, and the probe was where it "
                        f"had always been — the pool was not. That day is dealt with below.</p>"
                        if drained
                        else ""
                    )
                    + (
                        f"<p><strong>{spell(len(heated)).capitalize()} is the pool heater "
                        f"simply running.</strong> "
                        f"{', '.join(f'{e.date:%-d %B %Y}' for e in heated)} peaks at "
                        f"{max(e.peak_f for e in heated):.1f}°F in the afternoon with "
                        f"{max(e.gas_cf for e in heated):,.0f} cf on the gas meter — sun and "
                        f"gas together, which is neither of the other two patterns. It is the "
                        f"one excursion where the reading is the water's real temperature.</p>"
                        if heated
                        else ""
                    )
                ),
            )
        )
        # Three patterns, not two, and the third is defined by sitting between
        # the other two on *both* axes — the one thing a table of ten rows cannot
        # show at a glance and a 2D plot can. That is what earns the form here.
        # There is no third variable worth encoding as size: peak temperature
        # does not discriminate (spa 110.7-110.8, dry 102.2-111.6, heater 106.7),
        # so a bubble would draw a signal that is not in the data.
        pool_blocks.append(
            charts.scatter(
                "probe-classes",
                "Three ways for a pool probe to read above 100°F",
                "Every excursion, placed by the sun at its peak and the gas burned "
                "that day.",
                [
                    (
                        e.solar_at_peak,
                        e.gas_cf,
                        f"{e.date:%a %-d %b %Y}: {e.peak_f:.1f}°F, {e.window}",
                    )
                    for e in water_events
                ],
                # Probe readings, not metered water. One series: the three groups
                # are named in place, so position and labels carry it, not hue.
                "var(--ink-secondary)",
                "Solar at the peak reading (W/m²)",
                "Gas that day (cf)",
                annotations=(
                    [
                        (
                            statistics.fmean([e.solar_at_peak for e in spa]) + 40,
                            statistics.fmean([e.gas_cf for e in spa]),
                            "spa soaks — after dark, heater lit",
                        ),
                        (
                            max(e.solar_at_peak for e in dry),
                            statistics.fmean([e.gas_cf for e in dry]) + 30,
                            "probe out of the water — midday sun, gas idle",
                        ),
                    ]
                    + [
                        (
                            heated[0].solar_at_peak + 40,
                            heated[0].gas_cf + 25,
                            "heater running — sun and gas together",
                        )
                        for _ in heated[:1]
                    ]
                    if spa and dry
                    else None
                ),
                x_zero=True,
                note=(
                    f"A soak burns "
                    f"{statistics.fmean([e.gas_cf for e in spa]) / max(statistics.fmean([e.gas_cf for e in dry]), 1):.0f}× "
                    f"the gas of a dry-probe day at none of the sun, which is what makes "
                    f"those two a reading rather than a judgement call."
                    + (
                        f" The point between them is the one that matters: "
                        f"{heated[0].date:%-d %B %Y} has sun <em>and</em> gas, and is the "
                        f"one excursion where the probe was reporting the water's real "
                        f"temperature."
                        if heated else ""
                    )
                    if spa and dry else ""
                ),
            )
        )
    
    march = [d for d in days if dt.date(2026, 3, 27) <= d.date <= dt.date(2026, 4, 7)]
    if march:
        cells = []
        for d in march:
            ev = next((e for e in water_events if e.date == d.date), None)
            note = {
                "dry": "probe dry — pool drained",
                "spa": "spa soak",
                "heater": "heater running",
            }.get(ev.kind if ev else "", "")
            cells.append(
                f"<tr><td>{d.date:%a %-d %b}</td>"
                f"<td>{d.water_gal:,.0f}</td><td>{d.gas_cf:,.0f}</td>"
                f"<td>{f'{d.kwh:,.0f}' if d.kwh is not None else '—'}</td>"
                f"<td>{note}</td></tr>"
            )
        pool_blocks.append(
            Callout(
                kind="caution",
                title="29–30 March: the pool was drained and refilled",
                body=(
                    "<p>The 5,229-gallon event that opened this investigation is a service "
                    "visit, and the three meters narrate it between them:</p>"
                    "<p><strong>Sunday 29th</strong> — the probe hits 120.2°F in full "
                    "afternoon sun starting at 15:15, the exact minute the pump switches on. "
                    "The pump started and found no water. Pump-window consumption falls to "
                    "19.4 kWh, the lowest in weeks: you do not run a pump on a draining pool. "
                    "2,192 gallons go back in.</p>"
                    "<p><strong>Monday 30th</strong> — 3,036 more gallons, and the probe is "
                    "submerged again. The daily meter splits the same two days 1,922 and "
                    "3,307; the hourly one moves 270 gallons from Monday to Sunday and "
                    "totals the same. Where the two granularities disagree the finer one is "
                    "closer, and here it is also the one that can say the fill ran through "
                    "midnight.</p>"
                    "<p><strong>Tuesday 31st, then 4–6 April</strong> — 2,088 cf of gas, "
                    "bringing cold fresh water up to temperature. That single stretch is "
                    "11% of the year's gas.</p>"
                    "<p>The heating events also size the equipment. On 4 October the water "
                    "climbed 5.45°F/hour while the heater burned 879 cf over the ramp — "
                    f"{costs.POOL_HEATER_BTU_PER_HOUR:,.0f} BTU/h of gas going in, against "
                    f"the {equipment.POOL_HEATER.headline} input rating its label turned out "
                    f"to carry. Both are input rates, which is the only way the two are "
                    f"comparable; at the assumed 80% that ramp put about "
                    f"{costs.POOL_HEATER_BTU_PER_HOUR * costs.APPLIANCE_EFFICIENCY:,.0f} BTU/h "
                    f"into the water. Working "
                    "back from that rate gives a system volume near 4,750 gallons, "
                    "consistent with the 5,229 gallons the meter billed across the two days — "
                    + (
                        f"and with the {hourly.refill_net:,.0f} the hourly register later "
                        f"measured going in once the household's own use is taken back out"
                        if hourly and hourly.refill_net
                        else "and with the hourly register's own measurement of the refill"
                    )
                    + ".</p>"
                    "<p><strong>5,229 gallons is the entire system.</strong> Pool and spa "
                    "together hold about 5,000 gallons, so this was a complete drain and "
                    "refill, not a top-up — routine maintenance on water as hard as Las "
                    "Cruces'. That also explains the gas: 2,088 cf went into bringing a "
                    "full body of cold city water up to temperature from scratch, which is "
                    "why the reheat took three separate days.</p>"
                    # Priced from the same tariff call the cost section uses, rather
                    # than typed in — the March and April commodity rates turned out
                    # unusually low, and a hard-coded figure went stale silently.
                    f"<p>The whole episode cost roughly {money(refill_water)} in water and "
                    f"{money(refill_gas)} in gas: "
                    "operationally dramatic, financially trivial. Worth knowing before "
                    "chasing it.</p>"
                    '<div class="table-scroll"><table><thead><tr><th>Day</th>'
                    "<th>Water (gal)</th><th>Gas (cf)</th><th>Electric (kWh)</th>"
                    f"<th>Probe</th></tr></thead><tbody>{''.join(cells)}</tbody></table></div>"
                ),
            )
        )
    
    # How big is the pool? Four instruments, one number — the volume everything
    # else hangs from, so it leads the pool section rather than trailing it.
    volume_blocks: list[object] = []
    if evap and hourly and hourly.refill_net:
        volume_blocks.extend([
                    Callout(
                        kind="note",
                        title="Four instruments, none of which share a wire",
                        body=(
                            f"<p>The pool is on no drawing anyone kept, so its volume has "
                            f"to be inferred. Four separate chains do it, and the useful "
                            f"part is that they fail differently: a mistake in one has no "
                            f"way to propagate into the others.</p>"
                            + '<div class="table-scroll"><table><thead><tr>'
                            '<th>What measured it</th><th>How</th>'
                            '<th>Answer</th></tr></thead><tbody>'
                            f"<tr><td>Water meter, daily</td>"
                            f"<td>the March drain and refill, net of a normal day's use</td>"
                            f"<td>{refill_gallons:,.0f} gal</td></tr>"
                            f"<tr><td>Water meter, hourly</td>"
                            f"<td>the same refill, hour by hour, against a measured "
                            f"overnight baseline</td>"
                            f"<td>{hourly.refill_net:,.0f} gal</td></tr>"
                            f"<tr><td>Gas meter + pool thermometer</td>"
                            f"<td>how fast {costs.POOL_HEATER_BTU_PER_HOUR:,.0f} BTU/h "
                            f"raised the water on 4 October</td>"
                            f"<td>~4,750 gal</td></tr>"
                            f"<tr><td>Electricity meter + pool thermometer</td>"
                            f"<td>the pump's own step, which fixes when circulation "
                            f"starts but not how much water it moves</td>"
                            f"<td>turnover count only</td></tr>"
                            "</tbody></table></div>"
                            f"<p>The first three agree to "
                            f"{max(refill_gallons, hourly.refill_net, 4750) / min(refill_gallons, hourly.refill_net, 4750) - 1:.0%}. "
                            f"This page uses <strong>{SYSTEM_GALLONS:,.0f} gallons</strong> "
                            f"for pool and spa together, which is the refill rounded — and "
                            f"the refill is only the system volume if the drain emptied it, "
                            f"which is the owner's account rather than anything measured. "
                            f"That caveat is the one real weakness in the chain.</p>"
                        ),
                    ),
                    Callout(
                        kind="note",
                        title="What that volume costs to heat, and to replace",
                        body=(
                            f"<p>Two figures follow directly from the number above, and "
                            f"they are the ones worth carrying away from this section.</p>"
                            f"<p><strong>One degree costs {system_cf:.1f} cf of gas</strong> "
                            f"— {money(system_winter)} at January's rate, "
                            f"{money(system_summer)} at July's, for the "
                            f"{SYSTEM_GALLONS:,.0f} gallons of pool and spa together. "
                            f"Every heating question on this page reduces to that number "
                            f"multiplied by a temperature difference and a number of days, "
                            f"which is why it is worth stating once and plainly. The two "
                            f"rates differ only because gas is priced seasonally; the "
                            f"physics does not change.</p>"
                            f"<p><strong>A complete drain and refill costs about "
                            f"{money(refill_water + refill_gas)}</strong> — "
                            f"{money(refill_water)} of water for {refill_gallons:,.0f} "
                            f"gallons, plus {money(refill_gas)} of gas to bring it back up "
                            f"to temperature from cold city supply."
                            + (
                                " That month exceeded the highest water tier the bills "
                                "reveal, so treat the water half as a floor rather than a "
                                "quote."
                                if refill_lower_bound
                                else ""
                            )
                            + f"</p>"
                            + (
                                f"<p>One more measurement belongs here, because it sizes "
                                f"the <em>spa</em> rather than the whole system and does it "
                                f"without any energy accounting at all. The probe is dropped "
                                f"in at the bottom of a soak's heat-up, so the rise is clean "
                                f"and linear — "
                                f"{', '.join(f'{s.rate_f_per_hour:.0f}' for s in spa_rate)}°F "
                                f"an hour across three evenings. Inverting that against the "
                                f"heater's "
                                f"{costs.POOL_HEATER_BTU_PER_HOUR / 1000:.0f}k BTU/h input — "
                                f"{costs.POOL_HEATER_BTU_PER_HOUR * costs.APPLIANCE_EFFICIENCY / 1000:.0f}k "
                                f"of it reaching the water at the assumed "
                                f"{costs.APPLIANCE_EFFICIENCY:.0%} — gives "
                                f"<strong>{statistics.median([s.gallons for s in spa_rate]):,.0f} "
                                f"gallons</strong>, against the {SPA_GALLONS:,.0f} this page "
                                f"uses. Two methods on different assumptions, agreeing to "
                                f"within 15%, and the rate method needs neither a starting "
                                f"temperature nor any accounting for gas that went to the "
                                f"pool. It is what {SPA_GALLONS:,.0f} rests on.</p>"
                                if spa_rate
                                else ""
                            )
                        ),
                    ),
                    formula(Formula(
                        caption="Why one degree costs what it costs",
                        lhs=var("V", "cf"),
                        rhs=frac(
                            var("V") + ' · &rho; · &Delta;' + var("T"),
                            '&eta; · ' + var("h"),
                        ),
                        where=[
                            (var("V", "cf"), f"gas burned, cubic feet — "
                                             f"{system_cf:.1f} cf per °F here"),
                            (var("V"), f"water heated, {SYSTEM_GALLONS:,.0f} gal of pool "
                                       f"and spa together"),
                            ("&rho;", f"weight of water, {costs.LB_PER_GAL:.2f} lb/gal. "
                                      f"One BTU raises one pound one °F, so this is also "
                                      f"the BTU per gallon per degree — the specific heat "
                                      f"is 1 by definition and never appears"),
                            ('&Delta;' + var("T"), "temperature rise, °F — one, here"),
                            ("&eta;", f"appliance efficiency, "
                                      f"{costs.APPLIANCE_EFFICIENCY:.0%} — assumed, and the "
                                      f"only term on this line that is not measured or a "
                                      f"constant of nature"),
                            (var("h"), f"heat content of the gas, "
                                       f"{tariff.MCF_TO_DTH * 1000:,.0f} BTU/cf, taken from "
                                       f"the bill's own Mcf-to-Dth conversion rather than a "
                                       f"table"),
                        ],
                        note=f"Multiply by the gas rate to get money: "
                             f"{money(system_winter)} in January against "
                             f"{money(system_summer)} in July. The physics is identical; "
                             f"only the tariff moved.",
                    )),
        ])

    if pool_blocks or volume_blocks:
        section = (
            Section(
                id="pool",
                emoji="🏊",
                title="The pool explains (almost) everything else",
                lede=(
                    "How big it is, then what it explains. Three anomalies across three "
                    "utilities and one piece of equipment behind all of them — the "
                    "water-temperature probe turns out to be the most informative sensor "
                    "in the house."
                ),
                blocks=volume_blocks + pool_blocks,
            )
        )
    
    return section
