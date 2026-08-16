#!/usr/bin/env python3
"""Structural checks on the generated dashboard.

There is no browser in this environment, so correctness that would normally be
confirmed by looking at the page is confirmed here instead: every SVG parses,
the HTML nests properly, nothing is fetched from the network, and no drawn
element escapes its own viewBox. That last check has caught real bugs — axis
ticks emitted past the data maximum, and a reference line whose label landed
1,500 units above the frame.

    python3 tools/validate.py [path]
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

VOID = {
    "meta", "br", "hr", "img", "input", "link",
    "path", "rect", "circle", "line", "text", "tspan", "use",
}
# Rough advance width per character as a fraction of font-size, for the
# label-overflow estimate. Deliberately generous.
CHAR_WIDTH = 0.55


class SectionChildren(HTMLParser):
    """Collect the direct children of every <section>.

    A block dropped into a section without bottom spacing runs straight into
    the card beneath it. That is invisible to an HTML or SVG parse and there is
    no browser here to catch it, so the check is: does every direct child pick
    up a margin from somewhere?
    """

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.depth: int | None = None
        self.children: set[str] = set()

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        if tag == "section":
            self.depth = len(self.stack)
        elif self.depth is not None and len(self.stack) == self.depth + 1:
            self.children.add(classes.split()[0] if classes else tag)
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        if tag == "section":
            self.depth = None


def spacing_gaps(html: str) -> list[str]:
    """Section children with no bottom margin from any rule."""
    style = html[html.find("<style>") : html.find("</style>")]
    catch_all = "section > * { margin-bottom" in style
    parser = SectionChildren()
    parser.feed(html)
    missing = []
    for child in sorted(parser.children):
        # Children are recorded by their first class where they have one, and
        # by tag name otherwise, so try both forms against the stylesheet.
        declared = any(
            re.search(rf"{re.escape(sel)}\s*\{{[^}}]*margin[^}}]*\}}", style)
            for sel in (f".{child}", child)
        )
        if not declared and not catch_all:
            missing.append(child)
    return missing


class Nesting(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.errors.append(f"</{tag}> closed out of order (open: {self.stack[-3:]})")
            while self.stack and self.stack.pop() != tag:
                pass


def outside(value: float, lo: float, hi: float, slack: float = 0.5) -> bool:
    return value < lo - slack or value > hi + slack


def check_svg(svg: str) -> tuple[int, list[str]]:
    root = ET.fromstring(svg)
    _, _, width, height = (float(v) for v in root.get("viewBox").split())
    issues: list[str] = []

    for el in root.iter():
        tag = el.tag.split("}")[-1]
        try:
            if tag == "rect":
                x, y = float(el.get("x", 0)), float(el.get("y", 0))
                w, h = float(el.get("width", 0)), float(el.get("height", 0))
                if outside(x, 0, width) or outside(y, 0, height) or \
                   outside(x + w, 0, width) or outside(y + h, 0, height):
                    issues.append(f"rect {x:.0f},{y:.0f} {w:.0f}x{h:.0f}")
            elif tag == "circle":
                cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
                r = float(el.get("r", 0))
                if outside(cx - r, 0, width) or outside(cx + r, 0, width) or \
                   outside(cy - r, 0, height) or outside(cy + r, 0, height):
                    issues.append(f"circle {cx:.0f},{cy:.0f} r{r:.0f}")
            elif tag == "line":
                for ax, ay in (
                    (float(el.get("x1", 0)), float(el.get("y1", 0))),
                    (float(el.get("x2", 0)), float(el.get("y2", 0))),
                ):
                    if outside(ax, 0, width) or outside(ay, 0, height):
                        issues.append(f"line endpoint {ax:.0f},{ay:.0f}")
            elif tag == "path":
                for m in re.finditer(r"M(-?[\d.]+),(-?[\d.]+)", el.get("d", "")):
                    px, py = float(m.group(1)), float(m.group(2))
                    if outside(px, 0, width) or outside(py, 0, height):
                        issues.append(f"path start {px:.0f},{py:.0f}")
                        break
            elif tag == "text" and not el.get("transform"):
                # Rotated labels are skipped: their bounding box needs the full
                # transform, and they are all axis titles at fixed positions.
                x, y = float(el.get("x", 0)), float(el.get("y", 0))
                text = "".join(el.itertext())
                size = float(el.get("font-size", 11))
                w = len(text) * size * CHAR_WIDTH
                anchor = el.get("text-anchor", "start")
                x0 = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
                if x0 < -1 or x0 + w > width + 1 or y > height + 1 or y < 0:
                    issues.append(f"text y{y:.0f} {text[:30]!r}")
        except (TypeError, ValueError):
            continue

    return len(list(root.iter())), issues


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "build/dashboard.html")
    if not path.exists():
        print(f"missing {path} — run build.py first")
        return 1
    html = path.read_text(encoding="utf-8")

    svgs = re.findall(r"<svg .*?</svg>", html, re.S)
    ids = re.findall(r'<figure class="card" id="([^"]+)"', html)
    failures = 0

    print(f"{path}  ({len(html) / 1024:.0f} KB)\n")
    for fid, svg in zip(ids, svgs):
        try:
            count, issues = check_svg(svg)
        except ET.ParseError as exc:
            print(f"  {fid:16s} MALFORMED SVG: {exc}")
            failures += 1
            continue
        status = "ok" if not issues else f"{len(issues)} GEOMETRY ISSUES"
        print(f"  {fid:16s} {count:5d} elements  {status}")
        for issue in issues[:4]:
            print(f"      {issue}")
        failures += len(issues)

    nesting = Nesting()
    nesting.feed(html)
    # What this guards is the self-contained promise: open the file offline and
    # everything still renders. That means no *fetches* — `src` on any element,
    # and `href` on a <link>, which pulls stylesheets and icons. A plain <a>
    # hyperlink fetches nothing until someone clicks it, and forbidding those
    # would stop the page ever citing its own source repository.
    external = (
        re.findall(r"""\bsrc\s*=\s*["'](?:https?:|//)""", html)
        + re.findall(r"""<link\b[^>]*?\bhref\s*=\s*["'](?:https?:|//)""", html)
    )

    print()
    checks = [
        ("SVG figures parse", len(svgs) == len(ids) and len(svgs) > 0),
        ("HTML fully closed", not nesting.stack),
        ("HTML nesting ordered", not nesting.errors),
        ("No external requests", not external),
        ("Table view per figure", html.count("Table view") == len(svgs)),
        ("No dashed chrome", "stroke-dasharray" not in html),
        ("Light + dark declared", "prefers-color-scheme: dark" in html
            and '[data-theme="dark"]' in html),
        ("Keyboard tooltip parity", "focusin" in html),
        ("Section blocks all spaced", not spacing_gaps(html)),
    ]
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        failures += 0 if passed else 1

    for child in spacing_gaps(html):
        print(f"    no bottom margin: section > .{child}")
    if nesting.stack:
        print(f"    unclosed: {nesting.stack}")
    for err in nesting.errors[:3]:
        print(f"    {err}")

    print(f"\n{'PASS' if failures == 0 else f'{failures} PROBLEM(S)'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
