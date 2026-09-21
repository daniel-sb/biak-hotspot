"""Burned area per event from Sentinel-2 dNBR+ (Task 18; PLAN.md Phase 4).

For each event with at least `min_detections` detections: how much of its
footprint changed like a burn between the clear Sentinel-2 look nearest
before it and the one nearest after, how much of the footprint the clouds
hid, and what the land was the year before.

    python src/burned_area_gee.py <google-cloud-project-id>

Run by hand inside the `geolibre` conda environment, after `earthengine
authenticate` - never from the cron. Writes data/processed/burned_areas.json
and burned_areas.geojson.

The threshold is set by false-alarm rate, not by accuracy: the 99th
percentile of dNBR+ over nearby land never seen hot (see Task 18). There is
no reference data here, so nothing this writes is an accuracy, and the area
it reports is area that changed like a burn - an estimate, never proof, and
never a statement about why land was burned or who burned it (PLAN.md 8).

Every Earth Engine import sits inside a function: the offline parts
(event selection, footprints, the land-cover year, the bounds arithmetic)
are tested without Earth Engine installed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml
from shapely.geometry import Point, mapping
from shapely.ops import unary_union
from shapely import affinity

from events import membership
from recurrence import M_PER_DEG

ROOT = Path(__file__).resolve().parents[1]
S2 = "COPERNICUS/S2_SR_HARMONIZED"
CSP = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
ESRI = "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS"
ESRI_CLASSES = {1: "water", 2: "trees", 4: "flooded_vegetation", 5: "crops",
                7: "built", 8: "bare", 9: "snow_ice", 10: "clouds",
                11: "rangeland"}
# Task 18b. Esri's "trees" cannot tell forest from regrowth on cleared land;
# the JRC Tropical Moist Forest product was built to, from Landsat, for the
# humid tropics. Hansen's loss year adds the clearing history.
TMF = "projects/JRC/TMF/v1_2024/AnnualChanges"
TMF_CLASSES = {1: "undisturbed", 2: "degraded", 3: "deforested",
               4: "regrowth", 5: "water", 6: "other"}
HANSEN = "UMD/hansen/global_forest_change_2025_v1_13"

CAVEATS = [
    "Areas are pixels whose dNBR+ exceeds the 99th percentile of "
    "never-detected land within the event's reference ring. This controls "
    "false alarms on land that never burned; it is not an accuracy, and "
    "light burns below the local noise are missed.",
    "Each pixel uses the clear Sentinel-2 look nearest the event, so dates "
    "vary within one event; the look-lag statistics say by how much.",
    "changed_ha_upper assumes every cloud-gap pixel changed. The true area "
    "lies between changed_ha and changed_ha_upper, less expected_false_ha.",
    "A change like a burn is not proof of burning, and says nothing about "
    "why land was burned or who burned it (PLAN.md section 8).",
    "TMF is read for the year before each event, capped at its latest map; "
    "tmf_year says which year was used. For 2026 events that is December "
    "2024.",
    "Hansen loss records tree-cover removal from any cause; prior loss is "
    "history, not a statement about why land was cleared.",
]


# --------------------------------------------------------------------------
# Offline pieces

def select_events(events_doc, min_detections):
    """(assessed, not_assessed). Nothing is dropped silently: every event
    below the size bar is listed with the reason it was not assessed."""
    chosen, skipped = [], []
    for e in sorted(events_doc["events"], key=lambda e: e["event_id"]):
        if e["n_detections"] >= min_detections:
            chosen.append(e)
        else:
            skipped.append({"event_id": e["event_id"],
                            "reason": "fewer than %d detections"
                                      % min_detections})
    return chosen, skipped


def footprint(lats, lons, radius_m):
    """Union of radius_m circles around the member detections.

    Buffered on a local metre plane centred on the members, then mapped back
    to longitude/latitude, so the circles are circles on the ground rather
    than ellipses in degrees. Returns (lon/lat polygon, area in ha).
    """
    lat0 = sum(lats) / len(lats)
    lon0 = sum(lons) / len(lons)
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    ky = M_PER_DEG
    shape = unary_union([Point((lo - lon0) * kx, (la - lat0) * ky)
                         .buffer(radius_m, quad_segs=16)
                         for la, lo in zip(lats, lons)])
    area_ha = shape.area / 1e4
    geo = affinity.affine_transform(shape, [1 / kx, 0, 0, 1 / ky, lon0, lat0])
    return geo, area_ha


def land_cover_year(first_seen_wit):
    """The Esri annual map for the calendar year before the event, so the
    class describes the land before it burned, not after."""
    return int(first_seen_wit[:4]) - 1


def tmf_year(first_seen_wit, latest):
    """The TMF December map for the year before the event, or the latest map
    the asset holds if that year is not published yet."""
    return min(int(first_seen_wit[:4]) - 1, int(latest))


def prior_loss_max_code(first_seen_wit):
    """Largest Hansen `lossyear` code that counts as clearing before the
    event. Code n is loss in year 2000 + n; the event's own year is excluded
    because that loss may be the event itself."""
    return int(first_seen_wit[:4]) - 2000 - 1


def bounds(changed_ha, clear_ha, footprint_ha, quantile):
    """What the threshold admits on never-burned land, and the upper bound
    if every pixel the clouds hid had changed too (PLAN.md Phase 4: the
    cloud gap is published beside every area)."""
    return {
        "expected_false_ha": round((1.0 - quantile) * clear_ha, 2),
        "changed_ha_upper": round(changed_ha + (footprint_ha - clear_ha), 2),
        "clear_fraction": (round(clear_ha / footprint_ha, 4)
                           if footprint_ha else None),
    }


def reference_threshold(ref_stats, quantile, min_ref_px):
    """(threshold, reason) from the reference ring's reduceRegion result.

    A ring too small to carry a 99th percentile yields no threshold and no
    area for that event. There is deliberately no fallback: a threshold
    borrowed from another event, or a fixed number, would be an area figure
    resting on something the scene never measured.
    """
    px = ref_stats.get("dn_count") or 0
    if px < min_ref_px:
        return None, "no local reference"
    value = ref_stats.get("dn_p%d" % round(quantile * 100))
    if value is None:
        return None, "no local reference"
    return float(value), None


def windows(event, pre_days, post_days):
    """UTC date windows, end-exclusive, as Earth Engine's filterDate takes
    them. Pre ends before first_seen's UTC date; post starts the day after
    last_seen's - a same-day look could already hold the burning, or not
    yet, and neither is a clean before or after."""
    f = date.fromisoformat(event["first_seen_utc"][:10])
    l = date.fromisoformat(event["last_seen_utc"][:10])
    return ((f - timedelta(days=pre_days)).isoformat(), f.isoformat(),
            (l + timedelta(days=1)).isoformat(),
            (l + timedelta(days=1 + post_days)).isoformat())


# --------------------------------------------------------------------------
# Earth Engine

def nearest_look(ee, region, start, end, anchor, before, cs_min):
    """Per pixel, the clear look nearest `anchor`: the latest one before it,
    or the earliest one after. Adds a `lag` band in days from the anchor.

    ImageCollection.mosaic() stacks later images in the collection on top -
    checked on two constant images (values 1 then 2, mosaic -> 2) before
    this was written. So 'latest on top' is an ascending sort and 'earliest
    on top' a descending one.
    """
    import burn_indices_gee as bi
    anchor = ee.Date(anchor)
    csp = ee.ImageCollection(CSP)
    col = (ee.ImageCollection(S2).filterBounds(region)
           .filterDate(start, end).linkCollection(csp, ["cs_cdf"]))

    def prep(img):
        lag = img.date().difference(anchor, "day").abs()
        clear = img.select("cs_cdf").gte(cs_min)
        return (bi.scaled(img)
                .addBands(ee.Image.constant(lag).toFloat().rename("lag"))
                .updateMask(clear)
                .set("system:time_start", img.get("system:time_start")))

    col = col.map(prep).sort("system:time_start", before)
    return col.mosaic(), col.size()


def nbr_plus(ee, img):
    import burn_indices_gee as bi
    b = {k: img.select(k) for k in bi.BANDS}
    return bi.indices_of(b)["NBR+"]


def assess(ee, event, members, all_pts, p):
    from burn_indices_gee import near_image
    from drought_gee import land_mask

    fp_geo, fp_area_geom = footprint(members["latitude"].tolist(),
                                     members["longitude"].tolist(),
                                     p["footprint_m"])
    fp = ee.Geometry(mapping(fp_geo))
    centre = ee.Geometry.Point([event["centroid_lon"], event["centroid_lat"]])
    ring = centre.buffer(p["ref_radius_m"])
    region = ring.union(fp, 1)
    pre_s, pre_e, post_s, post_e = windows(event, p["pre_days"],
                                           p["post_days"])

    pre, n_pre = nearest_look(ee, region, pre_s, pre_e,
                              event["first_seen_utc"], True, p["cs_min"])
    post, n_post = nearest_look(ee, region, post_s, post_e,
                                event["last_seen_utc"], False, p["cs_min"])
    dn = nbr_plus(ee, post).subtract(nbr_plus(ee, pre)).rename("dn")
    land = land_mask()
    far = near_image(all_pts, p["far_m"]).Not()
    scale = p["scale_m"]
    kw = dict(scale=scale, maxPixels=1e10, tileScale=4)

    rec = {"event_id": event["event_id"],
           "first_seen_wit": event["first_seen_wit"],
           "last_seen_wit": event["last_seen_wit"],
           "n_detections": event["n_detections"],
           "windows_utc": {"pre": [pre_s, pre_e], "post": [post_s, post_e]},
           "n_scenes": {"pre": n_pre.getInfo(), "post": n_post.getInfo()}}
    if not rec["n_scenes"]["pre"] or not rec["n_scenes"]["post"]:
        rec["status"] = "no Sentinel-2 scene in the %s window" % (
            "pre" if not rec["n_scenes"]["pre"] else "post")
        return rec, []

    q = p["ref_quantile"]
    ref = dn.updateMask(land.And(far)).reduceRegion(
        ee.Reducer.percentile([q * 100]).combine(ee.Reducer.count(),
                                                 sharedInputs=True),
        ring, **kw).getInfo()
    rec["ref_clear_px"] = ref.get("dn_count") or 0
    t, reason = reference_threshold(ref, q, p["min_ref_px"])
    if reason:
        rec["status"] = reason
        return rec, []
    rec["threshold"] = round(t, 5)

    area = ee.Image.pixelArea().divide(1e4)
    clear = dn.mask().And(land)
    changed = clear.And(dn.gt(t))
    areas = ee.Image.cat([
        area.updateMask(land).rename("land"),
        area.updateMask(clear).rename("clear"),
        area.updateMask(changed).rename("changed"),
    ]).reduceRegion(ee.Reducer.sum(), fp, **kw).getInfo()
    fp_ha, clear_ha, changed_ha = (areas["land"] or 0.0,
                                   areas["clear"] or 0.0,
                                   areas["changed"] or 0.0)
    rec.update({"footprint_ha": round(fp_ha, 2),
                "clear_ha": round(clear_ha, 2),
                "changed_ha": round(changed_ha, 2)})
    rec.update(bounds(changed_ha, clear_ha, fp_ha, q))

    stats = ee.Image.cat([
        dn.updateMask(changed).rename("dn_changed"),
        pre.select("lag").updateMask(clear).rename("pre_lag"),
        post.select("lag").updateMask(clear).rename("post_lag"),
    ]).reduceRegion(ee.Reducer.percentile([50, 90]), fp, **kw).getInfo()
    rec["dnbr_p50_changed"] = (None if stats.get("dn_changed_p50") is None
                               else round(stats["dn_changed_p50"], 4))
    rec["look_lag_days"] = {
        k: {"p50": stats.get(k + "_p50"), "p90": stats.get(k + "_p90")}
        for k in ("pre_lag", "post_lag")}

    year = land_cover_year(event["first_seen_wit"])
    lc = (ee.ImageCollection(ESRI)
          .filterDate("%d-01-01" % year, "%d-01-01" % (year + 1))
          .mosaic().select("b1"))
    rec["land_cover_year"] = year
    for name, mask in (("clear_ha_by_class", clear),
                       ("changed_ha_by_class", changed)):
        got = area.updateMask(mask).addBands(lc).reduceRegion(
            ee.Reducer.sum().group(groupField=1, groupName="cls"), fp,
            **kw).getInfo()
        rec[name] = {ESRI_CLASSES.get(int(g["cls"]), str(g["cls"])):
                     round(g["sum"], 2) for g in got.get("groups", [])}

    ty = tmf_year(event["first_seen_wit"], p["tmf_latest_year"])
    tmf = ee.ImageCollection(TMF).mosaic().select("Dec%d" % ty)
    rec["tmf_year"] = ty
    for name, mask in (("clear_ha_by_tmf", clear),
                       ("changed_ha_by_tmf", changed)):
        got = area.updateMask(mask).addBands(tmf).reduceRegion(
            ee.Reducer.sum().group(groupField=1, groupName="cls"), fp,
            **kw).getInfo()
        rec[name] = {TMF_CLASSES.get(int(g["cls"]), str(g["cls"])):
                     round(g["sum"], 2) for g in got.get("groups", [])}

    loss = ee.Image(HANSEN).select("lossyear")
    prior = loss.gt(0).And(loss.lte(prior_loss_max_code(
        event["first_seen_wit"])))
    got = ee.Image.cat([
        area.updateMask(clear.And(prior)).rename("clear"),
        area.updateMask(changed.And(prior)).rename("changed"),
    ]).reduceRegion(ee.Reducer.sum(), fp, **kw).getInfo()
    rec["clear_ha_prior_loss"] = round(got["clear"] or 0.0, 2)
    rec["changed_ha_prior_loss"] = round(got["changed"] or 0.0, 2)

    polys = []
    if changed_ha > 0:
        vec = changed.selfMask().rename("changed").reduceToVectors(
            geometry=fp, scale=scale, geometryType="polygon",
            eightConnected=True, maxPixels=1e10, labelProperty="changed")
        for f in vec.getInfo()["features"]:
            polys.append({"type": "Feature", "geometry": f["geometry"],
                          "properties": {"event_id": event["event_id"],
                                         "threshold": rec["threshold"]}})
    rec["status"] = "assessed"
    rec["n_polygons"] = len(polys)
    return rec, polys


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", help="Google Cloud project for Earth Engine")
    args = ap.parse_args(argv)

    import ee
    # AGENTS never-2: if Earth Engine refuses, this raises and nothing is
    # written - no placeholder file, no stand-in area.
    ee.Initialize(project=args.project)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    p = cfg["burned_area"]
    processed = ROOT / cfg["output_paths"]["processed"]
    doc = json.loads((processed.parent / "events.json")
                     .read_text(encoding="utf-8"))
    det = pd.read_parquet(processed)
    det["detection_id"] = det["detection_id"].astype(str)
    member_of = membership(doc)
    det["event_id"] = det["detection_id"].map(member_of)
    all_pts = list(zip(det["longitude"], det["latitude"]))

    chosen, skipped = select_events(doc, p["min_detections"])
    records, features = [], []
    for e in chosen:
        m = det[det["event_id"] == e["event_id"]]
        rec, polys = assess(ee, e, m, all_pts, p)
        records.append(rec)
        features += polys
        print("%s %-18s %s" % (
            e["event_id"], rec["status"],
            "" if rec["status"] != "assessed" else
            "changed %.1f ha of %.1f clear (%.0f%% clear), t=%.4f"
            % (rec["changed_ha"], rec["clear_ha"],
               100 * (rec["clear_fraction"] or 0), rec["threshold"])))

    out = {"params": p, "events_registry_version": doc["registry_version"],
           "store_last_date_wit": doc["store_last_date_wit"],
           "assessed": records, "not_assessed": skipped,
           "caveats": CAVEATS}
    (processed.parent / "burned_areas.json").write_text(
        json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (processed.parent / "burned_areas.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features},
                   sort_keys=True) + "\n", encoding="utf-8")
    print("wrote burned_areas.json (%d assessed, %d not) and %d polygons"
          % (len(records), len(skipped), len(features)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
