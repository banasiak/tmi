"""Measured and observed constants for the one house this dashboard describes.

Everything here is either read off a meter during a known event, measured by the
owner, or read off the irrigation controller's own display. Nothing is a
default, an estimate, or a figure copied from a specification sheet — where a
number could not be established that way it lives in the model that derives it,
not here.

Isolated in one module because these are the assumptions the whole page rests
on: a reader checking whether a conclusion is sound should be able to find every
hand-supplied input in one screen, rather than hunting them through the code
that consumes them.
"""

from __future__ import annotations

import datetime as dt

# Recovered from the complete drain and refill of 29-30 March: the meter recorded
# the whole system going back in. The spa share comes from the evening soaks,
# which heat it alone.
SYSTEM_GALLONS = 5000.0
# Water surface, from the owner's measurement of the pool. Load-bearing only for
# the evaporation cross-check, which is also the one thing on this page able to
# argue with it — see `model.pool_evaporation`.
POOL_SURFACE_SQFT = 181.0
SPA_GALLONS = 550.0

# Total valve-open time of an irrigation cycle, in minutes. Two zones in series
# at 15 minutes each, and a seasonal-adjust percentage the owner drops to 50% for
# the winter and restores in the spring — which the X-Core applies per station
# and rounds to the minute, so 15 becomes 7 and a cycle is 14 minutes rather than
# 15. That rounding is why the winter figure is not exactly half.
#
# One program with a scaler on it, not two programs. Read off the controller
# by the owner; these are the only irrigation figures here that do not come from
# a meter.
#
# The controller has two states, not a season-long ramp. That matters for how
# every irrigation figure on this page is read: the winter-to-summer step is a
# programmed change of runtime, and anything that drifts smoothly across the year
# is something else drawing water — pool top-up through the float valve, hose
# work, washing the motorcycle. Holding these two numbers fixed is what lets the
# delivered rate be solved for, and it is what isolates July as the one week that
# does not fit.
IRRIGATION_WINTER_MIN = 14.0
IRRIGATION_SUMMER_MIN = 30.0
# Which months run the long program. Bracketed by the sampled weeks rather than
# asserted: the first week of February is still at winter volume and the last
# week of March is already at summer volume, so the switch falls between them.
IRRIGATION_SUMMER_MONTHS = {3, 4, 5, 6, 7, 8, 9, 10}
# March is the changeover and runs both programs in the same month — the hourly
# record has it starting at winter volume and ending at summer. It is therefore
# no use as a reference period, so the fault scan works from April.
IRRIGATION_SETTLED_SUMMER = IRRIGATION_SUMMER_MONTHS - {3}

# The leak the meter found, then confirmed by digging. The zone is the one thing
# here the water data could never have supplied: two zones run back-to-back
# inside a single hourly bucket, so the meter can say a cycle lost 96 gallons and
# can never say which valve was open at the time. Set to None until someone has
# actually looked — an unconfirmed inference should not be allowed to read like a
# finding, which is the whole reason this is a constant rather than prose.
LEAK_FOUND_ZONE = "Zone 1"

# The March drain and refill, as interval STARTS — the loader shifts the vendor's
# hour-ending stamps back an hour, so this is 15:00–18:00 as the export labels it.
REFILL_WINDOW = (dt.datetime(2026, 3, 29, 14), dt.datetime(2026, 3, 30, 17))


#
# The tilt is measured: 22.5 degrees, off the roof itself. The PVWatts runs
# were commissioned at 22.6 and are kept, because re-running them would move
# nothing that can be seen. Plane-of-array changes by 2.4 kWh/m² per degree
# on the east slope and 4.0 on the west, so the 0.1 degree between the runs
# and the roof is worth 0.02% — three orders of magnitude below the
# performance ratio's own uncertainty.
#
# Worth recording that the assumption held: 22.6 was originally picked
# because it sat near the optimum for a south roof, which was circular
# reasoning that stopped applying the moment the roof turned out to be an
# east-west gable. It survived on luck, not method.
MEASURED_TILT = 22.5
# Phone inclinometer, so about a degree either way — the reading is 22.5 but
# the claim is 22-23. Quoting it to a tenth would credit the instrument with
# precision it does not have, and would make the agreement with ROOF_TILT
# below look like a coincidence rather than what it is: a measurement that
# cannot distinguish the two, over a range where the distinction is worth
# about 0.2% of plane-of-array.
MEASURED_TILT_TOL = 1.0
ROOF_TILT = 22.6                # the tilt the PVWatts runs were made at
# Both measured off the roof rather than estimated. The mount height is what
# excludes the ridge as the eastern obstruction: a ridge blocks to B degrees
# only when the sensor sits (tan(pitch) - tan(B)) * D above the eave, and at
# 31 inches that needs ~85 ft of roof between sensor and ridgeline. The house
# is nothing like that wide, so the ridge accounts for part of the block and
# something further out — most likely the trees due east — accounts for the
# rest. The conclusion survives a threefold error in the house's width.
MOUNT_HEIGHT_IN = 31.0
MOUNT_BLOCK_DEG = 21.0          # eastern block, binned from the sky itself
# What the roof can contribute, bracketed rather than pinned. An aerial photo
# puts a branch ridgeline about 13 ft east of the sensor and the main ridge
# about 27; at a measured 31 in of pole those cut the sky at 12.6° and 17.7°
# respectively. Which is the actual horizon depends on how far north the main
# ridge runs, which the photo cannot settle — so the roof's share is a range,
# and every value in it falls short of the 21° observed.
MOUNT_RIDGE_NEAR_DEG = 12.6
MOUNT_RIDGE_FAR_DEG = 17.7
ROOF_AZIMUTHS = (90.0, 270.0)  # PVWatts convention: due east, due west

# The complete drain and refill, as calendar dates. Anomaly attribution needs
# the days; the hourly loader needs the interval bounds above. Same event.
REFILL_DATES = {dt.date(2026, 3, 29), dt.date(2026, 3, 30)}
