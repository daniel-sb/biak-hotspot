"""Six burned-area indices over the August 2026 corridor, judged by where
they are certainly wrong (Task 15; PLAN.md Phase 4; paper: Alcaras et al.,
Remote Sens. 14(8):1727, 2022, References/remotesensing-14-01727-v2.pdf).

No ground truth exists here, so nothing is classified. The indices are
scored on four strata, three of which they must NOT flag and one of which
is merely burning-plausible - never truth:

  water     ESA/WorldCover/v200 class 80 (permanent water), the same mask
            every other script here uses.
  cloud     SCL classes 3 (cloud shadow), 8 (cloud medium), 9 (cloud high)
            on the 2026-08-28 scene, taken uni-temporally on THAT scene.
            The primary post-image (2026-08-23) is 99.96% clear over the
            corridor land it covers and would leave this stratum empty, so
            the cloud stratum comes from a DIFFERENT DATE than the burn
            strata. That is a limitation stated here, not hidden.
  adjacent  land within ADJ_M of a FIRMS hotspot detection that precedes
            the post scene. Burning plausible, NOT ground truth: a 375 m
            VIIRS pixel locates a thermal anomaly, not a burn perimeter.
  far       land beyond FAR_M of every FIRMS detection ever stored.

The scene pairs are re-derived with src/s2_scene_survey.py's own measured
shares, never re-chosen by eye. Primary post-image is MID-EVENT: 23 August
sits inside the 19-25 August burning window, so it shows roughly four
fifths of the event and none of its last two days - a deliberate trade of
completeness for usable area. The pre-image is 35 days earlier; canopy
change over that gap is not separable from burning by any bi-temporal
index. Both facts travel with every number this script prints.

Read from the paper (2026-09-03, from the PDF):
  - Equation (5) typesets BAIS2 with the "+ 1" OUTSIDE the fraction:
    BAIS2 = (1 - sqrt(B6*B7*B8A/B4)) * ((B12-B8A)/sqrt(B12+B8A) + 1).
    Implemented exactly so.
  - Equation (1) defines NBR = (B12-B8A)/(B12+B8A): HIGH means burned.
    The paper's own section 3.1.1 prose ("high NBR ... healthy vegetation")
    describes the USGS convention and contradicts its equation; this
    script follows the equation, so all six indices are mutually
    comparable with HIGH = burned, and the bi-temporal form (eq 7,
    post minus pre) is HIGH where the ground changed toward burned.
    Mixing these numbers with USGS dNBR literature inverts the scale.
  - Section 3.2 motivates NBR+ = (B12-B8A-B3-B2)/(B12+B8A+B3+B2): water
    reflects strongly in blue-green, so subtracting B3 and B2 sends water
    dark, and clouds go negative because their B12 is far below the sum
    of the other three bands.

Reflectance is scaled /10000 before any index is computed; NBRSWIR, MIRBI
and BAIS2 carry additive constants (-0.02, +0.1, +2, +1) that are
meaningless against raw integer counts. The scaled per-scene range is
asserted sane and recorded in the output.

Writes docs/data/burn_indices.json - a NEW file; nothing under docs/data/
is modified. No threshold is chosen anywhere: per-stratum distributions
are published so any threshold can be evaluated later, including by a
reader who disagrees with us. If Earth Engine is unreachable, the survey
corridor is missing, or the re-derived pair no longer matches the survey's
own ranking, the script says so and writes nothing.

    python src/burn_indices_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from s2_scene_survey import (EVENT_FROM, EVENT_TO, S2, captured_share,
                             corridor_bounds, land_mask, pairs, scene_meta,
                             shares)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "burn_indices.json"
DET = ROOT / "data" / "processed" / "detections.parquet"

# The survey measured its shares at 60 m; scene selection reuses exactly
# that, so this script's pair cannot drift from the survey's numbers.
SELECT_SCALE = 60
SCALE = 20                    # all six indices are 20 m band products
ADJ_M = 1500                  # hotspot-adjacent radius (VIIRS 375 m pixel
                              # plus geolocation jitter, rounded up)
FAR_M = 3000                  # far-land: beyond this distance from every
                              # detection ever stored for the AOI
CLOUD_SCL = (3, 8, 9)         # SCL cloud shadow / cloud medium / cloud high
SURVEY_START, SURVEY_END = "2026-06-01", "2026-09-04"   # survey's window
CHECK_CAP_MIN = 0.999         # a check pair must capture (almost) all of it

BANDS = ["B2", "B3", "B4", "B6", "B7", "B8A", "B11", "B12"]
INDICES = ("NBR", "NBRSWIR", "NDSWIR", "MIRBI", "BAIS2", "NBR+")


def scaled(img):
    """Surface reflectance in 0-1: S2_SR stores integers."""
    return img.select(BANDS).divide(10000.0)


def indices_of(b):
    """The six indices, on scaled band images b, per the paper's eqs (1)-(6)."""
    import ee
    return {
        "NBR": b["B12"].subtract(b["B8A"]).divide(b["B12"].add(b["B8A"])),
        "NBRSWIR": b["B12"].subtract(b["B11"]).subtract(0.02)
            .divide(b["B12"].add(b["B11"]).add(0.1)),
        "NDSWIR": b["B11"].subtract(b["B8A"]).divide(b["B11"].add(b["B8A"])),
        "MIRBI": b["B12"].multiply(10).subtract(b["B11"].multiply(9.8))
            .add(2),
        # eq (5): the "+ 1" sits outside the fraction, added to
        # (B12-B8A)/sqrt(B12+B8A) - the typeset reading of the PDF.
        "BAIS2": ee.Image(1).subtract(
                b["B6"].multiply(b["B7"]).multiply(b["B8A"])
                .divide(b["B4"]).sqrt())
            .multiply(b["B12"].subtract(b["B8A"])
                      .divide(b["B12"].add(b["B8A"]).sqrt()).add(1)),
        "NBR+": b["B12"].subtract(b["B8A"]).subtract(b["B3"])
            .subtract(b["B2"])
            .divide(b["B12"].add(b["B8A"]).add(b["B3"]).add(b["B2"])),
    }


def index_bands(post_img, pre_img=None):
    """Multi-band image: six uni-temporal on the post scene, and when a
    pre scene is given six bi-temporal (post minus pre, the paper's eq 7).
    Band names avoid '+', which EE band names dislike."""
    import ee
    sp = scaled(post_img)
    b = {name: sp.select(name) for name in BANDS}
    idx = indices_of(b)
    bands = [idx[k].rename(k.replace("+", "_plus")) for k in INDICES]
    if pre_img is not None:
        sq = scaled(pre_img)
        bq = {name: sq.select(name) for name in BANDS}
        idx0 = indices_of(bq)
        bands += [idx[k].subtract(idx0[k])
                  .rename("d" + k.replace("+", "_plus")) for k in INDICES]
    return ee.Image.cat(bands)


def near_image(pts, radius_m):
    """1 within radius_m of any point, 0 elsewhere. Buffer + paint: the
    strata are defined by distance to FIRMS detections, not by the points
    themselves."""
    import ee
    fc = ee.FeatureCollection(
        [ee.Feature(ee.Geometry.Point([lon, lat])) for lon, lat in pts])
    return ee.Image(0).paint(fc.map(lambda f: f.buffer(radius_m)), 1) \
        .rename("near")


def dist_reduce():
    """min + max + percentiles + count, per band, in one reduceRegion."""
    import ee
    return (ee.Reducer.minMax()
            .combine(ee.Reducer.percentile([5, 25, 50, 75, 95]),
                     sharedInputs=True)
            .combine(ee.Reducer.count(), sharedInputs=True))


def strata_masks(cloud_img, region, adj_pts, all_pts):
    """The four strata, mutually exclusive by construction: water; cloud
    (from the cloud scene's own SCL) minus land; hotspot-adjacent minus
    land and cloud; far land (beyond FAR_M of every detection ever) minus
    land and cloud. Far is disjoint from adjacent by distance, since
    adjacent sits within ADJ_M < FAR_M of a detection. The land mask is
    deliberately NOT applied to water itself - it is WorldCover != 80 and
    would erase the stratum it is meant to bound."""
    import ee
    land = land_mask()
    scl = cloud_img.select("SCL")
    cloud_px = scl.eq(CLOUD_SCL[0])
    for c in CLOUD_SCL[1:]:
        cloud_px = cloud_px.Or(scl.eq(c))
    water = ee.Image("ESA/WorldCover/v200/2021").select("Map").eq(80) \
        .rename("water")
    adj = near_image(adj_pts, ADJ_M)
    far = near_image(all_pts, FAR_M).Not()
    masks = {
        "water": water,
        "cloud": cloud_px.And(land).rename("cloud"),
        "adjacent": adj.And(land).And(cloud_px.Not()).rename("adjacent"),
        "far": far.And(land).And(cloud_px.Not()).rename("far"),
    }
    return {k: v.unmask(0).toInt() for k, v in masks.items()}


def pair_stats(post_id, pre_id, region, strata, late=None):
    """Distributions per index/form/stratum, stratum pixel counts, pairwise
    overlaps, and false-alarm shares against the adjacent 95th percentile.
    One reduceRegion per stratum; exceedance shares in three more."""
    import ee

    post = ee.Image(S2 + "/" + post_id)
    pre = ee.Image(S2 + "/" + pre_id) if pre_id else None
    img = index_bands(post, pre)
    img = img.addBands(ee.Image(1).rename("anypx"))

    out = {"strata": {}, "indices": {"uni": {}, "bi": {}}, "overlap": None}
    for sname, smask in strata.items():
        got = img.updateMask(smask).reduceRegion(
            dist_reduce(), region, SCALE, maxPixels=int(1e13),
            bestEffort=False, tileScale=4).getInfo()
        count = got.get("anypx_count")
        out["strata"][sname] = {"n": int(count) if count else 0}
        forms = {"uni": "", "bi": "d"}
        for form, prefix in forms.items():
            for k in INDICES:
                key = prefix + k.replace("+", "_plus")
                vals = [got.get(f"{key}_{s}") for s in
                        ("min", "p5", "p25", "p50", "p75", "p95", "max")]
                if any(v is None for v in vals):
                    continue
                dist = dict(zip(("min", "p5", "p25", "p50", "p75", "p95",
                                 "max"), [round(v, 4) for v in vals]))
                dist["n"] = int(got.get(f"{key}_count") or 0)
                out["indices"][form][k] = out["indices"][form].get(k, {})
                out["indices"][form][k][sname] = dist

    # pairwise overlaps: six products, one reduceRegion, all must be 0
    keys = list(strata)
    prods = [strata[a].multiply(strata[b]).rename(f"{a}__{b}")
             for i, a in enumerate(keys) for b in keys[i + 1:]]
    got = ee.Image.cat(prods).reduceRegion(
        ee.Reducer.sum(), region, SCALE, maxPixels=int(1e13),
        bestEffort=False, tileScale=4).getInfo()
    out["overlap"] = {k: int(v or 0) for k, v in got.items()}

    # false-alarm share: share of each non-burnable stratum exceeding the
    # adjacent stratum's 95th percentile, per index and temporal form.
    # A share against a weak reference, never an accuracy.
    fa = {"uni": {}, "bi": {}}
    for form, prefix in (("uni", ""), ("bi", "d")):
        # "adjacent" is a stratum under each index, not an index itself
        if not out["indices"][form].get("NBR", {}).get("adjacent"):
            print(f"  note: adjacent stratum empty, no false-alarm "
                  f"reference for the {form} form")
            continue
        thr = {k: out["indices"][form][k]["adjacent"]["p95"]
               for k in INDICES}
        exc = ee.Image.cat([
            img.select(prefix + k.replace("+", "_plus")).gt(thr[k])
            .rename(k.replace("+", "_plus")) for k in INDICES])
        for sname in ("water", "cloud", "far"):
            got = exc.updateMask(strata[sname]).reduceRegion(
                ee.Reducer.mean(), region, SCALE, maxPixels=int(1e13),
                bestEffort=False, tileScale=4).getInfo()
            for k in INDICES:
                fa[form].setdefault(k, {})[sname] = \
                    round(got.get(k.replace("+", "_plus")), 4)
    out["false_alarm"] = fa

    if late is not None:
        got = img.updateMask(late).reduceRegion(
            dist_reduce(), region, SCALE, maxPixels=int(1e13),
            bestEffort=False, tileScale=4).getInfo()
        late_out = {}
        for form, prefix in (("uni", ""), ("bi", "d")):
            for k in INDICES:
                key = prefix + k.replace("+", "_plus")
                vals = [got.get(f"{key}_{s}") for s in
                        ("min", "p5", "p25", "p50", "p75", "p95", "max")]
                if any(v is None for v in vals):
                    continue
                dist = dict(zip(("min", "p5", "p25", "p50", "p75", "p95",
                                 "max"), [round(v, 4) for v in vals]))
                dist["n"] = int(got.get(f"{key}_count") or 0)
                late_out.setdefault(form, {})[k] = {"late_burning": dist}
        out["late_burning"] = late_out
    return out


def print_dist(title, dists):
    print(f"  {title}")
    order = ("water", "cloud", "adjacent", "far", "late_burning")
    for form in ("uni", "bi"):
        for k in INDICES:
            d = dists.get(form, {}).get(k)
            if not d:
                continue
            cells = []
            for s in order:
                if s in d:
                    v = d[s]
                    cells.append(f"{s[:4]} n={v['n']} "
                                 f"[{v['min']:.3f} {v['p50']:.3f} "
                                 f"{v['p95']:.3f} {v['max']:.3f}]")
            print(f"    {form} {k:<8} " + "  ".join(cells))


def main(project: str) -> None:
    import ee
    ee.Initialize(project=project)

    box = corridor_bounds()
    if box is None:
        raise SystemExit("survey corridor missing (fieldwork/"
                         "biak_ground_truth.gpkg) - run the survey first; "
                         "the strata are corridor quantities")
    print(f"corridor bbox {[round(v, 4) for v in box]}")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    aoi = ee.Geometry.Rectangle(
        [float(v) for v in cfg["aoi_bbox_wsen"]], None, False)
    geom = ee.Geometry.Rectangle(box, None, False).intersection(aoi, 1)
    land = land_mask()

    det = pd.read_parquet(DET)
    ev = det[(det.date_wit >= EVENT_FROM) & (det.date_wit <= EVENT_TO)
             & det.on_land]
    all_pts = list(zip(det[det.on_land].longitude,
                       det[det.on_land].latitude))
    print(f"hotspot record: {len(det)} detections, {int(det.on_land.sum())} "
          f"on land; event {EVENT_FROM}..{EVENT_TO} on-land {len(ev)}")

    base = ee.ImageCollection(S2).filterBounds(geom)
    rows = scene_meta(base.filterDate(SURVEY_START, SURVEY_END))
    denom, s = shares(rows, geom, land, SELECT_SCALE)
    for i, r in enumerate(rows):
        r["covers"] = s["f{}".format(i)] / denom
        r["clear"] = s["c{}".format(i)] / denom
    tile_best = {}
    for r in rows:
        if r.get("tile"):
            tile_best[r["tile"]] = max(tile_best.get(r["tile"], 0),
                                       r["covers"])
    tile = max(tile_best, key=tile_best.get)
    print(f"tiles reaching the corridor: "
          + ", ".join(f"{t} {100 * v:.1f}%" for t, v in
                      sorted(tile_best.items(), key=lambda kv: -kv[1])))
    if tile != "53MPU":
        raise SystemExit(f"best tile is {tile}, not 53MPU as the survey "
                         f"reported - stale pair, stopping")

    from datetime import timedelta
    post_from = (date.fromisoformat(EVENT_TO) + timedelta(days=1)) \
        .isoformat()
    pre_rows = [r for r in rows if r["tile"] == tile
                and SURVEY_START <= r["date"] < EVENT_FROM]
    mid_rows = [r for r in rows if r["tile"] == tile
                and EVENT_FROM <= r["date"] <= EVENT_TO]
    post_rows = [r for r in rows if r["tile"] == tile
                 and post_from <= r["date"] <= SURVEY_END]

    pr = pairs(pre_rows, mid_rows + post_rows, geom, land, SELECT_SCALE,
               top=20)
    for a, b, _ in pr:
        b["captured"] = captured_share(b["date"])
    primary = max((t for t in pr if (t[1].get("captured") or 0)
                   < CHECK_CAP_MIN), key=lambda t: t[2])
    check = max((t for t in pr if (t[1].get("captured") or 0)
                 >= CHECK_CAP_MIN), key=lambda t: t[2])
    pre_r, post_r = primary[0], primary[1]
    chk_r = check[1]
    # the survey's measured best pair, from the 2026-09-03 revision of
    # task 15; if the re-derivation drifts from it the pair is stale and
    # the run stops rather than proceeding on numbers nobody measured
    expected = {"pre": "2026-07-19", "mid": "2026-08-23",
                "post": "2026-08-28"}
    if (pre_r["date"], post_r["date"], chk_r["date"]) != \
            (expected["pre"], expected["mid"], expected["post"]):
        raise SystemExit(
            f"re-derived pair {pre_r['date']} -> {post_r['date']} "
            f"(check {chk_r['date']}) no longer matches the survey's "
            f"reported best {expected} - re-run src/s2_scene_survey.py "
            "and re-read it before proceeding")

    scenes = {
        "primary": {
            "pre": {"id": pre_r["id"], "date": pre_r["date"],
                    "tile": tile,
                    "meta_cloud_pct": pre_r.get("meta_cloud"),
                    "clear_share_of_corridor_land":
                        round(pre_r["clear"], 4)},
            "post": {"id": post_r["id"], "date": post_r["date"],
                     "tile": tile,
                     "meta_cloud_pct": post_r.get("meta_cloud"),
                     "clear_share_of_corridor_land":
                         round(post_r["clear"], 4)},
            "both_clear_share": round(primary[2], 4),
            "captured_share": round(post_r["captured"], 4),
            "post_is_mid_event": True,
            "pre_gap_days":
                (date.fromisoformat(post_r["date"])
                 - date.fromisoformat(pre_r["date"])).days,
        },
        "check": {
            "pre": {"id": pre_r["id"], "date": pre_r["date"],
                    "tile": tile,
                    "meta_cloud_pct": pre_r.get("meta_cloud"),
                    "clear_share_of_corridor_land":
                        round(pre_r["clear"], 4)},
            "post": {"id": chk_r["id"], "date": chk_r["date"],
                     "tile": tile,
                     "meta_cloud_pct": chk_r.get("meta_cloud"),
                     "clear_share_of_corridor_land":
                         round(chk_r["clear"], 4)},
            "both_clear_share": round(check[2], 4),
            "captured_share": round(chk_r["captured"], 4),
            "post_is_mid_event": False,
            "pre_gap_days":
                (date.fromisoformat(chk_r["date"])
                 - date.fromisoformat(pre_r["date"])).days,
        },
    }
    print("\nscene pairs (re-derived with the survey's own shares):")
    for nm in ("primary", "check"):
        sc = scenes[nm]
        print(f"  {nm:<8} {sc['pre']['date']} -> {sc['post']['date']} "
              f"tile {tile}  meta_cloud "
              f"{sc['pre']['meta_cloud_pct']:.1f}/"
              f"{sc['post']['meta_cloud_pct']:.1f}%  "
              f"clear {100 * sc['pre']['clear_share_of_corridor_land']:.1f}/"
              f"{100 * sc['post']['clear_share_of_corridor_land']:.1f}%  "
              f"both {100 * sc['both_clear_share']:.1f}%  "
              f"captured {100 * sc['captured_share']:.1f}%")
    print("  the primary post-image is MID-EVENT (inside "
          f"{EVENT_FROM}..{EVENT_TO}): it shows ~80% of the event and "
          "none of its last two days; the check pair covers all of it at "
          "less than half the usable area. The pre-image is "
          f"{scenes['primary']['pre_gap_days']} days earlier; canopy "
          "change over that gap is not separable from burning here.")

    region = ee.Image(S2 + "/" + post_r["id"]).geometry() \
        .intersection(geom, 1)

    ev_pre_df = ev[ev.date_wit < post_r["date"]]
    ev_late_df = ev[ev.date_wit >= post_r["date"]]
    ev_pre = list(zip(ev_pre_df.longitude, ev_pre_df.latitude))
    ev_late = list(zip(ev_late_df.longitude, ev_late_df.latitude))
    adj_max_date = str(ev_pre_df.date_wit.max())
    cloud_src = chk_r
    strata = strata_masks(ee.Image(S2 + "/" + cloud_src["id"]), region,
                          ev_pre, all_pts)
    late = near_image(ev_late, ADJ_M).And(
        strata["water"].Not()).And(strata["cloud"].Not()) \
        .rename("late")
    print(f"\nstrata (within tile {tile}, {SCALE} m pixels):")
    print(f"  cloud from scene {cloud_src['id']} of {cloud_src['date']} - "
          f"a DIFFERENT date than the burn strata, because the primary "
          f"post-image is too clear to build a cloud stratum on")
    print(f"  adjacent = within {ADJ_M} m of {len(ev_pre)} detections "
          f"dated {EVENT_FROM}..{adj_max_date}, every one of them earlier "
          f"than the post scene {post_r['date']}; the {len(ev_late)} "
          f"detections of {post_r['date']}..{EVENT_TO} are excluded here "
          f"and checked separately on the check pair")
    print(f"  far = beyond {FAR_M} m of all {len(all_pts)} on-land "
          f"detections ever stored")

    res = {
        "scenes": scenes,
        "sign_convention":
            "NBR per the paper's equation (1): (B12-B8A)/(B12+B8A), HIGH "
            "means burned; the paper's section 3.1.1 prose describes the "
            "USGS convention and contradicts its equation. All six "
            "indices are therefore mutually comparable with HIGH = "
            "burned, and the bi-temporal form (post minus pre, eq 7) is "
            "HIGH where the ground changed toward burned. Mixing with "
            "USGS dNBR literature inverts the severity scale.",
        "bais2_grouping":
            "equation (5) of the PDF typesets BAIS2 with the '+ 1' "
            "outside the fraction: (1 - sqrt(B6*B7*B8A/B4)) * "
            "((B12-B8A)/sqrt(B12+B8A) + 1). Implemented exactly so.",
        "false_alarm_definition":
            "share of each non-burnable stratum exceeding the 95th "
            "percentile of the hotspot-adjacent stratum, same temporal "
            "form. A rate against a weak reference, never an accuracy.",
        "reflectance_range": {},
    }

    for scene_key, sid in (("primary_pre", pre_r["id"]),
                           ("primary_post", post_r["id"]),
                           ("check_post", chk_r["id"])):
        got = scaled(ee.Image(S2 + "/" + sid)).reduceRegion(
            ee.Reducer.minMax(), region, SCALE, maxPixels=int(1e13),
            bestEffort=False, tileScale=4).getInfo()
        rng = {b: [round(got.get(f"{b}_min"), 4),
                   round(got.get(f"{b}_max"), 4)] for b in BANDS}
        res["reflectance_range"][scene_key] = rng
        lo = min(v[0] for v in rng.values())
        hi = max(v[1] for v in rng.values())
        print(f"  reflectance {scene_key}: scaled range {lo:.3f}..{hi:.3f}")
        # bright cloud tops in S2 L2A legitimately exceed 1.0 - measured
        # 2.17 on the 2026-08-28 scene - so the ceiling sits at 4, still
        # three orders below raw integer counts (~1e4) if /10000 was
        # forgotten or misapplied
        assert -0.1 <= lo and hi <= 4.0, (
            f"scaled reflectance out of sane range ({lo}..{hi}) - "
            "the /10000 scaling is wrong or the scene is corrupt")

    print("\ncomputing strata distributions (primary pair) ...")
    prim = pair_stats(post_r["id"], pre_r["id"], region, strata)
    res["strata"] = {"primary": prim["strata"],
                     "overlaps_primary": prim["overlap"],
                     "primary_adjacent_source": {
                         "post_scene_id": post_r["id"],
                         "post_scene_date": post_r["date"],
                         "detections_used": len(ev_pre),
                         "detection_date_range":
                             [str(ev_pre_df.date_wit.min()), adj_max_date],
                         "distance_m": ADJ_M,
                         "detections_excluded_on_or_after_post_date":
                             len(ev_late)},
                     "check": None, "overlaps_check": None,
                     "check_adjacent_source": None}
    res["indices_primary"] = prim["indices"]
    res["false_alarm_primary"] = prim["false_alarm"]
    print_dist("primary pair", prim["indices"])

    print("\ncomputing strata distributions (check pair) ...")
    strata_chk = strata_masks(ee.Image(S2 + "/" + cloud_src["id"]), region,
                              ev_pre + ev_late, all_pts)
    chk = pair_stats(chk_r["id"], pre_r["id"], region, strata_chk,
                     late=late)
    res["strata"]["check"] = chk["strata"]
    res["strata"]["overlaps_check"] = chk["overlap"]
    res["strata"]["check_adjacent_source"] = {
        "post_scene_id": chk_r["id"],
        "post_scene_date": chk_r["date"],
        "detections_used": len(ev_pre) + len(ev_late),
        "detection_date_range": [str(ev_pre_df.date_wit.min()),
                                 str(ev_late_df.date_wit.max())],
        "distance_m": ADJ_M,
        "late_burning_detections": len(ev_late)}
    res["indices_check"] = chk["indices"]
    res["indices_check_late_burning"] = chk["late_burning"]
    res["false_alarm_check"] = chk["false_alarm"]
    print_dist("check pair", chk["indices"])
    print_dist("check pair, late-burning clusters only "
               f"({len(ev_late)} detections of "
               f"{post_r['date']}..{EVENT_TO})", chk["late_burning"])

    print("\nfalse-alarm shares (share of stratum exceeding the adjacent "
          "95th percentile; a weak reference, never an accuracy):")
    for nm in ("primary", "check"):
        for form in ("uni", "bi"):
            fa = res[f"false_alarm_{nm}"][form]
            for k in INDICES:
                if k not in fa:
                    continue
                print(f"  {nm} {form} {k:<8} " + "  ".join(
                    f"{s} {fa[k][s]:.3f}" for s in ("water", "cloud", "far")
                    if s in fa[k]))

    res["coverage"] = {
        "region": f"MGRS {tile} footprint within the survey corridor",
        "scale_m": SCALE,
        "adjacent_radius_m": ADJ_M,
        "far_radius_m": FAR_M,
        "cloud_stratum_scene": cloud_src["id"],
        "cloud_stratum_date": cloud_src["date"],
        "cloud_stratum_scl_classes": list(CLOUD_SCL),
        "generated_utc": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    res["sources"] = {
        "imagery": "COPERNICUS/S2_SR_HARMONIZED, surface reflectance "
                   "scaled /10000 before any index; 20 m bands B2, B3, "
                   "B4, B6, B7, B8A, B11, B12",
        "water": "ESA/WorldCover/v200 class 80 (permanent water)",
        "cloud": "the 2026-08-28 scene's own SCL classes 3/8/9 "
                 "(cloud shadow, cloud medium, cloud high)",
        "hotspots": "data/processed/detections.parquet (FIRMS), on-land "
                    "only; the hotspot-adjacent stratum is burning-"
                    "plausible, never ground truth",
        "scene_selection": "re-derived with src/s2_scene_survey.py's "
                           "measured corridor-land shares at 60 m",
        "indices": "Alcaras, Costantino, Guastaferro, Parente, Pepe, "
                   "NBR+ paper, Remote Sens. 14(8):1727, 2022, "
                   "equations (1)-(7)",
    }
    OUT.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
