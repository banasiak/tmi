"""HTML assembly.

Produces one self-contained file: all CSS and JS inline, no network requests, no
build step. Open it with a browser or double-click it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .charts import Figure, esc
from .palette import FONT_STACK, css_variables


@dataclass
class Tile:
    """Stat-tile contract: label, value, optional unit / delta / footnote."""

    label: str
    value: str
    unit: str = ""
    detail: str = ""
    accent: str | None = None  # CSS colour for the identity dot


@dataclass
class Section:
    id: str
    title: str
    lede: str
    blocks: list[object]  # Figure | Tile rows | raw HTML strings
    # One emoji, rendered before the title and hidden from assistive tech. It is
    # decoration that helps the eye find a section while scrolling, so it must
    # not also be read aloud — the title already says what the section is.
    emoji: str = ""
    # Reference material folds away by default. The heading and lede stay
    # outside the fold so the section still announces itself, an anchor link
    # still lands on something visible, and the reader can judge whether to
    # open it — only the body is hidden.
    collapsed: bool = False
    fold_label: str = "Show the full section"


@dataclass
class Callout:
    """A finding worth stating in words, not just plotting."""

    kind: str  # "finding" | "caution" | "note"
    title: str
    body: str


@dataclass
class Formula:
    """A derivation shown rather than asserted.

    Every number on this page comes from somewhere. Where that somewhere is an
    equation rather than a meter reading, this puts the equation on the page
    next to the value it produced, with each symbol named and — where it is a
    fixed input rather than a variable — carrying the value actually used. The
    point is that a reader can check the arithmetic instead of trusting it.
    """

    lhs: str
    rhs: str
    where: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""
    caption: str = ""


def var(name: str, sub: str = "") -> str:
    """A variable, italicised, with an optional subscript."""
    body = f"<var>{esc(name)}</var>"
    return f"{body}<sub>{esc(sub)}</sub>" if sub else body


def frac(numerator: str, denominator: str) -> str:
    return (
        f'<span class="frac"><span class="frac-n">{numerator}</span>'
        f'<span class="frac-d">{denominator}</span></span>'
    )


def sqrt(inner: str) -> str:
    return f'<span class="radical">&#8730;</span><span class="radicand">{inner}</span>'


def formula(f: Formula) -> str:
    where = ""
    if f.where:
        # Emitted flat, not wrapped in a row element: the container is a
        # two-column grid, so a wrapper would become a single cell and collapse
        # the symbol and its definition onto one line.
        rows = "".join(
            f'<span class="where-sym">{sym}</span>'
            f'<span class="where-def">{meaning}</span>'
            for sym, meaning in f.where
        )
        where = f'<div class="formula-where">{rows}</div>'
    caption = f'<p class="formula-caption">{f.caption}</p>' if f.caption else ""
    note = f'<p class="formula-note">{f.note}</p>' if f.note else ""
    return (
        f'<div class="formula">{caption}'
        f'<div class="formula-expr"><span class="lhs">{f.lhs}</span>'
        f'<span class="eq">=</span><span class="rhs">{f.rhs}</span></div>'
        f"{where}{note}</div>"
    )


def tile_row(tiles: list[Tile]) -> str:
    cells = []
    for t in tiles:
        dot = (
            f'<span class="dot" style="background:{t.accent}"></span>'
            if t.accent
            else ""
        )
        unit = f'<span class="tile-unit">{esc(t.unit)}</span>' if t.unit else ""
        detail = f'<p class="tile-detail">{t.detail}</p>' if t.detail else ""
        cells.append(
            f'<div class="tile">'
            f'<p class="tile-label">{dot}{esc(t.label)}</p>'
            f'<p class="tile-value">{esc(t.value)}{unit}</p>'
            f"{detail}</div>"
        )
    return f'<div class="tiles">{"".join(cells)}</div>'


def hero(value: str, label: str, detail: str) -> str:
    return (
        f'<div class="hero"><p class="hero-value">{esc(value)}</p>'
        f'<p class="hero-label">{esc(label)}</p>'
        f'<p class="hero-detail">{detail}</p></div>'
    )


def callout(c: Callout) -> str:
    return (
        f'<aside class="callout callout-{esc(c.kind)}">'
        f'<p class="callout-title">{esc(c.title)}</p>'
        f'<div class="callout-body">{c.body}</div></aside>'
    )


def render_figure(fig: Figure) -> str:
    if not fig.svg:
        return ""
    legend = ""
    if fig.legend:
        items = "".join(
            f'<span class="key"><span class="dot" style="background:{color}"></span>'
            f"{esc(label)}</span>"
            for color, label in fig.legend
        )
        legend = f'<div class="legend">{items}</div>'

    table = ""
    if fig.table_rows:
        head = "".join(f"<th>{esc(h)}</th>" for h in fig.table_headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
            for row in fig.table_rows
        )
        table = (
            f'<details class="table-view"><summary>Table view</summary>'
            f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></details>"
        )

    note = f'<p class="fig-note">{fig.note}</p>' if fig.note else ""
    subtitle = f'<p class="fig-sub">{fig.subtitle}</p>' if fig.subtitle else ""
    return (
        f'<figure class="card" id="{esc(fig.id)}">'
        f'<figcaption><h3>{esc(fig.title)}</h3>{subtitle}</figcaption>'
        f"{legend}"
        f'<div class="chart-wrap">{fig.svg}</div>'
        f"{note}{table}</figure>"
    )


STYLES = """
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: __FONT__;
  background: var(--ink-plane);
  color: var(--ink-primary);
  line-height: 1.55;
  font-size: 15px;
}
.wrap { max-width: 1060px; margin: 0 auto; padding: 32px 20px 96px; }

header.page { padding: 24px 0 8px; }
header.page h1 { font-size: 30px; margin: 0 0 8px; letter-spacing: -0.015em; }
/* Wraps at 80% like every other run of prose on the page — .lede, .fig-sub,
   .fig-note and .hero-detail all hold the same measure, and the subtitle was
   the one line still running the full 1060px. */
header.page p {
  margin: 0; color: var(--ink-secondary); font-size: 16px; line-height: 1.45;
  max-width: 80%;
}
header.page p.source {
  margin-top: 10px; font-size: 13.5px; color: var(--ink-muted);
}

/* Links wear ink, never a stream color. Electric blue means electricity
   everywhere else on this page, and a hyperlink is not a series. */
a {
  color: inherit; text-decoration: underline;
  text-decoration-color: var(--ink-axis); text-underline-offset: 3px;
}
a:hover { color: var(--ink-primary); text-decoration-color: currentColor; }
a:focus-visible {
  outline: 2px solid var(--ink-primary); outline-offset: 2px; border-radius: 2px;
}

.theme-toggle {
  position: fixed; top: 14px; right: 14px; z-index: 20;
  border: 1px solid var(--ink-border); background: var(--ink-surface);
  color: var(--ink-secondary); border-radius: 999px;
  padding: 7px 14px; font: inherit; font-size: 12.5px; cursor: pointer;
}
.theme-toggle:hover { color: var(--ink-primary); }

footer.page {
  margin-top: 56px; padding-top: 20px; text-align: center;
  border-top: 1px solid var(--ink-border);
  color: var(--ink-muted); font-size: 12.5px;
}

section { margin-top: 64px; scroll-margin-top: 20px; }
/* A section title outranks the figure titles inside it, so it has to look it.
   The rule above carries the separation that the old uppercase label was doing
   with letter-spacing, which frees the heading itself to be simply bigger. */
section > h2 {
  font-size: 17px; text-transform: uppercase; letter-spacing: 0.06em;
  line-height: 1.25; color: var(--ink-primary); font-weight: 600;
  margin: 0 0 10px; padding-top: 22px;
  /* A hairline, like every other rule on the page — but in primary ink rather
     than the footer's 10% border, so it reads as a chapter break without
     adding weight the rest of the design does not use. */
  border-top: 1px solid var(--ink-primary);
}
/* The heading's tracking is meant for uppercase words; an emoji inheriting it
   sits too far from its own margin, so the span resets it and sets the gap
   itself. Not scaled up — at 17px it already out-weighs the text beside it. */
section > h2 > .section-emoji { letter-spacing: normal; margin-right: 0.45em; }
section > .lede {
  margin: 0 0 22px; color: var(--ink-secondary); font-size: 15.5px; max-width: 80%;
}
/* Every block in a section carries its own bottom margin — .card, .callout and
   .tiles all declare one. This is the safety net for any that does not: a class
   selector outranks it, so it only applies where nothing else has, and it stops
   a new block type from silently butting against the card below it. */
section > * { margin-bottom: 18px; }
section > *:last-child { margin-bottom: 0; }

.hero { padding: 8px 0 20px; margin-bottom: 0; }
.hero-value { font-size: 54px; font-weight: 600; margin: 0; letter-spacing: -0.02em; line-height: 1.05; }
.hero-label { margin: 4px 0 0; color: var(--ink-secondary); font-size: 15px; }
.hero-detail { margin: 6px 0 0; color: var(--ink-muted); font-size: 13.5px; max-width: 80%; }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
.tile { background: var(--ink-surface); border: 1px solid var(--ink-border); border-radius: 12px; padding: 14px 16px; }
.tile-label { margin: 0 0 6px; font-size: 12.5px; color: var(--ink-secondary); display: flex; align-items: center; gap: 6px; }
.tile-value { margin: 0; font-size: 25px; font-weight: 600; letter-spacing: -0.01em; }
.tile-unit { font-size: 13px; font-weight: 400; color: var(--ink-muted); margin-left: 5px; }
.tile-detail { margin: 6px 0 0; font-size: 12.5px; color: var(--ink-muted); line-height: 1.45; }

.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex: none; }

.card {
  background: var(--ink-surface); border: 1px solid var(--ink-border);
  border-radius: 14px; padding: 18px 18px 14px; margin: 0 0 18px;
}
.card figcaption { margin-bottom: 10px; }
.card h3 { margin: 0; font-size: 16.5px; font-weight: 600; letter-spacing: -0.005em; }
/* Every run of supporting prose is held to 80% of its container: the section
   lede, the hero detail, and a figure's subtitle and note. They were a mix of
   character measures before, which meant a figure's subtitle and the note
   beneath the same chart wrapped at different widths on a wide window. */
.fig-sub { margin: 4px 0 0; color: var(--ink-secondary); font-size: 13.5px; max-width: 80%; }
.fig-note { margin: 10px 0 0; color: var(--ink-muted); font-size: 12.5px; max-width: 80%; }
.chart-wrap { overflow-x: auto; margin: 6px -4px 0; }
.chart { display: block; min-width: 560px; }

.formula {
  margin: 0 0 18px; padding: 14px 16px; border-radius: 12px;
  border: 1px solid var(--ink-border); background: var(--ink-plane);
}
.formula-caption { margin: 0 0 10px; font-size: 12.5px; color: var(--ink-muted); }
.formula-expr {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px;
  font-size: 16px; color: var(--ink-primary); line-height: 2.1;
  overflow-x: auto;
}
.formula-expr var { font-style: italic; font-family: Georgia, "Times New Roman", serif; }
.formula-expr sub { font-size: 0.68em; }
.formula-expr sup { font-size: 0.68em; }
.formula-expr .eq { color: var(--ink-muted); }
/* A fraction is a two-row stack with a rule between, which keeps it legible at
   body size without pulling in a maths typesetting library. */
.frac { display: inline-flex; flex-direction: column; vertical-align: middle;
        text-align: center; margin: 0 2px; }
.frac-n { padding: 0 4px; }
.frac-d { padding: 0 4px; border-top: 1px solid currentColor; }
.radical { margin-right: -2px; }
.radicand { border-top: 1px solid currentColor; padding: 0 3px 0 2px; }
.formula-where {
  margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--ink-grid);
  display: grid; grid-template-columns: auto 1fr; gap: 4px 14px;
  font-size: 12.5px; color: var(--ink-secondary);
}
.where-sym { font-family: Georgia, "Times New Roman", serif; font-style: italic;
             color: var(--ink-primary); white-space: nowrap; }
.where-def { font-variant-numeric: tabular-nums; }
.muted-note { color: var(--ink-muted); font-weight: 400; }
.formula-note { margin: 10px 0 0; font-size: 12.5px; color: var(--ink-muted); }
@media (max-width: 620px) { .formula-expr { font-size: 14px; } }

.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 8px 0 2px; }
.key { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink-secondary); }

.table-view { margin-top: 12px; border-top: 1px solid var(--ink-border); padding-top: 8px; }
.table-view summary { cursor: pointer; font-size: 12.5px; color: var(--ink-secondary); }
.table-view summary:hover { color: var(--ink-primary); }

/* A whole section folded away. Child combinators throughout: every figure in
   here carries its own <details> table view, and an unscoped rule would style
   and toggle those too. */
.section-fold { border-top: 1px solid var(--ink-border); padding-top: 12px; }
.section-fold > summary {
  cursor: pointer; font-size: 13.5px; color: var(--ink-secondary);
  padding: 2px 0; user-select: none;
}
.section-fold > summary:hover { color: var(--ink-primary); }
.section-fold > summary:focus-visible {
  outline: 2px solid var(--stream-electric); outline-offset: 3px; border-radius: 3px;
}
.section-fold[open] > summary { margin-bottom: 4px; color: var(--ink-muted); }
/* Horizontal scrolling only. A wide table has to be able to slide sideways
   inside its card, but capping the height and scrolling vertically hides rows
   behind an inner scrollbar that is easy to miss — tables here are short enough
   to read whole, and a long one belongs in a collapsed table view anyway. */
.table-scroll { overflow-x: auto; margin-top: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 5px 12px 5px 0; border-bottom: 1px solid var(--ink-grid); white-space: nowrap; }
/* Tables carrying a column of prose rather than a column of numbers. Cells stay
   nowrap by default so a figure's table view keeps its columns aligned, but a
   sentence in a cell then pushes the card sideways instead of wrapping. These
   let everything wrap and hold the short columns narrow. */
table.prose { table-layout: fixed; width: 100%; }
table.prose th, table.prose td { white-space: normal; overflow-wrap: anywhere; }
table.prose td:first-child, table.prose th:first-child { width: 21%; }
/* Column 2 is wide enough to hold "Granularity" unbroken — overflow-wrap above
   is set to `anywhere`, so a column too narrow for its own header hyphenates it
   mid-word rather than overflowing. */
table.prose td:nth-child(2), table.prose th:nth-child(2) { width: 14%; }
table.prose td:nth-child(3), table.prose th:nth-child(3) { width: 15%; }
/* The cost table's own shape: a label, two figures, then the note. */
table.cost td:first-child, table.cost th:first-child { width: 26%; }
table.cost td:nth-child(2), table.cost th:nth-child(2) { width: 11%; }
table.cost td:nth-child(3), table.cost th:nth-child(3) { width: 9%; }
th { color: var(--ink-muted); font-weight: 600; position: sticky; top: 0; background: var(--ink-surface); }

.callout { border-radius: 12px; padding: 14px 16px; margin: 0 0 18px; border: 1px solid var(--ink-border); background: var(--ink-surface); }
.callout-title { margin: 0 0 5px; font-weight: 600; font-size: 14.5px; display: flex; align-items: center; gap: 8px; }
.callout-title::before { content: ""; width: 9px; height: 9px; border-radius: 50%; flex: none; }
.callout-finding .callout-title::before { background: var(--status-good); }
.callout-caution .callout-title::before { background: var(--status-critical); }
.callout-note .callout-title::before { background: var(--ink-muted); }
.callout-body { color: var(--ink-secondary); font-size: 14px; }
.callout-body p { margin: 0 0 8px; }
.callout-body p:last-child { margin-bottom: 0; }
.callout-body strong { color: var(--ink-primary); font-weight: 600; }

.anoms { display: grid; gap: 8px; }
.anom {
  display: grid; grid-template-columns: 8px 108px 1fr auto; gap: 12px; align-items: center;
  background: var(--ink-surface); border: 1px solid var(--ink-border);
  border-radius: 10px; padding: 11px 14px;
}
.anom .sev { width: 8px; height: 8px; border-radius: 50%; }
.anom .when { font-size: 13px; color: var(--ink-secondary); font-variant-numeric: tabular-nums; }
.anom .what { font-size: 13.5px; }
.anom .mag { font-size: 13.5px; font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.anom .badge { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-muted); }

#tip {
  position: fixed; pointer-events: none; opacity: 0; z-index: 50;
  background: var(--ink-primary); color: var(--ink-surface);
  padding: 6px 10px; border-radius: 7px; font-size: 12.5px;
  transition: opacity .09s ease; max-width: 300px; line-height: 1.4;
}
[data-tip] { cursor: crosshair; }
[data-tip]:focus-visible { outline: 2px solid var(--ink-primary); outline-offset: 1px; }


@media (max-width: 620px) {
  .hero-value { font-size: 42px; }
  .anom { grid-template-columns: 8px 1fr; row-gap: 4px; }
  .anom .mag, .anom .badge { grid-column: 2; }
  section { margin-top: 48px; }
  section > h2 { font-size: 15px; padding-top: 18px; }
  /* The header steps down too, or 30px against a 15px h2 inverts the hierarchy
     on a phone. The 80% measure also goes: at this width it costs more line
     breaks than it buys in readability. */
  header.page h1 { font-size: 24px; }
  header.page p { font-size: 15px; max-width: 100%; }
}
@media print { .theme-toggle { display: none; } .card { break-inside: avoid; } }
""".replace("__FONT__", FONT_STACK)


SCRIPT = """
(function () {
  var tip = document.getElementById('tip');
  function show(el, x, y) {
    var text = el.getAttribute('data-tip');
    if (!text) return;
    tip.textContent = text;
    tip.style.opacity = '1';
    var r = tip.getBoundingClientRect();
    var left = Math.min(Math.max(8, x + 14), window.innerWidth - r.width - 8);
    var top = y - r.height - 12;
    if (top < 8) top = y + 18;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function hide() { tip.style.opacity = '0'; }

  document.addEventListener('mousemove', function (e) {
    var el = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (el) show(el, e.clientX, e.clientY); else hide();
  });
  // Keyboard parity: focus surfaces exactly what hover does.
  document.addEventListener('focusin', function (e) {
    var el = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (!el) return hide();
    var r = el.getBoundingClientRect();
    show(el, r.left + r.width / 2, r.top);
  });
  document.addEventListener('focusout', hide);
  document.addEventListener('scroll', hide, true);

  var root = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  var saved = null;
  try { saved = localStorage.getItem('weather-theme'); } catch (err) {}
  if (saved) root.setAttribute('data-theme', saved);
  function current() {
    return root.getAttribute('data-theme') ||
      (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  function paint() { btn.textContent = current() === 'dark' ? 'Light' : 'Dark'; }
  btn.addEventListener('click', function () {
    var next = current() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('weather-theme', next); } catch (err) {}
    paint();
  });
  paint();
})();
"""


def render_page(
    title: str,
    heading: str,
    subtitle: str,
    sections: list[Section],
    footer: str,
    source_url: str = "",
    story_url: str = "",
) -> str:
    """Assemble the page.

    `title` is the browser tab; `heading` is the <h1>. They are separate because
    they are read in different places and need not match.

    `source_url` puts the repository under the subtitle. Every number here is
    computed rather than typed, which is only a claim unless the code that does
    the computing is reachable — so the link belongs at the top with the counts
    it is vouching for, not in the footer.

    `story_url` points at the write-up. This page says what is true about the
    house; the post says how long it took and what it cost to find out. Neither
    belongs inside the other, so each links to its counterpart from the top.
    Both are optional and the sentence assembles from whichever are supplied.
    """
    # Shown without their scheme, which is noise in a link people read rather
    # than type. The href keeps it.
    parts: list[str] = []
    if source_url:
        shown = source_url.split("://", 1)[-1].rstrip("/")
        parts.append(
            f"Every number below is recomputed from the raw exports on each "
            f"build; none of it is typed in by hand. The code that does that is "
            f'at <a href="{esc(source_url)}" rel="noopener noreferrer">'
            f"{esc(shown)}</a>."
        )
    if story_url:
        parts.append(
            f'How it got this far is a <a href="{esc(story_url)}" '
            f'rel="noopener noreferrer">separate, much longer, story</a> in the '
            f"Cesspool of Knowledge."
        )
    source_line = f'<p class="source">{" ".join(parts)}</p>' if parts else ""

    body: list[str] = []
    for s in sections:
        blocks = []
        for block in s.blocks:
            if isinstance(block, Figure):
                blocks.append(render_figure(block))
            elif isinstance(block, Callout):
                blocks.append(callout(block))
            else:
                blocks.append(str(block))
        inner = "".join(blocks)
        if s.collapsed:
            inner = (
                f'<details class="section-fold">'
                f"<summary>{esc(s.fold_label)}</summary>"
                f'<div class="section-fold-body">{inner}</div>'
                f"</details>"
            )
        mark = (
            f'<span class="section-emoji" aria-hidden="true">{esc(s.emoji)}</span>'
            if s.emoji
            else ""
        )
        body.append(
            f'<section id="{esc(s.id)}"><h2>{mark}{esc(s.title)}</h2>'
            f'<p class="lede">{s.lede}</p>{inner}</section>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{css_variables()}{STYLES}</style>
</head>
<body>
<button id="theme-toggle" class="theme-toggle" type="button">Dark</button>
<div class="wrap">
<header class="page"><h1>{esc(heading)}</h1><p>{subtitle}</p>{source_line}</header>
{"".join(body)}
<footer class="page">{footer}</footer>
</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{SCRIPT}</script>
</body>
</html>
"""
