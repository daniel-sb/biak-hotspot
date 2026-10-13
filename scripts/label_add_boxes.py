"""Draw more label boxes for one of the two accuracy strata (Tasks 22, 23).

    python scripts/label_add_boxes.py --stratum map_burned [--n N] [--dry-run]
    python scripts/label_add_boxes.py --stratum footprint_unmapped [--dry-run]

Run under the QGIS 3.44 python (geopandas). Close QGIS first: this appends to
data/labels/biak_labels.gpkg.

Two strata, two frames, one box size:

  map_burned          points inside the Task 18 dNBR+ polygons of the three
                      events with 1 m imagery. Sampling by the map being
                      tested is standard for a map accuracy assessment, and
                      is not circular as long as the map is never shown while
                      judging (constraint in Task 23).
  footprint_unmapped  points inside the VIIRS footprints and outside those
                      polygons: the ground the map does not claim. Sampled by
                      area alone, so it carries the omission rate the
                      `random_box` design of Task 22 could only hint at.

The 42 `random_box` points came from a third frame - 7 in and 7 out of each
footprint - so they keep their own inclusion probability and are never mixed
into either stratum here.

Both strata draw only on land inside the S2DR4 1 m imagery, because a box the
interpreter cannot see cannot be judged. The excluded ground is reported.

New rows carry `sampling = map_burned` or `sampling = footprint_unmapped`, with
`class`, `confidence` and `notes` empty. Existing rows are copied through
unchanged: this script appends and never edits a judgement.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import yaml
from shapely.geometry import Point, box, shape
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
GPKG = ROOT / "data/labels/biak_labels.gpkg"
BURNED = ROOT / "data/processed/burned_areas.geojson"
LAND = ROOT / "data/boundaries/biak_desa.geojson"
IMAGERY = ROOT / "data/labels/imagery"
UTM = "EPSG:32753"
# Only the events whose imagery exists. A box on a 2023 event cannot be judged
# against August 2026 chips, and without imagery there is nothing to judge at all.
EVENTS = ("E0301", "E0313", "E0368")

# sample_id prefixes. MAP continues the 25 boxes the first draw placed; B is a
# new stratum and starts at 1. Numbers are continued, never restarted, so a
# re-run cannot hand a second box a sample_id that is already in use.
PREFIX = {"map_burned": "MAP", "footprint_unmapped": "B"}
SEED_KEY = {"map_burned": "map_burned_2", "footprint_unmapped": "footprint_unmapped"}


def land_union():
    return unary_union([shape(f["geometry"]) for f in json.loads(
        LAND.read_text(encoding="utf-8"))["features"]])


def imagery_union():
    """The S2DR4 1 m chips' rectangles, in UTM: what the interpreter can see."""
    import rasterio
    tiles = []
    for eid in EVENTS:
        path = IMAGERY / f"{eid}_swir.tif"
        if not path.exists():
            raise SystemExit(f"missing imagery {path} - run scripts/label_prepare.py")
        with rasterio.open(path) as r:
            tiles.append(box(*r.bounds))
    return unary_union(tiles)


def next_number(labels, prefix):
    """One past the highest existing <prefix><digits> id, so ids never repeat."""
    found = [int(m.group(1)) for s in labels.sample_id.dropna()
             for m in [re.fullmatch(rf"{prefix}(\d+)", str(s))] if m]
    return max(found, default=0) + 1


def draw_boxes(frame, taken, n, seed, box_m, min_sep_m, tries=200_000):
    """n 60 m squares (UTM) inside `frame`, clear of `taken`, min_sep_m apart.

    Kept free of geopandas and of the file layer: the test drives it with two
    shapely geometries, which is the same rule the draw itself runs.
    """
    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = frame.bounds
    half = box_m / 2
    centres: list = []
    squares = []
    for _ in range(tries):
        if len(centres) == n:
            break
        p = np.array([rng.uniform(minx, maxx), rng.uniform(miny, maxy)])
        pt = Point(*p)
        # The point decides, not the box. A 60 m box on a curved polygon edge
        # inevitably overhangs it, and dropping the overhanging boxes would
        # drop the edge cases the assessment exists to test - F22 made the same
        # rule for map_burned, and the 42 random_box points were drawn the same
        # way, so all three strata agree on what puts a box in a stratum.
        if not frame.contains(pt):
            continue
        if any(pt.distance(q) < min_sep_m for q in centres):
            continue
        square = box(p[0] - half, p[1] - half, p[0] + half, p[1] + half)
        if square.intersects(taken):
            continue
        centres.append(pt)
        squares.append(square)
    return squares


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stratum", choices=sorted(PREFIX), default="map_burned")
    ap.add_argument("--n", type=int, default=None,
                    help="boxes to add (default: bring the stratum up to "
                         "labels.target_per_stratum in config.yaml)")
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = ap.parse_args()

    import geopandas as gpd
    import pandas as pd
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", UTM, always_xy=True).transform
    to_ll = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True).transform

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["labels"]
    box_m = float(cfg["box_m"])
    min_sep = float(cfg["min_separation_m"])
    seed = int(cfg["seeds"][SEED_KEY[args.stratum]])
    stratum = args.stratum

    labels = gpd.read_file(GPKG, layer="labels")
    fp_frame = gpd.read_file(GPKG, layer="footprints").to_crs(UTM)
    footprints = unary_union(fp_frame.geometry.tolist())
    burned = gpd.read_file(BURNED).to_crs(UTM)
    burned = burned[burned.event_id.isin(EVENTS)]
    mapped = unary_union(burned.geometry.tolist())
    if mapped.is_empty or footprints.is_empty:
        raise SystemExit("no dNBR+ polygons or no footprints - check "
                         f"{BURNED.name} and the footprints layer; nothing drawn")

    land = shp_transform(to_utm, land_union())
    imagery = imagery_union()
    frame = (mapped if stratum == "map_burned"
             else footprints.difference(mapped)).intersection(land).intersection(imagery)
    print(f"dNBR+ mapped area over {len(EVENTS)} events {mapped.area / 1e4:.0f} ha | "
          f"footprint {footprints.area / 1e4:.0f} ha | "
          f"unmapped inside the footprints {(footprints.difference(mapped)).area / 1e4:.0f} ha")
    print(f"{stratum} frame on land and inside the imagery: {frame.area / 1e4:.1f} ha")
    if stratum == "map_burned":
        off = mapped.difference(frame).area / 1e4
    else:
        off = footprints.difference(mapped).difference(frame).area / 1e4
    print(f"  excluded from the frame: {off:.1f} ha off land or outside the 1 m chips")

    have = int((labels.sampling == stratum).sum())
    want = args.n if args.n is not None else int(cfg["target_per_stratum"]) - have
    if want <= 0:
        print(f"{stratum} already holds {have} boxes, target "
              f"{cfg['target_per_stratum']} - nothing to draw")
        return 0
    print(f"{stratum}: {have} boxes already, target {cfg['target_per_stratum']}, "
          f"drawing {want} with seed {seed}")

    taken = unary_union(labels.to_crs(UTM).geometry.tolist())
    squares = draw_boxes(frame, taken, want, seed, box_m, min_sep)
    if len(squares) < want:
        print(f"only {len(squares)} of {want} fitted with {min_sep} m separation")
    rows = [{"sample_id": None, "event_id": None, "sampling": stratum,
             "class": None, "confidence": None, "notes": None,
             "drawn_on": None, "geometry": shp_transform(to_ll, square)}
            for square in squares]

    start = next_number(labels, PREFIX[stratum])
    for i, row in enumerate(rows):
        row["sample_id"] = f"{PREFIX[stratum]}{start + i:02d}"
        g = shp_transform(to_utm, row["geometry"])
        # the event the box sits in; a box crossing two footprints takes the
        # first, as the map stratum's draw does
        hit = (burned if stratum == "map_burned" else fp_frame)
        hit = hit[hit.intersects(g)]
        if len(hit):
            row["event_id"] = hit.iloc[0]["event_id"]

    print(f"{len(rows)} boxes drawn:",
          pd.Series([r["event_id"] for r in rows]).value_counts().to_dict())
    print("sample_ids", rows[0]["sample_id"], "to", rows[-1]["sample_id"])

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0

    out = gpd.GeoDataFrame(pd.concat(
        [labels.drop(columns=["fid"], errors="ignore"),
         gpd.GeoDataFrame(rows, crs="EPSG:4326")], ignore_index=True), crs="EPSG:4326")
    # The judgements are the one thing this file cannot regenerate. Appending is
    # the whole job, so refuse to write anything that is not the old layer
    # followed by the new rows, unchanged. Compared as values, not as pandas
    # dtypes: concat widens the string columns to object and that is harmless,
    # while a changed or reordered judgement is not.
    def same_values(old, new, count):
        return (new.iloc[:count].reset_index(drop=True).fillna("").astype(str).tolist()
                == old.reset_index(drop=True).fillna("").astype(str).tolist())

    for col in ("sample_id", "class", "confidence", "notes"):
        if not same_values(labels[col], out[col], len(labels)):
            raise SystemExit(f"existing {col} would change - nothing written")
    if len(out) != len(labels) + len(rows):
        raise SystemExit("box count does not add up - nothing written")

    out.to_file(GPKG, layer="labels", driver="GPKG", geometry_type="MultiPolygon")
    print(f"\nlabels layer now holds {len(out)} boxes, "
          f"{int(out['class'].isna().sum())} of them unjudged")
    print("rebuild the project so the new boxes show up:\n  "
          '"C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" '
          "scripts/label_qgis_project.py --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
