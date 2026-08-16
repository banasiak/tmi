"""Extend the weather record backwards with a calibrated NOAA proxy.

The backyard station is the reference; NOAA is only ever a stand-in for the
years before it existed. Two things make that stand-in usable:

  Station choice is measured, not assumed. Each cached candidate is scored
  against the backyard station over the overlapping year, and the best one wins.
  The nearest station is not automatically the best — the airport is the further
  of the two candidates and correlates far better than the nearer cooperative
  site, because instrumentation beats proximity.

  Calibration is forced through the origin. NOAA gives daily max and min; the
  station integrates 288 samples. Regressing one on the other with a free
  intercept invents heating degree-days on an August day and cooling degree-days
  in January — a fixed offset applied to every day of a billing period, which is
  exactly the sort of artifact that looks like a finding.

The proxy's own error is measured on the overlap and reported alongside any
result derived from it, because a normalised baseline is worthless without
knowing how wide the error bars are.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from .model import r_squared
from .sources import BillingPeriod, WeatherDay


@dataclass
class Calibration:
    """A NOAA station, scaled to reproduce the backyard station's degree-days."""

    station: str
    cooling_factor: float
    heating_factor: float
    cooling_r2: float
    heating_r2: float
    overlap_days: int
    daily: dict[dt.date, tuple[float, float]]  # date -> (tmax, tmin)

    @property
    def score(self) -> float:
        return self.cooling_r2 + self.heating_r2

    def cdd(self, day: dt.date, base: float) -> float | None:
        rec = self.daily.get(day)
        if rec is None:
            return None
        return self.cooling_factor * max(0.0, (rec[0] + rec[1]) / 2 - base)

    def hdd(self, day: dt.date, base: float) -> float | None:
        rec = self.daily.get(day)
        if rec is None:
            return None
        return self.heating_factor * max(0.0, base - (rec[0] + rec[1]) / 2)


def _through_origin(xs: list[float], ys: list[float]) -> float:
    """Least squares with the intercept pinned to zero.

    Zero degree-days in must give zero out; a free intercept would sprinkle a
    constant across every day of the year, summer included.
    """
    sxx = sum(x * x for x in xs)
    return sum(x * y for x, y in zip(xs, ys)) / sxx if sxx else 0.0


def load_calibrations(
    cache: Path, station_days: dict[dt.date, WeatherDay], cool_base: float, heat_base: float
) -> list[Calibration]:
    """Score every cached station against the backyard record."""
    out: list[Calibration] = []
    if not cache.exists():
        return out

    for path in sorted(cache.glob("*.json")):
        try:
            rows = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        daily: dict[dt.date, tuple[float, float]] = {}
        for row in rows:
            try:
                daily[dt.date.fromisoformat(row["DATE"])] = (
                    float(row["TMAX"]),
                    float(row["TMIN"]),
                )
            except (KeyError, ValueError, TypeError):
                continue

        overlap = [d for d in daily if d in station_days]
        if len(overlap) < 60:
            continue

        proxy_c = [max(0.0, (daily[d][0] + daily[d][1]) / 2 - cool_base) for d in overlap]
        truth_c = [station_days[d].cdd(cool_base) for d in overlap]
        proxy_h = [max(0.0, heat_base - (daily[d][0] + daily[d][1]) / 2) for d in overlap]
        truth_h = [station_days[d].hdd(heat_base) for d in overlap]

        kc = _through_origin(proxy_c, truth_c)
        kh = _through_origin(proxy_h, truth_h)
        out.append(
            Calibration(
                station=path.stem,
                cooling_factor=kc,
                heating_factor=kh,
                cooling_r2=r_squared(truth_c, [kc * v for v in proxy_c]),
                heating_r2=r_squared(truth_h, [kh * v for v in proxy_h]),
                overlap_days=len(overlap),
                daily=daily,
            )
        )
    out.sort(key=lambda c: -c.score)
    return out


@dataclass
class NormalisedPeriod:
    period: BillingPeriod
    source: str  # "station" | "proxy"
    cdd: float
    hdd: float
    weather_kwh_day: float

    @property
    def baseline_kwh_day(self) -> float:
        """Consumption with the weather-driven part removed."""
        return self.period.kwh_per_day - self.weather_kwh_day


@dataclass
class Normalisation:
    periods: list[NormalisedPeriod]
    calibration: Calibration
    proxy_bias: float  # kWh/day the proxy misplaces on the weather term
    proxy_sd: float
    station_sd: float

    @property
    def by_source(self) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {"station": [], "proxy": []}
        for p in self.periods:
            out[p.source].append(p.baseline_kwh_day)
        return out

    def trend_per_year(self) -> tuple[float, float]:
        """Slope in kWh/day per year, and the R2 behind it."""
        if len(self.periods) < 4:
            return 0.0, 0.0
        origin = min(p.period.end for p in self.periods)
        xs = [(p.period.end - origin).days for p in self.periods]
        ys = [p.baseline_kwh_day for p in self.periods]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            return 0.0, 0.0
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        pred = [my + slope * (x - mx) for x in xs]
        return slope * 365.0, r_squared(ys, pred)


def normalise_billing(
    bills: list[BillingPeriod],
    station_days: dict[dt.date, WeatherDay],
    calibration: Calibration,
    cool_base: float,
    heat_base: float,
    cooling_slope: float,
    heating_slope: float,
) -> Normalisation:
    """Strip weather out of every billing period the record can reach."""
    periods: list[NormalisedPeriod] = []
    proxy_errors: list[float] = []

    for bill in bills:
        span = [bill.start + dt.timedelta(days=i) for i in range(bill.days)]
        have_station = [d for d in span if d in station_days]
        have_proxy = [d for d in span if d in calibration.daily]

        # Where both exist, measure what the proxy would have got wrong.
        if len(have_station) >= bill.days - 1 and len(have_proxy) >= bill.days * 0.9:
            true_w = (
                cooling_slope * sum(station_days[d].cdd(cool_base) for d in have_station)
                + heating_slope * sum(station_days[d].hdd(heat_base) for d in have_station)
            ) / bill.days
            scale = bill.days / len(have_proxy)
            proxy_w = (
                cooling_slope * sum(calibration.cdd(d, cool_base) for d in have_proxy) * scale
                + heating_slope * sum(calibration.hdd(d, heat_base) for d in have_proxy) * scale
            ) / bill.days
            proxy_errors.append(proxy_w - true_w)

        if len(have_station) >= bill.days - 1:
            cdd = sum(station_days[d].cdd(cool_base) for d in have_station)
            hdd = sum(station_days[d].hdd(heat_base) for d in have_station)
            source = "station"
        elif len(have_proxy) >= bill.days * 0.9:
            scale = bill.days / len(have_proxy)
            cdd = sum(calibration.cdd(d, cool_base) for d in have_proxy) * scale
            hdd = sum(calibration.hdd(d, heat_base) for d in have_proxy) * scale
            source = "proxy"
        else:
            continue

        periods.append(
            NormalisedPeriod(
                period=bill,
                source=source,
                cdd=cdd,
                hdd=hdd,
                weather_kwh_day=(cooling_slope * cdd + heating_slope * hdd) / bill.days,
            )
        )

    by_source: dict[str, list[float]] = {"station": [], "proxy": []}
    for p in periods:
        by_source[p.source].append(p.baseline_kwh_day)

    return Normalisation(
        periods=periods,
        calibration=calibration,
        proxy_bias=statistics.fmean(proxy_errors) if proxy_errors else 0.0,
        proxy_sd=statistics.stdev(proxy_errors) if len(proxy_errors) > 1 else 0.0,
        station_sd=(
            statistics.stdev(by_source["station"]) if len(by_source["station"]) > 1 else 0.0
        ),
    )
