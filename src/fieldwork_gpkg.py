"""Build the field-survey GeoPackage for ground truth.

Reads the tracked detection store and writes a GeoPackage holding three
layers: burn targets clustered from a fire-season window, control points on
land far from every detection ever recorded, and an empty survey layer for
the surveyor to fill on the phone.

    python src/fieldwork_gpkg.py [--from YYYY-MM-DD] [--to YYYY-MM-DD]
                                 [--controls N] [--out PATH]

A GeoPackage is a SQLite database, so this writes one with sqlite3 alone
rather than adding geopandas or GDAL for a few hundred points
(AGENTS never-7). The output is deliberately outside docs/: it is field
material, and the survey layer will hold photographs of people's land before
any ethical clearance exists.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import struct
from pathlib import Path

import pandas as pd
import yaml
from shapely.geometry import Point, shape
from shapely.geometry import box as shapely_box
from shapely.prepared import prep
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
EARTH_R = 6371008.8

# The August 2026 burning ran 19-25 August and peaked at 283 detections on
# the 22nd. Scars from it are what a survey in September can still see.
EVENT_FROM, EVENT_TO = "2026-08-19", "2026-08-25"

# One VIIRS pixel. Detections closer than this cannot be told apart on the
# ground, so they are one target to walk to, not several.
CLUSTER_M = 375.0

# A control point must be far enough from every detection ever recorded that
# a surveyor standing on it is not standing on an unrecorded edge of a burn.
CONTROL_CLEAR_M = 1000.0


def metres(lat1, lon1, lat2, lon2):
    """Local flat-earth distance. Over 375 m at 1 S the error is microns."""
    dy = math.radians(lat2 - lat1) * EARTH_R
    dx = math.radians(lon2 - lon1) * EARTH_R * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


# --------------------------------------------------------------------------
# GeoPackage writing


def gpkg_point(lon, lat):
    """GeoPackageBinary for a 2D point: header, then little-endian WKB."""
    # magic 'GP', version 0, flags 0x01 (little endian, no envelope), srs_id
    return (b"GP" + bytes([0, 1]) + struct.pack("<i", 4326)
            + struct.pack("<BIdd", 1, 1, lon, lat))


def gpkg_create(path):
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA application_id = 1196444487")   # 'GPKG'
    con.execute("PRAGMA user_version = 10300")          # 1.3.0
    con.executescript(
        "CREATE TABLE gpkg_spatial_ref_sys ("
        " srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,"
        " organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,"
        " definition TEXT NOT NULL, description TEXT);"
        "CREATE TABLE gpkg_contents ("
        " table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,"
        " identifier TEXT UNIQUE, description TEXT DEFAULT '',"
        " last_change DATETIME NOT NULL DEFAULT"
        " (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
        " min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,"
        " srs_id INTEGER REFERENCES gpkg_spatial_ref_sys(srs_id));"
        "CREATE TABLE gpkg_geometry_columns ("
        " table_name TEXT NOT NULL, column_name TEXT NOT NULL,"
        " geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,"
        " z TINYINT NOT NULL, m TINYINT NOT NULL,"
        " CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));")
    wgs84 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,'
             '298.257223563]],PRIMEM["Greenwich",0],'
             'UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]')
    con.executemany(
        "INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
        [("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
         ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
         ("WGS 84 geodetic", 4326, "EPSG", 4326, wgs84, None)])
    return con


def gpkg_layer(con, name, fields, rows, description):
    """fields: list of (column, sql type). rows: dicts with lon/lat + fields."""
    cols = ", ".join('"{}" {}'.format(c, t) for c, t in fields)
    con.execute('CREATE TABLE "{}" (fid INTEGER PRIMARY KEY AUTOINCREMENT,'
                ' geom POINT, {})'.format(name, cols))
    con.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
                (name, "geom", "POINT", 4326, 0, 0))

    names = [c for c, _ in fields]
    marks = ", ".join("?" for _ in range(len(names) + 1))
    quoted = ", ".join('"{}"'.format(c) for c in names)
    con.executemany(
        'INSERT INTO "{}" (geom, {}) VALUES ({})'.format(name, quoted, marks),
        [[gpkg_point(r["lon"], r["lat"])] + [r.get(c) for c in names]
         for r in rows])

    if rows:
        xs = [r["lon"] for r in rows]
        ys = [r["lat"] for r in rows]
        box = (min(xs), min(ys), max(xs), max(ys))
    else:
        box = (None, None, None, None)
    con.execute(
        "INSERT INTO gpkg_contents"
        " (table_name, data_type, identifier, description,"
        "  min_x, min_y, max_x, max_y, srs_id)"
        " VALUES (?, 'features', ?, ?, ?, ?, ?, ?, 4326)",
        (name, name, description) + box)


def gpkg_table(con, name, fields, description):
    """A non-spatial GeoPackage table: data_type 'attributes', no geometry.

    One photo per point is not enough evidence for a burn scar - the ground,
    the surroundings and at least one direction of view all matter - so the
    photographs live in their own table, one row per picture, linked back to
    the survey point.
    """
    cols = ", ".join('"{}" {}'.format(c, t) for c, t in fields)
    con.execute('CREATE TABLE "{}" (fid INTEGER PRIMARY KEY AUTOINCREMENT,'
                ' {})'.format(name, cols))
    con.execute(
        "INSERT INTO gpkg_contents (table_name, data_type, identifier,"
        " description) VALUES (?, 'attributes', ?, ?)",
        (name, name, description))


# --------------------------------------------------------------------------
# Targets


def cluster(det):
    """Greedy 375 m clustering, strongest detection first.

    Seeding on the highest FRP puts the cluster centre on the most energetic
    detection rather than on whichever row the store happened to list first.
    """
    rows = det.sort_values("frp", ascending=False, na_position="last")
    clusters = []
    for r in rows.itertuples():
        for c in clusters:
            if metres(c["lat"], c["lon"], r.latitude, r.longitude) <= CLUSTER_M:
                c["members"].append(r)
                break
        else:
            clusters.append({"lat": r.latitude, "lon": r.longitude,
                             "members": [r]})
    return clusters


def targets(det):
    out = []
    ranked = sorted(cluster(det), key=lambda c: -len(c["members"]))
    for i, c in enumerate(ranked, start=1):
        m = c["members"]
        sats = {r.satellite for r in m}
        days = sorted({r.date_wit for r in m})
        # AGENTS never-3: the confidence column is never cast to a number.
        # VIIRS grades it l/n/h and MODIS as a percentage string, so the two
        # do not share a scale; only the VIIRS letter is read here.
        high = any(r.instrument == "VIIRS" and r.confidence == "h" for r in m)

        if len(m) >= 3 and (len(sats) >= 2 or len(days) >= 2):
            rank = "kuat"
        elif len(m) >= 2 or high:
            rank = "sedang"
        else:
            rank = "lemah"

        frps = [r.frp for r in m if r.frp == r.frp]
        out.append({
            "lat": round(c["lat"], 6), "lon": round(c["lon"], 6),
            "target_id": "T{:03d}".format(i),
            "prioritas": rank,
            "n_deteksi": len(m),
            "n_satelit": len(sats),
            "n_hari": len(days),
            "frp_maks": round(max(frps), 2) if frps else None,
            "conf_tinggi_viirs": int(high),
            "tgl_awal": days[0], "tgl_akhir": days[-1],
            "desa": m[0].desa, "distrik": m[0].distrik,
            "situs_berulang": int(any(r.recurrent_site for r in m)),
        })
    return out


def target_box(targets_out, pad_km=5.0):
    """Bounding box of the targets worth walking to, padded.

    Control points have to come from the same landscape as the burn targets.
    Sampling them across every desa put 46 of 80 on Numfor and Supiori,
    hundreds of kilometres from any target, off the basemap and out of
    reach - and worse, it would have confounded burned-against-unburned
    with which-island, so an index difference could have been geography.
    """
    use = [t for t in targets_out if t["prioritas"] in ("kuat", "sedang")]
    lons = [t["lon"] for t in use]
    lats = [t["lat"] for t in use]
    pad = pad_km / 110.57
    return (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)


def controls(det_all, desa_path, n, box=None, seed=20260903):
    """Random land points at least CONTROL_CLEAR_M from any detection ever.

    Without these the survey can measure only how often an index finds a
    burn, never how often it invents one - and inventing one is the failure
    NBR+ exists to address.
    """
    feats = json.loads(desa_path.read_text(encoding="utf-8"))["features"]
    # The national BIG geodatabase names its columns WADMKD/WADMKC/WADMKK,
    # not desa/distrik. Reading the friendly names with .get() returned None
    # for all 80 rows without raising anything; assert instead of guessing.
    assert "WADMKD" in feats[0]["properties"], (
        "unexpected boundary schema: {}".format(
            sorted(feats[0]["properties"])))
    polys = [shape(f["geometry"]) for f in feats]
    names = [(f["properties"]["WADMKD"], f["properties"]["WADMKC"])
             for f in feats]
    if box is not None:
        keep = [i for i, p in enumerate(polys)
                if p.intersects(shapely_box(*box))]
        polys = [polys[i] for i in keep]
        names = [names[i] for i in keep]
    ready = [prep(p) for p in polys]
    tree = STRtree(polys)

    hot = det_all[["latitude", "longitude"]].to_numpy()
    # A degree of latitude is ~111 km here; the longitude degree is shorter by
    # cos(lat), which at 1 S is 0.9998. Treating both as 111 km makes the
    # box prefilter slightly generous, which is the safe direction.
    deg = CONTROL_CLEAR_M / 111_000.0

    rng = random.Random(seed)
    if box is not None:
        minx, miny, maxx, maxy = box
    else:
        minx = min(p.bounds[0] for p in polys)
        miny = min(p.bounds[1] for p in polys)
        maxx = max(p.bounds[2] for p in polys)
        maxy = max(p.bounds[3] for p in polys)

    out, tries = [], 0
    while len(out) < n and tries < n * 5000:
        tries += 1
        lon = rng.uniform(minx, maxx)
        lat = rng.uniform(miny, maxy)
        near = hot[(abs(hot[:, 0] - lat) < deg) & (abs(hot[:, 1] - lon) < deg)]
        if any(metres(lat, lon, h[0], h[1]) <= CONTROL_CLEAR_M for h in near):
            continue
        pt = Point(lon, lat)
        for idx in tree.query(pt):
            if ready[idx].contains(pt):
                desa, distrik = names[idx]
                out.append({"lat": round(lat, 6), "lon": round(lon, 6),
                            "target_id": "K{:03d}".format(len(out) + 1),
                            "desa": desa, "distrik": distrik})
                break
    return out


# --------------------------------------------------------------------------

SURVEY_FIELDS = [
    # The photo table joins to THIS, never to fid. Mergin renumbers fid during
    # synchronisation, and photos linked by fid end up attached to whichever
    # point inherited the number - silently, and unrecoverably once the
    # original numbering is gone.
    ("uuid", "TEXT"),
    ("plot_id", "TEXT"),
    ("target_id", "TEXT"),          # which target this answers, blank if none
    ("kelas", "TEXT"),              # bakar / tidak_bakar - the label itself
    ("tingkat_yakin", "TEXT"),      # pasti / mungkin
    ("bukti", "TEXT"),              # arang / abu / batang hangus / tidak ada
    ("akurasi_m", "REAL"),          # GPS horizontal accuracy at capture
    ("waktu", "TEXT"),              # ISO local datetime, filled by the app
    ("catatan", "TEXT"),
]

PHOTO_FIELDS = [
    ("plot_uuid", "TEXT"),          # foreign key to survei.uuid
    ("berkas", "TEXT"),             # attachment path, relative to the project
    ("arah", "TEXT"),               # permukaan / utara / timur / selatan / barat
    ("keterangan", "TEXT"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="start", default=EVENT_FROM)
    ap.add_argument("--to", dest="end", default=EVENT_TO)
    ap.add_argument("--controls", type=int, default=80)
    ap.add_argument("--controls-anywhere", action="store_true",
                    help="sample controls across every desa instead of the "
                         "target corridor; unreachable in the field and it "
                         "confounds burned-vs-unburned with which island")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "fieldwork" / "biak_ground_truth.gpkg")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    store = ROOT / cfg["output_paths"]["processed"]
    det = pd.read_parquet(store)
    print("store {}: {} detections, {} to {}".format(
        store.name, len(det), det.date_wit.min(), det.date_wit.max()))

    window = det[(det.date_wit >= args.start) & (det.date_wit <= args.end)
                 & det.on_land]
    print("window {}..{} on land: {} detections".format(
        args.start, args.end, len(window)))
    if window.empty:
        raise SystemExit("no detections in that window - nothing to survey")

    tg = targets(window)
    counts = {r: sum(1 for t in tg if t["prioritas"] == r)
              for r in ("kuat", "sedang", "lemah")}
    print("targets: {} clusters at {:.0f} m  {}".format(
        len(tg), CLUSTER_M, counts))

    box = None if args.controls_anywhere else target_box(tg)
    if box is not None:
        print("controls confined to the target corridor {}".format(
            [round(v, 4) for v in box]))
    ct = controls(det, ROOT / cfg["admin_polygon"], args.controls, box)
    print("controls: {} land points >= {:.0f} m from every detection"
          " in the store".format(len(ct), CONTROL_CLEAR_M))
    if len(ct) < args.controls:
        print("  WARNING: asked for {}, the corridor yielded {}".format(
            args.controls, len(ct)))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    con = gpkg_create(args.out)
    gpkg_layer(con, "target_bakar",
               [("target_id", "TEXT"), ("prioritas", "TEXT"),
                ("n_deteksi", "INTEGER"), ("n_satelit", "INTEGER"),
                ("n_hari", "INTEGER"), ("frp_maks", "REAL"),
                ("conf_tinggi_viirs", "INTEGER"), ("tgl_awal", "TEXT"),
                ("tgl_akhir", "TEXT"), ("desa", "TEXT"), ("distrik", "TEXT"),
                ("situs_berulang", "INTEGER")],
               tg,
               "Klaster deteksi {}..{}, jarak {:.0f} m."
               " Bukan batas area terbakar.".format(
                   args.start, args.end, CLUSTER_M))
    gpkg_layer(con, "target_kontrol",
               [("target_id", "TEXT"), ("desa", "TEXT"), ("distrik", "TEXT")],
               ct,
               "Titik darat >= {:.0f} m dari setiap deteksi dalam arsip."
               " Calon kelas tidak_bakar.".format(CONTROL_CLEAR_M))
    gpkg_layer(con, "survei", SURVEY_FIELDS, [],
               "Diisi di lapangan. Kosong sampai ada yang berjalan ke sana.")
    gpkg_table(con, "foto", PHOTO_FIELDS,
               "Satu baris per foto, ditautkan ke survei.uuid (bukan fid).")
    con.commit()
    con.close()
    print("wrote {}".format(args.out))


if __name__ == "__main__":
    main()
