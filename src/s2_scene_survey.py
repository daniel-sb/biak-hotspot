"""Which Sentinel-2 scenes exist over the survey corridor, and how much of it
they actually see through the cloud.

Prints only. Writes nothing, downloads nothing, exports nothing - the point is
to find out whether a usable pre/post pair and a navigable basemap are
possible before spending time building either.

    python src/s2_scene_survey.py <google-cloud-project-id>
                                  [--from YYYY-MM-DD] [--to YYYY-MM-DD]
                                  [--aoi]        # whole AOI, not the corridor
                                  [--scale M]

Run inside the `geolibre` conda environment, after `earthengine authenticate`.

Every share printed is a share of the SAME denominator: the masked land
pixels of the target geometry. That is laboured throughout because it is
where this script first went wrong.

  meta_cloud   the granule's own CLOUDY_PIXEL_PERCENTAGE. A Sentinel-2
               granule is 110 km square and ours are mostly ocean, so this
               is a statement about a lot of sea we do not care about. It is
               printed to be ignored.
  covers       how much of the corridor's land this granule reaches at all.
               The corridor straddles four MGRS tiles, so no single scene
               covers it and "cloud-free" is not the only way to see nothing.
  clear        how much of the corridor's land this scene both covers and
               sees through. Pixels outside its footprint count against it,
               because for a mosaic they are as useless as cloud.

Then: the ceiling any mosaic could reach, how coverage grows scene by scene,
which pre/post pairs are clear in BOTH dates, and how many burn targets from
the field GeoPackage actually land on ground those scenes can see.
"""

from __future__ import annotations

import argparse
import sqlite3
import struct
import sys
from datetime import date, timedelta
from pathlib import Path

import ee
import yaml

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "fieldwork" / "biak_ground_truth.gpkg"

S2 = "COPERNICUS/S2_SR_HARMONIZED"

# The August 2026 burning ran 19-25 August (peak 283 detections on the 22nd).
EVENT_FROM, EVENT_TO = "2026-08-19", "2026-08-25"

# Scene Classification Layer classes counted as a clear view of the ground.
# 4 vegetation, 5 not vegetated, 6 water, 7 unclassified.
CLEAR_SCL = (4, 5, 6, 7)

# Class 2 is "dark area pixels", and a fresh burn scar is dark. Excluding it
# can therefore punch a hole in the mosaic over precisely the ground the
# survey is going to. Reported as a separate share so the cost is visible
# rather than assumed either way.
DARK_SCL = 2


def corridor_bounds():
    """Bounding box of the burn targets worth walking to, from the field
    GeoPackage. Falls back to the whole AOI when it has not been built."""
    if not GPKG.exists():
        return None
    con = sqlite3.connect(GPKG)
    rows = con.execute(
        "SELECT geom FROM target_bakar "
        "WHERE prioritas IN ('kuat','sedang')").fetchall()
    con.close()
    if not rows:
        return None
    pts = [struct.unpack("<BIdd", g[0][8:])[2:] for g in rows]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    pad = 5.0 / 110.57          # 5 km, the walking buffer around a target
    return [min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad]


def land_mask():
    """WorldCover class 80 is permanent water. Same mask as every other
    script here, or the shares are not comparable with anything."""
    return ee.Image("ESA/WorldCover/v200/2021").select("Map").neq(80)


def clear01(img, land, dark_ok):
    """1 where this scene sees the ground on a land pixel, 0 where it is
    covered but cloudy, masked outside the granule footprint.

    unmask(0) fills the cloud-masked pixels but does NOT extend the image
    past its own footprint, so this band's valid-pixel count is the granule's
    land coverage, not the corridor's. Never take a plain mean of it: that
    divides by the granule and answers a question nobody asked. Every share
    printed by this script divides by the corridor land count instead.
    """
    scl = img.select("SCL")
    ok = scl.eq(CLEAR_SCL[0])
    for c in CLEAR_SCL[1:]:
        ok = ok.Or(scl.eq(c))
    if dark_ok:
        ok = ok.Or(scl.eq(DARK_SCL))
    return ok.unmask(0).updateMask(land).rename("clear")


def scene_meta(coll):
    """Scene identity only - no reduction, so this stays cheap."""
    fc = ee.FeatureCollection(coll.map(lambda img: ee.Feature(None, {
        "id": img.get("system:index"),
        "date": img.date().format("YYYY-MM-dd"),
        "tile": img.get("MGRS_TILE"),
        "meta_cloud": img.get("CLOUDY_PIXEL_PERCENTAGE"),
    })))
    rows = [f["properties"] for f in fc.getInfo()["features"]]
    return sorted(rows, key=lambda r: (r["date"], r.get("tile") or ""))


def shares(rows, geom, land, scale):
    """Every share from ONE reduceRegion over ONE multi-band image, all of
    them divided by the same corridor land-pixel count.

    Taking a per-band mean instead divides each band by its own granule
    footprint, which reported a mosaic union (46.4%) as smaller than one of
    its own member scenes (49.8%) - arithmetically impossible, and the tell
    that four different denominators were in play. Sums over a shared
    denominator cannot do that.

    Returns (denominator, {name: sum}), sums in pixels.
    """
    imgs = [ee.Image(S2 + "/" + r["id"]) for r in rows]
    clear = [clear01(im, land, False) for im in imgs]
    bands = []
    for i, img in enumerate(imgs):
        bands.append(clear[i].rename("c{}".format(i)))
        bands.append(clear01(img, land, True).rename("d{}".format(i)))
        # how much of the corridor this granule reaches at all, cloud aside
        bands.append(clear[i].gte(0).rename("f{}".format(i)))
    bands.append(ee.ImageCollection(clear).max().rename("union"))
    # rows arrive in date order, so the running maximum is the coverage a
    # mosaic reaches after adding each scene
    for i in range(len(imgs)):
        bands.append(ee.ImageCollection(clear[:i + 1]).max()
                     .rename("cum{}".format(i)))
    # The denominator: one band that is valid on every corridor land pixel
    # and nowhere else, reduced on the same grid as everything above.
    bands.append(ee.Image(1).updateMask(land).rename("land"))

    got = ee.Image.cat(bands).reduceRegion(
        ee.Reducer.sum(), geom, scale,
        maxPixels=int(1e13), bestEffort=False, tileScale=4).getInfo()
    return got.pop("land"), got


def captured_share(before_date):
    """Share of the event's detections that had already happened before a
    given date - how much of the burning a scene on that date can show.

    Sentinel-2 crosses around 10:30 WIT while VIIRS passes at roughly 01:30
    and 13:30, so a detection on the scene's own date may be hours after the
    overpass. Counting only strictly earlier days is the conservative side.
    """
    import pandas as pd
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    det = pd.read_parquet(ROOT / cfg["output_paths"]["processed"])
    ev = det[(det.date_wit >= EVENT_FROM) & (det.date_wit <= EVENT_TO)
             & det.on_land]
    if ev.empty:
        return None
    return (ev.date_wit < before_date).sum() / len(ev)


def pairs(pre_rows, post_rows, geom, land, scale, top=12):
    """Corridor land clear in BOTH scenes of a pre/post pair.

    This, not either scene's own clear share, is what a bi-temporal index has
    to work with: a pixel clouded on one date contributes nothing to a
    difference. Only same-tile pairs are offered - crossing MGRS tiles means
    two granules, two footprints and a seam through the comparison.
    """
    cand = [(a, b) for a in pre_rows for b in post_rows
            if a.get("tile") and a["tile"] == b.get("tile")]
    cand.sort(key=lambda ab: -min(ab[0]["clear"], ab[1]["clear"]))
    cand = cand[:top]
    if not cand:
        return []

    bands = []
    for k, (a, b) in enumerate(cand):
        ia = clear01(ee.Image(S2 + "/" + a["id"]), land, False)
        ib = clear01(ee.Image(S2 + "/" + b["id"]), land, False)
        bands.append(ia.And(ib).rename("p{}".format(k)))
    bands.append(ee.Image(1).updateMask(land).rename("land"))
    got = ee.Image.cat(bands).reduceRegion(
        ee.Reducer.sum(), geom, scale,
        maxPixels=int(1e13), bestEffort=False, tileScale=4).getInfo()
    denom = got.pop("land")
    out = [(a, b, got["p{}".format(k)] / denom)
           for k, (a, b) in enumerate(cand)]
    out.sort(key=lambda t: -t[2])
    return out


def target_points():
    """The burn targets, as (target_id, prioritas, lon, lat)."""
    if not GPKG.exists():
        return []
    con = sqlite3.connect(GPKG)
    rows = con.execute(
        "SELECT target_id, prioritas, geom FROM target_bakar").fetchall()
    con.close()
    out = []
    for tid, pr, blob in rows:
        lon, lat = struct.unpack("<BIdd", blob[8:])[2:]
        out.append((tid, pr, lon, lat))
    return out


def targets_on(mask, pts, scale):
    """How many targets sit on a pixel this mask calls usable.

    A share of the corridor says nothing about whether the ground worth
    walking to is inside it.

    sameFootprint=False is required, not cosmetic: plain unmask() fills
    cloud-masked pixels but leaves the image undefined outside the granule
    footprint, so sampleRegions silently DROPS every target beyond it and the
    denominator shrinks - 53 targets reported out of the 60 that exist. A
    target no scene covers is a target this pair cannot see, and it has to be
    counted as such rather than disappear.
    """
    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([lon, lat]), {"id": tid, "pr": pr})
        for tid, pr, lon, lat in pts])
    got = mask.unmask(0, False).rename("ok").sampleRegions(
        collection=fc, scale=scale, geometries=False).getInfo()
    hits = {}
    for f in got["features"]:
        p = f["properties"]
        hits.setdefault(p["pr"], [0, 0])
        hits[p["pr"]][0] += 1 if p["ok"] else 0
        hits[p["pr"]][1] += 1
    return hits


def pct(v):
    return "  n/a" if v is None else "{:5.1f}".format(100 * v)


def report(name, coll, geom, land, scale):
    print("\n=== {} ===".format(name))
    rows = scene_meta(coll)
    if not rows:
        print("  no scenes")
        return []

    denom, s = shares(rows, geom, land, scale)
    print("  corridor land pixels at {} m: {:.0f}  (every share below is a "
          "share of these)".format(scale, denom))
    for i, r in enumerate(rows):
        r["covers"] = s["f{}".format(i)] / denom
        r["clear"] = s["c{}".format(i)] / denom
        r["clear_dark"] = s["d{}".format(i)] / denom

    print("  {:<12} {:<7} {:>10} {:>8} {:>7} {:>10}".format(
        "date", "tile", "meta_cloud", "covers", "clear", "clear+dark"))
    for r in rows:
        mc = r.get("meta_cloud")
        print("  {:<12} {:<7} {:>9}% {:>7}% {:>6}% {:>9}%".format(
            r["date"], r.get("tile") or "-",
            "  n/a" if mc is None else "{:5.1f}".format(mc),
            pct(r["covers"]), pct(r["clear"]), pct(r["clear_dark"])))

    best = max(rows, key=lambda r: r["clear"])
    print("  best single scene: {} {}  clear over {}% of corridor land".format(
        best["date"], best.get("tile") or "-", pct(best["clear"])))

    # A Sentinel-2 date over this corridor is four granules, not one image:
    # the corridor straddles MGRS 53MNU/53MNV/53MPU/53MPV. So the union of a
    # single date is already a mosaic, and it is the number that matters even
    # when there is only one date to report.
    union = s["union"] / denom
    print("  union of every scene in this window: {}% of corridor land "
          "(the ceiling any mosaic can reach)".format(pct(union)))
    assert union >= best["clear"] - 1e-9, (
        "union {} below member {} - the denominators are out of step again"
        .format(union, best["clear"]))

    if len({r["date"] for r in rows}) > 1:
        print("  mosaic coverage as scenes are added, in date order:")
        seen = -1.0
        for i, r in enumerate(rows):
            cum = s["cum{}".format(i)] / denom
            assert cum >= seen - 1e-9, "running maximum went down"
            if cum > seen + 1e-9:
                print("    through {} {:<7} {}%".format(
                    r["date"], r.get("tile") or "-", pct(cum)))
            seen = cum
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--from", dest="start", default="2026-06-01")
    ap.add_argument("--to", dest="end", default="2026-09-04")
    ap.add_argument("--aoi", action="store_true",
                    help="use the whole config AOI instead of the corridor")
    ap.add_argument("--scale", type=int, default=60,
                    help="reduction scale in metres; SCL is 20 m native and "
                         "60 m is plenty for a coverage share")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    box = None if args.aoi else corridor_bounds()
    if box is None:
        box = cfg["aoi_bbox_wsen"]
        where = "whole AOI from config.yaml"
    else:
        where = "survey corridor from fieldwork/biak_ground_truth.gpkg"

    ee.Initialize(project=args.project)
    geom = ee.Geometry.Rectangle(box, None, False)
    land = land_mask()

    land_px = land.updateMask(land).reduceRegion(
        ee.Reducer.count(), geom, args.scale,
        maxPixels=int(1e13), bestEffort=False, tileScale=4).getInfo()
    print("geometry: {}".format(where))
    print("  bbox {}".format([round(v, 4) for v in box]))
    print("  land pixels at {} m: {}".format(args.scale, land_px.get("Map")))
    print("  window {} .. {}   event {} .. {}".format(
        args.start, args.end, EVENT_FROM, EVENT_TO))
    print("  clear = SCL in {}; clear+dark also allows {} (burn scars are "
          "dark)".format(list(CLEAR_SCL), DARK_SCL))

    # filterDate's end is exclusive, so the pre window stops the day the
    # burning started and the post window starts the day after it ended.
    post_from = (date.fromisoformat(EVENT_TO) + timedelta(days=1)).isoformat()
    base = ee.ImageCollection(S2).filterBounds(geom)
    pre = base.filterDate(args.start, EVENT_FROM)
    mid = base.filterDate(EVENT_FROM, post_from)
    post = base.filterDate(post_from, args.end)

    print("  scenes: {} before the event, {} during it, {} after".format(
        pre.size().getInfo(), mid.size().getInfo(), post.size().getInfo()))

    pre_rows = report("PRE-EVENT  ({} .. {})".format(args.start, EVENT_FROM),
                      pre, geom, land, args.scale)
    # Scenes inside the burning window were being hidden from both sides,
    # and the clearest scene of the whole season turned out to be one of
    # them. A mid-event scene shows most of the burning at the cost of the
    # last days of it - a trade to weigh, not a scene to discard unseen.
    mid_rows = report("MID-EVENT  ({} .. {})  incomplete burning".format(
        EVENT_FROM, EVENT_TO), mid, geom, land, args.scale)
    post_rows = report("POST-EVENT ({} .. {})".format(post_from, args.end),
                       post, geom, land, args.scale)

    print("\n=== what this allows ===")
    if not pre_rows or not post_rows:
        print("  no usable pair: one side of the event has no scene at all.")
        print("  Task 15 cannot run on this window; widen --from/--to and "
              "look again before building anything.")
        return
    print("  best single pre-event scene sees {}% of corridor land".format(
        pct(max(r["clear"] for r in pre_rows))))
    print("  best single post-event scene sees {}% of corridor land".format(
        pct(max(r["clear"] for r in post_rows))))

    later = mid_rows + post_rows
    for r in later:
        r["captured"] = captured_share(r["date"])
    pr = pairs(pre_rows, later, geom, land, args.scale, top=20)
    if not pr:
        print("  no same-tile pre/post pair exists.")
        return
    print("\n  usable pairs, by land clear in BOTH scenes.")
    print("  'captured' is the share of the event's detections that had "
          "already happened")
    print("  before the later scene: a mid-event scene buys pixels and "
          "loses burning.")
    print("    {:<7} {:<12} {:<12} {:>9} {:>10}".format(
        "tile", "earlier", "later", "both", "captured"))
    for a, b, share in pr[:10]:
        print("    {:<7} {:<12} {:<12} {:>8}% {:>9}%".format(
            a["tile"], a["date"], b["date"], pct(share),
            pct(b.get("captured"))))
    best = pr[0]
    print("  best pair by coverage: {} {} -> {}, {}% of corridor land "
          "usable bi-temporally, {}% of the burning captured".format(
              best[0]["tile"], best[0]["date"], best[1]["date"], pct(best[2]),
              pct(best[1].get("captured"))))
    full = [t for t in pr if (t[1].get("captured") or 0) >= 0.999]
    if full and full[0] is not best:
        f = full[0]
        print("  best pair capturing ALL of it: {} {} -> {}, {}%".format(
            f[0]["tile"], f[0]["date"], f[1]["date"], pct(f[2])))

    pts = target_points()
    if pts:
        a, b, _ = best
        both = (clear01(ee.Image(S2 + "/" + a["id"]), land, False)
                .And(clear01(ee.Image(S2 + "/" + b["id"]), land, False)))
        post_union = ee.ImageCollection(
            [clear01(ee.Image(S2 + "/" + r["id"]), land, False)
             for r in post_rows]).max()
        print("\n  burn targets landing on usable ground:")
        print("    {:<9} {:>18} {:>22}".format(
            "prioritas", "in the best pair", "in the post-event mosaic"))
        pair_hits = targets_on(both, pts, args.scale)
        mos_hits = targets_on(post_union, pts, args.scale)
        for rank in ("kuat", "sedang", "lemah"):
            if rank not in pair_hits:
                continue
            ph, pn = pair_hits[rank]
            mh, mn = mos_hits[rank]
            print("    {:<9} {:>10} of {:<4} {:>14} of {:<4}".format(
                rank, ph, pn, mh, mn))

    print("\n  Task 15 needs SINGLE scenes on both sides, never a mosaic: "
          "compositing across dates destroys the pre/post pairing.")
    print("  The navigation basemap is the opposite - mosaic freely, it is "
          "only there to walk by. Two products, two scripts.")


if __name__ == "__main__":
    sys.exit(main())
