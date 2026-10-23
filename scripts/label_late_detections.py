"""Which label boxes have a thermal anomaly later than the chip they were
judged on (Task 26).

The labels were judged on S2DR4 chips with six dates. Burning continued
after some of those dates, so a chip can predate the final state of the
ground near a box. This script is a lookup table, not a judgement:

  - distance from each 60 m box to the nearest detection later than each
    chip date, in metres, with the detection's date and band;
  - the bands `inside`, `<=375`, `<=750`, `<=1500`, `>1500`;
  - the chip dates before the latest later detection within 375 m of the
    box, which is the last near anomaly a chip could not show; the literal
    nearest detection is stored beside it.

A detection near a box is not evidence that the box burned: a VIIRS pixel
locates a thermal anomaly, not a burn perimeter. No class is suggested, no
box is ranked, and no boolean such as `burned_later` or `suspect` is
written.

    python scripts/label_late_detections.py

The GeoPackage is opened read-only (`mode=ro`, `SELECT` only). The chip
dates come from the filenames in data/labels/imagery, so a new dated SWIR
file adds a date. Writes data/processed/label_late_detections.json.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from shapely.geometry import Point
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from burn_classifier import gpkg_geometry          # noqa: E402
from fieldwork_gpkg import metres                  # noqa: E402

CONFIG = ROOT / "config.yaml"
DETECTIONS = ROOT / "data/processed/detections.parquet"
OUT = ROOT / "data/processed/label_late_detections.json"

# 375 m is one VIIRS pixel; 1500 m is burn_indices_gee.ADJ_M. It is not
# imported because that module imports Earth Engine at module level.
VIIRS_M = 375.0
ADJ_M = 1500.0
STRATA = ("random_box", "map_burned", "footprint_unmapped")

CAVEATS = [
    "A detection near a box is not evidence that the box burned: a VIIRS "
    "pixel locates a thermal anomaly, not a burn perimeter. No class is "
    "suggested and no box is ranked.",
    "Distance is to the box polygon in a local metre plane; a detection "
    "inside the box is 0. Bands are inclusive at 375, 750 and 1500 m.",
    "Chip dates are read from the dated SWIR filenames in "
    "data/labels/imagery, so adding a file adds a date. The detection "
    "store's acq_date is already a WIT local day and is not shifted.",
    "The per-chip distance is the nearest later detection. The box table "
    "uses the latest detection within 375 m, so the chips list describes "
    "the last near thermal anomaly; the literal nearest detection is "
    "stored beside it. Ties use the latest date, then the nearest distance.",
    "Every box has an entry for every chip date. A box with no later "
    "detection anywhere in the record gets null distances and dates.",
    "Free-text notes are incidental free text, not a general record of "
    "which chip a box was judged on. The committed labels carry far more "
    "notes than the 23 in the task text, and many now mention a date.",
    "This is a lookup table for the owner's eye; it does not decide whether "
    "the 17 September sharpening is ground change or reconstruction.",
]


def load_config():
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        box_m = float(cfg["labels"]["box_m"])
        gpkg = Path(cfg["labels"]["gpkg"])
        mid_m = float(cfg["recurrence"]["radius_m"])
    except Exception as err:
        raise SystemExit("%s: label parameters: %s - nothing written"
                         % (CONFIG, err))
    if not gpkg.is_absolute():
        gpkg = ROOT / gpkg
    return box_m, gpkg, mid_m


def chip_dates(imagery_dir):
    """Dates from `*_swir_<YYYYMMDD>.tif` filenames. The year is not
    hard-coded; a new dated SWIR file changes the result."""
    if not Path(imagery_dir).is_dir():
        raise SystemExit("%s: imagery directory missing - nothing written"
                         % imagery_dir)
    dates = set()
    for path in Path(imagery_dir).glob("*_swir_*.tif"):
        token = path.stem.split("_")[-1]
        if len(token) != 8 or not token.isdigit():
            continue
        try:
            dates.add(date(int(token[:4]), int(token[4:6]),
                           int(token[6:])))
        except ValueError:
            raise SystemExit("%s: invalid date in filename - nothing written"
                             % path)
    if not dates:
        raise SystemExit("%s: no dated *_swir_*.tif - nothing written"
                         % imagery_dir)
    return sorted(dates)


def read_boxes(gpkg):
    """All label boxes, read-only. SELECT only; the connection cannot
    UPDATE, INSERT, VACUUM, or add a layer."""
    if not Path(gpkg).exists():
        raise SystemExit("%s: missing - nothing written" % gpkg)
    try:
        con = sqlite3.connect(f"file:{Path(gpkg).as_posix()}?mode=ro",
                              uri=True)
        try:
            rows = con.execute(
                'SELECT fid, sample_id, event_id, sampling, "class", notes, '
                'geom FROM labels ORDER BY sample_id').fetchall()
        finally:
            con.close()
    except sqlite3.Error as err:
        raise SystemExit("%s: %s - nothing written" % (gpkg, err))
    out = []
    for fid, sample_id, event_id, sampling, cls, notes, blob in rows:
        try:
            geom = gpkg_geometry(blob)
        except Exception as err:
            raise SystemExit("%s: %s: %s - nothing written"
                             % (gpkg, sample_id, err))
        out.append({
            "fid": fid,
            "sample_id": sample_id,
            "event_id": event_id,
            "sampling": sampling,
            "class": cls,
            "notes": notes if notes else None,
            "geometry": geom,
        })
    return out


def read_detections(path):
    if not Path(path).exists():
        raise SystemExit("%s: missing - nothing written" % path)
    try:
        det = pd.read_parquet(path)
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (path, err))
    for col in ("acq_date", "latitude", "longitude", "frp", "confidence"):
        if col not in det.columns:
            raise SystemExit("%s: missing column %s - nothing written"
                             % (path, col))
    try:
        det["acq_date_d"] = det["acq_date"].map(date.fromisoformat)
    except Exception as err:
        raise SystemExit("%s: acq_date: %s - nothing written" % (path, err))
    return det


def local_box(poly):
    """The box in a local metre plane, using fieldwork_gpkg.metres for
    both axes. The 60 m extent makes the flat-earth approximation exact
    to microns."""
    centre = poly.centroid
    lat0, lon0 = centre.y, centre.x
    local = transform(lambda x, y, z=None: (
        metres(lat0, lon0, lat0, x),
        metres(lat0, lon0, y, lon0)), poly)
    return lat0, lon0, local


def distance_to_box(poly, local, lat0, lon0, lat, lon):
    """Metres from a point to the box polygon; 0 when inside."""
    if poly.covers(Point(lon, lat)):
        return 0.0
    px = metres(lat0, lon0, lat0, lon)
    py = metres(lat0, lon0, lat, lon0)
    return float(Point(px, py).distance(local))


def band(distance, mid_m):
    if distance is None:
        return None
    if distance <= 1e-9:
        return "inside"
    if distance <= VIIRS_M:
        return "<=375"
    if distance <= mid_m:
        return "<=%g" % mid_m
    if distance <= ADJ_M:
        return "<=1500"
    return ">1500"


def summary(item, mid_m):
    """One detection's distance, band, WIT date, FRP and text confidence."""
    acq_date, distance, row = item
    return {
        "distance_m": round(float(distance), 2),
        "band": band(distance, mid_m),
        "acq_date": acq_date.isoformat(),
        "frp_mw": None if pd.isna(row.frp) else float(row.frp),
        "confidence": None if pd.isna(row.confidence)
                      else str(row.confidence),
    }


def empty_summary():
    return {"distance_m": None, "band": None, "acq_date": None,
            "frp_mw": None, "confidence": None}


def box_record(box, det, chips, mid_m):
    poly = box["geometry"]
    lat0, lon0, local = local_box(poly)
    distances = [
        (row.acq_date_d,
         distance_to_box(poly, local, lat0, lon0,
                         row.latitude, row.longitude), row)
        for row in det.itertuples(index=False)]

    by_chip = {}
    for chip in chips:
        later = [x for x in distances if x[0] > chip]
        by_chip[chip.isoformat()] = (
            summary(min(later, key=lambda t: (t[1], -t[0].toordinal())),
                    mid_m)
            if later else empty_summary())

    # Two box-level statements. `nearest` is the literal closest late
    # detection; `latest` is the last late detection within 375 m, which is
    # the one that decides whether a chip can show the final state.
    later = [x for x in distances
             if x[0] > chips[0] and x[1] <= VIIRS_M]
    if later:
        nearest_item = min(later, key=lambda t: (t[1],
                                                 -t[0].toordinal()))
        latest_item = max(later, key=lambda t: (t[0].toordinal(), -t[1]))
        nearest = summary(nearest_item, mid_m)
        latest = summary(latest_item, mid_m)
        before_nearest = [c.isoformat() for c in chips
                          if c < nearest_item[0]]
        before_latest = [c.isoformat() for c in chips
                         if c < latest_item[0]]
    else:
        nearest = None
        latest = None
        before_nearest = []
        before_latest = []

    return {
        "fid": box["fid"],
        "sample_id": box["sample_id"],
        "event_id": box["event_id"],
        "sampling": box["sampling"],
        "class": box["class"],
        "notes": box["notes"],
        "by_chip": by_chip,
        "nearest_within_375m": nearest,
        "chips_before_nearest_within_375m": before_nearest,
        "latest_within_375m": latest,
        "chips_before_latest_within_375m": before_latest,
    }


def build(box_m, gpkg, mid_m):
    imagery = Path(gpkg).parent / "imagery"
    chips = chip_dates(imagery)
    det = read_detections(DETECTIONS)
    boxes = read_boxes(gpkg)
    records = [box_record(box, det, chips, mid_m) for box in boxes]
    shortlist = [r for r in records if r["latest_within_375m"]]

    strata = sorted(set(STRATA) | {r["sampling"] for r in records})
    by_stratum = {}
    for stratum in strata:
        group = [r for r in records if r["sampling"] == stratum]
        by_stratum[stratum] = {
            "boxes": len(group),
            "shortlist": sum(1 for r in group
                             if r["latest_within_375m"]),
        }

    named = next((r for r in records
                  if r["sample_id"] == "E0301-IN03"), None)
    named_box = None
    if named is not None and named["latest_within_375m"] is not None:
        named_box = {
            "sample_id": named["sample_id"],
            "sampling": named["sampling"],
            "class": named["class"],
            "notes": named["notes"],
            "nearest_within_375m": named["nearest_within_375m"],
            "latest_within_375m": named["latest_within_375m"],
            "chips_before_latest_within_375m":
                named["chips_before_latest_within_375m"],
        }

    return {
        "parameters": {
            "box_m": box_m,
            "gpkg": Path(gpkg).relative_to(ROOT).as_posix(),
            "imagery_dir": Path(gpkg).parent.joinpath("imagery")
                           .relative_to(ROOT).as_posix(),
            "chip_dates": [c.isoformat() for c in chips],
            "band_edges_m": {
                "inside": 0.0,
                "viirs": VIIRS_M,
                "mid": mid_m,
                "adj": ADJ_M,
            },
            "distance_definition": "distance to the box polygon in a local "
                                   "metre plane; inside = 0",
            "later_than_chip": "strictly greater than the chip date",
            "date_calendar": "acq_date is WIT and is not shifted; chips are "
                             "WIT days",
            "nearest_tie_break": "latest acq_date among equal minimum "
                                 "distance",
            "latest_tie_break": "nearest distance among detections on the "
                                "latest date",
            "chips_list": "the table lists chips strictly before the latest "
                          "detection within 375 m; the nearest-detection "
                          "list is stored beside it",
        },
        "counts": {
            "boxes_total": len(records),
            "boxes_shortlist": len(shortlist),
            "by_stratum": by_stratum,
            "detections_total": int(len(det)),
            "detections_after_earliest_chip": int(
                (det["acq_date_d"] > chips[0]).sum()),
            "notes_count": sum(1 for r in records if r["notes"]),
        },
        "boxes": records,
        "named_box": named_box,
        "caveats": list(CAVEATS) + [
            "The committed GeoPackage carries %d notes across %d boxes, "
            "not the 23 in the task text. They are free text, and many "
            "mention a date; they are not a general register of the chip "
            "each box was judged on." % (sum(1 for r in records
                                             if r["notes"]), len(records)),
        ],
    }


def print_shortlist(shortlist):
    print("\nboxes with a detection within 375 m later than at least one "
          "chip:")
    if not shortlist:
        print("  none - clean negative")
        return
    print("  sample_id      sampling              class      dist_m  "
          "latest_det  chips postdated")
    for row in sorted(shortlist, key=lambda r: (r["sampling"],
                                                r["sample_id"])):
        latest = row["latest_within_375m"]
        chips = ", ".join(c[5:] for c in
                          row["chips_before_latest_within_375m"]) or "-"
        print("  %-13s %-20s %-9s %6.1f  %-10s  %s" %
              (row["sample_id"], row["sampling"], row["class"],
               latest["distance_m"], latest["acq_date"], chips))


def main():
    box_m, gpkg, mid_m = load_config()
    doc = build(box_m, gpkg, mid_m)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print("wrote %s" % OUT.relative_to(ROOT))
    print("chip dates: %s" % ", ".join(doc["parameters"]["chip_dates"]))
    print_shortlist([r for r in doc["boxes"]
                     if r["latest_within_375m"]])

    print("\nboxes and shortlist by stratum, never pooled:")
    print("  stratum                 boxes  shortlist")
    for stratum in sorted(doc["counts"]["by_stratum"]):
        c = doc["counts"]["by_stratum"][stratum]
        print("  %-22s %5d %9d" % (stratum, c["boxes"], c["shortlist"]))

    named = doc["named_box"]
    print("\nnamed box E0301-IN03:")
    if named is None:
        print("  not in the shortlist")
    else:
        print("  sampling %s, class %s" % (named["sampling"],
                                           named["class"]))
        print("  note: %s" % (named["notes"] or "none"))
        if named["latest_within_375m"] is None:
            print("  no detection within 375 m later than any chip")
        else:
            n = named["latest_within_375m"]
            print("  latest late detection within 375 m: %.1f m on %s"
                  % (n["distance_m"], n["acq_date"]))
            print("  chips postdated: %s"
                  % (", ".join(named["chips_before_latest_within_375m"])
                     or "-"))

    print("\nnotes: %d of %d boxes carry notes. They are incidental free "
          "text, not a date register; the task text's 23 is stale and many "
          "current notes mention a date."
          % (doc["counts"]["notes_count"], doc["counts"]["boxes_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())