"""Add label boxes drawn from the dNBR+ map stratum (Task 22, accuracy assessment).

    python scripts/label_add_map_stratum.py [--n 25] [--dry-run]

Close QGIS first: this appends to data/labels/biak_labels.gpkg.

The first 42 boxes were stratified by the VIIRS footprint, and only 3 of the 36
judged ones came back burned. Three positives cannot carry a precision figure:
the interval on 3 of 8 runs from roughly 14% to 69%.

So this draws a second stratum from the map being tested: random points inside
the Task 18 dNBR+ polygons, outside the boxes already placed. Sampling by the
map is standard practice for map accuracy assessment, and it is not circular as
long as the map is never shown while judging. What it buys is the stratified
estimator: with both strata and their areas, the agreement figures become a
corrected area estimate with a confidence interval, which F11 has never had.

New rows carry `sampling = map_burned`. The existing `random_box` rows are not
touched, and neither is any class already filled in.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "data/labels/biak_labels.gpkg"
BURNED = ROOT / "data/processed/burned_areas.geojson"
UTM = "EPSG:32753"
BOX_M = 60.0            # same unit as the first stratum
MIN_SEP_M = 150.0       # neighbouring pixels are correlated; keep samples apart
SEED = 20261009         # a new seed: the first draw used 20260928
# Only the events whose imagery exists. A box on a 2023 event cannot be judged
# against August 2026 chips, and without imagery there is nothing to judge at all.
EVENTS = ("E0301", "E0313", "E0368")

to_utm = Transformer.from_crs("EPSG:4326", UTM, always_xy=True).transform
to_ll = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True).transform


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=25, help="boxes to add (default 25)")
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = ap.parse_args()

    import geopandas as gpd
    import pandas as pd

    labels = gpd.read_file(GPKG, layer="labels")
    burned = gpd.read_file(BURNED).to_crs(UTM)
    burned = burned[burned.event_id.isin(EVENTS)]
    region = unary_union(burned.geometry.tolist())
    taken = unary_union(labels.to_crs(UTM).geometry.tolist())
    print(f"dNBR+ mapped area over {len(EVENTS)} events {region.area / 1e4:.0f} ha | "
          f"{len(labels)} boxes already placed")

    rng = np.random.default_rng(SEED)
    minx, miny, maxx, maxy = region.bounds
    half = BOX_M / 2
    picked: list = []
    rows = []
    for _ in range(200_000):
        if len(picked) == args.n:
            break
        p = np.array([rng.uniform(minx, maxx), rng.uniform(miny, maxy)])
        from shapely.geometry import Point
        pt = Point(*p)
        if not region.contains(pt):
            continue
        if any(pt.distance(q) < MIN_SEP_M for q in picked):
            continue
        square = box(p[0] - half, p[1] - half, p[0] + half, p[1] + half)
        if square.intersects(taken):
            continue
        picked.append(pt)
        n = len(picked)
        rows.append({"sample_id": f"MAP{n:02d}", "event_id": None,
                     "sampling": "map_burned", "class": None, "confidence": None,
                     "notes": None, "drawn_on": None,
                     "geometry": shp_transform(to_ll, square)})
    if len(picked) < args.n:
        print(f"only {len(picked)} of {args.n} fitted with {MIN_SEP_M} m separation")

    # name each new box after the event whose polygons it sits in
    for row in rows:
        g = shp_transform(to_utm, row["geometry"])
        hit = burned[burned.intersects(g)]
        if len(hit):
            row["event_id"] = hit.iloc[0]["event_id"]
    print(f"{len(rows)} boxes drawn:",
          pd.Series([r["event_id"] for r in rows]).value_counts().to_dict())

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0

    out = gpd.GeoDataFrame(pd.concat(
        [labels.drop(columns=["fid"], errors="ignore"),
         gpd.GeoDataFrame(rows, crs="EPSG:4326")], ignore_index=True), crs="EPSG:4326")
    out.to_file(GPKG, layer="labels", driver="GPKG", geometry_type="MultiPolygon")
    print(f"\nlabels layer now holds {len(out)} boxes, "
          f"{int(out['class'].isna().sum())} of them unjudged")
    print("rebuild the project so the new boxes show up:\n  "
          '"C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" '
          "scripts/label_qgis_project.py --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
