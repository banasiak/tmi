"""Four boxes in the same weather.

House, garage, shed and patio, and the question the whole project started from.
"""

from __future__ import annotations

import datetime as dt
import statistics

from src import charts, costs, psychro, report, sources, tariff, zones
from src.analysis import Analysis
from src.prose import money
from src.report import Callout, Formula, Section, formula, frac, var


def build(data: Analysis) -> Section:
    """Four boxes in the same weather."""
    # Everything this section reads from the analysis layer.
    couplings = data.couplings
    days = data.days
    glazing = data.glazing
    minisplit = data.minisplit
    pump_cost = data.pump_cost
    zone_series = data.zone_series

    rungs = zones.ladder(zone_series)
    by_zone = {r.zone: r for r in rungs}
    moisture = zones.moisture_months(zone_series)
    responses, onset_count = zones.monsoon_response(zone_series)
    by_response = {r.zone: r for r in responses}
    summer_rate = tariff.marginal_rate(dt.date(2026, 7, 15))
    latent = zones.latent_load(days, zone_series, summer_rate)
    
    inner = [z for z in sources.ZONE_ORDER if z != "outdoor"]
    zone_blocks: list[object] = [
        report.tile_row(
            [
                report.Tile(
                    label=by_zone[z].label,
                    value=f"{by_zone[z].swing_ratio:.2f}",
                    unit="×",
                    # A phase lag only describes a wall if the zone is actually
                    # following the weather. The conditioned zones track a
                    # thermostat instead (r ≈ 0.70, and most of that is the
                    # seasonal cycle), so quoting hours for them would put a
                    # property of the building on a number that has not got one.
                    detail=(
                        f"of the outdoor swing"
                        + (
                            f" · {by_zone[z].lag_hours} h behind"
                            if by_zone[z].corr >= 0.9
                            else " · follows its thermostat"
                        )
                        + f"<br>{by_zone[z].min_offset:+.0f}°F on the daily low, "
                        f"{by_zone[z].max_offset:+.0f}°F on the high"
                    ),
                    accent="var(--zone-accent)",
                )
                for z in inner
            ]
        ),
        Callout(
            kind="finding",
            title="The shed is not a control — it is an amplifier",
            body=(
                f"<p>Four boxes, one weather. Ranked by how much of the outdoor daily swing "
                f"each one lets through, they fall in the order you would guess — except at "
                f"the top. The shed passes "
                f"<strong>{by_zone['shed'].swing_ratio:.2f}×</strong> the outdoor swing: it "
                f"does not merely fail to insulate, it <em>adds</em> to the weather. Its "
                f"daily high averages {by_zone['shed'].max_offset:+.1f}°F against the "
                f"outdoor high and it still runs {by_zone['shed'].min_offset:+.1f}°F warm at "
                f"dawn, peaking at {by_zone['shed'].t_max:.0f}°F over the year — hotter than "
                f"the {by_zone['outdoor'].t_max:.0f}°F the outdoor sensor ever saw. That is a "
                f"solar oven with enough mass to stay warm overnight, not a passive box.</p>"
                f"<p>The garage is the interesting one. It cuts the swing to "
                f"<strong>{by_zone['garage'].swing_ratio:.2f}×</strong> and runs "
                f"<strong>{by_zone['garage'].lag_hours} hours behind</strong> the weather, "
                f"the longest lag of any zone — that delay is thermal mass, the slab and the "
                f"shared wall. But its protection is lopsided: "
                f"<strong>{by_zone['garage'].min_offset:+.1f}°F on the daily low against "
                f"only {by_zone['garage'].max_offset:+.1f}°F on the high</strong>. It is very "
                f"good at keeping cold out and barely does anything about heat. Anything "
                f"stored there that minds freezing is safe; anything that minds "
                f"{by_zone['garage'].t_max:.0f}°F is not.</p>"
            ),
        ),
    ]
    
    hot_days = zones.hottest_days(zone_series, 30)
    hot_profile = zones.diurnal(zone_series, "temp", hot_days)
    zone_blocks.append(
        charts.zone_multiples(
            "zone-diurnal",
            "One day, four buildings — the 30 hottest days of the year",
            "Every panel on the same scale, each against the same outdoor curve.",
            [
                charts.ZonePanel(
                    label=by_zone[z].label,
                    values=hot_profile[z],
                    # A peak hour is only meaningful if there is a peak. The
                    # conditioned zones move less over a whole day than the
                    # sensor's own resolution argues about, so quoting the hour
                    # of their maximum would dress noise up as a schedule.
                    caption=(
                        f"peaks {hot_profile[z].index(max(hot_profile[z])):02d}:00"
                        if max(hot_profile[z]) - min(hot_profile[z]) >= 3.0
                        else f"flat within {max(hot_profile[z]) - min(hot_profile[z]):.1f}°F"
                    ),
                )
                for z in inner
            ],
            ("Outdoors", hot_profile["outdoor"]),
            "°F",
            [f"{h:02d}:00" for h in range(24)],
            note=(
                f"The shed tracks the sun; the house ignores it. Outdoors peaks at "
                f"{hot_profile['outdoor'].index(max(hot_profile['outdoor'])):02d}:00 — "
                f"the garage crests later, which is the thermal mass showing up as a "
                f"delay rather than as a smaller number."
            ),
        )
    )
    
    garage_temp = couplings.get(("garage", "temperature"))
    garage_moist = couplings.get(("garage", "moisture"))
    patio_temp = couplings.get(("patio", "temperature"))
    patio_moist = couplings.get(("patio", "moisture"))
    if garage_temp and garage_moist and patio_temp and patio_moist:
        zone_blocks.append(
            charts.coupling_scatter(
                "zone-coupling",
                "The shared wall, measured",
                "Each dot is one day. Garage minus shed, against house minus outdoors.",
                garage_temp.points,
                (garage_temp.intercept, garage_temp.slope),
                "House warmer than outdoors (°F)",
                "Garage warmer than shed (°F)",
                "°F",
                note=(
                    f"Slope {garage_temp.slope:.3f}, R²={garage_temp.r2:.3f} over "
                    f"{garage_temp.n} days. The line runs through both halves of the year: "
                    f"when the house is cooler than outdoors, the garage goes cool relative "
                    f"to the shed by the same fraction."
                ),
            )
        )
        zone_blocks.append(
            Callout(
                kind="finding",
                title=(
                    f"About {garage_temp.slope:.0%} of the house reaches the garage, "
                    f"and {garage_moist.slope:.0%} of its moisture"
                ),
                body=(
                    f"<p>The garage is compared with the <strong>shed</strong> here, not with "
                    f"outdoors. Both are unconditioned boxes on the same property carrying "
                    f"the same model of sensor. The one difference between them is that the "
                    f"garage shares a wall with the house — so <em>garage minus shed</em> "
                    f"isolates that wall, and regressing it on <em>house minus outdoors</em> "
                    f"gives the fraction of the house's gradient that arrives next door.</p>"
                    f"<p><strong>{garage_temp.slope:.1%} of the temperature gradient</strong> "
                    f"(R²={garage_temp.r2:.3f}) and "
                    f"<strong>{garage_moist.slope:.1%} of the moisture gradient</strong> "
                    f"(R²={garage_moist.r2:.3f}) get through. Moisture crosses more readily "
                    f"than heat, which fits a gap that leaks air: water vapour carried into "
                    f"the garage has nowhere to go, while the heat that rides in with it "
                    f"conducts straight back out through an uninsulated door.</p>"
                    f"<p>The patio, by contrast, is not really an outbuilding at all. It "
                    f"follows the house's temperature gradient at a slope of "
                    f"<strong>{patio_temp.slope:.3f}</strong> with "
                    f"<strong>R²={patio_temp.r2:.3f}</strong> — one-to-one, sitting a "
                    f"steady {abs(patio_temp.intercept):.1f}°F off the house. Its moisture "
                    f"slope of {patio_moist.slope:.2f} is the only sign it is not simply "
                    f"another room: about {1 - patio_moist.slope:.0%} more outdoor air gets "
                    f"in, which is what a wall of sliding doors would do.</p>"
                ),
            )
        )
    
        zone_blocks.append(
            Callout(
                kind="note",
                title="That wall of sliding doors, measured",
                body=(
                    f"<p>Two sliding doors face <strong>due south</strong>, dual pane with "
                    f"low-E, {costs.GLAZING_SQFT:.0f} sq ft of glass. Orientation had to be "
                    f"measured rather than guessed, and this is why: projected onto that "
                    f"surface, a due-south window here collects <strong>more energy in "
                    f"December than a horizontal one does</strong> (ratio 1.01) and barely "
                    f"a third as much in June (0.39). The summer sun is too high to get in; "
                    f"the winter sun strikes it nearly square.</p>"
                    # Unit spelled out on both figures. This one is insolation on the
                    # glass; the caveats quote a coincidentally identical 358 that is
                    # cooling *electricity*, and dropping the unit made them look like
                    # the same number.
                    f"<p>So the glass is a passive-solar asset, and a measurable one. Of "
                    f"the {glazing.total:,.0f} kWh/m² landing on that face across the year, "
                    f"{glazing.while_heating:,.0f} arrives while the zone actually wants "
                    f"heat — which shows up as a gap between the two heat-loss "
                    f"coefficients. The envelope's is {minisplit.ua_envelope:.0f} BTU/h/°F; "
                    f"the heat pump only has to cover {minisplit.ua:.0f}. <strong>"
                    f"{minisplit.solar_share_of_winter_load:.0%} of the winter heating load "
                    f"is carried by the windows for free.</strong></p>"
                    f"<p>The low-E coating is close to a wash in energy — about "
                    f"{minisplit.lowe_saving_kwh:,.0f} kWh of cooling saved against clear "
                    f"glass, {minisplit.lowe_heating_penalty_kwh:,.0f} kWh of heating added "
                    f"— but it wins on money, because a summer kilowatt-hour costs "
                    f"{tariff.marginal_rate(dt.date(2026, 7, 15)) / tariff.marginal_rate(dt.date(2026, 1, 15)):.2f}× "
                    f"a winter one. And it keeps the room usable on a July afternoon, which "
                    f"no energy balance captures.</p>"
                ),
            )
        )
    
    month_labels = [
        dt.date(int(m.month[:4]), int(m.month[5:]), 1).strftime("%b") for m in moisture
    ]
    zone_blocks.append(
        charts.zone_multiples(
            "zone-moisture",
            "Water in the air, by month",
            "Mixing ratio relative to outdoors — above the line is wetter than outside.",
            [
                charts.ZonePanel(
                    label=by_zone[z].label,
                    values=[m.excess[z] for m in moisture],
                )
                for z in inner
            ],
            # The outdoor reference *is* the zero line here, so no second rule.
            ("Outdoors", [0.0 for _ in moisture]),
            "g/kg",
            month_labels,
            note=(
                "Relative humidity would mostly restate the thermometers here. Mixing "
                "ratio is absolute: equal readings mean equal water, whatever the "
                "temperature."
            ),
        )
    )
    
    zone_blocks.append(formula(Formula(
        caption="Why every moisture comparison here is a mixing ratio, not a humidity",
        lhs=var("w"),
        rhs=f'1000 · &epsilon; · {frac(var("e"), f"{var("p")} &minus; {var("e")}")}'
            f'&nbsp;&nbsp;&nbsp;with&nbsp;&nbsp;&nbsp;'
            f'{var("e")} = 6.112 · exp{frac(f"17.67 · {var("T","d")}", f"{var("T","d")} + 243.5")}',
        where=[
            (var("w"), "grams of water vapour per kilogram of dry air"),
            ("&epsilon;", f"ratio of molar masses, {psychro.EPSILON:.3f}"),
            (var("e"), "vapour pressure, hPa — the saturation pressure at the dew point, "
                       "which is what a dew point means"),
            (var("T","d"), "dew point, °C, as transmitted by each zone's sensor"),
            (var("p"), "station absolute pressure, hPa — measured, not assumed: at "
                       "3,900 ft the air is about 12% thinner than sea level"),
        ],
        note="Relative humidity divides by a temperature-dependent denominator, so "
             "comparing a 50°F garage with a 74°F house on RH would mostly restate "
             "their thermometers. Mixing ratio is absolute: equal readings mean equal "
             "water.",
    )))
    
    winter = [m for m in moisture if m.month[5:] in {"12", "01", "02"}]
    summer = [m for m in moisture if m.month[5:] in {"07", "08"}]
    if winter and summer:
        w_house = statistics.fmean(m.excess["indoor"] for m in winter)
        s_house = statistics.fmean(m.excess["indoor"] for m in summer)
        zone_blocks.append(
            Callout(
                kind="finding",
                title=(
                    "The house is wetter than outside in winter and drier in summer — "
                    "the air conditioner is why"
                ),
                body=(
                    f"<p>In winter the house holds <strong>{w_house:+.1f} g/kg</strong> more "
                    f"water than the air outside — occupants, showers and cooking, with a "
                    f"tight envelope keeping it in. In July and August it holds "
                    f"<strong>{s_house:+.1f} g/kg</strong>, drier than outdoors. Nothing in "
                    f"the house removes water on purpose; that is the air conditioner "
                    f"condensing it out of the air as a side effect of cooling, and dumping "
                    f"it on the ground.</p>"
                    f"<p>The <strong>{w_house - s_house:.1f} g/kg reversal</strong> is the "
                    f"one moisture number here that no instrument error can manufacture. "
                    f"Comparing two sensors risks their calibration; comparing one sensor "
                    f"with itself in a different season does not. A hygrometer reading half "
                    f"a gram high all year shifts every month equally and leaves the swing "
                    f"exactly where it is.</p>"
                    f"<p>The zones fall in the same order in both directions. The patio "
                    f"follows the house closely, the garage weakly, the shed not at all — "
                    f"and the shed sitting flat against outdoors all year is the useful "
                    f"negative: it says the ladder is measuring the building, not five "
                    f"sensors disagreeing.</p>"
                ),
            )
        )
    
    zone_blocks.append(
        charts.zone_multiples(
            "zone-monsoon",
            "Where the monsoon gets in, and how long it stays",
            f"Mixing ratio against the day before, averaged over {onset_count} rain onsets.",
            [
                charts.ZonePanel(
                    label=by_zone[z].label,
                    values=by_response[z].profile,
                    caption=f"{by_response[z].retained:.0%} left on day 4",
                )
                for z in inner
            ],
            ("Outdoors", by_response["outdoor"].profile),
            "g/kg",
            ["−1", "0", "+1", "+2", "+3", "+4"],
            zero_line=True,
            note=(
                "Rain lands on day 0. Outdoor air peaks the next day and is most of the "
                "way back to normal by day 3."
            ),
        )
    )
    
    zone_blocks.append(
        Callout(
            kind="caution",
            title="The garage dries out last",
            body=(
                f"<p>Four days after the rain, outdoor air has shed "
                f"<strong>{1 - by_response['outdoor'].retained:.0%}</strong> of the moisture "
                f"it took on and the shed "
                f"<strong>{1 - by_response['shed'].retained:.0%}</strong>. The garage has "
                f"released only <strong>{1 - by_response['garage'].retained:.0%}</strong>. "
                # Every zone peaks on day +1, the garage included — the difference is
                # entirely in the decay, so the claim has to be about day +2 retention
                # rather than about a later peak.
                f"All four zones peak on the same day, +1; what separates them is what "
                f"happens next. By day 2 the shed has given back "
                f"{1 - by_response['shed'].profile[3] / by_response['shed'].peak:.0%} of its "
                f"peak and the outside air "
                f"{1 - by_response['outdoor'].profile[3] / by_response['outdoor'].peak:.0%}, "
                f"while the garage has released just "
                f"{1 - by_response['garage'].profile[3] / by_response['garage'].peak:.0%} — "
                f"it is still sitting at its wettest well after the sky has cleared.</p>"
                f"<p>Less wet air gets into the garage than into the shed — the peak is "
                f"{by_response['garage'].peak:.2f} g/kg against the shed's "
                f"{by_response['shed'].peak:.2f} — but what does get in is slower to "
                f"leave: on day 4 the garage still holds "
                f"{by_response['garage'].retained:.0%} of its peak while the shed holds "
                f"{by_response['shed'].retained:.0%} and the outside air "
                f"{by_response['outdoor'].retained:.0%}. That is what a slab and a stack of "
                f"stored material do: they absorb water vapour on the way in and give it "
                f"back slowly. The practical reading is that the garage spends several days "
                f"a monsoon at its own private humidity, well after the weather has moved "
                f"on.</p>"
            ),
        )
    )
    
    if latent:
        zone_blocks.append(
            Callout(
                kind="finding",
                title=f"“But it’s a dry heat” — except for ${latent.season_cost:.0f} of it",
                body=(
                    f"<p>Degree-days measure heat, not water, so an air conditioner's work "
                    f"condensing moisture is invisible to them. Adding outdoor mixing ratio "
                    f"as a second term to the cooling-season regression over "
                    f"{latent.n} days puts a number on it: "
                    f"<strong>{latent.per_gram:+.2f} kWh per g/kg per day</strong> "
                    f"(t = {latent.t_stat:.1f}), lifting R² from {latent.r2_without:.3f} to "
                    f"{latent.r2:.3f}.</p>"
                    f"<p>The two terms are close to independent — VIF "
                    f"{latent.vif:.2f} — which is what makes the split meaningful rather "
                    f"than an artifact of humid days also being hot ones. Between a dry "
                    f"cooling day ({latent.dry_w:.1f} g/kg, {latent.dry_days} of them) and a "
                    f"monsoon one ({latent.humid_w:.1f} g/kg, {latent.humid_days}), the "
                    f"humidity alone accounts for "
                    f"<strong>{latent.extra_kwh_day:.1f} kWh, or "
                    f"${latent.extra_cost_day:.2f} a day</strong> at the summer marginal "
                    f"rate of ${summer_rate:.4f}.</p>"
                    f"<p>Across the season, measured against the driest quarter of cooling "
                    f"days rather than against an impossible zero, that is "
                    f"<strong>{latent.season_kwh:.0f} kWh — ${latent.season_cost:.0f}</strong>. "
                    f"Not large next to the {money(pump_cost)} the pool pump costs, but it "
                    f"is real, and it is the part of the summer bill that arrives with the "
                    f"clouds rather than with the heat.</p>"
                    f"<p>So the local consolation is mostly true and precisely bounded. It "
                    f"<em>is</em> a dry heat, for {latent.dry_days} of the cooling days "
                    f"measured here — and on the {latent.humid_days} monsoon days it is "
                    f"not, at ${latent.extra_cost_day:.2f} a day. The saying is correct "
                    f"about the climate and wrong about the bill.</p>"
                ),
            )
        )
    
    
    section = (
        Section(
            id="zones",
            emoji="📦",
            title="Four boxes in the same weather",
            lede=(
                "The house, patio, garage and shed stand in identical weather and are built "
                "to four different standards. That makes the weather an instrument: outdoors "
                "supplies the forcing, and each zone's response measures how well it is "
                "separated from it."
            ),
            blocks=zone_blocks,
        )
    )
    
    
    return section
