"""Offline navigation basemap for the field survey, as MBTiles.

Renders one Sentinel-2 date over the survey corridor into an MBTiles file the
Mergin Maps project can carry onto a phone, so the surveyor can see the burn
scars with no signal.

    python src/basemap_mbtiles.py <google-cloud-project-id>
                                  [--date YYYY-MM-DD] [--minzoom 8]
                                  [--maxzoom 16] [--quality 75]
                                  [--natural] [--dry-run]

Run inside the `geolibre` conda environment, after `earthengine authenticate`.

Why one date and not a cloud-free composite: `src/s2_scene_survey.py` measured
2026-08-23 at 99.96% clear over corridor land, and its four granules together
cover 100.0% of it. A single date needs no cloud masking, has no seams between
dates, and shows the ground as it was on one morning. A composite would buy
nothing here and would smear dates across the scars.

This is NOT the analysis input. Task 15 needs single scenes with their cloud
pixels intact and their reflectance unscaled; this file is 8-bit JPEG stretched
for a phone screen in sunlight. Never compute an index from it.

False colour SWIR (B12/B8A/B4) is the default because burn scars read as bright
orange against dark vegetation, which is legible on a phone outdoors. Natural
colour renders scars and cloud shadow as the same grey. --natural if you want
it anyway.
"""

from __future__ import annotations

import argparse
import io
import math
import sqlite3
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "fieldwork" / "biak_ground_truth.gpkg"
OUT = ROOT / "fieldwork" / "biak_basemap.mbtiles"

S2 = "COPERNICUS/S2_SR_HARMONIZED"
DEFAULT_DATE = "2026-08-23"

FALSE_COLOUR = ["B12", "B8A", "B4"]
NATURAL = ["B4", "B3", "B2"]

# The stretch is measured from the scene, not guessed. Guessing it produced a
# uniformly saturated green map on the first attempt: B8A over this forest
# runs 2384 to 4079 between its 2nd and 98th percentiles, so a hand-picked
# ceiling of 4000 mapped almost every land pixel to full green, while B12's
# 98th percentile of 1822 against a ceiling of 3000 left the burn scars in
# the bottom half of the red channel. Percentiles adapt to whatever date and
# area this is pointed at; a constant only ever suits the scene it was tuned
# on.
STRETCH_LOW, STRETCH_HIGH = 2, 98


def corridor_bounds(pad_km=5.0):
    con = sqlite3.connect(GPKG)
    rows = con.execute("SELECT geom FROM target_bakar "
                       "WHERE prioritas IN ('kuat','sedang')").fetchall()
    con.close()
    pts = [struct.unpack("<BIdd", g[0][8:])[2:] for g in rows]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    pad = pad_km / 110.57
    return [min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad]


def deg2tile(lat, lon, z):
    """Web Mercator XYZ tile containing a point. Latitude is clamped to the
    Mercator limit; beyond it the tangent blows up and the index is garbage."""
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n)
    return min(x, n - 1), min(y, n - 1)


def tiles_for(box, z):
    x0, y0 = deg2tile(box[3], box[0], z)      # north-west
    x1, y1 = deg2tile(box[1], box[2], z)      # south-east
    return [(z, x, y)
            for x in range(min(x0, x1), max(x0, x1) + 1)
            for y in range(min(y0, y1), max(y0, y1) + 1)]


def mbtiles_open(path, name, box, minz, maxz, fmt="jpg"):
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE metadata (name TEXT, value TEXT);"
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER,"
        " tile_row INTEGER, tile_data BLOB);"
        "CREATE UNIQUE INDEX tile_index ON tiles"
        " (zoom_level, tile_column, tile_row);")
    con.executemany("INSERT INTO metadata VALUES (?,?)", [
        ("name", name), ("type", "baselayer"), ("version", "1.0"),
        ("description", "Sentinel-2 false colour, field navigation only - "
                        "not an analysis input"),
        ("format", fmt),
        ("bounds", ",".join("{:.6f}".format(v) for v in box)),
        ("center", "{:.6f},{:.6f},{}".format(
            (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, maxz)),
        ("minzoom", str(minz)), ("maxzoom", str(maxz)),
    ])
    return con


def fetch(url, tries=4):
    import requests
    for attempt in range(tries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                return r.content
            if r.status_code in (404, 400):
                return None
            # 429 and 5xx are worth waiting out
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def to_jpeg(png_bytes, quality):
    """PNG tiles from Earth Engine carry alpha; JPEG cannot. Returns None for
    a fully transparent tile so open sea outside the granules costs nothing."""
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes))
    if im.mode in ("RGBA", "LA"):
        alpha = im.getchannel("A")
        if alpha.getextrema()[1] == 0:
            return None
        bg = Image.new("RGB", im.size, (0, 0, 0))
        bg.paste(im.convert("RGB"), mask=alpha)
        im = bg
    else:
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("--date", default=DEFAULT_DATE)
    ap.add_argument("--minzoom", type=int, default=8)
    ap.add_argument("--maxzoom", type=int, default=16,
                    help="Sentinel-2 is 10 m, which is native at about z14; "
                         "z16 is already 4x upsampled and z17 only adds blur")
    ap.add_argument("--quality", type=int, default=75)
    ap.add_argument("--pad-km", type=float, default=5.0)
    ap.add_argument("--natural", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true",
                    help="count tiles and stop, without downloading any")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not GPKG.exists():
        raise SystemExit(
            "{} is missing - run src/fieldwork_gpkg.py first".format(GPKG))

    box = corridor_bounds(args.pad_km)
    todo = [t for z in range(args.minzoom, args.maxzoom + 1)
            for t in tiles_for(box, z)]
    print("corridor bbox {}".format([round(v, 4) for v in box]))
    print("zoom {}..{}: {} tiles".format(args.minzoom, args.maxzoom, len(todo)))
    for z in range(args.minzoom, args.maxzoom + 1):
        n = len(tiles_for(box, z))
        if n > 1:
            print("  z{:<3} {:>7} tiles  ~{:6.1f} MB at 18 KB".format(
                z, n, n * 18 / 1024))
    if args.dry_run:
        return

    # Earth Engine, requests and Pillow are imported where they are used, so
    # the tile arithmetic above can be tested in an environment that has none
    # of them - which is every environment except `geolibre`.
    import ee
    ee.Initialize(project=args.project)
    day = ee.Date(args.date)
    coll = (ee.ImageCollection(S2)
            .filterBounds(ee.Geometry.Rectangle(box, None, False))
            .filterDate(day, day.advance(1, "day")))
    n = coll.size().getInfo()
    if n == 0:
        raise SystemExit("no Sentinel-2 granule on {} over the corridor - "
                         "run src/s2_scene_survey.py and pick a date it "
                         "reports".format(args.date))
    print("{}: {} granules {}".format(
        args.date, n, coll.aggregate_array("MGRS_TILE").getInfo()))

    bands = NATURAL if args.natural else FALSE_COLOUR
    mosaic = coll.mosaic()
    # Percentiles over LAND only. Including the sea would drag every low end
    # down to open-water reflectance and flatten the land into the top of the
    # range - the ocean is most of this box and none of the subject.
    land = ee.Image("ESA/WorldCover/v200/2021").select("Map").neq(80)
    st = (mosaic.select(bands).updateMask(land).reduceRegion(
        ee.Reducer.percentile([STRETCH_LOW, STRETCH_HIGH]),
        ee.Geometry.Rectangle(box, None, False), 60,
        maxPixels=int(1e13), tileScale=4).getInfo())
    lo = [st["{}_p{}".format(b, STRETCH_LOW)] for b in bands]
    hi = [st["{}_p{}".format(b, STRETCH_HIGH)] for b in bands]
    for b, a, z in zip(bands, lo, hi):
        print("  {:<4} p{} {:>6.0f}   p{} {:>6.0f}".format(
            b, STRETCH_LOW, a, STRETCH_HIGH, z))
    mapid = mosaic.visualize(bands=bands, min=lo, max=hi).getMapId()

    con = mbtiles_open(args.out, "Biak {} S2".format(args.date), box,
                       args.minzoom, args.maxzoom)
    done = {"n": 0, "empty": 0, "fail": 0, "bytes": 0}

    def one(t):
        z, x, y = t
        raw = fetch(ee.data.getTileUrl(mapid, x, y, z))
        if raw is None:
            return t, None, True
        return t, to_jpeg(raw, args.quality), False

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for t, blob, failed in pool.map(one, todo):
            z, x, y = t
            if failed:
                done["fail"] += 1
            elif blob is None:
                done["empty"] += 1
            else:
                # MBTiles rows are TMS: y counts up from the south, XYZ counts
                # down from the north. Getting this wrong yields a map that
                # loads and is vertically mirrored, which is easy to miss.
                con.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                            (z, x, (1 << z) - 1 - y, blob))
                done["n"] += 1
                done["bytes"] += len(blob)
            total = done["n"] + done["empty"] + done["fail"]
            if total % 500 == 0:
                print("  {}/{}  written {}  empty {}  failed {}  {:.1f} MB"
                      .format(total, len(todo), done["n"], done["empty"],
                              done["fail"], done["bytes"] / 1e6))
    con.commit()
    con.close()

    size = args.out.stat().st_size
    print("wrote {}".format(args.out))
    print("  {} tiles, {} empty (outside the granules), {} failed".format(
        done["n"], done["empty"], done["fail"]))
    print("  {:.1f} MB on disk, {:.1f} KB per tile".format(
        size / 1e6, done["bytes"] / max(done["n"], 1) / 1024))
    if done["fail"]:
        print("  {} tiles failed after retries: the map has holes. Re-run to "
              "fill them - existing rows are replaced, not duplicated."
              .format(done["fail"]))


if __name__ == "__main__":
    sys.exit(main())
