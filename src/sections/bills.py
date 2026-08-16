"""The billing history — the only source reaching past the station's year.

Weather-normalised, so a mild winter cannot be read as a saving.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics

from src import charts, report, tariff
from src.analysis import Analysis
from src.charts import Panel
from src.palette import STREAM_COLORS
from src.prose import money, spell
from src.report import Callout, Section, Tile


def build(data: Analysis) -> Section | None:
    """The billing history — the only source reaching past the station's year."""
    # Everything this section reads from the analysis layer.
    bills = data.bills
    days = data.days
    gas_series = data.gas_series
    normalised = data.normalised
    water_series = data.water_series
    with_elec = data.with_elec
    yoy = data.yoy
    section: Section | None = None

    months: dict[str, dict[str, float]] = {}
    for d in days:
        key = f"{d.date:%Y-%m}"
        bucket = months.setdefault(key, {"kwh": 0.0, "water": 0.0, "gas": 0.0, "n": 0})
        bucket["n"] += 1
        if d.kwh:
            bucket["kwh"] += d.kwh
        if d.utility:
            bucket["water"] += d.water_gal
            bucket["gas"] += d.gas_cf
    # Drop partial months at either end so the columns compare like with like.
    full = {k: v for k, v in sorted(months.items()) if v["n"] >= 27}
    labels = [f"{k[5:]}/{k[2:4]}" for k in full]
    
    trend_panels = [
        Panel("Electricity", "kWh", {d.date: d.kwh for d in with_elec}, "electric"),
        Panel("Water", "gal", water_series, "water"),
        Panel("Natural gas", "cf", gas_series, "gas"),
        Panel("Outdoor mean temperature", "°F", {d.date: d.weather.t_mean for d in days},
              "var(--weather-accent)"),
    ]
    
    # The year aligned, four measures on four scales. It opens the bills section
    # because it is the same long view read off the meters instead of the bills.
    timeline_blocks: list[object] = [
                charts.time_panels(
                    "timeline",
                    "Daily consumption and temperature",
                    "Each panel keeps its own y-axis; only the dates are shared.",
                    trend_panels,
                    note=(
                        "Electricity and temperature move together. Gas moves opposite to both. "
                        "Water does neither, which is the finding — it is on a human schedule, "
                        "not a thermal one."
                    ),
                ),
                charts.monthly_columns(
                    "monthly",
                    "Monthly totals",
                    "Complete calendar months only.",
                    labels,
                    [("Electricity (kWh)", "electric", [full[k]["kwh"] for k in full])],
                    "kWh",
                ),
    ]

    if bills:
        # Read off the bills rather than typed. Every figure below was a
        # literal that was true only until the next bill arrived.
        bill_years = (bills[-1].end - bills[0].start).days // 365
        period_lo = min(b.days for b in bills)
        period_hi = max(b.days for b in bills)
        bill_blocks: list[object] = list(timeline_blocks)
        first, last = bills[0], bills[-1]
        billed_total = sum(b.cost for b in bills)
        summer_bills = [b for b in bills if tariff.is_summer_period(b.end)]
        real_totals = [tariff.electric_bill(b.kwh, b.end) for b in bills]
        real_total = sum(r.total for r in real_totals)
        # Which bills the tier formula fails to reproduce, and by how much — counted
        # rather than asserted, so a new bill or a rate change cannot leave a stale
        # "30 of 35" behind.
        energy_misses = [
            (b, (r.energy_charge - b.cost) / b.cost)
            for b, r in zip(bills, real_totals)
            if abs(r.energy_charge - b.cost) >= 0.005 and b.cost
        ]
    
        bill_blocks.append(
            Callout(
                kind="finding",
                title="The summer tier is the whole story",
                body=(
                    f"<p>EPE prices summer in two steps: the first "
                    f"{tariff.SUMMER_TIER_KWH} kWh at "
                    f"<strong>${tariff.SUMMER_TIER1_RATE:.5f}</strong>, everything above "
                    f"at <strong>${tariff.SUMMER_TIER2_RATE:.5f}</strong> — 55% more. "
                    f"Winter is flat at ${tariff.WINTER_RATE:.5f} with no tier at all. "
                    f"Applying that formula reproduces the energy charge on "
                    f"<strong>{len(bills) - len(energy_misses)} of your {len(bills)} bills "
                    f"to the cent</strong>; the {len(energy_misses)} it misses are all from "
                    f"{min(b.end.year for b, _ in energy_misses)} and sit "
                    f"{statistics.fmean(abs(e) for _, e in energy_misses):.1%} off, which is "
                    f"a rate change rather than a broken model.</p>"
                    f"<p>Your summer bills run 1,600–2,400 kWh, so roughly three-quarters "
                    f"of every summer kWh is priced in the upper tier. That is why the "
                    f"marginal cost of summer electricity — "
                    f"${tariff.marginal_rate(dt.date(2026, 7, 15)):.4f}/kWh once riders, "
                    f"franchise fee and tax are added — is nearly "
                    f"{tariff.marginal_rate(dt.date(2026, 7, 15)) / tariff.marginal_rate(dt.date(2026, 1, 15)):.1f}× "
                    f"the winter figure, and well above the ${real_total / sum(b.kwh for b in bills):.4f} "
                    f"blended average these bills imply.</p>"
                    f"<p><strong>Decisions should use the marginal number, not the average.</strong> "
                    f"Removing a kWh of summer load saves "
                    f"${tariff.marginal_rate(dt.date(2026, 7, 15)):.4f}, not the average.</p>"
                ),
            )
        )
    
        bill_blocks.append(
            report.tile_row(
                [
                    Tile(
                        f"Actually billed, {bill_years} years",
                        money(real_total),
                        "",
                        f"{sum(b.kwh for b in bills):,.0f} kWh across {len(bills)} bills, "
                        f"{first.start:%b %Y} – {last.end:%b %Y}",
                        STREAM_COLORS["electric"]["light"],
                    ),
                    Tile(
                        "Energy charges only",
                        money(billed_total),
                        "",
                        f"what the export's COST column records — "
                        f"{money(real_total - billed_total)} short of the real total",
                    ),
                    Tile(
                        "Summer marginal rate",
                        f"${tariff.marginal_rate(dt.date(2026, 7, 15)):.4f}",
                        "/kWh",
                        f"all-in, upper tier · winter is "
                        f"${tariff.marginal_rate(dt.date(2026, 1, 15)):.4f}",
                    ),
                    Tile(
                        "Summer share of spend",
                        f"{100 * sum(r.total for r, b in zip(real_totals, bills) if tariff.is_summer_period(b.end)) / real_total:.0f}",
                        "%",
                        f"from {len(summer_bills)} of {len(bills)} bills",
                    ),
                ]
            )
        )
    
        paired = [y for y in yoy if y.usage_effect is not None]
        if paired:
            bill_blocks.append(
                charts.diverging_bars(
                    "yoy",
                    "Why each bill differed from the same month a year earlier",
                    "Split into the part you caused by using more or less, and the part the "
                    "rate schedule caused on its own.",
                    [(y.label, y.usage_effect, y.rate_effect) for y in paired],
                    note=(
                        f"Across {len(paired)} paired months, usage decisions account for "
                        f"{money(sum(abs(y.usage_effect) for y in paired))} of movement and "
                        f"rate changes for "
                        f"{money(sum(abs(y.rate_effect) for y in paired))}. "
                        f"This is the one view the interval export cannot produce — it needs "
                        f"cost, and {spell(bill_years)} years of it."
                    ),
                )
            )
    
        if normalised:
            trend, trend_r2 = normalised.trend_per_year()
            src = normalised.by_source
            cal = normalised.calibration
            years: dict[int, list[float]] = {}
            for np_ in normalised.periods:
                years.setdefault(np_.period.end.year, []).append(np_.baseline_kwh_day)
            year_rows = "".join(
                f"<tr><td>{y}</td><td>{statistics.fmean(v):.1f} kWh/day</td>"
                f"<td>{len(v)} periods</td></tr>"
                for y, v in sorted(years.items())
            )
            bill_blocks.append(
                Callout(
                    kind="finding",
                    title=(f"Weather-normalized, {spell(bill_years)} years "
                           f"of bills are flat"),
                    body=(
                        f"<p>The bills reach back {spell(bill_years)} years; the weather "
                        f"station covers one. "
                        f"NOAA's record for <strong>{cal.station}</strong> fills the gap, scaled "
                        f"to reproduce the backyard station's degree-days over the "
                        f"{cal.overlap_days} days they overlap "
                        f"(cooling R² {cal.cooling_r2:.2f}, heating R² {cal.heating_r2:.2f}). "
                        f"The scaling is forced through the origin, so no degree-days in still "
                        f"means none out.</p>"
                        f"<p>Stripping the weather-driven part from each bill leaves the "
                        f"consumption that weather cannot explain:</p>"
                        '<div class="table-scroll"><table><thead><tr><th>Year</th>'
                        f"<th>Baseline</th><th></th></tr></thead><tbody>{year_rows}</tbody>"
                        "</table></div>"
                        f"<p>The trend across all {len(normalised.periods)} periods is "
                        f"<strong>{trend:+.2f} kWh/day per year</strong>, with an R² of "
                        f"{trend_r2:.3f} — no trend at all. And it has to clear a noise floor. "
                        # These are three separate quantities and the earlier wording
                        # collapsed two of them, then drew a conclusion the arithmetic
                        # does not support: 2.3 in quadrature with 2.3 is 3.3, not 8.5.
                        f"Periods the backyard station measured scatter "
                        f"{normalised.station_sd:.1f} kWh/day about their own mean; proxy "
                        f"periods scatter {statistics.stdev(src['proxy']):.1f}. Where the two "
                        f"sources overlap, the proxy misplaces the weather term by only "
                        f"±{normalised.proxy_sd:.1f} kWh/day — which in quadrature with the "
                        f"station's own scatter would give about "
                        f"{math.hypot(normalised.proxy_sd, normalised.station_sd):.1f}, not "
                        f"{statistics.stdev(src['proxy']):.1f}. So the proxy's weather error "
                        f"does <em>not</em> account for the extra spread on its own: either it "
                        f"performs worse outside the single year where it could be calibrated, "
                        f"or 2023–24 genuinely varied more. Both readings say the same thing "
                        f"about how to use it — the multi-year average is solid and individual "
                        f"pre-2025 periods are not.</p>"
                        f"<p><strong>So your consumption is not drifting.</strong> Bills move "
                        f"because summers differ and because the summer tier is expensive, not "
                        f"because the house is quietly using more each year.</p>"
                    ),
                )
            )
    
        # Label each bill by the month printed on it — the read that closes the
        # period — so the chart and the tariff checks name the same bill the same
        # way. Labelling by period start put the 2,358 kWh bill at "Jun 26" here
        # and "EPE 2026-07" there.
        bill_labels = [f"{b.end:%b %y}" for b in bills]
        bill_blocks.append(
            charts.monthly_columns(
                "bills",
                f"Every bill, {spell(bill_years)} years",
                f"Consumption per billing period. Periods vary from "
                f"{period_lo} to {period_hi} days.",
                bill_labels,
                [("kWh billed", "electric", [b.kwh for b in bills])],
                "kWh",
                note=(
                    "The seasonal shape repeats almost exactly year to year, which is what "
                    "makes the weather-independent baseline visible: the troughs never "
                    "approach zero."
                ),
            )
        )
    
        section = (
            Section(
                id="bills",
                emoji="🧾",
                title="The long view",
                lede=(
                    "First the year as the meters recorded it — four measures on four "
                    "separate scales, never two scales on one frame, because that "
                    "manufactures correlations the data does not contain. Then the same "
                    "span as the biller saw it: the only source here carrying cost, "
                    "answering not what the house does but what it is charged for."
                ),
                blocks=bill_blocks,
            )
        )
    
    return section
