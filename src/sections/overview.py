"""The top of the page: what the year cost, and what it was measured with.

Headline total, the four meter tiles, and the manifest of sources.
"""

from __future__ import annotations

import math

from src import datafiles, equipment, report, tariff
from src.analysis import Analysis
from src.palette import STREAM_COLORS
from src.prose import money, spell
from src.report import Section, Tile


SOURCE_ROW = "<tr><td>"


def sources_table(data: Analysis) -> str:
    """The manifest: every source, its granularity, and what it settles.

    A function rather than a value because the page headline counts its rows.
    """
    bill_files = data.bill_files
    bills = data.bills
    electric = data.electric
    hourly = data.hourly
    noaa_station_count = data.noaa_station_count
    tariff_checks = data.tariff_checks
    tariff_worst_delta = data.tariff_worst_delta
    utilities = data.utilities
    weather = data.weather
    weather_channels = data.weather_channels

    # The rows are built apart from the card so that both the fold label and
    # `source_count` can count them, rather than either asserting a number: the
    # literal "nine sources" outlived the source it counted.
    sources_rows = f"""
      <tr><td>AmbientWeather WS-2000</td><td>5 minutes</td>
          <td>{len(weather)} days</td>
          <td>{weather_channels} channels — five sensed zones with temperature, humidity
          and dew point, plus sun, wind, rain, lightning and the pool probe</td></tr>
      <tr><td>El Paso Electric, interval</td><td>15 minutes</td>
          <td>{len(electric)} days</td>
          <td>Separates what never switches off from what runs to a timer and what
          answers the weather</td></tr>
      <tr><td>El Paso Electric, billing</td><td>per bill</td>
          <td>{len(bills)} periods{f", {bills[0].start:%b %Y}–{bills[-1].end:%b %Y}" if bills else ""}</td>
          <td>The only source carrying cost, and the only one reaching further back
          than the year of station data that can be exported</td></tr>
      <tr><td>City of Las Cruces UtilityHawk</td>
          <td>daily,<br>and hourly</td>
          <td>{len(utilities)} days daily;<br>{sum(w.days for w in hourly.periods) if hourly else 0} days
          hourly, continuous</td>
          <td>Water and gas. The hourly series is what finds a leak — it puts a clock on
          irrigation, measures the pool refill directly, shows the float valve replacing
          evaporation overnight, and caught a split line the daily series structurally
          could not. <strong>The same meter at two granularities, so the two never corroborate
          each other</strong> — where they disagree, the finer one is simply closer</td></tr>
      <tr><td>Utility bills, PDF</td><td>per bill</td>
          <td>{len(bill_files)}</td>
          <td>Every rate on this page, written into the tariff engine as a literal value
          rather than parsed at run time, and re-checked against its source bill on each build —
          {len(tariff_checks)} checks, all reproducing their source to within
          {spell(math.ceil(tariff_worst_delta * 100))} cents</td></tr>
      <tr><td>Appliance nameplates</td><td>per machine</td>
          <td>{len(equipment.TRANSCRIBED)}</td>
          <td>Turns assumptions into readings: furnace efficiency, pool heater rating,
          filter flow ceiling, and what the air conditioner is allowed to draw</td></tr>
      <tr><td>NOAA GHCN-Daily</td><td>daily</td>
          <td>{noaa_station_count} stations</td>
          <td>Stands in for the weather the station's export cannot reach — it has
          been recording far longer than the rolling year that can be downloaded —
          calibrated against it where the two overlap</td></tr>
      <tr><td>NREL PVWatts<br><span class="muted-note">the only modeled input here, and
          the only one not measured at this house</span></td>
          <td>hourly,<br>typical year</td>
          <td>{len(datafiles.find("pvwatts", required=False))} roof planes</td>
          <td>Every plane-of-array figure in the solar section. It is here because the
          station's own pyranometer sits below the roof ridge and loses its eastern sky —
          which a due-south plane would average out but an east-west roof cannot</td></tr>
"""

    # Folded by default: the reader arriving at the top of the page wants the
    # headline number, not a manifest. The card keeps its place and its point —
    # only the manifest itself is behind the summary.
    sources_table = f"""
<div class="card">
  <h3>What this is built from</h3>
  <p class="fig-sub">Granularity matters more than volume here: the same house looks like
  different things at 5 minutes, a day and a billing period, and several of these exist
  only to check another one.</p>
  <details class="section-fold">
    <summary>Show all {sources_rows.count("<tr><td>")} sources, their granularity and what
    each settles</summary>
    <div class="section-fold-body">
      <div class="table-scroll"><table class="prose">
        <thead><tr><th>Source</th><th>Granularity</th><th>Span</th><th>What it settles</th></tr></thead>
        <tbody>{sources_rows}</tbody>
      </table></div>
      <p class="fig-note">Two of these arrived to check figures already derived — the hourly
      water and the nameplates — and both overturned what they were meant to confirm, which is
      why the numbers here are the corrected ones. One source is absent by choice: a charge log
      from the motorcycle's OpenEVSE, a rolling eight-week window that no amount of care turns
      into a year.</p>
    </div>
  </details>
</div>
"""
    return sources_table


def source_count(data: Analysis) -> int:
    """Read off the table itself, so removing a source cannot leave the headline
    claiming it. The literal "nine" survived the charge log by one build.
    """
    return sources_table(data).count(SOURCE_ROW)


def build(data: Analysis) -> Section:
    """The top of the page: what the year cost, and what it was measured with."""
    # Everything this section reads from the analysis layer.
    fixed_other = data.fixed_other
    gas_cost = data.gas_cost
    household_cost = data.household_cost
    span = data.span
    tariff_worst_delta = data.tariff_worst_delta
    total_cost = data.total_cost
    total_gas = data.total_gas
    total_kwh = data.total_kwh
    total_water = data.total_water
    water_cost = data.water_cost
    with_elec = data.with_elec

    tiles = [
        Tile(
            "Electricity",
            money(total_cost),
            "",
            f"{total_kwh:,.0f} kWh over {len(with_elec)} metered days · "
            f"{total_kwh / len(with_elec):.0f} kWh/day · "
            f"{100 * total_cost / household_cost:.0f}% of the total",
            STREAM_COLORS["electric"]["light"],
        ),
        Tile(
            "Natural gas",
            money(gas_cost),
            "",
            f"{total_gas:,.0f} cf · ${tariff.GAS_ACCESS_FEE:.2f}/mo of that is the "
            f"fixed access fee",
            STREAM_COLORS["gas"]["light"],
        ),
        Tile(
            "Water",
            money(water_cost),
            "",
            f"{total_water:,.0f} gal · first 3,000 gal each month are free",
            STREAM_COLORS["water"]["light"],
        ),
        Tile(
            "Wastewater + refuse",
            money(fixed_other),
            "",
            "effectively fixed — neither responds to what you do",
        ),
    ]

    section = (
        Section(
            id="overview",
            emoji="🏠",
            title="Overview",
            lede=(
                f"Every data source this house produces, joined on local calendar date and priced with tariffs "
                f"extracted from the utility bills themselves. Everything is joined over "
                f"<strong>{span}</strong>, the span the weather station covers; the bills, "
                f"the weather proxy and the hourly water meter all reach further back, and "
                f"four late arrivals exist to check what the first five had already "
                f"produced."
            ),
            blocks=[
                report.hero(
                    money(household_cost),
                    "to run this house for a year",
                    f"Electricity, gas, water, wastewater and refuse, priced with the "
                    f"tariffs transcribed from your bills — every rate below reproduces "
                    f"its source bill to within "
                    f"{spell(math.ceil(tariff_worst_delta * 100))} cents. "
                    f"See <a href='#provenance'>Data &amp; Provenance</a>.",
                ),
                report.tile_row(tiles),
                sources_table(data),
            ],
        )
    )
    return section
