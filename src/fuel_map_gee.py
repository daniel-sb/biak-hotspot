"""A six-class fuel map for the survey corridor, and what it says about
where hotspots were seen (Task 27; PLAN.md 2.3).

This is a reclassification of three products the repository already reads,
not a supervised classification. There is no fuel ground truth for Biak,
so nothing here is an accuracy, a validation, or a statement about why a
patch burned. The classes describe expected burning behaviour only; they
are not inputs to a spread model.

    1 grass_savanna       fast surface burning
    2 shrub_regrowth      low shrub, secondary growth
    3 cultivation_mosaic  clearing fuel, burned repeatedly
    4 forest_closed       closed canopy, rarely carries burning
    5 mangrove            saline coastal fringe, effectively non-fuel
    6 nonfuel             built, bare rock and karst, open water

Base is ESA WorldCover v200 2021 (10 m). Dynamic World (10 m) is the
independent second reading, reduced to its per-pixel mode over the config
window; that window ends before the first August 2026 detection because
Dynamic World reads burned ground as bare. JRC TMF (30 m, December band
from burned_area.tmf_latest_year) splits WorldCover's single tree class
into closed forest and regrowth. TMF is upsampled to the 10 m output grid
with nearest neighbour; the output is not coarsened to 30 m.

FGBFM 40 is deliberately not used: it is calibrated on US fuels and has
no Papuan analogue, so importing it would repeat the peat-frame error in
another form. The output says so in its notes.

No threshold and no fire-behaviour figure is produced. Areas and counts
are published with all six classes present, even at zero, so a class that
does not occur cannot vanish from the record.

    python src/fuel_map_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment with Earth Engine credentials.
If any input cannot be read, or Earth Engine refuses a request, the script
says which and exits non-zero with no file written.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml
from shapely import wkb
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

from s2_scene_survey import corridor_bounds

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
DETECTIONS = ROOT / "data/processed/detections.parquet"
BURNED = ROOT / "data/processed/burned_areas.geojson"
GPKG = ROOT / "data/labels/biak_labels.gpkg"
OUT = ROOT / "data/processed/fuel_map.json"

FUEL_NAMES = {
    1: "grass_savanna",
    2: "shrub_regrowth",
    3: "cultivation_mosaic",
    4: "forest_closed",
    5: "mangrove",
    6: "nonfuel",
}
FUEL_BEHAVIOUR = {
    1: "fast surface burning, residence time in minutes",
    2: "surface burning with low shrub, the secondary-growth fuel",
    3: "the clearing fuel, burned on purpose and repeatedly",
    4: "closed canopy, low flammability, rarely carries burning",
    5: "saline coastal fringe, effectively non-fuel",
    6: "built, bare rock and karst outcrop, open water",
}

# Exhaustive WorldCover v200 classes. 10 is split by TMF below; the rest
# follow the task's reclass table. Unknown values would fall to 6, which
# is why the full product list is asserted in the offline test.
WC_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
WC_TO_FUEL = {10: 4, 20: 2, 30: 1, 40: 3, 50: 6, 60: 6, 70: 6,
              80: 6, 90: 6, 95: 5, 100: 6}
DW_CLASSES = (0, 1, 2, 3, 4, 5, 6, 7, 8)
DW_TO_FUEL = {0: 6, 1: 4, 2: 1, 3: 6, 4: 3, 5: 2, 6: 6, 7: 6, 8: 6}

NOTES = [
    "FGBFM 40 (Scott & Burgan 2005) is deliberately not used: it is "
    "calibrated on US fuels and has no Papuan analogue.",
    "The map is a reclassification of three global products, not a "
    "classification. There is no fuel ground truth for Biak, so no "
    "accuracy or validation is claimed.",
    "Dynamic World is reduced to its per-pixel mode over a window that ends "
    "before the first August 2026 detection, because the product reads "
    "burned ground as bare. Land pixels with no Dynamic World scene in the "
    "window are counted separately and excluded from the 6x6 matrix.",
    "TMF is 30 m and is upsampled to the 10 m output grid with nearest "
    "neighbour. The closed-forest/regrowth split is therefore blocky at "
    "30 m; the WorldCover and Dynamic World classes keep 10 m detail.",
    "WorldCover class 90 (herbaceous wetland) is mapped to nonfuel. It can "
    "carry burning when dry, and its area is reported separately so the "
    "choice can be re-cut.",
    "TMF class 2 (degraded) is mapped to closed forest as the conservative "
    "choice; its area is reported separately. Tree cover that TMF does not "
    "resolve also stays closed forest and is reported separately.",
    "Hotspots are where satellites saw heat, not a random sample of land. "
    "A class over-represented among them is an association, not a cause, "
    "and no significance test is computed.",
    "The class names describe expected burning behaviour. They are not "
    "fuel load, moisture, rate of spread, flame length, or inputs to a "
    "spread model.",
    "The free-text notes are one interpreter's incidental remarks, written "
    "for a different question. The fuel class at each noted box is printed "
    "as a spot-check only; no agreement figure is computed from it.",
]


# --------------------------------------------------------------------------
# Offline pieces

def gpkg_geometry(blob):
    """GeoPackage binary to shapely geometry: 'GP' magic, version, flags,
    srs id, an optional envelope whose length the flags give, then WKB.
    Read with sqlite3 alone, as burn_classifier does."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob")
    envelope = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 0x07]
    return wkb.loads(blob[8 + envelope:])


def read_label_notes(path=GPKG):
    """Boxes with a non-empty note, at their centroid. The note text stays
    verbatim; nothing is scored against it."""
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            'SELECT sample_id, event_id, notes, geom FROM labels '
            'WHERE notes IS NOT NULL AND trim(notes) != "" '
            'ORDER BY sample_id').fetchall()
    finally:
        con.close()
    out = []
    for sample_id, event_id, note, blob in rows:
        centre = gpkg_geometry(blob).centroid
        out.append({"sample_id": sample_id, "event_id": event_id,
                    "note": note, "lon": round(centre.x, 6),
                    "lat": round(centre.y, 6)})
    return out


def dynamicworld_window(cfg):
    """The configured [start, end) window as dates, checked for shape."""
    window = cfg["fuel"]["dynamicworld_window"]
    if len(window) != 2:
        raise SystemExit("fuel.dynamicworld_window must be [start, end]")
    start, end = (date.fromisoformat(str(v)) for v in window)
    if start >= end:
        raise SystemExit("fuel.dynamicworld_window start is not before end")
    return start, end


def first_august_detection(det):
    """The earliest WIT day in August 2026, or None when the store has no
    such row. The window must end at or before it."""
    aug = det[det["date_wit"].astype(str).str.startswith("2026-08")]
    if aug.empty:
        return None
    return date.fromisoformat(str(aug["date_wit"].min()))


def check_window(window, first):
    """Stop before writing when the Dynamic World window reaches into the
    August 2026 burning. `end` is exclusive, so end == first is safe."""
    if first is not None and window[1] > first:
        raise SystemExit(
            "fuel.dynamicworld_window ends %s, after the first August 2026 "
            "detection %s - nothing written" % (window[1], first))


def tmf_regrowth(tmf):
    """TMF deforested (3) or regrowth (4): tree cover that is not closed."""
    import ee
    return tmf.eq(3).Or(tmf.eq(4))


def tmf_unresolved(wc, tmf):
    """Tree cover TMF left as water/other/unmapped: the fallback count."""
    import ee
    return wc.eq(10).And(tmf.eq(0).Or(tmf.eq(5)).Or(tmf.eq(6)))


def tmf_degraded(wc, tmf):
    """Tree cover TMF calls degraded (2): the conservative call."""
    import ee
    return wc.eq(10).And(tmf.eq(2))


def wetland(wc):
    """WorldCover herbaceous wetland (90): nonfuel here, reported apart."""
    import ee
    return wc.eq(90)


def worldcover_fuel(wc, tmf):
    """WorldCover Map plus TMF Dec band -> fuel codes 1-6.

    TMF 3/4 move tree cover to shrub_regrowth; 1/2/5/6/0 stay
    forest_closed. The WorldCover mask is kept, so a masked base pixel is
    not silently called nonfuel.
    """
    import ee
    fuel = ee.Image(6)
    for code, cls in WC_TO_FUEL.items():
        fuel = fuel.where(wc.eq(code), cls)
    fuel = fuel.where(wc.eq(10).And(tmf_regrowth(tmf)), 2)
    return fuel.rename("fuel").toInt().updateMask(wc.mask())


def dynamicworld_fuel(dw, tmf):
    """Dynamic World label plus the same TMF split -> fuel codes 1-6.

    The Dynamic World mask is kept: a pixel with no scene in the window
    has no class and is counted, never called nonfuel.
    """
    import ee
    fuel = ee.Image(6)
    for code, cls in DW_TO_FUEL.items():
        fuel = fuel.where(dw.eq(code), cls)
    fuel = fuel.where(dw.eq(1).And(tmf_regrowth(tmf)), 2)
    return fuel.rename("fuel").toInt().updateMask(dw.mask())


def corridor_shape(bounds):
    return box(*bounds)


def burned_union(path, bounds):
    """Union of the mapped burned polygons, clipped to the corridor.
    Returns (union, total features, used features, outside features,
    outside event ids). A feature outside the corridor is named, not
    silently dropped."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    region = corridor_shape(bounds)
    kept, outside = [], []
    for i, feature in enumerate(doc["features"]):
        try:
            geom = shape(feature["geometry"])
            clipped = geom.intersection(region)
        except Exception as err:
            raise SystemExit(
                "burned_areas.geojson feature %d unreadable (%s) - nothing "
                "written" % (i, err))
        if clipped.is_empty:
            outside.append(feature["properties"].get("event_id"))
        else:
            kept.append(clipped)
    union = unary_union(kept) if kept else None
    return (union, len(doc["features"]), len(kept), len(outside),
            sorted({str(e) for e in outside if e is not None}))


def read_detections(path=DETECTIONS):
    det = pd.read_parquet(path)
    det["detection_id"] = det["detection_id"].astype(str)
    det["date_wit"] = det["date_wit"].astype(str)
    return det


def class_zeroes():
    return {str(code): 0.0 for code in FUEL_NAMES}


def share_table(areas, total):
    return {str(code): (round(areas[str(code)] / total, 6) if total else None)
            for code in FUEL_NAMES}


def detection_table(sub):
    """Counts and FRP by fuel class, all six keys. Confidence is not
    carried: it is a text column with two vocabularies, and nothing here
    needs it."""
    out = {}
    total = len(sub)
    for code in FUEL_NAMES:
        rows = sub[sub["fuel_class"] == code]
        out[str(code)] = {
            "n": int(len(rows)),
            "share": round(len(rows) / total, 6) if total else None,
            "frp_sum_mw": round(float(rows["frp"].sum()), 3),
            "frp_median_mw": (round(float(rows["frp"].median()), 3)
                              if len(rows) and rows["frp"].notna().any()
                              else None),
        }
    return out


# --------------------------------------------------------------------------
# Earth Engine

def area_by_code(fuel, region, land, scale):
    """Hectares per fuel code over the region, land-masked. Every class is
    present in the result even when the reducer returns no group for it."""
    import ee
    area = ee.Image.pixelArea().divide(1e4)
    image = area.updateMask(land).addBands(fuel.select("fuel").toInt())
    got = image.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="code"),
        geometry=region, scale=scale, maxPixels=int(1e10), tileScale=4,
        bestEffort=False).getInfo()
    out = class_zeroes()
    for group in got.get("groups", []):
        code = int(group["code"])
        if str(code) not in out:
            raise SystemExit("fuel code %d outside 1-6 - nothing written"
                             % code)
        out[str(code)] = float(group["sum"])
    return out


def area_sum(mask, region, scale):
    """Hectares where the mask is true. Null from an empty reduction is a
    real zero for this mask."""
    import ee
    image = ee.Image.pixelArea().divide(1e4).updateMask(mask)
    got = image.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=scale,
        maxPixels=int(1e10), tileScale=4, bestEffort=False).getInfo()
    return float(got.get("area") or 0.0)


def count_masked(mask, region, scale):
    """Pixels where the mask is true, counted rather than converted from
    an area."""
    import ee
    image = ee.Image.constant(1).updateMask(mask)
    got = image.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=region, scale=scale,
        maxPixels=int(1e10), tileScale=4, bestEffort=False).getInfo()
    return int(got.get("constant") or 0)


def sample_fuel(fuel, features, scale):
    """Fuel code at each feature, keyed by its `id` property. A feature
    without a class stays absent so the caller can count it."""
    import ee
    got = fuel.sampleRegions(collection=features, scale=scale,
                             geometries=False, tileScale=4).getInfo()
    out = {}
    for feature in got["features"]:
        props = feature["properties"]
        if props.get("fuel") is not None and props.get("id") is not None:
            out[str(props["id"])] = int(props["fuel"])
    return out


def confusion(fuel_wc, fuel_dw, region, land, scale):
    """6x6 hectares: rows WorldCover-based, columns Dynamic World-based."""
    import ee
    pair = fuel_wc.multiply(10).add(fuel_dw).rename("pair").toInt()
    area = ee.Image.pixelArea().divide(1e4)
    image = area.updateMask(land).addBands(pair)
    got = image.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="pair"),
        geometry=region, scale=scale, maxPixels=int(1e10), tileScale=4,
        bestEffort=False).getInfo()
    matrix = {str(r): {str(c): 0.0 for c in FUEL_NAMES}
              for r in FUEL_NAMES}
    for group in got.get("groups", []):
        key = int(group["pair"])
        row, col = divmod(key, 10)
        if str(row) not in matrix or str(col) not in matrix:
            raise SystemExit("fuel pair %d outside 1-6 - nothing written"
                             % key)
        matrix[str(row)][str(col)] = float(group["sum"])
    return matrix


def compute(ee, cfg, bounds, window, det, notes, first_august):
    fuel_cfg = cfg["fuel"]
    scale = int(fuel_cfg["scale_m"])
    tmf_year = int(cfg["burned_area"]["tmf_latest_year"])
    tmf_band = "Dec%d" % tmf_year
    corridor = ee.Geometry.Rectangle(bounds, None, False)

    wc = ee.Image(fuel_cfg["worldcover_asset"]).select("Map")
    tmf = (ee.ImageCollection(fuel_cfg["tmf_asset"]).mosaic()
           .select(tmf_band).unmask(0)
           .reproject(crs="EPSG:4326", scale=scale))
    collection = (ee.ImageCollection(fuel_cfg["dynamicworld_asset"])
                  .filterBounds(corridor)
                  .filterDate(window[0].isoformat(), window[1].isoformat())
                  .select("label"))
    n_dw = collection.size().getInfo()
    if not n_dw:
        raise SystemExit(
            "Dynamic World returned no scenes for %s..%s - nothing written"
            % (window[0], window[1]))
    dw = collection.mode()

    fuel_wc = worldcover_fuel(wc, tmf)
    fuel_dw = dynamicworld_fuel(dw, tmf)
    land = wc.neq(80)

    corridor_area = area_by_code(fuel_wc, corridor, land, scale)
    corridor_land_ha = sum(corridor_area.values())
    degraded_ha = area_sum(tmf_degraded(wc, tmf), corridor, scale)
    fallback_ha = area_sum(tmf_unresolved(wc, tmf), corridor, scale)
    wetland_ha = area_sum(wetland(wc), corridor, scale)
    dw_unmapped = land.And(dw.mask().eq(0))
    dw_unmapped_ha = area_sum(dw_unmapped, corridor, scale)
    dw_unmapped_px = count_masked(dw_unmapped, corridor, scale)

    matrix = confusion(fuel_wc, fuel_dw, corridor, land, scale)
    matched_ha = sum(sum(row.values()) for row in matrix.values())
    if abs(matched_ha + dw_unmapped_ha - corridor_land_ha) > 1.0:
        raise SystemExit(
            "confusion matrix %.2f ha plus unmapped %.2f ha is not corridor "
            "land %.2f ha - nothing written"
            % (matched_ha, dw_unmapped_ha, corridor_land_ha))

    union, n_features, n_used, n_outside, events_outside = burned_union(
        BURNED, bounds)
    if union is None:
        burned_area = class_zeroes()
    else:
        burned_area = area_by_code(fuel_wc, ee.Geometry(mapping(union)),
                                   land, scale)
    burned_ha = sum(burned_area.values())

    points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([float(r.longitude), float(r.latitude)]),
                   {"id": r.detection_id})
        for r in det.itertuples()])
    fuel_of = sample_fuel(fuel_wc, points, scale)
    missing = sorted(set(det["detection_id"]) - set(fuel_of))
    if missing:
        raise SystemExit(
            "%d detections got no fuel class (first %s) - nothing written"
            % (len(missing), missing[0]))
    det = det.copy()
    det["fuel_class"] = det["detection_id"].map(fuel_of)

    note_points = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([n["lon"], n["lat"]]),
                   {"id": n["sample_id"]}) for n in notes])
    note_fuel = sample_fuel(fuel_wc, note_points, scale)
    for note in notes:
        note["fuel_class"] = note_fuel.get(note["sample_id"])
        if note["fuel_class"] is None:
            raise SystemExit(
                "label note %s got no fuel class - nothing written"
                % note["sample_id"])

    all_det = detection_table(det)
    y2026 = det[det["date_wit"].str.startswith("2026")]
    det2026 = detection_table(y2026)

    return {
        "parameters": {
            "worldcover_asset": fuel_cfg["worldcover_asset"],
            "dynamicworld_asset": fuel_cfg["dynamicworld_asset"],
            "tmf_asset": fuel_cfg["tmf_asset"],
            "tmf_year": tmf_year,
            "tmf_band": tmf_band,
            "dynamicworld_window": [str(window[0]), str(window[1])],
            "dynamicworld_window_end_exclusive": True,
            "first_august_2026_detection": (str(first_august)
                                             if first_august else None),
            "scale_m": scale,
            "corridor_bounds_wsen": [round(float(v), 6) for v in bounds],
            "land_mask": "WorldCover Map != 80",
            "tmf_resampling": ("30 m TMF upsampled to the 10 m output grid "
                               "with nearest neighbour"),
        },
        "fuel_classes": {str(c): {"name": FUEL_NAMES[c],
                                  "behaviour": FUEL_BEHAVIOUR[c]}
                         for c in FUEL_NAMES},
        "corridor": {
            "land_ha": round(corridor_land_ha, 4),
            "area_ha_by_class": {k: round(v, 4)
                                 for k, v in corridor_area.items()},
            "share_by_class": share_table(corridor_area, corridor_land_ha),
        },
        "detections": {
            "all": {"n": int(len(det)), "date_wit_range": [
                det["date_wit"].min(), det["date_wit"].max()],
                "by_class": all_det},
            "2026": {"n": int(len(y2026)), "date_wit_range": [
                y2026["date_wit"].min() if len(y2026) else None,
                y2026["date_wit"].max() if len(y2026) else None],
                "by_class": det2026},
        },
        "burned_area": {
            "n_features": n_features,
            "n_features_used": n_used,
            "n_features_outside_corridor": n_outside,
            "events_outside_corridor": events_outside,
            "land_ha": round(burned_ha, 4),
            "area_ha_by_class": {k: round(v, 4)
                                 for k, v in burned_area.items()},
            "share_by_class": share_table(burned_area, burned_ha),
        },
        "confusion_matrix_ha": {
            "rows": "WorldCover-based fuel",
            "columns": "Dynamic World-based fuel",
            "matrix": {r: {c: round(v, 4) for c, v in row.items()}
                       for r, row in matrix.items()},
            "matched_ha": round(matched_ha, 4),
        },
        "dynamicworld": {
            "scenes": int(n_dw),
            "unmapped_ha": round(dw_unmapped_ha, 4),
            "unmapped_pixels": int(dw_unmapped_px),
        },
        "judgement_calls_ha": {
            "forest_closed_from_degraded_ha": round(degraded_ha, 4),
            "forest_closed_from_tmf_fallback_ha": round(fallback_ha, 4),
            "nonfuel_from_wetland_ha": round(wetland_ha, 4),
        },
        "label_notes": notes,
        "notes": NOTES,
    }


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="Google Cloud project for Earth Engine")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    window = dynamicworld_window(cfg)
    try:
        det = read_detections()
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (DETECTIONS, err))
    first_august = first_august_detection(det)
    check_window(window, first_august)
    try:
        notes = read_label_notes()
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (GPKG, err))
    bounds = corridor_bounds()
    if bounds is None:
        raise SystemExit("survey corridor missing (fieldwork/"
                         "biak_ground_truth.gpkg) - nothing written")

    import ee
    try:
        ee.Initialize(project=args.project)
    except Exception as err:
        raise SystemExit("Earth Engine: %s - nothing written" % err)
    try:
        doc = compute(ee, cfg, bounds, window, det, notes, first_august)
    except SystemExit:
        raise
    except Exception as err:
        raise SystemExit("Earth Engine request failed: %s - nothing written"
                         % err)

    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print("wrote %s" % OUT.relative_to(ROOT))
    print("\ncorridor land %.1f ha" % doc["corridor"]["land_ha"])
    for code in FUEL_NAMES:
        c = doc["corridor"]["area_ha_by_class"][str(code)]
        s = doc["corridor"]["share_by_class"][str(code)]
        print("  %d %-20s %9.1f ha  %6.2f%%" %
              (code, FUEL_NAMES[code], c, 100 * (s or 0)))
    print("\nshare by class, corridor beside the burned area and both "
          "detection counts:")
    print("  class                 corridor   burned   det_all  det_2026")
    for code in FUEL_NAMES:
        key = str(code)
        corridor = doc["corridor"]["share_by_class"][key]
        burned = doc["burned_area"]["share_by_class"][key]
        allshare = doc["detections"]["all"]["by_class"][key]["share"]
        yshare = doc["detections"]["2026"]["by_class"][key]["share"]
        cells = [corridor, burned, allshare, yshare]
        print("  %-20s" % FUEL_NAMES[code]
              + "".join("      -" if v is None else "%7.2f%%" % (100 * v)
                        for v in cells))
    print("\njudgement calls:")
    for key, value in doc["judgement_calls_ha"].items():
        print("  %-40s %9.1f ha" % (key, value))
    print("\nDynamic World: %d scenes, %.1f ha unmapped"
          % (doc["dynamicworld"]["scenes"],
             doc["dynamicworld"]["unmapped_ha"]))
    print("\nlabel notes (spot-check, not validation):")
    for note in doc["label_notes"]:
        print("  %-12s %-18s fuel=%s  %s" %
              (note["sample_id"], note["event_id"],
               note["fuel_class"], note["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())