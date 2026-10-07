"""Pre-event and post-event Sentinel-2 chips for the labelling project.

    python scripts/label_pre_imagery.py <google-cloud-project-id>

Run in the `geolibre` conda environment, after `earthengine authenticate`.

The 1 m S2DR4 imagery shows only 28 August 2026, so an interpreter looking at it
can judge what the ground looks like, not what changed. dNBR+ measures change
between a pre look and a post look, so the two were answering different
questions. These chips close that: the same nearest-clear-look rule as Task 18,
the same windows, the same cloud masking, written over each event's tile.

Colours match the 1 m chips: B12/B8A/B4 on one fixed reflectance scale, so a
patch that reads brown there reads brown here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TILES = ROOT / "data/raw/s2dr4_biak_2026-08-28/output/ID/T53MPU"
TILE = {"E0301": "T53MPU-4e09bbfee", "E0313": "T53MPU-0c59f172e", "E0368": "T53MPU-c501689c0"}
OUT = ROOT / "data/labels/imagery"
CEILING = 0.40          # same fixed scale as the 1 m chips
SCALE_M = 20            # the scale Task 18 computes dNBR+ at
MID_DATE = "2026-08-23"  # the clearest scene of the episode, and the basemap the
                         # field survey used. It is mid-episode, not after: all
                         # three events ran to 25 August.


def main(project: str) -> int:
    import ee
    import burned_area_gee as ba
    import json

    ee.Initialize(project=project)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["burned_area"]
    events = {e["event_id"]: e for e in
              json.loads((ROOT / "data/processed/events.json").read_text(encoding="utf-8"))["events"]}

    for eid, tile in TILE.items():
        with rasterio.open(TILES / tile / f"S2L3Ax10_{tile}-20260828_MS.tif") as r:
            bounds, crs = r.bounds, r.crs
        region = ee.Geometry.Rectangle(list(bounds), proj=str(crs), geodesic=False)
        pre_s, pre_e, post_s, post_e = ba.windows(events[eid], cfg["pre_days"], cfg["post_days"])

        for tag, (start, end, anchor, ascending) in {
                "pre": (pre_s, pre_e, pre_e, True),
                "mid": (MID_DATE, MID_DATE[:8] + str(int(MID_DATE[8:]) + 1), MID_DATE, True),
                "post": (post_s, post_e, post_s, False)}.items():
            img, n = ba.nearest_look(ee, region, start, end, anchor, ascending, cfg["cs_min"])
            rgb = (img.select(["B12", "B8A", "B4"]).divide(CEILING).clamp(0, 1)
                   .multiply(255).toByte())
            url = rgb.getDownloadURL({"region": region, "scale": SCALE_M,
                                      "crs": str(crs), "format": "GEO_TIFF"})
            resp = requests.get(url, timeout=600)
            resp.raise_for_status()
            path = OUT / f"{eid}_{tag}_s2.tif"
            path.write_bytes(resp.content)
            with rasterio.open(path) as r:
                blank = float((r.read() == 0).all(axis=0).mean())
            print(f"{eid} {tag:4s} {start} to {end}  images {n.getInfo():2d}  "
                  f"{len(resp.content) / 1e6:5.1f} MB  blank {blank:.1%}  -> {path.name}")
    print("\nnext: rebuild the project\n  "
          '"C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" '
          "scripts/label_qgis_project.py --force")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/label_pre_imagery.py <google-cloud-project-id>")
    sys.exit(main(sys.argv[1]))
