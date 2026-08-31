"""Verify Earth Engine access, and ask the two questions that shape Phase 3/4.

Usage:
    python scripts/gee_check.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
Reads the AOI from config.yaml so it checks the box we actually publish.
"""
import sys

import ee
import yaml

if len(sys.argv) != 2:
    sys.exit(__doc__)
project = sys.argv[1]

ee.Initialize(project=project)
print("initialised    ", project)

w, s, e, n = yaml.safe_load(open("config.yaml"))["aoi_bbox_wsen"]
aoi = ee.Geometry.Rectangle([w, s, e, n])
print("aoi            ", [w, s, e, n])

# Sentinel-2: how much of August is actually usable through the cloud?
# This decides whether dNBR burn-area mapping is viable at all.
s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
      .filterBounds(aoi).filterDate("2026-08-01", "2026-08-31"))
clear = s2.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
print("S2 scenes Aug  ", s2.size().getInfo(),
      "| under 40% cloud:", clear.size().getInfo())

# CHIRPS lags real time by weeks. Ask what it holds rather than assume, and
# never reduce an empty collection - that returns an image with no bands and
# fails with a misleading "Dictionary does not contain key" error.
chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
last = ee.Date(chirps.aggregate_max("system:time_start")).format("YYYY-MM-dd")
print("CHIRPS latest  ", last.getInfo())

recent = chirps.filterDate("2026-07-01", "2026-08-31")
count = recent.size().getInfo()
print("CHIRPS Jul-Aug ", count, "daily images")
if count:
    mm = recent.sum().reduceRegion(
        ee.Reducer.mean(), aoi, 5000).get("precipitation").getInfo()
    print("               ", round(mm, 1), "mm total, AOI mean")

print("\nOK - Earth Engine is usable from this environment.")
