"""Design tokens.

Values come from the data-viz reference palette. The three categorical slots
used here — blue / orange / aqua for electric / gas / water — were validated
with `validate_palette.js` under `--pairs all` in both modes:

    light  worst CVD dE 9.2, worst normal-vision dE 24.0, aqua 2.74:1 (WARN)
    dark   worst CVD dE 9.4, worst normal-vision dE 20.9, all >= 3:1

The light-mode contrast warning on aqua is discharged the way the method
requires: every chart ships visible direct labels and a table view, so no value
is reachable by colour alone.

Colour follows the *stream*, never the rank — water is aqua in every chart on
the page, whatever order it appears in.
"""

from __future__ import annotations

# --- categorical: one fixed slot per utility stream -------------------------
STREAM_COLORS = {
    "electric": {"light": "#2a78d6", "dark": "#3987e5", "name": "Electric"},
    "gas": {"light": "#eb6834", "dark": "#d95926", "name": "Natural gas"},
    "water": {"light": "#1baf7a", "dark": "#199e70", "name": "Water"},
}

# --- the building envelope: one accent, plus neutral ink for context --------
#
# The four indoor zones are an *ordered* ladder — outdoor, shed, garage, patio,
# house — so the obvious move is a five-step sequential ramp. It was tried and
# rejected: five steps of one hue fail the normal-vision separation floor
# (worst pair dE 6.6), which is exactly what a sequential ramp is expected to do
# when it is asked to carry identity instead of magnitude.
#
# The zone charts are small multiples instead. Each panel holds one zone in the
# accent below against the same outdoor curve in muted ink, so the palette that
# actually renders is two colours, and the ladder is read from the panels rather
# than from a legend. Validated as the pair it is, in both modes:
#
#     light  CVD dE 9.9, normal-vision dE 20.7, both >= 3:1
#     dark   CVD dE 9.4, normal-vision dE 17.7, both >= 3:1
#
# The chroma floor fails on the grey in both modes, which is the intent: it is
# the shared reference, not a series competing for identity. Magenta was chosen
# over violet because violet collides with electric blue under tritanopia
# (dE 4.0).
#
# The accent means *the building as a thermal object* — the zone panels, the
# coupling scatter, the envelope. It also stands in where a non-metered series
# has to sit beside a stream colour and be told apart from it: the evaporation
# prediction against the water meter, the pool probe against the pump's load.
#
# It is not a general "not a utility" colour. That was tried and it flattened a
# dozen unrelated figures into one apparent family. The rules that replaced it:
#
#   * a subject that recurs earns a hue — utilities, the building, the weather;
#   * a chart with one series and no neighbour takes `--ink-secondary`, because
#     its title already names it and an accent would imply a contrast that is
#     not there;
#   * layout is not subject. Reusing the zone small-multiples for the gas and
#     water meters does not make those charts about the building, and they carry
#     their own stream colour through `zone_multiples(accent=...)`.
#
# Where the accent does share a frame with a stream, the pairings were measured:
#
#     vs water    light dE 35.2 / CVD 15.0     dark dE 29.0 / CVD 12.1
#     vs gas      light dE 22.2 / CVD 15.1     dark dE 18.7 / CVD 13.0
#     vs electric light dE 24.1 / CVD 12.8     dark dE 23.0 / CVD  7.9
#
# One exclusion survives: magenta and electric blue must not share a frame in
# dark mode, where protanopia brings them to dE 7.9, just under the target of 8.
ZONE_ACCENT = {"light": "#b0338c", "dark": "#e07ec0"}

# --- sequential: single hue, light -> dark ----------------------------------
BLUE_RAMP = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef",
    "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
    "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

# Sequential ramps per stream, so a water heatmap reads as water. Each is one
# hue stepped light->dark; never a rainbow.
ORANGE_RAMP = [
    "#fce3d6", "#f9cdb6", "#f6b595", "#f39d74",
    "#ef8553", "#eb6834", "#d95926", "#c14d20",
    "#a5411b", "#8a3616",
]
AQUA_RAMP = [
    "#d0f0e4", "#a9e4d0", "#7fd7ba", "#54caa4",
    "#2fbc8e", "#1baf7a", "#199e70", "#158a61",
    "#117252", "#0d5a41",
]

STREAM_RAMPS = {"electric": BLUE_RAMP, "gas": ORANGE_RAMP, "water": AQUA_RAMP}

# --- sunlight, and atmospheric electricity -----------------------------------
#
# Colour follows the physical quantity, not the billing relationship. That is the
# rule the page had all along without saying so: solar *generation* is electric
# blue even though no meter ever recorded it, because it is electricity. Read the
# same way, rain is water and takes the water hue — it is not the city's water,
# but it is not a different substance either.
#
# Two things fall outside all three streams and still recur:
#
#   Sunlight, as W/m^2 rather than the kWh it might become. Gold, measured
#   against everything it can appear beside — worst pair is the zone accent in
#   light at CVD dE 9.0; against gas, which it is nearest in hue, 21.3 / 15.1.
#   Contrast 6.7:1 light and 12.1:1 dark.
#
#   Lightning. Physically electricity, but painting it the utility blue would
#   have a reader looking for it on a bill. Violet is deliberately adjacent to
#   blue without being it. One series, alone in its panel, so only surface
#   contrast applies: 8.8:1 light, 6.4:1 dark. It must not share a plot with
#   electric blue (dark dE 13.7) or the zone accent (12.3); neither happens.
SOLAR_ACCENT = {"light": "#854d0e", "dark": "#fcd34d"}
# --- money ------------------------------------------------------------------
#
# Dollars are their own quantity. A chart of what a day *cost* is not a chart of
# electricity, even when the dollars came off the electric bill — the same way
# heating degree-days are not gas. Three charts plot money and had been wearing
# the stream colours of the meters the money came from.
#
# Emerald, because green reads as money and the water hue is the only other
# green on the page. Measured against every colour it could be confused with,
# nearest first:
#
#     vs water   light dE 16.5 / CVD 16.2     dark dE 15.4 / CVD 15.2
#     vs solar   light dE 16.7 / CVD  7.9     dark dE 20.3 / CVD 12.9
#
# The water pairing clears both floors, which is what allows two greens. The
# solar pairing does not clear CVD, so the two must not share a frame — money
# appears on the cost scatter, the array-size bars and the year-on-year split;
# sunlight appears only on the pump-start panels. They never meet.
#
# Note what does NOT take this colour: the ranked cost chart, which is money
# split *by meter* and where the stream colours are the entire point.
MONEY_ACCENT = {"light": "#047857", "dark": "#34d399"}
STORM_ACCENT = {"light": "#5b21b6", "dark": "#a78bfa"}

# --- weather, everything without a hue of its own ----------------------------
#
# Rain took the water hue and lightning took violet because each is unmistakably
# one substance. What is left is the ambient backdrop — outdoor temperature,
# wind — and it gets one colour between them rather than a hue each.
#
# Temperature belongs here rather than with the building accent. A zone chart is
# about a room; an outdoor temperature is about the day, and the same reading
# drives the gas fit, the cooling fit and the cost curve. That makes it one of
# the most-used quantities on the page, not a leftover, so it gets a colour with
# presence. A warm brick also says heat, which is most of what it carries.
#
# Chosen by searching the hue wheel rather than by taste, scored against what it
# actually shares a frame with — rain and lightning on the monsoon panels, and
# all three meters on the daily timeline, where outdoor temperature is one panel
# among four:
#
#     worst adjacent  dE 20.4 / CVD 19.5   (gas, dark)
#     nearest on the page but never beside it  dE 11.2 (sunlight)
#     contrast 9.8:1 light, 9.2:1 dark
#
# Swapping brick and the lightning violet was considered and rejected on that
# timeline pairing: violet against electric blue measures dE 13.7 / CVD 5.1 in
# dark, under both floors, and temperature cannot avoid sharing that figure.
# Brick clears every meter in both modes. The cost is that a warm red implies
# heat on a quantity that runs both ways — accepted, because the alternative
# fails a pairing the page actually contains.
#
# A warm neutral was tried first and reverted. It measured well — better than any
# hue against the full palette — but only because it is barely a colour, and the
# quantity it carries deserves better than an absence.
#
# It sits near `status-critical` in hue. No chart paints a status colour; those
# are callout dots, a different context entirely.
WEATHER_ACCENT = {"light": "#7f1d1d", "dark": "#fca5a5"}

# --- ordered bands within one stream ----------------------------------------
#
# Three temperature bands of the *same* quantity — electricity — are ordered, not
# categorical, so they take three steps of the stream's own hue rather than three
# different hues. Painting cold days aqua and hot days orange, as this once did,
# says "water" and "gas" to anyone reading the rest of the page.
#
# Steps differ per mode because a ramp anchored for white is invisible on black.
# Measured, adjacent pairs:
#
#     light  dE 14.4 and 19.5; contrast 2.91, 5.26, 11.64 : 1
#     dark   dE 20.3 and 14.9; contrast 13.16, 6.96, 3.94 : 1
#
# One hue is near-immune to colour-vision deficiency: the worst adjacent pair
# under protanopia, deuteranopia or tritanopia is dE 14.4, against a target of 8.
# The lightest light-mode step sits under 3:1, discharged the same way the aqua
# stream's warning is — every line carries a direct end-label in ink and the
# figure ships a table view, so nothing is reachable by colour alone.
BAND = {
    "light": ["#5598e7", "#256abf", "#0d366b"],
    "dark": ["#cde2fb", "#6da7ec", "#2a78d6"],
}

# --- status: reserved, never reused for a series ----------------------------
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# --- held out of a fit ------------------------------------------------------
#
# Points a model excluded are not a status. They are not bad days, they are days
# a heating fit has no business explaining — a spa soak, the pool heater. So they
# do not take a status colour, and `critical` red in particular fails against the
# gas stream it has to sit beside: OKLab dE 10.8 in light and 6.8 in dark, both
# under the normal-vision floor of 15, which is exactly the pairing a reader
# reported as hard to tell apart.
#
# A neutral slate reads as "set aside" rather than "alarming", and clears both
# streams in both modes. Measured, worst case across gas and electric:
#
#     light  normal dE 23.8, CVD dE 23.0
#     dark   normal dE 15.4, CVD dE 13.2
#
# Size carries it too: excluded marks are smaller and drawn first, so the days
# the fit used sit on top of the days it discarded. Hollow rings were tried and
# reverted — a ring has two contours to a dot's one, so it out-shouts the solid
# marks it is supposed to sit behind.
#
# The two modes are not mirror images. Light keeps a dark slate because nothing
# lighter clears the normal-vision floor against electric blue. Dark deliberately
# does *not* use the mirror-image near-white: #cbd5e1 measured 11.7:1 against the
# surface and drew the eye harder than the data, which is the wrong emphasis for
# points a model threw out. #94a3b8 sits at 6.8:1 — present, checkable, quiet.
EXCLUDED = {"light": "#334155", "dark": "#94a3b8"}

# --- chrome & ink -----------------------------------------------------------
INK = {
    "surface": {"light": "#fcfcfb", "dark": "#1a1a19"},
    "plane": {"light": "#f9f9f7", "dark": "#0d0d0d"},
    "primary": {"light": "#0b0b0b", "dark": "#ffffff"},
    "secondary": {"light": "#52514e", "dark": "#c3c2b7"},
    "muted": {"light": "#898781", "dark": "#898781"},
    "grid": {"light": "#e1e0d9", "dark": "#2c2c2a"},
    "axis": {"light": "#c3c2b7", "dark": "#383835"},
    "border": {"light": "rgba(11,11,11,0.10)", "dark": "rgba(255,255,255,0.10)"},
    "success": {"light": "#006300", "dark": "#0ca30c"},
}

FONT_STACK = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def css_variables() -> str:
    """Emit the token block, with dark declared under both scopes.

    The media query covers the OS setting; the `data-theme` scope covers the
    page's own toggle and must win in both directions.
    """

    def block(mode: str) -> str:
        lines = []
        for role, pair in INK.items():
            lines.append(f"    --ink-{role}: {pair[mode]};")
        for stream, spec in STREAM_COLORS.items():
            lines.append(f"    --stream-{stream}: {spec[mode]};")
        lines.append(f"    --zone-accent: {ZONE_ACCENT[mode]};")
        lines.append(f"    --mark-excluded: {EXCLUDED[mode]};")
        lines.append(f"    --solar-accent: {SOLAR_ACCENT[mode]};")
        lines.append(f"    --money-accent: {MONEY_ACCENT[mode]};")
        lines.append(f"    --weather-accent: {WEATHER_ACCENT[mode]};")
        lines.append(f"    --storm-accent: {STORM_ACCENT[mode]};")
        for i, step in enumerate(BAND[mode], 1):
            lines.append(f"    --band-{i}: {step};")
        for name, hexv in STATUS.items():
            lines.append(f"    --status-{name}: {hexv};")
        return "\n".join(lines)

    return f"""
:root {{
    color-scheme: light;
{block("light")}
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
{block("dark")}
  }}
}}
:root[data-theme="dark"] {{
    color-scheme: dark;
{block("dark")}
}}
"""


def ramp_for(stream: str) -> list[str]:
    return STREAM_RAMPS.get(stream, BLUE_RAMP)
