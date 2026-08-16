"""Number-to-text helpers for running prose.

The page mixes narrative and figures in the same sentence, so a number has to
read as English without ceasing to be checkable. These two rules are applied
page-wide rather than per-sentence so that the same quantity never appears in
two different shapes.
"""

from __future__ import annotations

_SMALL = ("no", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten")


def spell(n: int) -> str:
    """Small counts read better as words in running prose than as numerals.

    Kept data-driven rather than typed in: these counts come from the registries,
    so a machine added to `equipment` must not leave a stale "two" behind.
    """
    return _SMALL[n] if 0 <= n < len(_SMALL) else f"{n:,}"


def money(value: float) -> str:
    """Dollars, with enough precision to still be a number.

    Whole dollars are right for a bill and wrong for a rate: rounding there
    turned an open door's 3.5 cents an hour into "$0", and a $0.35 session into
    "$0 ($0-$0)". Small amounts therefore keep as many places as they need to
    stay distinguishable from zero, and large ones stay clean.
    """
    magnitude = abs(value)
    if magnitude >= 10.0 or value == 0.0:
        return f"${value:,.0f}"
    if magnitude >= 1.0:
        return f"${value:,.2f}"
    if magnitude >= 0.10:
        return f"${value:.2f}"
    return f"${value:.3f}"
