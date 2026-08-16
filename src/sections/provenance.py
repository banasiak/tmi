"""What each source can support, and where the numbers stop being measurements.

The section the rest of the page is accountable to.
"""

from __future__ import annotations

import math

import statistics

from src import charts, costs, equipment, tariff
from src.analysis import Analysis
from src.house import (IRRIGATION_SUMMER_MIN, IRRIGATION_WINTER_MIN,
                       MEASURED_TILT,
                       MEASURED_TILT_TOL,
                       MOUNT_BLOCK_DEG,
                       MOUNT_RIDGE_FAR_DEG,
                       MOUNT_RIDGE_NEAR_DEG, ROOF_TILT,
                       SYSTEM_GALLONS)
from src.prose import spell
from src.report import Section


def build(data: Analysis) -> Section:
    """What each source can support, and where the numbers stop being measurements."""
    # Everything this section reads from the analysis layer.
    agreement = data.agreement
    bill_files = data.bill_files
    cooling_check = data.cooling_check
    cycle_summer = data.cycle_summer
    days = data.days
    electric = data.electric
    flow_rows = data.flow_rows
    gas_identified_phrase = data.gas_identified_phrase
    glazing_bias = data.glazing_bias
    glazing_pm_am = data.glazing_pm_am
    hourly = data.hourly
    leak_sens = data.leak_sens
    meter_check = data.meter_check
    minisplit = data.minisplit
    normalised = data.normalised
    pump_options = data.pump_options
    pyranometer = data.pyranometer
    scheduled = data.scheduled
    shortfall = data.shortfall
    tariff_checks = data.tariff_checks
    tariff_worst_delta = data.tariff_worst_delta
    utilities = data.utilities
    warm_gas = data.warm_gas
    water_above_tier = data.water_above_tier
    water_events = data.water_events
    weather = data.weather
    with_elec = data.with_elec
    with_util = data.with_util
    # Derived here rather than carried over from the solar and zones
    # sections. A section must never depend on another section having
    # run: this page is assembled from whichever sections had inputs.
    garage_moist = data.couplings.get(("garage", "moisture"))
    west_poa = data.planes[270.0].annual_poa if data.planes.get(270.0) else None
    flat_poa = data.pv_flat.annual_poa if data.pv_flat else None

    gaps_note = ""
    missing = [
        (days[i].date, days[i + 1].date)
        for i in range(len(days) - 1)
        if (days[i + 1].date - days[i].date).days > 1
    ]
    if missing:
        gaps_note = "".join(
            f"<li>Weather gap between {a:%-d %b %Y} and {b:%-d %b %Y}</li>"
            for a, b in missing
        )
    
    provenance = f"""
    <div class="callout callout-note">
      <p class="callout-title">How much to trust each number</p>
      <div class="callout-body">
        <p><strong>Weather</strong> — your WS-2000, {len(weather)} complete days at 5-minute
        resolution. Degree-days are integrated across every sample of the day —
        {statistics.fmean([d.weather.samples for d in days]):.0f} on average, exactly 288 on
        {sum(1 for d in days if d.weather.samples == 288)} of {len(days)} days — rather than
        derived from (max+min)/2, which matters near the balance point where the fits live.
        The station agrees closely with the weather UtilityHawk reports independently:
        daily highs r = {agreement.get('high_r', 0):.3f} (bias {agreement.get('high_bias', 0):+.1f}°F),
        lows r = {agreement.get('low_r', 0):.3f} (bias {agreement.get('low_bias', 0):+.1f}°F)
        over {agreement.get('n', 0)} days. The station's authority here is earned, not assumed.</p>
    
        <p><strong>Electricity</strong> — {len(electric)} days of 15-minute interval data,
        {len(with_elec)} of which overlap the weather station. Essentially complete: one day
        carries 92 intervals rather than 96, which is the spring-forward hour behaving correctly.</p>
    
        <p><strong>Water and gas</strong> — UtilityHawk supplied {len(utilities)} daily
        readings; {len(with_util)} of them fall inside the weather station's coverage and are
        the ones used here.
        Daily resolution is the binding constraint on leak detection. A leak has to
        lift the quietest day of the week before it registers at all, which sets that
        sensitivity at roughly {leak_sens.detectable_leak_gal:.0f} gallons a day — enough for
        a running toilet, nowhere near enough for a dripping tap, and blind to the one fault
        this house actually had. A split irrigation line leaks only
        while its valve is open, so it never lifts a quiet day at all.
        The hourly series answers a different question and answers it far better: it reads
        each irrigation cycle directly, and a cycle that changes size is visible within a
        week. See <a href="#leak">the leak</a> and
        <a href="#hourly-water">Water, by the hour</a>.</p>
    
        <p><strong>The two electric exports agree — but they are not two measurements.</strong>
        {f'Summing the 15-minute intervals over each of the {meter_check.periods} billing '
         f'periods they fully cover gives {meter_check.interval_kwh:,.0f} kWh against '
         f'{meter_check.billed_kwh:,.0f} kWh billed — a difference of '
         f'{meter_check.total_deviation_pct:+.2f}%, with no single period off by more than '
         f'{meter_check.worst_deviation_pct:.2f}%. The interval file reads consistently a '
         f'hair high, which is what rounding to whole kWh on the bill would produce.'
         if meter_check else 'No billing period is fully covered by the interval export, so no cross-check was possible.'}
        Both files are the utility rendering the same smart meter register two ways, so this
        is a consistency check on the pipeline, not corroboration of the measurement — a
        miscalibrated meter would be miscalibrated in both. What it rules out is a misaligned
        billing boundary, intervals dropped from the export, a scaling error in parsing, or
        mishandled daylight saving. Those are the failure modes actually in play, and nothing
        in this dataset can test the meter itself.</p>
    
        <p><strong>What is genuinely independent</strong> is elsewhere: the backyard weather
        station against UtilityHawk's own weather source (different sensors, different
        operators); the pool pump's electrical signature against a thermometer in the water;
        and that pump's measured draw against its nameplate. Those are separate instruments
        agreeing, and they carry the weight this one cannot.</p>
    
        <p><strong>Money comes from {len(bill_files)} PDF bills, transcribed rate by rate.</strong>
        Nothing here divides a total by a usage figure to guess a price. Every tariff is
        typed from a bill and checked against it on each build — all
        {len(tariff_checks)} checks reproduce their source to within
        {spell(math.ceil(tariff_worst_delta * 100))} cents, and the
        build aborts if any drifts. The worst disagreement across all of them is
        {tariff_worst_delta * 100:.1f}
        cents, on {max(tariff_checks, key=lambda c: abs(c.expected - c.actual)).label
        if tariff_checks else "—"}. Listing all {len(tariff_checks)} passes would say
        nothing the sentence before it does not; the build failing is what carries the
        claim.</p>
    
        <p><strong>What {len(bill_files)} bills still cannot pin down.</strong> A complete
        year of both utilities — {sum(1 for f in bill_files if f.name.startswith("epe"))} EPE
        and {sum(1 for f in bill_files if f.name.startswith("lascruces"))} Las Cruces, one per
        meter read. Every rate below is now read off a bill for the month it applies to rather
        than carried forward from a neighbouring one, so these are the remaining edges:</p>
        <ul>{"".join(f"<li>{charts.esc(gap)}</li>" for gap in tariff.KNOWN_GAPS)}</ul>
        {f"<p>In this dataset that matters for {len(water_above_tier)} month(s) — "
         f"{charts.esc(', '.join(water_above_tier))} — where water use exceeded 6,000 gallons "
         f"and the cost shown is a lower bound.</p>" if water_above_tier else ""}
    
        <p><strong>Meter quantisation.</strong> The gas meter reads in whole Mcf and the bill
        charges whole dekatherms, so a month of 552 cf is billed as a full 1,000 cf. The water
        meter reads in whole 1,000-gallon units. UtilityHawk's daily figures are finer than
        either meter, which is why a month's daily sum need not land exactly on the billed
        volume — over the June–July 2026 period the daily water figures totalled 5,874 gal
        against 6,000 billed, a 2.1% difference entirely explained by rounding.</p>
    
        <p><strong>Caveats worth keeping in view.</strong> What follows is load-bearing
        for numbers on this page and is <em>not</em> measured:</p>
        <ul>
          <li><strong>Pool heater efficiency at
          {costs.APPLIANCE_EFFICIENCY:.0%}.</strong> Its label prints an input rating and no
          efficiency, and it is the only appliance still relying on the assumption — the pool
          and spa heating costs and the per-degree figures all run through it. A real heater between 70% and 85% moves those by roughly a
          fifth either way. The furnace, which prints both
          {equipment.FURNACE_INPUT_BTU:,.0f} BTU/h in and {equipment.FURNACE_OUTPUT_BTU:,.0f}
          out, comes to {equipment.FURNACE_EFFICIENCY:.1%} — within
          {abs(equipment.FURNACE_EFFICIENCY - costs.APPLIANCE_EFFICIENCY) * 100:.1f} of a
          point of the assumed figure, and the only independent support the pool heater's
          number has.</li>
    
          <li><strong>Pump flow at {costs.PUMP_FLOW_GPM:.0f} GPM.</strong> The turnover counts
          scale inversely with it: at 45 GPM today's runtime is
          {scheduled.hours / costs.turnover_hours(SYSTEM_GALLONS, 45):.1f} turnovers rather
          than {pump_options[0].turnovers:.1f}. Assumed, but bounded: the filter's
          private-pool rating of {equipment.FILTER_MAX_GPM_PRIVATE:.0f} GPM caps
          it, and even at that ceiling the runtime is
          {scheduled.hours / costs.turnover_hours(SYSTEM_GALLONS, equipment.FILTER_MAX_GPM_PRIVATE):.1f}
          turnovers. The conclusion that it runs well past one or two survives the whole
          admissible range; the exact figure does not.</li>
    
          {f'''<li><strong>That the March drain was complete.</strong> The refill itself is now
          measured rather than inferred — the hourly register puts
          {hourly.refill_net:,.0f} gallons into the system over 28 hours, against the
          {SYSTEM_GALLONS:,.0f} this page uses. But that is how much water went <em>in</em>,
          which equals the system volume only if the drain emptied it. That it did is the
          owner's account, not a measurement; a partial drain would mean a larger pool and a
          proportionally larger per-degree cost.</li>'''
           if hourly else ''}
    
          <li><strong>The patio's glazing — the coefficient, not the area.</strong>
          The glass is measured: {equipment.PATIO_GLAZING_FT[0] * 12:.0f} ×
          {equipment.PATIO_GLAZING_FT[1] * 12:.0f} inches over both doors,
          {equipment.PATIO_GLAZING_SQFT:.0f} sq ft. The solar heat gain coefficient is assumed at
          {costs.GLAZING_SHGC:.2f}, so the conduction half of the mini-split's cooling
          ({minisplit.cooling_kwh - minisplit.solar_kwh:,.0f} kWh of electricity) is derived from
          measurement and the solar half ({minisplit.solar_kwh:,.0f} kWh of electricity) is
          half-measured — right area, assumed transmittance. Not to be confused with the
          similar-looking insolation figures in that section, which are kWh per square meter
          falling on the glass rather than kilowatt-hours drawn by the heat pump.
          One knock-on from the solar section belongs here too: this window is projected from
          the same station whose eastern sky is blocked by the roof ridge, so its mornings are
          under-read. A due-south window should collect near-symmetrically about noon and this
          one comes out {glazing_pm_am:.2f} afternoon-to-morning, which puts the annual figure
          roughly {glazing_bias:.0%} low. That is small next to the assumed transmittance
          above, and in the opposite direction to it, but it is a floor rather than a
          correction — nothing here has been adjusted for it.</li>
    
          {f'''<li><strong>Weather before {days[0].date:%b %Y}</strong> is a NOAA proxy. Not
          because the station was not there — it was, and it was recording — but because
          AmbientWeather only serves a rolling year, so the earlier record exists and
          cannot be fetched. The proxy carries
          ±{normalised.proxy_sd:.1f} kWh/day of error over the one year where it could be
          checked — and proxy-era periods scatter
          {statistics.stdev(normalised.by_source['proxy']):.1f} kWh/day against the station
          era's {normalised.station_sd:.1f}, more than that error alone explains. Individual
          pre-{days[0].date:%Y} periods should not be read closely; only the multi-year
          average is solid.</li>''' if normalised else ''}
    
          {f'''<li><strong>The solar sensor is not used for solar.</strong> The station's
          pyranometer reads {pyranometer.shortfall:.0%} low against NSRDB, and only
          {shortfall.instrument:.0%} of that is the instrument — the rest is an eastern
          horizon standing about {MOUNT_BLOCK_DEG:.0f}° up. Once the mount height is
          measured rather than estimated, the roof can account for at most
          {MOUNT_RIDGE_FAR_DEG:.0f}° of that and possibly as little as
          {MOUNT_RIDGE_NEAR_DEG:.0f}°; the balance is most likely the trees due east, whose
          height is unmeasured, so this page does not claim to have divided them. That is
          invisible on a
          south plane and disqualifying on an east one, so plane-of-array here comes from
          PVWatts. <strong>It is the only modeled input on this page</strong>, and it brings
          typical-year weather with it: the monthly figures answer what an array would do in a
          normal year, not what it would have done in this one. Where the station is still
          used it is scaled by ×{pyranometer.scale:.2f}, which a flat PVWatts plane
          independently confirms to about 2%.</li>

          <li><strong>The roof pitch is measured to about a degree.</strong>
          {MEASURED_TILT:.1f}° ± {MEASURED_TILT_TOL:.0f}° by phone inclinometer.
          The PVWatts runs were commissioned at {ROOF_TILT:.1f}°, inside that band, and are
          kept: plane-of-array moves about
          {abs((west_poa - flat_poa) / ROOF_TILT):.0f} kWh/m² per degree here, so the whole
          band is worth about
          {abs((west_poa - flat_poa) / ROOF_TILT) * MEASURED_TILT_TOL / west_poa:.1%}. Pitch
          matters four to five times more on an east-west roof than on a south one — the
          span of common pitches covers about 9% of production rather than 2% — which is why
          a degree of resolution was enough and a guess was not.</li>'''
           if pyranometer and shortfall and west_poa and flat_poa else ''}

          {f'''<li><strong>The two irrigation runtimes are the owner's account, not a
          measurement.</strong> {IRRIGATION_WINTER_MIN:.0f} minutes in winter and
          {IRRIGATION_SUMMER_MIN:.0f} in summer, read off the Hunter X-Core. An hourly bucket
          records volume and never duration, so nothing here can check them directly — the
          corroboration is indirect and worth stating as such: dividing every clean month's
          cycle by the runtime it was set to yields
          {min(r[3] for r in flow_rows):.2f}–{max(r[3] for r in flow_rows):.2f} GPM across
          both programs, and a wrong pair of runtimes would have produced two different
          flow rates rather than one. That is evidence, not proof.</li>'''
           if flow_rows else ''}
    
          {f'''<li><strong>The hourly record does not reach back before
          {hourly.periods[0].start:%B %Y}.</strong> It covers
          {sum(p.days for p in hourly.periods):,} days, which is enough to hold one summer
          against the previous one — the comparison the leak rests on. It is not enough to
          say whether the {cycle_summer:.0f}-gallon summer cycle is itself normal for this
          system, only that it held for two seasons before it stopped. A second clean summer
          would settle that, and there is no way to fetch one retrospectively.</li>'''
           if hourly else ''}
    
          <li><strong>The condenser's power factor at {equipment.ASSUMED_POWER_FACTOR:.2f}.</strong>
          A nameplate prints amps, not watts, so turning
          {equipment.COMPRESSOR_RLA + equipment.CONDENSER_FAN_FLA:.1f} A at
          {equipment.NAMEPLATE_VOLTS:.0f} V into the
          {equipment.rated_draw_kw():.2f} kW ceiling needs one. It is typical for a
          single-phase hermetic compressor under load but is not on the label, and it is
          load-bearing twice over: the unit's
          {cooling_check.load_factor:.0%} load factor would be
          {cooling_check.measured_kw / equipment.rated_draw_kw(1.0):.0%} at unity, and the
          open-door section's headroom argument moves with it. The measured
          {cooling_check.measured_kw:.2f} kW does not — that is a meter reading.</li>
    
          <li><strong>The five hygrometers were never cross-calibrated.</strong> Nothing here
          establishes that they agree, so between-zone moisture is reported as regression
          slopes, which a constant offset cannot move, rather than as differences of means,
          which it can. The zone comparisons are built to survive an error of about a gram
          per kilogram in any one sensor{
          f'; the garage and shed happen to agree to {abs(garage_moist.intercept):.2f} g/kg '
          f'once the house is accounted for, but that is a result rather than an assumption'
          if garage_moist else ''}.</li>
        </ul>
    
        <p><strong>What is identified, and on what evidence.</strong> The 15:15 timer block is
        the pool pump, on three independent grounds — the 1.65 kW electrical step, the water
        temperature stepping at the same quarter-hour, and an
        A.O. Smith SQ1102 nameplate that predicts 1,641 W against 1,650 W measured. And
        {gas_identified_phrase} are
        identified rather than merely flagged: {warm_gas.total_events if warm_gas else 0} are
        pool heating on days with no heating demand, and the other
        {len([e for e in water_events if e.kind == 'spa'])} are evening spa soaks, pinned by the
        absence of sun at their peak. {len(equipment.TRANSCRIBED)} appliance nameplates have since
        been transcribed. They put the furnace's efficiency at
        {equipment.FURNACE_EFFICIENCY:.1%} from its printed input and output, and establish that
        the central system <strong>cools only</strong>, so central heat is the gas furnace
        and the patio mini-split is the property's only heat pump.
        {'<br>Weather gaps: <ul>' + gaps_note + '</ul>' if gaps_note else ''}</p>
      </div>
    </div>
    """

    section = (
        Section(
            id="provenance",
            emoji="🗂️",
            title="Data & provenance",
            lede="What each source can support, and where the numbers stop being measurements.",
            blocks=[provenance],
            collapsed=True,
            fold_label="Show what each source can and cannot support",
        )
    )
    return section
