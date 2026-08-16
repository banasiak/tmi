"""What a roof array would do here, on a roof that faces the wrong way twice.

The only modeled input on the page, and the section most careful about saying
so: the station's own pyranometer cannot judge an east-west roof.
"""

from __future__ import annotations

from src import charts, model, solar, tariff
from src.analysis import Analysis
from src.house import (MEASURED_TILT, MEASURED_TILT_TOL, MOUNT_BLOCK_DEG,
                       MOUNT_HEIGHT_IN,
                       MOUNT_RIDGE_FAR_DEG,
                       MOUNT_RIDGE_NEAR_DEG, ROOF_TILT)
from src.prose import money, spell
from src.report import Callout, Formula, Section, formula, frac, var


def build(data: Analysis) -> Section | None:
    """What a roof array would do here, on a roof that faces the wrong way twice."""
    # Everything this section reads from the analysis layer.
    days = data.days
    irradiance = data.irradiance
    planes = data.planes
    pv_flat = data.pv_flat
    pv_south = data.pv_south
    pyranometer = data.pyranometer
    scheduled = data.scheduled
    shortfall = data.shortfall
    total_kwh = data.total_kwh
    section: Section | None = None

    # The roof is an east-west gable — it peaks along a central ridge and slopes
    # due east and due west. It is not south-facing, which this section assumed
    # for a long time and which cost about 15% of the production quoted here.

    roof = None
    if all(planes.values()):
        dates = [d.date for d in days]
        plane_daily = {az: solar.pvwatts_daily(r, dates) for az, r in planes.items()}
        # Half the array on each slope, so the effective plane is their mean.
        # The two are within 2.3% of each other, which is what makes an even
        # split the obvious arrangement rather than a compromise.
        roof_poa = {
            d: sum(p[d] for p in plane_daily.values()) / len(plane_daily)
            for d in dates
        }
        roof = model.net_metered_solar(
            days, roof_poa, lambda kwh, end: tariff.electric_bill(kwh, end).total
        )

    if roof:
        pick = roof.recommended
        # Slot-level generation against slot-level load. The monthly view balances
        # because a billing period is the accounting unit; this one shows the
        # mismatch inside a day that net metering is what papers over.
        # The pump comes out of the load curve. It is the one large draw whose
        # clock position is arbitrary, so leaving it in makes the mismatch look
        # worse than it is — and hides the question actually worth asking, which
        # is where it ought to run instead.
        # Both planes at 15-minute grain, averaged the same way the daily figures
        # are. An east array and a west array peak on opposite sides of noon, so
        # the combined curve is the flatter, wider one this chart is about.
        plane_slots = [solar.pvwatts_slots(r, dates) for r in planes.values()]
        every_slot = set().union(*(s.keys() for s in plane_slots))
        roof_slots = {
            k: sum(s.get(k, 0.0) for s in plane_slots) / len(plane_slots)
            for k in every_slot
        }
        timing = model.generation_timing(
            days,
            roof_slots,
            pick.kw,
            0.78,
            remove=(
                (scheduled.start_slot, scheduled.end_slot, scheduled.magnitude_kw)
                if scheduled else None
            ),
        )
        # What the pitch costs. On a south roof this was a gain and the argument
        # was that it barely mattered; on an east-west roof flat is optimal and
        # every degree of slope is a loss, so the same conclusion — do not pay
        # for racking — now follows from the opposite direction.
        # Two bases, kept apart deliberately. The geometry comparisons below run
        # on a full typical year, because a claim about what a slope is worth
        # should not depend on how many days this dataset happens to cover. The
        # production figures run on the days actually covered, which is what
        # `roof.poa_annual` sums — so the per-plane numbers quoted beside it have
        # to use the same basis or the arithmetic will not check out on the page.
        east_poa = planes[90.0].annual_poa
        west_poa = planes[270.0].annual_poa
        ew_poa = (east_poa + west_poa) / 2.0
        flat_poa = pv_flat.annual_poa if pv_flat else None
        south_poa = pv_south.annual_poa if pv_south else None
        east_covered = sum(plane_daily[90.0].values())
        west_covered = sum(plane_daily[270.0].values())
    
        monthly_gen: dict[str, float] = {}
        monthly_use: dict[str, float] = {}
        for d in days:
            key = f"{d.date:%Y-%m}"
            if d.date in roof_poa:
                monthly_gen[key] = monthly_gen.get(key, 0.0) + roof_poa[d.date] * pick.kw * 0.78
            if d.kwh is not None:
                monthly_use[key] = monthly_use.get(key, 0.0) + d.kwh
        shared = [k for k in sorted(monthly_use) if k in monthly_gen
                  and sum(1 for d in days if f"{d.date:%Y-%m}" == k and d.kwh is not None) >= 27]
        labels = [f"{k[5:]}/{k[2:4]}" for k in shared]
    
        size_rows = "".join(
            f"<tr><td>{sc.kw:.0f} kW</td><td>{sc.panels}</td>"
            f"<td>{sc.roof_sqft:,.0f}</td><td>{sc.produced:,.0f}</td>"
            f"<td>{sc.share_of_use:.0%}</td><td>{money(sc.gross_cost)}</td>"
            f"<td>{money(sc.net_cost)}</td><td>{money(sc.saved)}</td>"
            f"<td>{sc.spilled:,.0f}</td><td>{sc.payback_years:.1f} yr</td>"
            f"<td>{money(sc.lifetime_net)}</td></tr>"
            for sc in roof.scenarios
        )
        size_table = (
            f'<div class="card"><h3>Every size, in full</h3>'
            f'<p class="fig-sub">Net cost is after the {model.FEDERAL_ITC:.0%} federal '
            f'credit and New Mexico\'s {model.STATE_CREDIT:.0%}. Spill is production that '
            f'overran the month it was made in.</p>'
            f'<div class="table-scroll"><table><thead><tr>'
            f"<th>Array</th><th>Panels</th><th>Roof ft²</th><th>kWh/yr</th><th>% of use</th>"
            f"<th>Gross</th><th>Net</th><th>Saved/yr</th><th>Spill</th><th>Payback</th>"
            f"<th>25-yr net</th></tr></thead><tbody>{size_rows}</tbody></table></div></div>"
        )
    
        solar_blocks: list[object] = [
            Callout(
                kind="caution",
                title=(
                    f"First: the station's solar sensor reads {pyranometer.shortfall:.0%} "
                    f"low, and only {shortfall.instrument:.0%} of that is the sensor"
                ),
                body=(
                    f"<p>This section does not use the weather station for how much sun "
                    f"falls on the roof. It is worth explaining why, because the reason is "
                    f"more interesting than the correction.</p>"
                    f"<p>The sensor reports "
                    f"<strong>{pyranometer.ghi_annual:,.0f} kWh/m² a year</strong>, peaking "
                    f"at {pyranometer.peak:.0f} W/m². NSRDB puts Las Cruces between "
                    f"{solar.NSRDB_GHI_LOW:,.0f} and {solar.NSRDB_GHI_HIGH:,.0f} — a "
                    f"shortfall of about {pyranometer.shortfall:.0%}. It can be caught out "
                    f"without leaving the dataset: the clearness index should approach "
                    f"{solar.CLEAR_SKY_KT:.2f} on a clear desert day, and restricted to "
                    f"{pyranometer.samples:,} moments with the sun above 50°, where geometry "
                    f"cannot be blamed, the <strong>median is {pyranometer.median_kt:.2f}"
                    f"</strong> with a 99th percentile of {pyranometer.p99_kt:.2f}.</p>"
                    f"<p><strong>But that shortfall is two faults, not one.</strong> An "
                    f"instrument that under-reads and an instrument with something in front "
                    f"of it are indistinguishable in an annual total, and separate by sun "
                    f"angle: a hardware fault is there at every altitude, an obstruction "
                    f"runs out once the sun climbs above it. Above 50° elevation, where "
                    f"nothing blocks either instrument, the station reads a steady "
                    f"<strong>{shortfall.high_sun_ratio:.0%}</strong> of PVWatts. That "
                    f"<strong>{shortfall.instrument:.0%}</strong> is the silicon photodiode "
                    f"a consumer station carries in place of a thermopile: it answers to a "
                    f"narrow slice of the spectrum where a thermopile absorbs the whole of "
                    f"it. That the gap holds flat as the sun climbs is what identifies it — "
                    f"a spectral shortfall is the same at every angle, where a cosine error "
                    f"would widen as the sun fell. The remaining "
                    f"<strong>{shortfall.obstruction:.0%}</strong> does exactly that, and it "
                    f"is the subject of the next panel.</p>"
                    f"<p>Where the station is still used — the timing chart below, and "
                    f"every non-solar figure on this page — it is scaled by "
                    f"<strong>×{pyranometer.scale:.2f}</strong>, applied to the horizontal "
                    f"reading before any tilt geometry: the beam-and-diffuse split depends "
                    f"on clearness, so correcting afterwards would keep an overstated "
                    f"diffuse fraction. That scale is now confirmed from outside. A flat "
                    f"PVWatts plane is just global horizontal, and it returns "
                    f"{flat_poa:,.0f} kWh/m² against the corrected sensor's "
                    f"{sum(solar.plane_of_array(irradiance, 0.0, pyranometer.scale).values()):,.0f} "
                    f"— agreement to about 2%, from a source that shares none of its "
                    f"hardware.</p>"
                ),
            ),
            Callout(
                kind="finding",
                title=(
                    f"The other {shortfall.obstruction:.0%}: something stands in the "
                    f"sensor's eastern sky"
                ),
                body=(
                    f"<p>The pyranometer sits on an old satellite mount "
                    f"{MOUNT_HEIGHT_IN:.0f} inches above the eave, on the west slope below "
                    f"the ridge — which makes the ridge the obvious suspect, and the "
                    f"arithmetic rules it out. Cutting the sky at {MOUNT_BLOCK_DEG:.0f}° "
                    f"from a {MOUNT_HEIGHT_IN:.0f}-inch pole needs "
                    f"<strong>{(MOUNT_HEIGHT_IN / 12) / 0.0303:.0f} ft</strong> of roof "
                    f"between sensor and ridgeline; this house is about half that across, "
                    f"and the conclusion holds even if that estimate is three times off. "
                    f"The roof accounts for {MOUNT_RIDGE_NEAR_DEG:.0f}–"
                    f"{MOUNT_RIDGE_FAR_DEG:.0f}° of the {MOUNT_BLOCK_DEG:.0f}°, depending "
                    f"which ridgeline the sightline clears, and cannot be the whole of "
                    f"it.</p>"
                    f"<p>An aerial photograph of the property supplies the likelier "
                    f"candidate: mature trees stand due east of the sensor at the same "
                    f"latitude, tall enough to throw shadows several times the length of the "
                    f"shrubs beside them. A canopy is also the better fit for the shape "
                    f"measured — an obstruction that ramps rather than cuts. Their height "
                    f"has not been measured, so how the remaining degrees divide between "
                    f"roof and trees is <strong>open</strong>.</p>"
                    f"<p><strong>What is in the way is unsettled; that something is in the "
                    f"way is not.</strong> The evidence is in the sky, not the specification. "
                    f"Binning every "
                    f"clear-day reading by where the sun actually was, the eastern sky is "
                    f"blocked to roughly <strong>21° of elevation</strong> while the western "
                    f"sky is clear to the horizon. At matched altitude and therefore matched "
                    f"airmass, morning clearness runs 0.11 against an afternoon 0.34 — a "
                    f"three-fold gap that no atmosphere produces. It is not the instrument "
                    f"either: above 65° the two halves of the day agree to 0.003.</p>"
                    f"<p>Three explanations were tested and failed. <strong>Dew</strong> "
                    f"predicts the deficit growing on humid nights; it is largest on the "
                    f"driest. A <strong>nocturnal inversion</strong> predicts a winter "
                    f"maximum; the deficit is twice as large in summer. <strong>The Organ "
                    f"Mountains</strong> to the east subtend only a few degrees from this "
                    f"side of the valley and would cut a sharp edge — the eastern sky "
                    f"instead fades in gradually over an 18°-wide span of elevation, and "
                    f"the block gets <em>worse</em> toward the north, where the range is "
                    f"further away and lower.</p>"
                    f"<p>The same test convicts the roof. A ridgeline a dozen feet away is "
                    f"the sharpest edge in this problem and should cut rather than fade — "
                    f"which is the second reason to look past it.</p>"
                    f"<p><strong>Why it matters here and nowhere else.</strong> On the "
                    f"due-south roof the error would cancel "
                    f"exactly — a south plane weighs morning and afternoon symmetrically "
                    f"about noon. On an east-west roof it does not cancel; it is the entire "
                    f"measurement. The station puts the west slope 7.4% ahead of the east. "
                    f"PVWatts, from a clear horizon, puts them within "
                    f"{abs(east_poa - west_poa) / ew_poa:.1%}. That is why production below "
                    f"comes from a model rather than from the backyard.</p>"
                    f"<p><strong>Worth pricing before anyone climbs up.</strong> Moving the "
                    f"pole to the nearest ridgeline gains about three feet and buys perhaps "
                    f"three degrees — {MOUNT_BLOCK_DEG:.0f}° down to 18. The main ridge "
                    f"would gain nine and help more. Neither clears a tree, which is why "
                    f"the canopy wants measuring before the obvious fix is worth doing.</p>"
                ),
            ),
            formula(Formula(
                caption="The test that catches the sensor, using nothing outside the data",
                lhs=var("k","t"),
                rhs=f'{frac(var("GHI"), f"{var("G","sc")} · {var("E","0")} · sin&thinsp;&alpha;")}',
                where=[
                    (var("k","t"), "clearness index — the share of the extraterrestrial "
                                   "beam that reaches the ground"),
                    (var("GHI"), "what the station reports, W/m²"),
                    (var("G","sc"), f"solar constant, {solar.SOLAR_CONSTANT:,.0f} W/m²"),
                    (var("E","0"), "eccentricity correction for the day of year"),
                    ("&alpha;", "solar altitude — restricted here to above 50°, so a low "
                                "sun cannot be blamed for a low reading"),
                ],
                note=f"A clear desert moment should reach {solar.CLEAR_SKY_KT:.2f}. The "
                     f"median is {pyranometer.median_kt:.2f}, which is why everything "
                     f"below is scaled by ×{pyranometer.scale:.2f}.",
            )),
            formula(Formula(
                caption="From plane-of-array insolation to kilowatt-hours",
                lhs=var("E"),
                rhs=f'{var("H","poa")} · {var("P","dc")} · {var("PR")}',
                where=[
                    (var("E"), f"annual generation, kWh. The tables below land about "
                               f"{1 - pick.produced / (roof.poa_annual * pick.kw * 0.78):.1%} "
                               f"under what this line gives, because net metering settles "
                               f"per billing month: they price the "
                               f"{spell(roof.months)} complete months and scale to twelve, "
                               f"which leaves out a high-sun August"),
                    (var("H","poa"), f"insolation on the roof planes, "
                                     f"{roof.poa_annual:,.0f} kWh/m² — the mean of "
                                     f"{east_covered:,.0f} east and {west_covered:,.0f} "
                                     f"west, across the {len(days)} days covered"),
                    (var("P","dc"), "array size, kW — rated at 1,000 W/m², which is why "
                                    "the areas cancel and no panel efficiency appears"),
                    (var("PR"), "performance ratio, 0.78 — inverter, wiring, soiling, and "
                                "the temperature derate that matters at 110°F"),
                ],
            )),
            Callout(
                kind="finding",
                # The pitch you already have is what matters, not slope-vs-flat. An
                title="Your pitch costs you, and there is nothing worth doing about it",
                body=(
                    f"<p>On a south roof, any common pitch is near enough the right one — "
                    f"the whole 14° to 32° span sits within a couple of percent of "
                    f"optimum. That is not true here. <strong>On an east-west roof, flat "
                    f"is optimal and every degree of pitch is a loss.</strong></p>"
                    f"<p>A horizontal plane here collects <strong>{flat_poa:,.0f} kWh/m²"
                    f"</strong>. The same panels laid on your two slopes collect "
                    f"{ew_poa:,.0f} — <strong>{1 - ew_poa / flat_poa:.1%} less</strong>. "
                    f"A south roof at the same pitch would have collected "
                    # "a 18%" — the article has to follow the number, which moves.
                    f"{south_poa:,.0f}, "
                    f"{'an' if f'{south_poa / ew_poa - 1:.0%}'[0] in '811' else 'a'} "
                    f"<strong>{south_poa / ew_poa - 1:.0%} premium</strong> "
                    f"that this roof simply does not have available to it.</p>"
                    f"<p>The reason the conclusion survives is that the alternative is "
                    f"worse. Tilt-up racking on an east or west slope has to fight the "
                    f"roof rather than follow it: to reach a south-facing tilt it needs "
                    f"ballast, wind loading and row spacing that a flush mount never pays "
                    f"for, on a roof whose planes are only {1 - ew_poa / flat_poa:.1%} off "
                    f"horizontal to begin with. <strong>Flush-mount both slopes and take "
                    f"the {1 - ew_poa / flat_poa:.1%}.</strong></p>"
                    f"<p><strong>The pitch is measured, not assumed</strong> — "
                    f"{MEASURED_TILT:.1f}° off the roof by phone inclinometer, an instrument "
                    f"good to about <strong>±{MEASURED_TILT_TOL:.0f}°</strong>.</p>"
                    f"<p>The figures here come from PVWatts runs at {ROOF_TILT:.1f}°, which "
                    f"sits inside that band, and re-running them at the reading itself would "
                    f"be theatre. Plane-of-array moves "
                    f"{abs((east_poa - flat_poa) / ROOF_TILT):.1f} kWh/m² per degree on the "
                    f"east slope and {abs((west_poa - flat_poa) / ROOF_TILT):.1f} on the "
                    f"west, so the full width of the measurement's uncertainty is worth "
                    f"about {abs((west_poa - flat_poa) / ROOF_TILT) * MEASURED_TILT_TOL / west_poa:.1%} "
                    f"— well under the uncertainty in the performance ratio these numbers "
                    f"are multiplied by. The measurement's job was never to refine the "
                    f"model; it was to confirm the roof is not the 25–30° the sensor's "
                    f"blocked horizon once suggested.</p>"
                ),
            ),
            charts.monthly_columns(
                "solar-monthly",
                f"{'An' if str(int(pick.kw))[0] == '8' else 'A'} {pick.kw:.0f} kW array against the months it has to cover",
                "Generation split evenly across the east and west slopes, against metered "
                "consumption. Complete months only.",
                labels,
                [
                    ("Consumption", "var(--ink-muted)", [monthly_use[k] for k in shared]),
                    ("Generation", "electric", [monthly_gen[k] for k in shared]),
                ],
                "kWh",
                note=(
                    f"Consumption is the context and generation the proposal, so only one "
                    f"of them is drawn as a series. Note how much flatter generation is "
                    f"than consumption: "
                    f"the array varies about {max(monthly_gen[k] for k in shared) / min(monthly_gen[k] for k in shared):.1f}× "
                    f"across the year against the house's "
                    f"{max(monthly_use[k] for k in shared) / min(monthly_use[k] for k in shared):.1f}×, "
                    f"because summer heat derates panels and a tilted plane loses to a high "
                    f"sun. The binding month is spring, not summer — that is where "
                    f"generation first catches consumption and surplus starts."
                ),
            ),
        ]
        if timing:
            solar_blocks.extend([
                charts.profile_lines(
                    "solar-timing",
                    f"When the power arrives against when it is used",
                    f"{'An' if str(int(pick.kw))[0] == '8' else 'A'} {pick.kw:.0f} kW "
                    f"array's mean output against everything the house draws "
                    f"<em>except</em> the pool pump, at each 15-minute slot of the day.",
                    [
                        ("Load without the pump", "var(--ink-muted)", timing.load),
                        ("Generation", "var(--stream-electric)", timing.generation),
                    ],
                    "kW",
                    # Both curves converge overnight, so end-of-line labels would
                    # stack on the axis. Their peaks are hours apart in the clock
                    # and kilowatts apart in height, which is the natural place.
                    label_at="peak",
                    highlight=(
                        (timing.removed.now_slot,
                         (timing.removed.now_slot + timing.removed.slots) % 96 or 96,
                         f"pump removed ({timing.removed.kw:.2f} kW)")
                        if timing.removed else None
                    ),
                    note=(
                        f"The pool pump is taken out because its schedule is arbitrary — "
                        f"the shaded band is where it runs today. What is left is the load "
                        f"the house cannot move: "
                        f"generation peaks at "
                        f"{timing.gen_peak_slot * 15 // 60:02d}:00, the remaining load peaks "
                        f"at {timing.load_peak_slot * 15 // 60:02d}:00, and the array is "
                        f"finished by then."
                        if timing.removed else
                        f"Generation peaks at {timing.gen_peak_slot * 15 // 60:02d}:00 and "
                        f"the house at {timing.load_peak_slot * 15 // 60:02d}:00."
                    ),
                ),
                Callout(
                    kind="finding",
                    title=(
                        f"Only {timing.self_consumed:.0%} of what the array makes would be "
                        f"used as it is made"
                    ),
                    body=(
                        f"<p>Matching the two curves slot by slot, "
                        f"<strong>{timing.self_consumed:.0%}</strong> of generation lands "
                        f"while the house is already drawing at least that much. The other "
                        f"{1 - timing.self_consumed:.0%} — about "
                        f"{timing.surplus_kwh:,.0f} kWh a year — has to leave the property "
                        f"and come back later.</p>"
                        f"<p><strong>That is the entire case for net metering, in one "
                        f"picture.</strong> With it, the exported kilowatt-hour returns at "
                        f"retail and the mismatch costs nothing; the monthly chart above is "
                        f"the honest one because the billing period is the accounting unit. "
                        f"Without it, this chart is the honest one, and roughly "
                        f"{1 - timing.self_consumed:.0%} of the array's output would be "
                        f"sold at a fraction of what it displaces — which is what turns a "
                        f"{pick.payback_years:.0f}-year payback into something much "
                        f"longer.</p>"
                    ),
                ),
                Callout(
                    kind="note",
                    title=(
                        f"Where the pump should run: "
                        f"{timing.removed.best_time} rather than "
                        f"{timing.removed.now_time}"
                        if timing.removed else "The pool pump"
                    ),
                    body=(
                        f"<p>Taking the pump out of the curve is what makes the question "
                        f"answerable. It is a fixed block — "
                        f"{timing.removed.kw:.2f} kW for "
                        f"{timing.removed.slots / 4:.2f} hours, "
                        f"{timing.removed.kwh_per_day:.1f} kWh a day — that can be dropped "
                        f"anywhere on the clock, so the only question is where it lands "
                        f"against the surplus the rest of the house leaves unused.</p>"
                        f"<p>Scanning all 96 start times: today it begins at "
                        f"<strong>{timing.removed.now_time}</strong>, where "
                        f"<strong>{timing.removed.now_covered:.0%}</strong> of it could be "
                        f"met by generation the house is not otherwise using. The best start "
                        f"is <strong>{timing.removed.best_time}</strong>, which lifts that to "
                        f"<strong>{timing.removed.best_covered:.0%}</strong> — it fits almost "
                        f"entirely inside the day's surplus.</p>"
                        f"<p>Worth being clear about what that is and is not worth. "
                        f"<strong>Under net metering it is worth nothing</strong>, because an "
                        f"exported kilowatt-hour and a self-consumed one settle at the same "
                        f"price — the section below puts the whole diversion case at a few "
                        f"dollars a year. It matters in exactly two situations: if there is "
                        f"no array at all and time-of-use pricing arrives, or if there is an "
                        f"array and the tariff stops crediting exports at retail. In both, "
                        f"this is a free change to a timer that is already running.</p>"
                        f"<p>And it is free of the filtration argument entirely. Cutting the "
                        f"runtime saves money today at any tariff; moving it saves nothing "
                        f"today and a good deal under a worse one. They are independent "
                        f"decisions about the same timer.</p>"
                        if timing.removed else ""
                    ),
                ),
            ])
        solar_blocks.extend([
            charts.monthly_columns(
                "solar-sizes",
                "What each array size returns",
                "Priced by rebuilding both bills from the real tariff, month by month.",
                [f"{s.kw:.0f} kW" for s in roof.scenarios],
                # Dollars saved, not kilowatt-hours generated.
                [("Annual bill saving", "var(--money-accent)",
                  [s.saved for s in roof.scenarios])],
                "$/yr",
                category_label="Array size",
                note=(
                    f"Payback improves with size — {roof.scenarios[0].payback_years:.1f} "
                    f"years at {roof.scenarios[0].kw:.0f} kW against "
                    f"{roof.scenarios[-1].payback_years:.1f} at "
                    f"{roof.scenarios[-1].kw:.0f} kW — because installed cost per watt falls "
                    f"while every kWh keeps the same value. Cost, panel count, roof area and "
                    f"spill are in the table below."
                ),
            ),
            size_table,
            Callout(
                kind="finding",
                title=(
                    f"{pick.kw:.0f} kW — {pick.panels} panels, {money(pick.saved)} a year, "
                    f"{pick.payback_years:.1f} year payback"
                ),
                body=(
                    f"<p>At {money(pick.price_per_w)}/W installed that is "
                    f"{money(pick.gross_cost)} gross, or <strong>{money(pick.net_cost)}</strong> "
                    f"after the {model.FEDERAL_ITC:.0%} federal credit and New Mexico's "
                    f"{model.STATE_CREDIT:.0%}. It produces {pick.produced:,.0f} kWh — "
                    f"{pick.share_of_use:.0%} of the {roof.annual_use:,.0f} kWh this house "
                    f"uses — and needs about {pick.roof_sqft:,.0f} ft² of roof, which an "
                    f"even split puts at {pick.roof_sqft / 2:,.0f} ft² on each slope. That "
                    f"consumption figure is the complete billing months scaled to twelve, so "
                    f"it sits a little under the {total_kwh:,.0f} kWh totalled at the top of "
                    f"this page from every metered day.</p>"
                    f"<p>Every kWh is worth <strong>${pick.effective_rate:.3f}</strong>, and "
                    f"that figure holds flat across every size below "
                    f"{roof.scenarios[-1].kw:.0f} kW. That is the whole difference net "
                    f"metering makes: without it an array this size would be discarding a "
                    f"fifth to a third of its output, and a battery would be an expensive "
                    f"way to buy some of it back.</p>"
                    f"<p>Held at today's rates and degrading the panels "
                    f"{model.DEGRADATION:.1%} a year, {model.LIFETIME_YEARS} years returns "
                    f"<strong>{money(pick.lifetime_net)}</strong> net of the install. Rates "
                    f"rising is the upside case — roughly a year off the payback per 1%/yr "
                    f"of increase.</p>"
                ),
            ),
            Callout(
                kind="note",
                title="What no array can touch, and what could still go wrong",
                body=(
                    f"<p><strong>{money(roof.irreducible)} a year survives a zero-kWh "
                    f"month.</strong> Customer charge, franchise fee and gross receipts tax "
                    f"are not per-kWh, so they are outside solar's reach entirely. Nobody's "
                    f"quote will mention it.</p>"
                    f"<p><strong>Above about {roof.scenarios[-1].kw:.0f} kW it turns "
                    f"over.</strong> At that size {roof.scenarios[-1].spilled:,.0f} kWh a "
                    f"year overruns the month it was generated in, and surplus is modeled "
                    f"at ${roof.excess_credit:.3f}/kWh rather than retail. New Mexico "
                    f"utilities also generally cap system size near historical use, so this "
                    f"is a regulatory ceiling as well as an economic one.</p>"
                    f"<p><strong>The tariff is the real risk, not the hardware.</strong> "
                    f"These paybacks assume the rate schedule transcribed elsewhere on this "
                    f"page still applies in fifteen years. EPE has pursued separate rate "
                    f"classes for solar customers before; ask directly which tariff you "
                    f"would be moved onto, because that question is worth more than a "
                    f"percentage point of panel efficiency.</p>"
                    f"<p>One thing that stops mattering: <strong>under net metering it no "
                    f"longer matters when the pool pump runs.</strong> An exported kWh and a "
                    f"self-consumed one are worth the same, so the case for re-timing it "
                    f"disappears. Cutting its runtime still saves what it always did, and "
                    f"now that saving is clean — it also shrinks the array you need.</p>"
                ),
            ),
        ])
    
        section = (
            Section(
                id="solar",
                emoji="🌞",
                title="What solar would do here",
                lede=(
                    "A grid-tied, net-metered array split across the east and west slopes, "
                    "priced by rebuilding the actual bill month by month rather than "
                    "multiplying production by an average rate."
                ),
                blocks=solar_blocks,
            )
        )
    
    return section
