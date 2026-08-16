"""The dashboard's sections — one module each, in reading order.

Each module exposes `build(data: Analysis)` and returns either a `Section` or,
where the data it needs may be absent, `None`. A section reads only from the
analysis layer: it may not read another section's working, so the page survives
any subset of its sources being missing.

Reading order is declared by `MODULES` below rather than emerging from the order
the code happens to compute things in. That used to be a list of section ids
checked against the built sections at run time; ordering the modules themselves
makes the check unnecessary, because there is no longer an order to get wrong.
"""

from __future__ import annotations

import sys

from src.analysis import Analysis
from src.report import Section
from src.sections import (anomalies, bills, costs, electricity, equipment,
                          hourly_water, irrigation, overview, pool, provenance,
                          solar, watch, weather, zones)

# Grouped by what the reader is being told about: the money, then one meter at a
# time, then the pool that crosses all three, then the house as a thermal
# object, then what departed from prediction, then the long view.
MODULES = (
    overview, costs,              # what it costs
    electricity, solar,           # the electricity meter
    irrigation, hourly_water,     # the water meter
    pool,                         # the system that crosses both
    weather, zones,               # the house against the weather
    anomalies,                    # what departed from prediction
    bills,                        # the long view
    # The tail of the page is reference rather than argument: what to carry
    # forward to the next export, the nameplates everything above was checked
    # against, and what the whole thing rests on. `equipment` sits here rather
    # than mid-page because it is a lookup table — nothing downstream reads
    # better for having met the machines first.
    watch, equipment, provenance,
)


def build_all(data: Analysis) -> list[Section]:
    """Build every section whose inputs are present, in reading order."""
    sections = [s for s in (m.build(data) for m in MODULES) if s is not None]
    _check(sections)
    return sections


def _check(sections: list[Section]) -> None:
    """Refuse to build on the mistakes that are invisible on the rendered page.

    A missing emoji is invisible in a diff and a repeated one is worse than
    none: it makes two sections look like the same subject. A duplicate id
    silently breaks every in-page link to one of them.
    """
    if unmarked := [s.id for s in sections if not s.emoji]:
        sys.exit(f"Section(s) {unmarked} have no emoji — refusing to build.")
    marks = [s.emoji for s in sections]
    if dupes := sorted({e for e in marks if marks.count(e) > 1}):
        sys.exit(f"Emoji {dupes} used by more than one section — refusing to build.")
    ids = [s.id for s in sections]
    if clashes := sorted({i for i in ids if ids.count(i) > 1}):
        sys.exit(f"Section id(s) {clashes} used more than once — refusing to build.")
