"""Inline-SVG chart builders.

Everything renders to a string of SVG with a `viewBox`, so charts scale with
their container and carry no external dependency. Colours are referenced as CSS
custom properties rather than literal hex, which is what lets one stylesheet
swap the whole page between light and dark.

Conventions held across every chart here:
  * gridlines and axes are solid 1px hairlines, one step off the surface
  * marks are thin; area fills are a ~10% wash, never a saturated block
  * a 2px surface gap separates touching marks; dots carry a 2px surface ring
  * labels are selective — endpoints and extremes, never a number per point
  * text wears ink tokens; identity comes from the coloured mark beside it
  * every figure ships a table twin, so no value is reachable by colour alone
"""

from __future__ import annotations

import datetime as dt
import html
import math
from dataclasses import dataclass, field

from .palette import STATUS, ramp_for

# Charts are authored against this user-unit width and scaled by the container.
W = 900


@dataclass
class Figure:
    """A chart plus the accessible twin that must accompany it."""

    id: str
    title: str
    svg: str
    subtitle: str = ""
    note: str = ""
    table_headers: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    legend: list[tuple[str, str]] = field(default_factory=list)  # (css color, label)


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def fmt(value: float, unit: str = "") -> str:
    if value is None:
        return "—"
    if abs(value) >= 1000:
        body = f"{value:,.0f}"
    elif abs(value) >= 100:
        body = f"{value:.0f}"
    elif abs(value) >= 10:
        body = f"{value:.1f}"
    else:
        body = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{body}{unit}"


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Round axis ticks to 1/2/5 x 10^k so labels read as clean numbers."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        step = mag * mult
        if raw <= step:
            break
    start = math.floor(lo / step) * step
    ticks, value = [], start
    # Stop at `hi`, never past it: a tick beyond the data maximum lands outside
    # the plot area and its label renders off-canvas.
    while value <= hi + step * 1e-9:
        if value >= lo - step * 1e-9:
            ticks.append(round(value, 10))
        value += step
    return ticks


def clip_segment(
    x0: float, y0: float, x1: float, y1: float,
    x_lo: float, x_hi: float, y_lo: float, y_hi: float,
) -> tuple[float, float, float, float] | None:
    """Clip a line to a rectangle in data space (Liang-Barsky).

    Fitted and reference lines are defined by their slope, not by the plot's
    extent, so an unclipped one happily runs hundreds of units past the frame —
    which is how a label ends up 1,500 units above the chart.
    """
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - x_lo), (dx, x_hi - x0), (-dy, y0 - y_lo), (dy, y_hi - y0)):
        if p == 0:
            if q < 0:
                return None  # parallel to this edge and outside it
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return (x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy)


def quantile_edges(values: list[float], bins: int = 7) -> list[float]:
    """Bin edges at even quantiles, rounded outward to readable numbers.

    Utility usage is heavily right-skewed — a linear ramp would put 95% of days
    in the first colour. Quantiles spread the ramp across the data that exists,
    and the legend prints the real boundaries so magnitude is never implied by
    colour alone.
    """
    pool = sorted(v for v in values if v is not None)
    if not pool:
        return []
    edges: list[float] = []
    for i in range(1, bins):
        idx = int(len(pool) * i / bins)
        edges.append(pool[min(idx, len(pool) - 1)])

    out: list[float] = []
    for e in edges:
        if e <= 0:
            rounded = 0.0
        else:
            mag = 10 ** math.floor(math.log10(e))
            rounded = round(e / mag) * mag
        if not out or rounded > out[-1]:
            out.append(rounded)
    return out


def bin_index(value: float, edges: list[float]) -> int:
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _axis_left(x: float, y0: float, y1: float, ticks, scale, label_fn) -> str:
    parts = [
        f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" '
        f'stroke="var(--ink-axis)" stroke-width="1"/>'
    ]
    for t in ticks:
        y = scale(t)
        parts.append(
            f'<text x="{x - 8}" y="{y + 4}" text-anchor="end" font-size="11" '
            f'fill="var(--ink-muted)" style="font-variant-numeric:tabular-nums">'
            f"{esc(label_fn(t))}</text>"
        )
    return "".join(parts)


def _gridlines(x0: float, x1: float, ticks, scale) -> str:
    return "".join(
        f'<line x1="{x0}" y1="{scale(t)}" x2="{x1}" y2="{scale(t)}" '
        f'stroke="var(--ink-grid)" stroke-width="1"/>'
        for t in ticks
    )


def paint(token: str | None) -> str:
    """Resolve a series colour from a stream name or a literal.

    The three stream colours mean electricity, gas and water and nothing else,
    so a chart plotting temperature, rainfall, a model's prediction or a total
    across meters must not reach for one. Those pass a literal instead —
    `var(--zone-accent)` for measured-but-not-a-utility — and this is the single
    place that decides which it got. `None` means neutral ink: context, not a
    series with an identity.
    """
    if not token:
        return "var(--ink-muted)"
    return token if token.startswith(("var(", "#")) else f"var(--stream-{token})"


def _svg(height: float, body: str, aria: str) -> str:
    return (
        f'<svg viewBox="0 0 {W} {height}" width="100%" height="auto" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="{esc(aria)}" class="chart">{body}</svg>'
    )


# ---------------------------------------------------------------------------
# Calendar heatmap
# ---------------------------------------------------------------------------

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def calendar_heatmap(
    fig_id: str,
    title: str,
    subtitle: str,
    series: dict[dt.date, float],
    stream: str,
    unit: str,
    note: str = "",
) -> Figure:
    """A year of daily values as a week x weekday grid.

    This is the view that makes an anomaly impossible to miss: a single dark
    cell in a field of pale ones needs no statistics to read.
    """
    if not series:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    ramp = ramp_for(stream)
    dates = sorted(series)
    start = dates[0]
    grid_start = start - dt.timedelta(days=start.weekday())
    edges = quantile_edges(list(series.values()), bins=len(ramp) - 2)

    cell, gap = 13, 2
    pitch = cell + gap
    left, top = 44, 34
    height = top + 7 * pitch + 34

    parts: list[str] = []

    # Month labels ride the top, placed at each month's first column.
    seen: set[tuple[int, int]] = set()
    for d in dates:
        key = (d.year, d.month)
        if key in seen:
            continue
        seen.add(key)
        col = (d - grid_start).days // 7
        parts.append(
            f'<text x="{left + col * pitch}" y="{top - 10}" font-size="11" '
            f'fill="var(--ink-muted)">{_MON[d.month - 1]}</text>'
        )

    for i, name in enumerate(_DOW):
        if i % 2 == 0:
            parts.append(
                f'<text x="{left - 8}" y="{top + i * pitch + cell - 2}" '
                f'text-anchor="end" font-size="10" fill="var(--ink-muted)">{name}</text>'
            )

    for d in dates:
        value = series[d]
        col = (d - grid_start).days // 7
        row = d.weekday()
        x = left + col * pitch
        y = top + row * pitch
        color = ramp[bin_index(value, edges)]
        tip = f"{d:%a %-d %b %Y} — {fmt(value)} {unit}"
        # The 2px pitch gap is the separator; no stroke is drawn around cells.
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
            f'fill="{color}" data-tip="{esc(tip)}" tabindex="0"/>'
        )

    # Legend: prints real boundaries, so colour never has to carry magnitude.
    ly = top + 7 * pitch + 20
    parts.append(
        f'<text x="{left}" y="{ly + 10}" font-size="11" fill="var(--ink-secondary)">'
        f"Less</text>"
    )
    lx = left + 34
    for i, color in enumerate(ramp[: len(edges) + 1]):
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" '
            f'fill="{color}"/>'
        )
        lx += pitch
    parts.append(
        f'<text x="{lx + 6}" y="{ly + 10}" font-size="11" fill="var(--ink-secondary)">'
        f"More · breaks at {esc(', '.join(fmt(e) for e in edges))} {esc(unit)}</text>"
    )

    rows = [
        [f"{d:%Y-%m-%d}", f"{d:%a}", fmt(series[d]), unit]
        for d in sorted(series, key=lambda k: series[k], reverse=True)[:25]
    ]
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: daily {unit} calendar heatmap"),
        table_headers=["Date", "Day", "Value", "Unit"],
        table_rows=rows,
    )


# ---------------------------------------------------------------------------
# Energy signature scatter
# ---------------------------------------------------------------------------


def signature_scatter(
    fig_id: str,
    title: str,
    subtitle: str,
    points: list[tuple[float, float, str, bool]],
    stream: str,
    x_label: str,
    y_label: str,
    fit_line: tuple[float, float] | None = None,
    note: str = "",
) -> Figure:
    """Usage against degree-days, with the fitted line drawn through it.

    `points` are (x, y, tooltip, is_outlier). Outliers keep their position but
    wear the critical status colour — hiding them would misrepresent the year,
    and they are the entire reason the fit needed trimming.
    """
    if not points:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 380
    left, right, top, bottom = 62, 24, 22, 52
    plot_w, plot_h = W - left - right, height - top - bottom

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_max = max(xs) * 1.04 or 1
    y_max = max(ys) * 1.08 or 1

    def sx(v: float) -> float:
        return left + v / x_max * plot_w

    def sy(v: float) -> float:
        return top + plot_h - v / y_max * plot_h

    x_ticks = nice_ticks(0, x_max)
    y_ticks = nice_ticks(0, y_max)

    parts = [_gridlines(left, left + plot_w, y_ticks, sy)]
    parts.append(_axis_left(left, top, top + plot_h, y_ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    for t in x_ticks:
        parts.append(
            f'<text x="{sx(t)}" y="{top + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">{esc(fmt(t))}</text>'
        )

    if fit_line:
        intercept, slope = fit_line
        seg = clip_segment(
            0.0, intercept, x_max, intercept + slope * x_max, 0.0, x_max, 0.0, y_max
        )
        if seg:
            ax, ay, bx, by = seg
            parts.append(
                f'<line x1="{sx(ax):.1f}" y1="{sy(ay):.1f}" x2="{sx(bx):.1f}" '
                f'y2="{sy(by):.1f}" stroke="{paint(stream)}" stroke-width="2" '
                f'stroke-linecap="round" opacity="0.85"/>'
            )

    # Excluded points are smaller, quieter and drawn first, so the data the fit
    # actually used sits on top of them. Size and colour carry the distinction;
    # an earlier version drew them as hollow rings, which was worse — a ring has
    # two contours to a dot's one, so it reads heavier than the solid marks it is
    # meant to sit behind, and a stack of them at the same x becomes a chain of
    # donuts. The colour is a measured pair: critical red against gas orange came
    # out at dE 10.8 light and 6.8 dark, both under the readable floor of 15.
    for x, y, tip, outlier in points:
        if outlier:
            parts.append(
                f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3" '
                f'fill="var(--mark-excluded)" fill-opacity="0.75" '
                f'data-tip="{esc(tip)}" tabindex="0"/>'
            )
    for x, y, tip, outlier in points:
        if not outlier:
            parts.append(
                f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" '
                f'fill="{paint(stream)}" fill-opacity="0.6" '
                f'stroke="var(--ink-surface)" stroke-width="2" '
                f'data-tip="{esc(tip)}" tabindex="0"/>'
            )

    parts.append(
        f'<text x="{left + plot_w / 2}" y="{height - 10}" text-anchor="middle" '
        f'font-size="11" fill="var(--ink-secondary)">{esc(x_label)}</text>'
    )
    parts.append(
        f'<text x="14" y="{top + plot_h / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {top + plot_h / 2})">'
        f"{esc(y_label)}</text>"
    )

    outliers = [p for p in points if p[3]]
    rows = [[p[2], fmt(p[0]), fmt(p[1]), "outlier" if p[3] else "in fit"] for p in
            sorted(points, key=lambda p: -p[1])[:25]]
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: {y_label} against {x_label}"),
        table_headers=["Day", x_label, y_label, "Role"],
        table_rows=rows,
        # One series needs no legend box — the title already names what is
        # plotted. The box earns its place only once outliers add a second mark.
        legend=(
            [
                (paint(stream), "Explained by the fit"),
                ("var(--mark-excluded)", f"Held out of the fit ({len(outliers)})"),
            ]
            if outliers
            else []
        ),
    )


# ---------------------------------------------------------------------------
# Stacked time panels (small multiples sharing one x-axis)
# ---------------------------------------------------------------------------


@dataclass
class Panel:
    label: str
    unit: str
    values: dict[dt.date, float]
    stream: str | None = None  # None -> neutral ink (weather context)
    kind: str = "area"  # "area" | "line" | "bar"


def time_panels(
    fig_id: str,
    title: str,
    subtitle: str,
    panels: list[Panel],
    note: str = "",
) -> Figure:
    """Several measures over the same dates, one plot each, stacked.

    Never a second y-axis: two scales on one frame invent a correlation the data
    does not contain. Aligned x-axes let the eye do the comparison honestly.
    """
    panels = [p for p in panels if p.values]
    if not panels:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    all_dates = sorted({d for p in panels for d in p.values})
    start, end = all_dates[0], all_dates[-1]
    span = max((end - start).days, 1)

    left, right = 62, 18
    panel_h, pad = 92, 26
    top = 14
    height = top + len(panels) * (panel_h + pad) + 22
    plot_w = W - left - right

    def sx(d: dt.date) -> float:
        return left + (d - start).days / span * plot_w

    parts: list[str] = []

    for idx, panel in enumerate(panels):
        base = top + idx * (panel_h + pad)
        values = [v for v in panel.values.values()]
        v_min = min(0.0, min(values))
        v_max = max(values) * 1.08 or 1.0

        def sy(v: float, base=base, v_min=v_min, v_max=v_max) -> float:
            return base + panel_h - (v - v_min) / (v_max - v_min) * panel_h

        color = paint(panel.stream)
        ticks = nice_ticks(v_min, v_max, target=3)
        parts.append(_gridlines(left, left + plot_w, ticks, sy))
        parts.append(_axis_left(left, base, base + panel_h, ticks, sy, lambda t: fmt(t)))

        ordered = sorted(panel.values)
        pts = [(sx(d), sy(panel.values[d])) for d in ordered]

        if panel.kind == "area":
            path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                            for i, (x, y) in enumerate(pts))
            zero = sy(max(v_min, 0.0))
            parts.append(
                f'<path d="{path} L{pts[-1][0]:.1f},{zero:.1f} L{pts[0][0]:.1f},'
                f'{zero:.1f} Z" fill="{color}" fill-opacity="0.10"/>'
            )
            parts.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
        else:
            path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                            for i, (x, y) in enumerate(pts))
            parts.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )

        # Direct-label the panel and its peak — selectively, never every point.
        peak_date = max(panel.values, key=lambda d: panel.values[d])
        px, py = sx(peak_date), sy(panel.values[peak_date])
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}" '
            f'stroke="var(--ink-surface)" stroke-width="2"/>'
        )
        anchor = "end" if px > left + plot_w * 0.75 else "start"
        dx = -8 if anchor == "end" else 8
        parts.append(
            f'<text x="{px + dx:.1f}" y="{py - 8:.1f}" text-anchor="{anchor}" '
            f'font-size="11" fill="var(--ink-primary)" font-weight="600">'
            f"{esc(fmt(panel.values[peak_date]))} {esc(panel.unit)}</text>"
        )
        parts.append(
            f'<text x="{left}" y="{base - 6}" font-size="11.5" '
            f'fill="var(--ink-secondary)" font-weight="600">'
            f'<tspan fill="{color}">■</tspan> {esc(panel.label)} '
            f'<tspan fill="var(--ink-muted)" font-weight="400">({esc(panel.unit)})</tspan>'
            f"</text>"
        )

        # Invisible hit columns give every day a generous hover target.
        step = plot_w / max(len(ordered) - 1, 1)
        for d in ordered:
            tip = f"{d:%a %-d %b %Y} — {fmt(panel.values[d])} {panel.unit}"
            parts.append(
                f'<rect x="{sx(d) - step / 2:.1f}" y="{base}" '
                f'width="{max(step, 2):.1f}" height="{panel_h}" fill="transparent" '
                f'data-tip="{esc(tip)}"/>'
            )

    # Shared x-axis at the foot.
    axis_y = top + len(panels) * (panel_h + pad) - pad + 6
    parts.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{left + plot_w}" y2="{axis_y}" '
        f'stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    cursor = dt.date(start.year, start.month, 1)
    while cursor <= end:
        if cursor >= start:
            parts.append(
                f'<text x="{sx(cursor):.1f}" y="{axis_y + 17}" text-anchor="middle" '
                f'font-size="11" fill="var(--ink-muted)">'
                f"{_MON[cursor.month - 1]}</text>"
            )
        cursor = dt.date(
            cursor.year + (cursor.month == 12), (cursor.month % 12) + 1, 1
        )

    headers = ["Date"] + [f"{p.label} ({p.unit})" for p in panels]
    rows = []
    for d in all_dates[::7]:
        rows.append([f"{d:%Y-%m-%d}"] + [fmt(p.values.get(d)) for p in panels])

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: aligned daily time series"),
        table_headers=headers,
        table_rows=rows,
        # No legend box: every panel draws its own label and swatch inline, above
        # its own plot. A legend repeats that, and once two panels legitimately
        # share a colour — rain and lightning are both weather — it lists two
        # entries a reader cannot tell apart.
    )


# ---------------------------------------------------------------------------
# Grouped monthly columns
# ---------------------------------------------------------------------------


def monthly_columns(
    fig_id: str,
    title: str,
    subtitle: str,
    labels: list[str],
    series: list[tuple[str, str, list[float]]],
    unit: str,
    note: str = "",
    category_label: str = "Month",
    stacked: bool = False,
) -> Figure:
    """Columns per category (months by default).

    `series` is (label, colour, values), where colour is either a stream name
    ("water") or a literal CSS colour. The literal form exists so a breakdown of
    one stream can use the emphasis pattern — accent for the part that matters,
    de-emphasis grey for context — rather than implying two separate entities.

    `stacked` when the series are parts of one whole and their sum is the claim.
    Grouped is the default and the right choice for comparing series against
    each other; it is the wrong one when a series is zero for most categories,
    because the empty slot reads as a gap rather than as nothing.
    """
    if not labels or not series:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 320
    left, right, top, bottom = 62, 18, 20, 46
    plot_w, plot_h = W - left - right, height - top - bottom

    if stacked:
        v_max = max(
            sum(vals[i] for _, _, vals in series) for i in range(len(labels))
        ) * 1.1 or 1
    else:
        v_max = max(max(vals) for _, _, vals in series) * 1.1 or 1
    band = plot_w / len(labels)
    # Cap the mark thickness and let the leftover band be air.
    bar_w = min(24.0, (band - 10) / len(series))

    def sy(v: float) -> float:
        return top + plot_h - v / v_max * plot_h

    ticks = nice_ticks(0, v_max)
    parts = [_gridlines(left, left + plot_w, ticks, sy)]
    parts.append(_axis_left(left, top, top + plot_h, ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )

    stack_w = min(30.0, band - 14)
    group_w = stack_w if stacked else bar_w * len(series) + 2 * (len(series) - 1)
    for i, label in enumerate(labels):
        cx = left + band * (i + 0.5)
        parts.append(
            f'<text x="{cx:.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)">{esc(label)}</text>'
        )
        running = 0.0
        for j, (name, stream, values) in enumerate(series):
            v = values[i]
            fill = paint(stream)
            if stacked:
                x, w = cx - stack_w / 2, stack_w
                base = sy(running)
                y = sy(running + v)
                running += v
                h = base - y
                if h <= 0:
                    continue
                # A 2px surface gap between touching segments, so the boundary
                # is a boundary and not a colour change.
                gap = 2.0 if j else 0.0
                top_r = min(4.0, w / 2, h) if j == len(series) - 1 else 0.0
                path = (
                    f"M{x:.1f},{base - gap:.1f} L{x:.1f},{y + top_r:.1f} "
                    f"Q{x:.1f},{y:.1f} {x + top_r:.1f},{y:.1f} "
                    f"L{x + w - top_r:.1f},{y:.1f} "
                    f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + top_r:.1f} "
                    f"L{x + w:.1f},{base - gap:.1f} Z"
                )
            else:
                x, w = cx - group_w / 2 + j * (bar_w + 2), bar_w
                y = sy(v)
                h = top + plot_h - y
                if h <= 0:
                    continue
                # 4px rounded data-end, square at the baseline.
                r = min(4.0, w / 2, h)
                path = (
                    f"M{x:.1f},{top + plot_h:.1f} L{x:.1f},{y + r:.1f} "
                    f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                    f"L{x + w - r:.1f},{y:.1f} "
                    f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
                    f"L{x + w:.1f},{top + plot_h:.1f} Z"
                )
            parts.append(
                f'<path d="{path}" fill="{fill}" '
                f'data-tip="{esc(f"{label} · {name}: {fmt(v)} {unit}")}" tabindex="0"/>'
            )

    parts.append(
        f'<text x="14" y="{top + plot_h / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {top + plot_h / 2})">'
        f"{esc(unit)}</text>"
    )

    rows = [[labels[i]] + [fmt(vals[i]) for _, _, vals in series]
            for i in range(len(labels))]
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: monthly columns"),
        table_headers=[category_label] + [name for name, _, _ in series],
        table_rows=rows,
        legend=[
            (paint(s), n)
            for n, s, _ in series
        ],
    )


def schedule_clock(
    fig_id: str,
    title: str,
    subtitle: str,
    cycles: list[tuple[dt.date, int, str]],
    eras: list[tuple[dt.date, dt.date, int, int, str]],
    intended_hour: int,
    stream: str = "water",
    note: str = "",
) -> Figure:
    """The hour each cycle actually fired, against the hour it was set to.

    A controller with a working clock draws one flat row of dots. Every
    departure from that row is a clock that lost the time, so the excursions
    are read from their *position* rather than from a colour — one series, and
    the anomalies label themselves.

    The vertical axis is the 24-hour day rather than a fitted range, because a
    midday watering is only alarming relative to midnight and noon. Compressing
    it to the data's own span would flatter the record.
    """
    if len(cycles) < 2:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height, top, left, right = 300, 26, 54, 18
    plot_h = height - top - 46
    plot_w = W - left - right
    lo, hi = cycles[0][0], cycles[-1][0]
    span_days = max(1, (hi - lo).days)
    colour = paint(stream)

    def sx(d: dt.date) -> float:
        return left + (d - lo).days / span_days * plot_w

    def sy(hour: float) -> float:
        return top + plot_h - (hour / 24.0) * plot_h

    ticks = [0, 6, 12, 18, 24]
    parts = [
        _gridlines(left, left + plot_w, ticks, sy),
        # 24 is labelled as itself rather than wrapped to 00:00 — the axis is a
        # day's span, and two identically labelled ends read as a bug.
        _axis_left(left, top, top + plot_h, ticks, sy, lambda t: f"{int(t):02d}:00"),
        # The hour the controller was told to use. Everything on this line is
        # the machine behaving; everything off it is the clock adrift.
        f'<line x1="{left}" y1="{sy(intended_hour):.1f}" x2="{left + plot_w}" '
        f'y2="{sy(intended_hour):.1f}" stroke="var(--ink-axis)" stroke-width="1"/>',
        f'<text x="{left + plot_w:.1f}" y="{sy(intended_hour) - 7:.1f}" '
        f'text-anchor="end" font-size="10.5" fill="var(--ink-muted)">'
        f"set to {intended_hour:02d}:00</text>",
    ]

    # Label only the excursions, on the far side of the dots from the reference
    # line. A slip an hour above the line has almost no room beneath it, and the
    # 20:00 row is the densest on the chart to collide with.
    for start, end, hour, _count, label in eras:
        if hour == intended_hour or not label:
            continue
        mid = start + (end - start) / 2
        x = min(max(sx(mid), left + 40), left + plot_w - 40)
        dy = -11.0 if hour > intended_hour else 20.0
        parts.append(
            f'<text x="{x:.1f}" y="{sy(hour) + dy:.1f}" text-anchor="middle" '
            f'font-size="10.5" font-weight="600" fill="{STATUS["serious"]}">'
            f"{esc(label)}</text>"
        )

    for day, hour, tip in cycles:
        adrift = hour != intended_hour
        parts.append(
            f'<circle cx="{sx(day):.1f}" cy="{sy(hour):.1f}" r="4" '
            f'fill="{STATUS["serious"] if adrift else colour}" '
            f'stroke="var(--ink-surface)" stroke-width="2" '
            f'data-tip="{esc(tip)}" tabindex="0"/>'
        )

    step = max(1, round(span_days / 330))
    month = dt.date(lo.year, lo.month, 1)
    i = 0
    while month <= hi:
        if month >= lo and i % step == 0:
            parts.append(
                f'<text x="{sx(month):.1f}" y="{top + plot_h + 18}" '
                f'text-anchor="middle" font-size="10" fill="var(--ink-muted)">'
                f"{_MON[month.month - 1]}</text>"
            )
        month = dt.date(month.year + month.month // 12, month.month % 12 + 1, 1)
        i += 1

    parts.append(
        f'<text x="{left}" y="{top - 10}" font-size="10.5" fill="var(--ink-muted)">'
        f"Hour the cycle actually ran</text>"
    )

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: the hour each irrigation cycle ran"),
        table_headers=["From", "To", "Fires at", "Cycles", "What it was"],
        table_rows=[
            [f"{s:%Y-%m-%d}", f"{e:%Y-%m-%d}", f"{h:02d}:00", f"{c}",
             lbl or "as programmed"]
            for s, e, h, c, lbl in eras
        ],
    )


# ---------------------------------------------------------------------------
# Diverging bars (cost decomposition)
# ---------------------------------------------------------------------------


def event_series(
    fig_id: str,
    title: str,
    subtitle: str,
    points: list[tuple[dt.date, float, str]],
    stream: str,
    y_label: str,
    baseline: float | None = None,
    baseline_label: str = "",
    baseline_span: tuple[dt.date, dt.date] | None = None,
    break_date: dt.date | None = None,
    break_label: str = "",
    note: str = "",
) -> Figure:
    """One dot per event on a real date axis, against the level it used to hold.

    A line chart would imply the quantity exists between the dots, and it does
    not — the controller runs three nights a week and delivers nothing on the
    other four. Dots keep the gaps honest, and the reference line is what turns
    a scatter of volumes into a before-and-after.
    """
    if len(points) < 2:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height, top, left, right = 300, 22, 54, 18
    plot_h = height - top - 46
    plot_w = W - left - right
    lo, hi = points[0][0], points[-1][0]
    span_days = max(1, (hi - lo).days)
    v_max = max(v for _, v, _ in points) * 1.08
    colour = paint(stream)

    def sx(d: dt.date) -> float:
        return left + (d - lo).days / span_days * plot_w

    def sy(v: float) -> float:
        return top + plot_h - (v / v_max) * plot_h

    ticks = nice_ticks(0.0, v_max, target=4)
    parts = [
        _gridlines(left, left + plot_w, ticks, sy),
        _axis_left(left, top, top + plot_h, ticks, sy, lambda t: fmt(t)),
    ]

    # The clean period, shaded, so "baseline" is a span of the record rather
    # than an assertion about one.
    if baseline_span:
        a, b = baseline_span
        parts.append(
            f'<rect x="{sx(a):.1f}" y="{top}" width="{max(1.0, sx(b) - sx(a)):.1f}" '
            f'height="{plot_h}" fill="var(--ink-primary)" fill-opacity="0.05"/>'
        )

    if baseline is not None:
        parts.append(
            f'<line x1="{left}" y1="{sy(baseline):.1f}" x2="{left + plot_w}" '
            f'y2="{sy(baseline):.1f}" stroke="var(--ink-axis)" stroke-width="1"/>'
            # Below the line and hard right: the level being marked is one the
            # early data sits directly on, so anything above it at the left
            # collides with the very points it describes.
            f'<text x="{left + plot_w:.1f}" y="{sy(baseline) + 14:.1f}" '
            f'text-anchor="end" font-size="10.5" fill="var(--ink-muted)">'
            f"{esc(baseline_label)}</text>"
        )

    if break_date is not None:
        parts.append(
            f'<line x1="{sx(break_date):.1f}" y1="{top}" '
            f'x2="{sx(break_date):.1f}" y2="{top + plot_h}" '
            f'stroke="{STATUS["serious"]}" stroke-width="1.5"/>'
            f'<text x="{sx(break_date) + 7:.1f}" y="{top + 12}" font-size="10.5" '
            f'fill="{STATUS["serious"]}" font-weight="600">'
            f"{esc(break_label)}</text>"
        )

    for d, v, label in points:
        after = break_date is not None and d >= break_date
        parts.append(
            f'<circle cx="{sx(d):.1f}" cy="{sy(v):.1f}" r="4" '
            f'fill="{STATUS["serious"] if after else colour}" '
            f'stroke="var(--ink-surface)" stroke-width="2" '
            f'data-tip="{esc(label)}" tabindex="0"/>'
        )

    # Month ticks, thinned so the labels never collide.
    step = max(1, round(span_days / 330))
    month = dt.date(lo.year, lo.month, 1)
    i = 0
    while month <= hi:
        if month >= lo and i % step == 0:
            parts.append(
                f'<text x="{sx(month):.1f}" y="{top + plot_h + 18}" '
                f'text-anchor="middle" font-size="10" fill="var(--ink-muted)">'
                f"{_MON[month.month - 1]}</text>"
            )
        month = dt.date(month.year + month.month // 12, month.month % 12 + 1, 1)
        i += 1

    parts.append(
        f'<text x="{left}" y="{top - 8}" font-size="10.5" fill="var(--ink-muted)">'
        f"{esc(y_label)}</text>"
    )

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: one point per event over time"),
        table_headers=["Date", "Day", y_label],
        table_rows=[[f"{d:%Y-%m-%d}", f"{d:%a}", f"{v:,.0f}"] for d, v, _ in points],
        legend=(
            [(colour, "Before"), (STATUS["serious"], "After")]
            if break_date is not None else []
        ),
    )


def ranked_bars(
    fig_id: str,
    title: str,
    subtitle: str,
    rows_in: list[tuple[str, float, str, str]],   # label, value, stream, detail
    unit_prefix: str = "$",
    note: str = "",
    legend: list[tuple[str, str]] | None = None,
) -> Figure:
    """One bar per line item, longest first, coloured by which meter it lands on.

    Magnitude plus identity, which is a ranked bar's job. The colour is doing
    real work here rather than decorating: it is what makes "the two largest
    items are both electricity" a thing the reader sees instead of a thing the
    prose has to assert.

    Rows arrive pre-sorted — the caller owns the order, because the ranking is
    the argument.
    """
    if not rows_in:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    row_h, bar_h, top = 25, 13, 18
    left, right = 168, 92
    plot_w = W - left - right
    height = top + len(rows_in) * row_h + 34
    limit = max(v for _, v, _, _ in rows_in) * 1.02
    total = sum(v for _, v, _, _ in rows_in)

    def sx(v: float) -> float:
        return v / limit * plot_w if limit else 0.0

    parts = []
    for t in nice_ticks(0.0, limit, target=5):
        if t <= 0:
            continue
        x = left + sx(t)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top - 2}" x2="{x:.1f}" '
            f'y2="{top + len(rows_in) * row_h - 6}" stroke="var(--ink-grid)" '
            f'stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{top + len(rows_in) * row_h + 10}" '
            f'text-anchor="middle" font-size="10" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">'
            f"{esc(unit_prefix)}{esc(fmt(t))}</text>"
        )

    for i, (label, value, stream, detail) in enumerate(rows_in):
        y = top + i * row_h
        parts.append(
            f'<text x="{left - 10}" y="{y + bar_h - 2}" text-anchor="end" '
            f'font-size="11" fill="var(--ink-secondary)">{esc(label)}</text>'
        )
        bw = sx(value)
        r = min(4.0, bw)
        if bw >= 0.6:
            # Round only the data end; the baseline stays square against the axis.
            path = (
                f"M{left},{y} L{left + bw - r:.1f},{y} "
                f"Q{left + bw:.1f},{y} {left + bw:.1f},{y + r:.1f} "
                f"L{left + bw:.1f},{y + bar_h - r:.1f} "
                f"Q{left + bw:.1f},{y + bar_h} {left + bw - r:.1f},{y + bar_h} "
                f"L{left},{y + bar_h} Z"
            )
            tip = f"{label}: {unit_prefix}{value:,.0f} — {detail}" if detail else \
                  f"{label}: {unit_prefix}{value:,.0f}"
            parts.append(
                f'<path d="{path}" fill="{paint(stream)}" '
                f'data-tip="{esc(tip)}" tabindex="0"/>'
            )
        parts.append(
            f'<text x="{left + bw + 8:.1f}" y="{y + bar_h - 2}" font-size="11" '
            f'fill="var(--ink-primary)" font-weight="600" '
            f'style="font-variant-numeric:tabular-nums">'
            f"{esc(unit_prefix)}{value:,.0f}</text>"
        )

    parts.append(
        f'<line x1="{left}" y1="{top - 2}" x2="{left}" '
        f'y2="{top + len(rows_in) * row_h - 6}" stroke="var(--ink-axis)" '
        f'stroke-width="1"/>'
    )

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: ranked bars"),
        table_headers=["What", "Per year", "Share", "Detail"],
        table_rows=[
            [lbl, f"{unit_prefix}{v:,.0f}", f"{v / total:.1%}" if total else "—", det]
            for lbl, v, _, det in rows_in
        ],
        legend=legend or [],
    )


def diverging_bars(
    fig_id: str,
    title: str,
    subtitle: str,
    rows_in: list[tuple[str, float, float]],
    note: str = "",
) -> Figure:
    """Per-period split of a bill change into usage effect and rate effect.

    Diverging because the reader's question is directional — did this cost me
    more or less — so the zero line is the reference and the two poles read as
    opposite.
    """
    if not rows_in:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 60 + len(rows_in) * 26 + 40
    left, right, top = 78, 120, 34
    plot_w = W - left - right
    limit = max(
        max(abs(u) for _, u, _ in rows_in), max(abs(r) for _, _, r in rows_in), 1.0
    ) * 1.15
    mid = left + plot_w / 2

    def sx(v: float) -> float:
        return mid + v / limit * (plot_w / 2)

    parts = [
        f'<line x1="{mid}" y1="{top - 8}" x2="{mid}" y2="{top + len(rows_in) * 26}" '
        f'stroke="var(--ink-axis)" stroke-width="1"/>'
    ]
    for t in nice_ticks(-limit, limit, target=4):
        if abs(t) < 1e-9:
            continue
        parts.append(
            f'<text x="{sx(t):.1f}" y="{top - 14}" text-anchor="middle" font-size="10" '
            f'fill="var(--ink-muted)" style="font-variant-numeric:tabular-nums">'
            f"${esc(fmt(abs(t)))}</text>"
        )

    bar_h = 9
    for i, (label, usage, rate) in enumerate(rows_in):
        y = top + i * 26
        parts.append(
            f'<text x="{left - 10}" y="{y + 13}" text-anchor="end" font-size="11" '
            f'fill="var(--ink-secondary)" style="font-variant-numeric:tabular-nums">'
            f"{esc(label)}</text>"
        )
        # Both halves are dollars, so neither takes a meter's colour. The split
        # that matters is agency: money the household moved, against money the
        # tariff moved on its own. One is actionable and one is weather.
        for j, (value, stream, name) in enumerate(
            [(usage, "var(--money-accent)", "Usage"),
             (rate, "var(--ink-secondary)", "Rate")]
        ):
            bx = min(sx(0), sx(value))
            bw = abs(sx(value) - sx(0))
            by = y + j * (bar_h + 2)
            r = min(4.0, bw)
            if bw < 0.6:
                continue
            # Round only the data end; the baseline end stays square.
            if value >= 0:
                path = (
                    f"M{bx:.1f},{by} L{bx + bw - r:.1f},{by} "
                    f"Q{bx + bw:.1f},{by} {bx + bw:.1f},{by + r:.1f} "
                    f"L{bx + bw:.1f},{by + bar_h - r:.1f} "
                    f"Q{bx + bw:.1f},{by + bar_h} {bx + bw - r:.1f},{by + bar_h} "
                    f"L{bx:.1f},{by + bar_h} Z"
                )
            else:
                path = (
                    f"M{bx + bw:.1f},{by} L{bx + r:.1f},{by} "
                    f"Q{bx:.1f},{by} {bx:.1f},{by + r:.1f} "
                    f"L{bx:.1f},{by + bar_h - r:.1f} "
                    f"Q{bx:.1f},{by + bar_h} {bx + r:.1f},{by + bar_h} "
                    f"L{bx + bw:.1f},{by + bar_h} Z"
                )
            parts.append(
                f'<path d="{path}" fill="{paint(stream)}" '
                f'data-tip="{esc(f"{label} · {name}: {value:+,.0f} dollars")}" '
                f'tabindex="0"/>'
            )
        total = usage + rate
        parts.append(
            f'<text x="{left + plot_w + 12}" y="{y + 13}" font-size="11" '
            f'fill="var(--ink-primary)" font-weight="600" '
            f'style="font-variant-numeric:tabular-nums">{total:+,.0f}</text>'
        )

    parts.append(
        f'<text x="{left + plot_w + 12}" y="{top - 14}" font-size="10" '
        f'fill="var(--ink-muted)">Net $</text>'
    )

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: usage versus rate effect"),
        table_headers=["Period", "Usage effect $", "Rate effect $", "Net $"],
        table_rows=[
            [lbl, f"{u:+,.2f}", f"{r:+,.2f}", f"{u + r:+,.2f}"] for lbl, u, r in rows_in
        ],
        legend=[
            ("var(--money-accent)", "Usage effect — you used more or less"),
            ("var(--ink-secondary)", "Rate effect — the price moved"),
        ],
    )


# ---------------------------------------------------------------------------
# Carpet plot — the year as day x time-of-day
# ---------------------------------------------------------------------------


def carpet_plot(
    fig_id: str,
    title: str,
    subtitle: str,
    columns: list[tuple[dt.date, list[float | None]]],
    stream: str,
    unit: str = "kW",
    note: str = "",
) -> Figure:
    """Every interval of the year: date across, time of day down.

    Nothing else shows a schedule as plainly. A load on a timer draws a
    horizontal band; a weather-driven load draws a seasonal bulge; a one-off
    event is a single dark mark. Cells are contiguous here rather than gapped —
    this is a continuous field, not a set of discrete categorical marks.
    """
    if not columns:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    slots = len(columns[0][1])
    left, right, top, bottom = 54, 18, 22, 56
    plot_w, plot_h = W - left - right, 300
    height = top + plot_h + bottom

    col_w = plot_w / len(columns)
    row_h = plot_h / slots

    ramp = ramp_for(stream)
    flat = [v for _, col in columns for v in col if v is not None]
    edges = quantile_edges(flat, bins=len(ramp) - 2)

    # Two compressions, because a naive cell-per-rect carpet is ~35,000
    # elements and megabytes of markup:
    #   1. run-length encode down each column, so the overnight floor — hours of
    #      identical value — becomes one mark instead of twenty;
    #   2. group every run of the same colour into a single <path>, so the file
    #      carries one element per colour bin rather than one per run.
    # Neither changes a pixel of what renders.
    runs_by_bin: dict[int, list[str]] = {}

    def add_run(x: float, start: int, end: int, colour_bin: int) -> None:
        y = top + start * row_h
        h = (end - start) * row_h + 0.4
        w = col_w + 0.4
        runs_by_bin.setdefault(colour_bin, []).append(
            f"M{x:.1f},{y:.1f}h{w:.2f}v{h:.2f}h-{w:.2f}z"
        )

    for i, (day, col) in enumerate(columns):
        x = left + i * col_w
        run_start: int | None = None
        run_bin: int | None = None
        for j, value in enumerate(col):
            b = bin_index(value, edges) if value is not None else None
            if b != run_bin:
                if run_start is not None and run_bin is not None:
                    add_run(x, run_start, j, run_bin)
                run_start, run_bin = (j, b) if b is not None else (None, None)
        if run_start is not None and run_bin is not None:
            add_run(x, run_start, len(col), run_bin)

    parts: list[str] = [
        f'<path d="{"".join(runs)}" fill="{ramp[b]}" shape-rendering="crispEdges"/>'
        for b, runs in sorted(runs_by_bin.items())
    ]

    # One hover target per day rather than per cell: 35,000 listeners would
    # bloat the page for no gain, and the day summary is what a reader wants.
    for i, (day, col) in enumerate(columns):
        vals = [v for v in col if v is not None]
        if not vals:
            continue
        peak_idx = max(range(len(col)), key=lambda k: col[k] if col[k] is not None else -1)
        tip = (
            f"{day:%a %-d %b %Y} — {fmt(sum(vals) / 4)} kWh · "
            f"peak {fmt(max(vals))} {unit} at "
            f"{peak_idx * 24 // len(col):02d}:{(peak_idx * 1440 // len(col)) % 60:02d}"
        )
        parts.append(
            f'<rect x="{left + i * col_w:.2f}" y="{top}" width="{max(col_w, 1.2):.2f}" '
            f'height="{plot_h}" fill="transparent" data-tip="{esc(tip)}"/>'
        )

    for hour in range(0, 25, 6):
        y = top + hour / 24 * plot_h
        parts.append(
            f'<text x="{left - 8}" y="{y + 4}" text-anchor="end" font-size="11" '
            f'fill="var(--ink-muted)" style="font-variant-numeric:tabular-nums">'
            f"{hour % 24:02d}:00</text>"
        )

    seen: set[tuple[int, int]] = set()
    for i, (day, _) in enumerate(columns):
        key = (day.year, day.month)
        if key in seen:
            continue
        seen.add(key)
        parts.append(
            f'<text x="{left + i * col_w:.1f}" y="{top + plot_h + 17}" '
            f'font-size="11" fill="var(--ink-muted)">{_MON[day.month - 1]}</text>'
        )

    ly = top + plot_h + 32
    parts.append(
        f'<text x="{left}" y="{ly + 10}" font-size="11" fill="var(--ink-secondary)">'
        f"Less</text>"
    )
    lx = left + 34
    for color in ramp[: len(edges) + 1]:
        parts.append(
            f'<rect x="{lx}" y="{ly}" width="13" height="13" rx="2.5" fill="{color}"/>'
        )
        lx += 15
    parts.append(
        f'<text x="{lx + 6}" y="{ly + 10}" font-size="11" fill="var(--ink-secondary)">'
        f"More · breaks at {esc(', '.join(fmt(e) for e in edges))} {esc(unit)}</text>"
    )

    rows = []
    for day, col in columns[::14]:
        vals = [v for v in col if v is not None]
        if vals:
            rows.append([f"{day:%Y-%m-%d}", fmt(sum(vals) / 4), fmt(max(vals)), fmt(min(vals))])
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: interval load by date and time of day"),
        table_headers=["Date", "kWh", f"Peak {unit}", f"Floor {unit}"],
        table_rows=rows,
    )


# ---------------------------------------------------------------------------
# Daily load-shape lines
# ---------------------------------------------------------------------------


def profile_lines(
    fig_id: str,
    title: str,
    subtitle: str,
    series: list[tuple[str, str, list[float]]],
    unit: str,
    highlight: tuple[int, int, str] | None = None,
    note: str = "",
    # Where to hang each series' direct label. "end" suits curves that separate
    # at the right edge; "peak" suits curves that converge there — a series
    # ending at zero would otherwise be labelled on the axis, under its
    # neighbour, which is exactly what a generation curve does at midnight.
    label_at: str = "end",
    # Category labels for the x-axis. Without them the axis is a 24-hour clock,
    # which is what this was written for; with them it will take any ordered
    # sequence — months, say — so a two-series comparison over the year does not
    # need a third line-chart builder that would drift from this one.
    x_labels: list[str] | None = None,
) -> Figure:
    """Average load shape across a day, or any ordered series sharing an x-axis.

    `series` is (label, **css color**, values) — a paintable colour such as
    `var(--stream-electric)`, not a stream name. Passing a bare stream name
    yields an invalid stroke and the line silently does not render.
    """
    if not series:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 360
    left, right, top, bottom = 62, 96, 22, 52
    plot_w, plot_h = W - left - right, height - top - bottom
    slots = len(series[0][2])

    v_max = max(max(vals) for _, _, vals in series) * 1.12 or 1.0

    def sx(i: float) -> float:
        return left + i / (slots - 1) * plot_w

    def sy(v: float) -> float:
        return top + plot_h - v / v_max * plot_h

    ticks = nice_ticks(0, v_max)
    parts = [_gridlines(left, left + plot_w, ticks, sy)]

    if highlight:
        a, b, label = highlight
        parts.append(
            f'<rect x="{sx(a):.1f}" y="{top}" width="{sx(b) - sx(a):.1f}" '
            f'height="{plot_h}" fill="var(--ink-primary)" fill-opacity="0.05"/>'
        )
        parts.append(
            f'<text x="{(sx(a) + sx(b)) / 2:.1f}" y="{top + 14}" text-anchor="middle" '
            f'font-size="10.5" fill="var(--ink-muted)">{esc(label)}</text>'
        )

    parts.append(_axis_left(left, top, top + plot_h, ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    if x_labels:
        # Thinned so labels never collide, whatever the series length.
        step = max(1, round(len(x_labels) / 12))
        for i, text in enumerate(x_labels):
            if i % step:
                continue
            parts.append(
                f'<text x="{sx(i):.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
                f'font-size="11" fill="var(--ink-muted)">{esc(text)}</text>'
            )
    else:
        for hour in range(0, 25, 3):
            i = min(hour * slots // 24, slots - 1)
            parts.append(
                f'<text x="{sx(i):.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
                f'font-size="11" fill="var(--ink-muted)" '
                f'style="font-variant-numeric:tabular-nums">{hour % 24:02d}:00</text>'
            )

    for label, color, vals in series:
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(vals)
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        # Few enough points to be individual observations rather than a curve:
        # mark them, with a surface ring so overlapping series stay separable.
        if slots <= 24:
            for i, v in enumerate(vals):
                parts.append(
                    f'<circle cx="{sx(i):.1f}" cy="{sy(v):.1f}" r="4" fill="{color}" '
                    f'stroke="var(--ink-surface)" stroke-width="2" '
                    f'data-tip="{esc(f"{label}: {fmt(v)} {unit}")}" tabindex="0"/>'
                )
        anchor_i = max(range(slots), key=lambda i: vals[i]) if label_at == "peak" else slots - 1
        parts.append(
            f'<circle cx="{sx(anchor_i):.1f}" cy="{sy(vals[anchor_i]):.1f}" r="4" '
            f'fill="{color}" stroke="var(--ink-surface)" stroke-width="2"/>'
        )
        if label_at == "peak":
            # Above the peak, centred, and nudged inboard if it would overhang.
            width = len(label) * 11 * 0.55
            lx = min(max(sx(anchor_i), left + width / 2), W - 4 - width / 2)
            parts.append(
                f'<text x="{lx:.1f}" y="{sy(vals[anchor_i]) - 10:.1f}" '
                f'text-anchor="middle" font-size="11" '
                f'fill="var(--ink-primary)">{esc(label)}</text>'
            )
        else:
            # Measure before placing: a long series name at the right edge would
            # otherwise run off the canvas. If it will not fit, anchor it to the
            # edge instead of letting it overflow.
            lx = sx(slots - 1) + 10
            width = len(label) * 11 * 0.55
            if lx + width > W - 4:
                parts.append(
                    f'<text x="{W - 4}" y="{sy(vals[-1]) + 4:.1f}" text-anchor="end" '
                    f'font-size="11" fill="var(--ink-primary)">{esc(label)}</text>'
                )
            else:
                parts.append(
                    f'<text x="{lx:.1f}" y="{sy(vals[-1]) + 4:.1f}" '
                    f'font-size="11" fill="var(--ink-primary)">{esc(label)}</text>'
                )

    for i in range(slots):
        tip = " · ".join(
            f"{label}: {fmt(vals[i])} {unit}" for label, _, vals in series
        )
        hour = i * 24 // slots
        minute = (i * 1440 // slots) % 60
        parts.append(
            f'<rect x="{sx(i) - plot_w / slots / 2:.1f}" y="{top}" '
            f'width="{plot_w / slots:.1f}" height="{plot_h}" fill="transparent" '
            f'data-tip="{esc(f"{hour:02d}:{minute:02d} — {tip}")}"/>'
        )

    parts.append(
        f'<text x="14" y="{top + plot_h / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {top + plot_h / 2})">'
        f"{esc(unit)}</text>"
    )

    # The table is the chart's accessible twin, so it carries every point when
    # there are few of them. Only the 24-hour form is thinned, and only because
    # 96 quarter-hour rows help nobody. Deriving the row label from the slot
    # index assumed a clock — with month labels that produced three rows headed
    # "00:00", "08:00", "16:00" for a twelve-month series.
    if x_labels:
        rows = [
            [x_labels[i]] + [fmt(vals[i]) for _, _, vals in series]
            for i in range(slots)
        ]
    else:
        rows = []
        for i in range(0, slots, 4):
            hour = i * 24 // slots
            rows.append([f"{hour:02d}:00"] + [fmt(vals[i]) for _, _, vals in series])
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(
            height, "".join(parts),
            f"{title}: {'series over time' if x_labels else 'average load shape by time of day'}",
        ),
        table_headers=[("Period" if x_labels else "Time")]
        + [label for label, _, _ in series],
        table_rows=rows,
        legend=[(color, label) for label, color, _ in series],
    )


# ---------------------------------------------------------------------------
# Stacked time-of-day panels
# ---------------------------------------------------------------------------


@dataclass
class SlotPanel:
    label: str
    unit: str
    color: str
    values: list[float]
    zero_line: bool = False


def profile_panels(
    fig_id: str,
    title: str,
    subtitle: str,
    panels: list[SlotPanel],
    highlight: tuple[int, int, str] | None = None,
    note: str = "",
) -> Figure:
    """Several measures across one day, each on its own axis, sharing time.

    Built for comparisons where the quantities have nothing in common
    dimensionally — a temperature rate, a power, an irradiance. Stacking them
    against a shared time axis lets the eye line up a cause with its effect
    without ever putting two scales on one frame.
    """
    panels = [p for p in panels if p.values]
    if not panels:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    slots = len(panels[0].values)
    left, right = 66, 20
    panel_h, pad = 86, 30
    top = 16
    height = top + len(panels) * (panel_h + pad) + 16
    plot_w = W - left - right

    def sx(i: float) -> float:
        return left + i / (slots - 1) * plot_w

    parts: list[str] = []

    for idx, panel in enumerate(panels):
        base = top + idx * (panel_h + pad)
        v_min = min(min(panel.values), 0.0) if panel.zero_line else min(panel.values)
        v_max = max(panel.values)
        pad_v = (v_max - v_min) * 0.12 or 1.0
        v_min -= pad_v if panel.zero_line and v_min < 0 else 0
        v_max += pad_v

        def sy(v: float, base=base, v_min=v_min, v_max=v_max) -> float:
            return base + panel_h - (v - v_min) / (v_max - v_min) * panel_h

        ticks = nice_ticks(v_min, v_max, target=3)
        parts.append(_gridlines(left, left + plot_w, ticks, sy))
        parts.append(
            _axis_left(left, base, base + panel_h, ticks, sy, lambda t: fmt(t))
        )

        if highlight:
            a, b, label = highlight
            parts.append(
                f'<rect x="{sx(a):.1f}" y="{base}" width="{sx(b) - sx(a):.1f}" '
                f'height="{panel_h}" fill="var(--ink-primary)" fill-opacity="0.05"/>'
            )
            if idx == 0:
                parts.append(
                    f'<text x="{(sx(a) + sx(b)) / 2:.1f}" y="{base - 6}" '
                    f'text-anchor="middle" font-size="10.5" fill="var(--ink-muted)">'
                    f"{esc(label)}</text>"
                )

        if panel.zero_line and v_min < 0 < v_max:
            parts.append(
                f'<line x1="{left}" y1="{sy(0):.1f}" x2="{left + plot_w}" '
                f'y2="{sy(0):.1f}" stroke="var(--ink-axis)" stroke-width="1"/>'
            )

        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}"
            for i, v in enumerate(panel.values)
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{panel.color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )

        peak = max(range(slots), key=lambda i: panel.values[i])
        parts.append(
            f'<circle cx="{sx(peak):.1f}" cy="{sy(panel.values[peak]):.1f}" r="4" '
            f'fill="{panel.color}" stroke="var(--ink-surface)" stroke-width="2"/>'
        )
        anchor = "end" if sx(peak) > left + plot_w * 0.7 else "start"
        dx = -9 if anchor == "end" else 9
        parts.append(
            f'<text x="{sx(peak) + dx:.1f}" y="{sy(panel.values[peak]) + 4:.1f}" '
            f'text-anchor="{anchor}" font-size="11" fill="var(--ink-primary)" '
            f'font-weight="600">{esc(fmt(panel.values[peak]))} {esc(panel.unit)}</text>'
        )
        parts.append(
            f'<text x="{left}" y="{base - 6}" font-size="11.5" '
            f'fill="var(--ink-secondary)" font-weight="600">'
            f'<tspan fill="{panel.color}">■</tspan> {esc(panel.label)} '
            f'<tspan fill="var(--ink-muted)" font-weight="400">'
            f"({esc(panel.unit)})</tspan></text>"
        )

        for i in range(slots):
            hour, minute = i * 24 // slots, (i * 1440 // slots) % 60
            parts.append(
                f'<rect x="{sx(i) - plot_w / slots / 2:.1f}" y="{base}" '
                f'width="{plot_w / slots:.1f}" height="{panel_h}" fill="transparent" '
                f'data-tip="{esc(f"{hour:02d}:{minute:02d} — {panel.label}: {fmt(panel.values[i])} {panel.unit}")}"/>'
            )

    axis_y = top + len(panels) * (panel_h + pad) - pad + 8
    parts.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{left + plot_w}" y2="{axis_y}" '
        f'stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    for hour in range(0, 25, 3):
        i = min(hour * slots // 24, slots - 1)
        parts.append(
            f'<text x="{sx(i):.1f}" y="{axis_y + 16}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">{hour % 24:02d}:00</text>'
        )

    # Every slot, not every other one: decimating the table would drop the very
    # samples the chart exists to show.
    rows = []
    for i in range(slots):
        hour, minute = i * 24 // slots, (i * 1440 // slots) % 60
        rows.append([f"{hour:02d}:{minute:02d}"] + [fmt(p.values[i]) for p in panels])
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: aligned time-of-day panels"),
        table_headers=["Time"] + [f"{p.label} ({p.unit})" for p in panels],
        table_rows=rows,
        legend=[(p.color, p.label) for p in panels],
    )


# ---------------------------------------------------------------------------
# Generic scatter (envelope response)
# ---------------------------------------------------------------------------


def scatter(
    fig_id: str,
    title: str,
    subtitle: str,
    points: list[tuple[float, float, str]],
    stream: str,
    x_label: str,
    y_label: str,
    fit_line: tuple[float, float] | None = None,
    reference: tuple[float, float] | None = None,
    reference_label: str = "",
    note: str = "",
    # A curve through the cloud, for relationships a straight `fit_line` would
    # misrepresent. Drawn as given, so the caller decides what it means —
    # binned medians, a rolling average, a fitted curve.
    overlay: list[tuple[float, float]] | None = None,
    overlay_label: str = "",
    mark: tuple[float, float, str] | None = None,
    # Whether the x-axis has to include zero. True where the origin carries
    # meaning; False where it is only dead space to the left of the data.
    x_zero: bool = True,
    # (x, y, text) drawn at data coordinates — for naming clusters in place.
    annotations: list[tuple[float, float, str]] | None = None,
) -> Figure:
    if not points:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 360
    left, right, top, bottom = 62, 24, 22, 52
    plot_w, plot_h = W - left - right, height - top - bottom

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    y_lo, y_hi = min(0.0, min(ys)), max(ys) * 1.08 or 1.0
    if x_zero:
        # Anchored at zero, for x-quantities where the origin is part of the
        # claim — a swing-against-swing plot has to show that no forcing means
        # no response.
        x_lo, x_hi = min(0.0, min(xs)), max(xs) * 1.03
    else:
        # Framed on the data. Outdoor temperature never approaches zero here, so
        # anchoring would spend a third of the width on degrees that never occur.
        span = max(xs) - min(xs) or 1.0
        x_lo, x_hi = min(xs) - span * 0.04, max(xs) + span * 0.04

    def sx(v: float) -> float:
        return left + (v - x_lo) / (x_hi - x_lo) * plot_w

    def sy(v: float) -> float:
        return top + plot_h - (v - y_lo) / (y_hi - y_lo) * plot_h

    y_ticks = nice_ticks(y_lo, y_hi)
    parts = [_gridlines(left, left + plot_w, y_ticks, sy)]
    parts.append(_axis_left(left, top, top + plot_h, y_ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    for t in nice_ticks(x_lo, x_hi):
        if t < x_lo:
            continue
        parts.append(
            f'<text x="{sx(t):.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">{esc(fmt(t))}</text>'
        )

    if reference:
        a, b = reference
        seg = clip_segment(
            x_lo, a + b * x_lo, x_hi, a + b * x_hi, x_lo, x_hi, y_lo, y_hi
        )
        if seg:
            ax, ay, bx, by = seg
            parts.append(
                f'<line x1="{sx(ax):.1f}" y1="{sy(ay):.1f}" '
                f'x2="{sx(bx):.1f}" y2="{sy(by):.1f}" '
                f'stroke="var(--ink-axis)" stroke-width="1"/>'
            )
            if reference_label:
                # Label where the line actually exits the frame, not where an
                # unclipped one would have ended.
                parts.append(
                    f'<text x="{sx(bx) + 8:.1f}" y="{sy(by) + 14:.1f}" '
                    f'font-size="10.5" fill="var(--ink-muted)">'
                    f"{esc(reference_label)}</text>"
                )

    for x, y, tip in points:
        parts.append(
            f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="4" '
            f'fill="{paint(stream)}" fill-opacity="0.55" '
            f'stroke="var(--ink-surface)" stroke-width="2" '
            f'data-tip="{esc(tip)}" tabindex="0"/>'
        )

    if fit_line:
        a, b = fit_line
        parts.append(
            f'<line x1="{sx(x_lo):.1f}" y1="{sy(a + b * x_lo):.1f}" '
            f'x2="{sx(x_hi):.1f}" y2="{sy(a + b * x_hi):.1f}" '
            f'stroke="{paint(stream)}" stroke-width="2" stroke-linecap="round"/>'
        )

    if overlay and len(overlay) > 1:
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}"
            for i, (x, y) in enumerate(overlay)
        )
        # Ringed in surface colour so it stays legible where it crosses the
        # densest part of the cloud.
        parts.append(
            f'<path d="{path}" fill="none" stroke="var(--ink-surface)" '
            f'stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="var(--ink-primary)" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        if overlay_label:
            lx, ly = overlay[-1]
            parts.append(
                f'<text x="{sx(lx) - 6:.1f}" y="{sy(ly) - 10:.1f}" text-anchor="end" '
                f'font-size="10.5" fill="var(--ink-secondary)">'
                f"{esc(overlay_label)}</text>"
            )

    if mark:
        mx, my, mlabel = mark
        parts.append(
            f'<circle cx="{sx(mx):.1f}" cy="{sy(my):.1f}" r="5" '
            f'fill="var(--ink-primary)" stroke="var(--ink-surface)" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{sx(mx):.1f}" y="{sy(my) - 14:.1f}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-primary)" font-weight="600">'
            f"{esc(mlabel)}</text>"
        )

    # Free text at data coordinates. Where a cloud falls into groups separated by
    # position, naming them in place beats a legend: identity comes from where a
    # point sits, so the palette never has to carry it.
    for ax, ay, alabel in annotations or []:
        anchor = "start" if sx(ax) < left + plot_w / 2 else "end"
        parts.append(
            f'<text x="{sx(ax):.1f}" y="{sy(ay):.1f}" text-anchor="{anchor}" '
            f'font-size="11" font-weight="600" fill="var(--ink-secondary)">'
            f"{esc(alabel)}</text>"
        )

    parts.append(
        f'<text x="{left + plot_w / 2}" y="{height - 10}" text-anchor="middle" '
        f'font-size="11" fill="var(--ink-secondary)">{esc(x_label)}</text>'
    )
    parts.append(
        f'<text x="14" y="{top + plot_h / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {top + plot_h / 2})">'
        f"{esc(y_label)}</text>"
    )

    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: {y_label} against {x_label}"),
        table_headers=["Day", x_label, y_label],
        table_rows=[[p[2], fmt(p[0]), fmt(p[1])] for p in
                    sorted(points, key=lambda p: -p[1])[:25]],
    )


# ---------------------------------------------------------------------------
# Zone small multiples
# ---------------------------------------------------------------------------


@dataclass
class ZonePanel:
    label: str
    values: list[float]
    caption: str = ""


def zone_multiples(
    fig_id: str,
    title: str,
    subtitle: str,
    panels: list[ZonePanel],
    reference: tuple[str, list[float]],
    unit: str,
    x_labels: list[str],
    note: str = "",
    zero_line: bool = False,
    # The layout is "one series against a shared reference", which is not only a
    # zone thing — the gas and water meters get read the same way. Those pass
    # their own stream colour, because a gas chart in the zone accent claims to
    # be about the building when it is about the meter.
    accent: str = "var(--zone-accent)",
    # Legend text for the accent series. "Zone" is wrong on a chart whose panels
    # are seasons or temperature bands rather than rooms.
    series_label: str = "Zone",
) -> Figure:
    """One panel per zone, every panel on the same scale, sharing a reference.

    Small multiples rather than five lines in one frame. Five zones would need
    five categorical hues, and the zones are an ordered ladder rather than five
    unrelated things, so the honest encoding — one hue stepped light to dark —
    is the one that fails the separation floor when it is asked to carry
    identity. Splitting the frame removes the problem instead of arguing with
    it: each panel holds one accent line against the same reference curve in
    muted ink, so the palette is two colours and the comparison is positional.

    The shared y-scale is what makes the panels comparable. Per-panel scaling
    would draw every zone with the same apparent swing and quietly delete the
    finding.
    """
    panels = [p for p in panels if p.values]
    if not panels:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    ref_label, ref_values = reference
    cols = 2
    rows_n = (len(panels) + cols - 1) // cols
    left, right, top = 52, 18, 30
    gap_x, gap_y = 34, 46
    panel_w = (W - left - right - gap_x * (cols - 1)) / cols
    panel_h = 132
    height = top + rows_n * panel_h + (rows_n - 1) * gap_y + 34

    slots = len(panels[0].values)
    everything = [v for p in panels for v in p.values] + list(ref_values)
    lo, hi = min(everything), max(everything)
    pad = (hi - lo) * 0.12 or 1.0
    lo, hi = lo - pad, hi + pad
    ticks = nice_ticks(lo, hi, 6)

    parts: list[str] = []
    for index, panel in enumerate(panels):
        col, row = index % cols, index // cols
        px = left + col * (panel_w + gap_x)
        py = top + row * (panel_h + gap_y)

        def sx(i: float, px=px) -> float:
            return px + (i / (slots - 1) * panel_w if slots > 1 else panel_w / 2)

        def sy(v: float, py=py) -> float:
            return py + panel_h - (v - lo) / (hi - lo) * panel_h

        parts.append(_gridlines(px, px + panel_w, ticks, sy))
        if zero_line and lo < 0 < hi:
            parts.append(
                f'<line x1="{px}" y1="{sy(0):.1f}" x2="{px + panel_w:.1f}" '
                f'y2="{sy(0):.1f}" stroke="var(--ink-secondary)" stroke-width="1"/>'
            )

        ref_path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}"
            for i, v in enumerate(ref_values)
        )
        parts.append(
            f'<path d="{ref_path}" fill="none" stroke="var(--ink-muted)" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        zone_path = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}"
            for i, v in enumerate(panel.values)
        )
        parts.append(
            f'<path d="{zone_path}" fill="none" stroke="{accent}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )

        parts.append(
            f'<text x="{px}" y="{py - 12}" font-size="12" font-weight="600" '
            f'fill="var(--ink-primary)">{esc(panel.label)}</text>'
        )
        if panel.caption:
            # Measured before placing so a long caption cannot run past the
            # panel it belongs to.
            width = len(panel.caption) * 10.5 * 0.55
            parts.append(
                f'<text x="{px + panel_w:.1f}" y="{py - 12}" text-anchor="end" '
                f'font-size="10.5" fill="var(--ink-muted)" '
                f'style="font-variant-numeric:tabular-nums">{esc(panel.caption)}</text>'
                if width < panel_w - 60 else ""
            )

        if col == 0:
            parts.append(_axis_left(px, py, py + panel_h, ticks, sy, lambda t: fmt(t)))
        parts.append(
            f'<line x1="{px}" y1="{py + panel_h}" x2="{px + panel_w:.1f}" '
            f'y2="{py + panel_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
        )
        step = max(1, slots // 5)
        for i in range(0, slots, step):
            parts.append(
                f'<text x="{sx(i):.1f}" y="{py + panel_h + 16}" text-anchor="middle" '
                f'font-size="10.5" fill="var(--ink-muted)" '
                f'style="font-variant-numeric:tabular-nums">'
                f"{esc(x_labels[i])}</text>"
            )

        for i in range(slots):
            tip = (
                f"{x_labels[i]} — {panel.label}: {fmt(panel.values[i])} {unit} · "
                f"{ref_label}: {fmt(ref_values[i])} {unit}"
            )
            # Clamped to the panel: with few points the half-width band around
            # the last one runs past the right edge of the canvas, which is a
            # real overflow rather than a rounding artifact.
            band = panel_w / slots
            x0 = max(px, sx(i) - band / 2)
            x1 = min(px + panel_w, sx(i) + band / 2)
            parts.append(
                f'<rect x="{x0:.1f}" y="{py}" '
                f'width="{x1 - x0:.1f}" height="{panel_h}" fill="transparent" '
                f'data-tip="{esc(tip)}"/>'
            )

    parts.append(
        f'<text x="14" y="{height / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {height / 2})">'
        f"{esc(unit)}</text>"
    )

    table_rows = [
        [x_labels[i], fmt(ref_values[i])] + [fmt(p.values[i]) for p in panels]
        for i in range(slots)
    ]
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: one panel per zone, shared scale"),
        table_headers=["", ref_label] + [p.label for p in panels],
        table_rows=table_rows,
        legend=[(accent, series_label), ("var(--ink-muted)", ref_label)],
    )


def coupling_scatter(
    fig_id: str,
    title: str,
    subtitle: str,
    points: list[tuple[float, float]],
    fit: tuple[float, float],
    x_label: str,
    y_label: str,
    unit: str,
    note: str = "",
) -> Figure:
    """A signed scatter with its fitted line, for the zone coupling regressions.

    Distinct from `scatter` because both axes here cross zero and mean it: the
    driving gradient reverses sign between the heating and cooling seasons, and
    the point of the chart is that the response reverses with it. An axis pinned
    to zero at the bottom, as the utility scatters use, would hide half the data.
    """
    if not points:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    height = 380
    left, right, top, bottom = 66, 26, 24, 56
    plot_w, plot_h = W - left - right, height - top - bottom

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_pad = (max(xs) - min(xs)) * 0.06 or 1.0
    y_pad = (max(ys) - min(ys)) * 0.10 or 1.0
    x_lo, x_hi = min(xs) - x_pad, max(xs) + x_pad
    y_lo, y_hi = min(ys) - y_pad, max(ys) + y_pad

    def sx(v: float) -> float:
        return left + (v - x_lo) / (x_hi - x_lo) * plot_w

    def sy(v: float) -> float:
        return top + plot_h - (v - y_lo) / (y_hi - y_lo) * plot_h

    y_ticks = nice_ticks(y_lo, y_hi, 5)
    x_ticks = nice_ticks(x_lo, x_hi, 6)
    parts = [_gridlines(left, left + plot_w, y_ticks, sy)]

    for value, orient in ((0.0, "v"), (0.0, "h")):
        if orient == "v" and x_lo < value < x_hi:
            parts.append(
                f'<line x1="{sx(value):.1f}" y1="{top}" x2="{sx(value):.1f}" '
                f'y2="{top + plot_h}" stroke="var(--ink-secondary)" stroke-width="1"/>'
            )
        if orient == "h" and y_lo < value < y_hi:
            parts.append(
                f'<line x1="{left}" y1="{sy(value):.1f}" x2="{left + plot_w}" '
                f'y2="{sy(value):.1f}" stroke="var(--ink-secondary)" stroke-width="1"/>'
            )

    for x, y in points:
        parts.append(
            f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.2" '
            f'fill="var(--zone-accent)" fill-opacity="0.5"/>'
        )

    intercept, slope = fit
    seg = clip_segment(
        x_lo, intercept + slope * x_lo, x_hi, intercept + slope * x_hi,
        x_lo, x_hi, y_lo, y_hi,
    )
    if seg:
        ax, ay, bx, by = seg
        parts.append(
            f'<line x1="{sx(ax):.1f}" y1="{sy(ay):.1f}" x2="{sx(bx):.1f}" '
            f'y2="{sy(by):.1f}" stroke="var(--ink-primary)" stroke-width="2"/>'
        )

    parts.append(_axis_left(left, top, top + plot_h, y_ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    for t in x_ticks:
        parts.append(
            f'<text x="{sx(t):.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">{esc(fmt(t))}</text>'
        )
    parts.append(
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 12}" text-anchor="middle" '
        f'font-size="11" fill="var(--ink-secondary)">{esc(x_label)}</text>'
    )
    parts.append(
        f'<text x="16" y="{top + plot_h / 2:.1f}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" '
        f'transform="rotate(-90 16 {top + plot_h / 2:.1f})">{esc(y_label)}</text>'
    )

    for x, y in points:
        parts.append(
            f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="9" fill="transparent" '
            f'data-tip="{esc(f"{x_label}: {fmt(x)} {unit} · {y_label}: {fmt(y)} {unit}")}"/>'
        )

    ordered = sorted(points)
    step = max(1, len(ordered) // 24)
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: {y_label} against {x_label}"),
        table_headers=[x_label, y_label],
        table_rows=[[fmt(p[0]), fmt(p[1])] for p in ordered[::step]],
    )


# ---------------------------------------------------------------------------
# Load duration curve
# ---------------------------------------------------------------------------


def duration_curve(
    fig_id: str,
    title: str,
    subtitle: str,
    curve: list[float],
    stream: str,
    unit: str,
    markers: list[tuple[float, str]] | None = None,
    note: str = "",
    # Percentiles off the *full* sorted series. The drawn curve is downsampled,
    # so reading them back off it would disagree with the prose quoting the
    # exact figures — by a few hundredths, which is exactly the kind of drift a
    # reader notices and cannot explain.
    percentiles: dict[int, float] | None = None,
    # Time the curve represents. A percentage answers "how often" in a unit
    # nobody budgets in; days answer it in one they do. Given both, "10% of the
    # year" also reads as "36 days", which is the form the number gets used in.
    total_days: float | None = None,
) -> Figure:
    """Every reading of the year sorted descending, against share of the year.

    Not a time series: the x-axis is rank, so a point says "this load was
    exceeded for this fraction of the year" and nothing at all about when. That
    is the whole point of the form — it separates how *much* from how *often*,
    which a calendar view deliberately mixes together.
    """
    if len(curve) < 2:
        return Figure(id=fig_id, title=title, svg="", subtitle=subtitle)

    # A second row of axis labels needs the room; without days the layout is
    # unchanged from before this option existed.
    height = 374 if total_days else 360
    left, right, top, bottom = 62, 30, 22, (66 if total_days else 52)
    plot_w, plot_h = W - left - right, height - top - bottom
    n = len(curve)
    v_max = max(curve) * 1.08 or 1.0

    def sx(i: float) -> float:
        return left + i / (n - 1) * plot_w

    def sy(v: float) -> float:
        return top + plot_h - v / v_max * plot_h

    ticks = nice_ticks(0, v_max)
    parts = [_gridlines(left, left + plot_w, ticks, sy)]
    parts.append(_axis_left(left, top, top + plot_h, ticks, sy, lambda t: fmt(t)))
    parts.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="var(--ink-axis)" stroke-width="1"/>'
    )
    for pct in range(0, 101, 20):
        x = left + pct / 100 * plot_w
        parts.append(
            f'<text x="{x:.1f}" y="{top + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="var(--ink-muted)" '
            f'style="font-variant-numeric:tabular-nums">{pct}%</text>'
        )
        if total_days:
            parts.append(
                f'<text x="{x:.1f}" y="{top + plot_h + 33}" text-anchor="middle" '
                f'font-size="10" fill="var(--ink-muted)" '
                f'style="font-variant-numeric:tabular-nums">'
                f"{pct / 100 * total_days:.0f}d</text>"
            )

    # Filled to the baseline: the area under the curve is the year's energy, so
    # the fill is meaningful rather than decorative.
    area = (
        f"M{sx(0):.1f},{sy(curve[0]):.1f} "
        + " ".join(f"L{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(curve))
        + f" L{sx(n - 1):.1f},{sy(0):.1f} L{sx(0):.1f},{sy(0):.1f} Z"
    )
    parts.append(f'<path d="{area}" fill="{paint(stream)}" fill-opacity="0.14"/>')
    line = " ".join(
        f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(curve)
    )
    parts.append(
        f'<path d="{line}" fill="none" stroke="{paint(stream)}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    for share, label in markers or []:
        x = left + share * plot_w
        i = min(n - 1, int(share * (n - 1)))
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" '
            f'stroke="var(--ink-axis)" stroke-width="1"/>'
        )
        anchor = "end" if share > 0.6 else "start"
        dx = -6 if share > 0.6 else 6
        parts.append(
            f'<text x="{x + dx:.1f}" y="{sy(curve[i]) - 10:.1f}" text-anchor="{anchor}" '
            f'font-size="10.5" fill="var(--ink-secondary)">{esc(label)}</text>'
        )

    for i, v in enumerate(curve):
        share = i / (n - 1)
        # The two ends are not percentiles. At the left edge "the share of the
        # year at or above" is one interval, which rounds to 0% and then to zero
        # days — reading as "never", about the highest number in the series. Say
        # what those points are instead.
        if i == 0:
            tip = f"the year's peak: {fmt(v)} {unit}"
        elif i == n - 1:
            tip = f"the year's quietest quarter-hour: {fmt(v)} {unit}"
        else:
            # A decimal in the first and last percent, where whole numbers round
            # to 0% or 100% and contradict the duration printed beside them.
            pct = f"{share:.1%}" if share < 0.01 or share > 0.99 else f"{share:.0%}"
            if total_days:
                days = share * total_days
                span = f"{days:.0f} days" if days >= 1.5 else f"{days * 24:.0f} hours"
                tip = f"{pct} of the year — {span} — at or above {fmt(v)} {unit}"
            else:
                tip = f"{pct} of the year at or above {fmt(v)} {unit}"
        parts.append(
            f'<rect x="{sx(i) - plot_w / n / 2:.1f}" y="{top}" '
            f'width="{plot_w / n:.1f}" height="{plot_h}" fill="transparent" '
            f'data-tip="{esc(tip)}"/>'
        )

    parts.append(
        f'<text x="{left + plot_w / 2}" y="{height - 10}" text-anchor="middle" '
        f'font-size="11" fill="var(--ink-secondary)">'
        f"share of the year at or above</text>"
    )
    parts.append(
        f'<text x="14" y="{top + plot_h / 2}" text-anchor="middle" font-size="11" '
        f'fill="var(--ink-secondary)" transform="rotate(-90 14 {top + plot_h / 2})">'
        f"{esc(unit)}</text>"
    )

    src = dict(percentiles or {})
    src.setdefault(0, curve[0])
    src.setdefault(100, curve[-1])
    # Whatever the caller measured off the full series, plus the two ends. The
    # dense steps below 1% are where a load-duration curve earns its keep: this
    # one gives up almost as much in its first percent as across the other
    # ninety-nine, and a table jumping straight from the peak to 1% hides the
    # whole cliff in a single row.
    picks = tuple(sorted({0.0, 100.0} | {float(p) for p in src}))
    values = [src[p] if p in src else curve[min(n - 1, int(n * p / 100))] for p in picks]
    # Both ends are named, matching the tooltips. 0% is the peak rather than a
    # share of the year — printing it as "0% of the year, 0 days" says the
    # largest reading never happened. 100% keeps its share, because "the whole
    # year sat at or above this" is the true and useful reading of the floor.
    labels = [
        "Peak" if p == 0 else "100% (floor)" if p == 100 else f"{p:g}%"
        for p in picks
    ]

    def span(p: float) -> str:
        """A share of the year in days, kept in one unit so the header stays true.

        Fractions below ten days rather than a switch to hours: the column is
        headed Days, and a table that reads 9 h, 22 h, 2, 4 is three units deep
        before the reader reaches the middle of it.
        """
        days = p / 100 * total_days
        return f"{days:.1f}" if days < 10 else f"{days:.0f}"

    if total_days:
        headers = ["Share of the year", "Days", f"At or above ({unit})"]
        rows = [
            [lab, "—" if p == 0 else span(p), fmt(v)]
            for lab, p, v in zip(labels, picks, values)
        ]
    else:
        headers = ["Share of the year", f"At or above ({unit})"]
        rows = [[lab, fmt(v)] for lab, v in zip(labels, values)]
    return Figure(
        id=fig_id,
        title=title,
        subtitle=subtitle,
        note=note,
        svg=_svg(height, "".join(parts), f"{title}: {unit} against share of the year"),
        table_headers=headers,
        table_rows=rows,
    )
