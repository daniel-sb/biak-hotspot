"""Verify Earth Engine access for this project's AOI.

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

# Sentinel-2 over the burning window: how much is actually usable?
s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
      .filterBounds(aoi).filterDate("2026-08-01", "2026-08-30"))
clear = s2.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
print("S2 scenes Aug  ", s2.size().getInfo(), "| under 40% cloud:", clear.size().getInfo())

# CHIRPS: the precipitation record the multi-year chart needs.
chirps = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
          .filterDate("2026-08-01", "2026-08-30"))
mm = chirps.sum().reduceRegion(
    ee.Reducer.mean(), aoi, 5000).get("precipitation").getInfo()
print("CHIRPS Aug sum ", None if mm is None else round(mm, 1), "mm (AOI mean)")

print("\nOK - Earth Engine is usable from this environment.")
