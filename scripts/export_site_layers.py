"""Export the field survey and the Sentinel-2 tiles that the web map needs.

    "$CONDA/envs/geolibre/python.exe" scripts/export_site_layers.py
    "$CONDA/envs/geolibre/python.exe" scripts/export_site_layers.py --check

Two sources that until now existed only inside QGIS projects become files the
published map can load:

  fieldwork/biak_ground_truth.gpkg   the three plots visited on 2026-09-03,
                                     with the photograph taken at each one
  data/labels/imagery/*.tif          the S2DR4 1 m scenes that data/labels/
                                     biak_labels.qgz drapes under the labels

Outputs, all overwritten on every run:

    docs/data/survey.geojson      3 visited plots
    docs/photos/<plot>_<arah>.webp   one photograph per plot, EXIF removed
    docs/imagery/<event>_<kind>_<date>.webp
    docs/data/imagery.json        the manifest the map reads: for each tile
                                  its WGS84 corner quad, its date and its note

This lives in scripts/ rather than src/ because it needs rasterio and Pillow,
which the project's default environment does not carry, and because it reads
only inputs that never change. It is deliberately NOT in the daily workflow:
re-running it can only reproduce the same bytes, and a cron job that rewrites
published imagery is exactly what adr/0003 forbids.

WHAT IS AND IS NOT PUBLISHED

The survey table holds 3 visited plots, 281 planned burn targets and 80
planned control targets. Only the 3 visited plots are published. The 361
planned targets are a sampling design over named desa in a populated place,
nobody ever stood on them, and a dot on a public map saying "burn target"
beside someone's garden is a claim this project cannot support. The visited
plots are evidence: the surveyor stood there and photographed the ground.

EXIF is stripped from every photograph. A phone photo carries GPS to a few
metres, the device serial and the exact second, and the plot's own coordinate
is already published beside it at the accuracy the surveyor recorded.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "fieldwork" / "biak_ground_truth.gpkg"
IMAGERY_SRC = ROOT / "data" / "labels" / "imagery"
DOCS = ROOT / "docs"

# Longest side of a published raster, in pixels. The source scenes are 4100 px
# over about 4.1 km, so 1280 is 3.2 m per pixel: coarser than the 1 m product
# and still three times finer than the 20 m bands the sensor actually measured.
# The full-resolution scenes are 24-38 MB each and 36 of them do not belong in
# a git repository.
MAX_PX = 1280
PHOTO_PX = 1280
WEBP_Q = 80

# The three events that have hand-drawn label boxes and 1 m imagery, with the
# desa the event centroid falls in. Names come from data/processed/events.csv.
EVENTS = {
    "E0301": "Anjareuw",
    "E0313": "Yendidori",
    "E0368": "Insumarires",
}
KINDS = {
    "tci": ("True colour",
            "Sentinel-2 true colour, super-resolved to 1 m by S2DR4 and "
            "published here at about 3 m, with one contrast stretch applied "
            "across all six dates of this event so the series stays "
            "comparable. Burn scars read as dull grey-brown; so does bare "
            "coral rubble, and so does cloud shadow."),
    "swir": ("False colour (B12/B8A/B4)",
             "Shortwave infrared in red, near infrared in green. Burned "
             "ground is magenta to orange, living vegetation is green, and "
             "cloud is white. A band combination, not a fire detection."),
}


# ---------------------------------------------------------------- survey ----

def gpkg_point(blob):
    """Decode one GeoPackage POINT blob to (lon, lat).

    Reimplemented rather than imported so this script does not need a GDAL
    vector driver for four bytes of header and sixteen of payload.
    """
    flags = blob[3]
    envelope = (flags >> 1) & 7
    skip = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
    wkb = blob[8 + skip:]
    order = "<" if wkb[0] == 1 else ">"
    kind = struct.unpack(order + "I", wkb[1:5])[0]
    if kind != 1:
        raise ValueError(f"expected WKB point, got type {kind}")
    return struct.unpack(order + "dd", wkb[5:21])


def read_survey():
    """The visited plots, each with the photograph taken standing on it."""
    con = sqlite3.connect(f"file:{GPKG.as_posix()}?mode=ro", uri=True)
    try:
        photos = {}
        for uuid, berkas, arah, ket in con.execute(
                "select plot_uuid, berkas, arah, keterangan from foto"):
            photos.setdefault(uuid, []).append(
                {"berkas": berkas, "arah": arah, "keterangan": ket})
        rows = []
        for (fid, geom, uuid, plot_id, target_id, kelas, yakin, bukti,
             akurasi, waktu, catatan) in con.execute(
                "select fid, geom, uuid, plot_id, target_id, kelas, "
                "tingkat_yakin, bukti, akurasi_m, waktu, catatan from survei"):
            lon, lat = gpkg_point(geom)
            rows.append({
                "fid": fid, "uuid": uuid, "plot_id": plot_id,
                "target_id": target_id, "kelas": kelas, "tingkat_yakin": yakin,
                "bukti": bukti, "akurasi_m": akurasi, "waktu": waktu,
                "catatan": catatan, "lon": lon, "lat": lat,
                "photos": photos.get(uuid, []),
            })
    finally:
        con.close()
    return rows


def find_photo(berkas):
    """The survey app stores a bare file name; the files sit beside the gpkg."""
    for candidate in (GPKG.parent / berkas,
                      GPKG.parent / "foto_timestamp" / berkas):
        if candidate.exists():
            return candidate
    return None


def write_photo(src, dst):
    """Re-encode without EXIF. Pillow drops metadata unless asked to keep it."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((PHOTO_PX, PHOTO_PX), Image.LANCZOS)
        clean = Image.frombytes("RGB", im.size, im.tobytes())
        dst.parent.mkdir(parents=True, exist_ok=True)
        clean.save(dst, "WEBP", quality=WEBP_Q, method=5)
    return dst.stat().st_size


def export_survey():
    rows = read_survey()
    out_dir = DOCS / "photos"
    features, missing = [], []
    for r in rows:
        shots = []
        for p in r["photos"]:
            src = find_photo(p["berkas"])
            if src is None:
                # A missing file is not an absent photograph. Say which.
                missing.append(p["berkas"])
                continue
            name = f'{r["plot_id"]}_{p["arah"]}.webp'
            write_photo(src, out_dir / name)
            shots.append({"file": f"photos/{name}", "arah": p["arah"],
                          "keterangan": p["keterangan"]})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(r["lon"], 6),
                                         round(r["lat"], 6)]},
            "properties": {
                "plot_id": r["plot_id"], "target_id": r["target_id"],
                "kelas": r["kelas"], "tingkat_yakin": r["tingkat_yakin"],
                "bukti": r["bukti"], "akurasi_m": r["akurasi_m"],
                "waktu": r["waktu"], "catatan": r["catatan"],
                "photos": shots,
            },
        })
    fc = {"type": "FeatureCollection", "features": features}
    path = DOCS / "data" / "survey.geojson"
    path.write_text(json.dumps(fc, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return fc, missing


# --------------------------------------------------------------- imagery ----

def series_limits(frames, lo=2, hi=98):
    """One pair of per-band byte limits for every date of one event.

    Sentinel-2 true colour over humid tropical forest sits in the bottom of
    the byte range, and an unstretched tile is a layer nobody can read. A
    per-date stretch would be worse than none: a burn darkens the frame, the
    stretch brightens it straight back, and the dates stop being comparable
    with each other. So the limits are computed once across every date of the
    event and applied unchanged to each. The false-colour tiles are left
    alone; they are already legible.
    """
    pool = np.concatenate([f.reshape(3, -1)[:, ::311].T for f in frames])
    valid = pool.max(axis=1) > 0
    if not valid.any():
        return None
    a, b = np.percentile(pool[valid].astype(np.float32), [lo, hi], axis=0)
    b = np.where(b <= a, a + 1.0, b)
    return a, b


def to_wgs84_webp(src_path, dst_path, limits=None):
    """Warp one UTM scene to WGS84 and write it as a lossy WebP with alpha.

    The corner quad MapLibre needs is axis-aligned in lon/lat, so the scene
    has to be warped rather than merely reprojected at the corners: zone 53's
    grid convergence here is about 0.02 degrees, small but not nothing at 1 m.
    Warping leaves void slivers at the frame edge and some scenes are only
    partly covered; both become transparent rather than black, because a black
    block on a burn map reads as burned ground.
    """
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        scale = min(1.0, MAX_PX / max(width, height))
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds,
            dst_width=width, dst_height=height)
        rgb = np.zeros((3, height, width), dtype=np.uint8)
        for band in (1, 2, 3):
            reproject(
                source=rasterio.band(src, band),
                destination=rgb[band - 1],
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs="EPSG:4326",
                resampling=Resampling.average, src_nodata=None, dst_nodata=0)
        west, north = transform * (0, 0)
        east, south = transform * (width, height)

    # S2DR4 writes true black only where it has no data; inside a scene even
    # deep burn scar and shadow sit above zero in at least one band.
    alpha = np.where(rgb.max(axis=0) == 0, 0, 255).astype(np.uint8)
    shown = rgb
    if limits is not None:
        a, b = limits
        scaled = (rgb.astype(np.float32) - a[:, None, None]) / \
            (b - a)[:, None, None]
        shown = (np.clip(scaled, 0, 1) * 255).astype(np.uint8)
    im = Image.fromarray(np.dstack([shown.transpose(1, 2, 0), alpha]), "RGBA")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst_path, "WEBP", quality=WEBP_Q, method=5)
    return [round(west, 6), round(south, 6), round(east, 6), round(north, 6)]


def read_bands(tif):
    with rasterio.open(tif) as src:
        return src.read([1, 2, 3])


def export_imagery():
    tiles, skipped = [], []
    for event, desa in EVENTS.items():
        for kind, (label, note) in KINDS.items():
            sources = [s for s in sorted(IMAGERY_SRC.glob(f"{event}_{kind}_*.tif"))
                       if len(s.stem.rsplit("_", 1)[1]) == 8
                       and s.stem.rsplit("_", 1)[1].isdigit()]
            skipped += [s.name for s in sorted(
                IMAGERY_SRC.glob(f"{event}_{kind}_*.tif")) if s not in sources]
            limits = (series_limits([read_bands(s) for s in sources])
                      if kind == "tci" and sources else None)
            for src in sources:
                date = src.stem.rsplit("_", 1)[1]
                name = f"{event}_{kind}_{date}.webp"
                bounds = to_wgs84_webp(src, DOCS / "imagery" / name, limits)
                tiles.append({
                    "id": f"{event}-{kind}-{date}",
                    "event": event, "desa": desa, "kind": kind,
                    "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                    "label": label, "note": note,
                    "file": f"imagery/{name}", "bounds": bounds,
                })
    manifest = {
        "source": "Sentinel-2 L2A (Copernicus), super-resolved to 1 m by "
                  "S2DR4 and republished here at about 3 m per pixel.",
        "published_px": MAX_PX,
        "events": [{"event": e, "desa": d} for e, d in EVENTS.items()],
        "tiles": tiles,
    }
    (DOCS / "data" / "imagery.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest, skipped


# ----------------------------------------------------------------- check ----

def demo():
    """Assert the things a reader of the map would notice if they broke."""
    fc = json.loads((DOCS / "data" / "survey.geojson").read_text("utf-8"))
    feats = fc["features"]
    assert len(feats) == 3, f"expected 3 visited plots, got {len(feats)}"
    for f in feats:
        p = f["properties"]
        assert p["photos"], f'{p["plot_id"]} has no photograph'
        for shot in p["photos"]:
            img = DOCS / shot["file"]
            assert img.exists(), f"{shot['file']} is referenced and missing"
            with Image.open(img) as im:
                assert not im.getexif(), f"{shot['file']} still carries EXIF"
        lon, lat = f["geometry"]["coordinates"]
        assert 135.7 < lon < 136.5 and -1.4 < lat < -0.6, \
            f'{p["plot_id"]} is outside Biak'
    # The planned targets must not have leaked into the published file.
    assert "target_bakar" not in json.dumps(fc), "planned targets published"

    man = json.loads((DOCS / "data" / "imagery.json").read_text("utf-8"))
    assert man["tiles"], "no imagery tiles"
    for t in man["tiles"]:
        img = DOCS / t["file"]
        assert img.exists(), f"{t['file']} is in the manifest and missing"
        w, s, e, n = t["bounds"]
        assert w < e and s < n, f"{t['id']} has an inverted bounding box"
        assert 135.7 < w < 136.5 and -1.4 < s < -0.6, \
            f"{t['id']} is outside Biak"
        # 4.1 km square scenes: about 0.037 degrees on a side either way.
        assert 0.02 < e - w < 0.06 and 0.02 < n - s < 0.06, \
            f"{t['id']} is not scene-sized: {e - w:.4f} x {n - s:.4f}"
    dates = {t["date"] for t in man["tiles"]}
    assert len(dates) >= 2, "a single date cannot show a change"
    print(f"survey: {len(feats)} plots, "
          f"{sum(len(f['properties']['photos']) for f in feats)} photographs")
    print(f"imagery: {len(man['tiles'])} tiles over {len(dates)} dates, "
          f"{sum((DOCS / t['file']).stat().st_size for t in man['tiles']) / 1e6:.1f} MB")
    print("all assertions passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="assert the existing output, write nothing")
    args = ap.parse_args()
    if args.check:
        demo()
        return 0
    fc, missing = export_survey()
    print(f"docs/data/survey.geojson: {len(fc['features'])} plots")
    if missing:
        # Never silently publish a plot whose photograph did not export.
        print(f"MISSING photograph files: {missing}", file=sys.stderr)
    man, skipped = export_imagery()
    print(f"docs/data/imagery.json: {len(man['tiles'])} tiles")
    if skipped:
        print(f"skipped unparseable names: {skipped}", file=sys.stderr)
    demo()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
