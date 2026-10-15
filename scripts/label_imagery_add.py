"""Add the 2026-10 S2DR4 dates, and the native Sentinel-2 beside each of them.

    python scripts/label_imagery_add.py            # writes into data/labels/imagery/
    python scripts/label_imagery_add.py --dry-run  # says what it would write

Two things go in, named so the QGIS project can group them by date:

    <event>_swir_<acq>.tif        S2DR4 1 m, B12/B8A/B4
    <event>_tci_<acq>.tif         S2DR4 1 m, true colour
    <event>_s2n_swir_<acq>.tif    native Sentinel-2 20 m, the same three bands
    <event>_s2n_tci_<acq>.tif     native Sentinel-2 10 m, true colour

**The date in the name is the acquisition, not the date that was asked for.**
The 2026-10-14 wheel names its output after the request. Asking for 21 August
returned a file called 20260821 that is the 23 August scene, and asking for 24
August returned one called 20260824 that is the 25 August scene, bit for bit
identical to the 25 August tile the old wheel produced (scripts/s2dr4_compare.py,
2026-10-15). ASKED_FOR records that correction; nothing here guesses it.

The native chips come from the Element84 STAC on AWS, which is the catalogue
S2DR4 itself reads. Public COGs: no credential, no credits, no Earth Engine.
They are the unprocessed observation, and they are here to be compared against
the 1 m reconstruction - cloud, haze and smoke included.

Nothing in this script touches the GeoPackage. label_prepare.py would rewrite
the sample points, so it must not be re-run to get imagery.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from label_prepare import (  # noqa: E402  - the band order and stretch live there
    SWIR_BANDS, TILE, stretch_to_byte,
)

NEW = ROOT / "data/raw/s2dr4_biak_20261015/output/ID/T53MPU"
IMG = ROOT / "data/labels/imagery"
STAC = "https://earth-search.aws.element84.com/v1/search"

# What each file of the 2026-10 run really holds. The key is the date in the
# file name, which is the date the run asked for; the value is the acquisition.
ASKED_FOR = {"20260813": "20260813", "20260821": "20260823", "20260824": "20260825",
             "20260828": "20260828", "20260902": "20260902", "20260917": "20260917"}

# Native Sentinel-2 assets. swir22 is B12 and nir08 is B8A, both 20 m; red is
# B04 at 10 m and is averaged down to the 20 m grid so the three share one grid.
SWIR_ASSETS = ["swir22", "nir08", "red"]


def dash(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def stac_item(bounds_ll: tuple, acq: str) -> dict | None:
    """The Sentinel-2 L2A item over this box on this day, or None."""
    body = json.dumps({
        "collections": ["sentinel-2-l2a"],
        "bbox": list(bounds_ll),
        "datetime": f"{dash(acq)}T00:00:00Z/{dash(acq)}T23:59:59Z",
        "limit": 1,
    }).encode()
    req = urllib.request.Request(STAC, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        feats = json.loads(r.read().decode()).get("features", [])
    return feats[0] if feats else None


# These chips are stretched exactly like the 1 m ones, through label_prepare's
# stretch_to_byte: digital number / 10000 / 0.40, no offset. That is not the
# physically correct conversion - the catalogue states offset -0.1 for these
# assets, as Sentinel-2 processing baseline 04.00 and later requires - but it is
# the convention every existing chip and every judged box already uses, and
# S2DR4 writes its own output on the same raw scale (medians over the E0301 tile
# on 23 August: B12 1125 against the native 1149, B8A 2859 against 2929, B4 579
# against 562). Applying the offset to one side only would make S2DR4 look
# brighter than the sensor by 0.1 reflectance, which is the opposite of what
# these pairs are here to show. Anything that needs absolute reflectance must
# apply the offset itself.


def read_window(href: str, bounds, shape=None):
    """A window of a remote COG, in the window's own CRS. No download of the
    whole scene: /vsicurl/ fetches only the tiles the window covers."""
    with rasterio.open(f"/vsicurl/{href}") as src:
        win = from_bounds(*bounds, transform=src.transform)
        out = src.read(1, window=win, out_shape=shape,
                       resampling=Resampling.average, boundless=True, fill_value=0)
        tr = src.window_transform(win)
        if shape is not None:
            tr = tr * tr.scale(win.width / shape[1], win.height / shape[0])
        return out, tr, src.crs


def write(path: Path, arr: np.ndarray, transform, crs, dry: bool) -> None:
    if dry:
        print(f"   would write {path.name}  {arr.shape[2]}x{arr.shape[1]}")
        return
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[1],
                       width=arr.shape[2], count=arr.shape[0], dtype="uint8",
                       crs=crs, transform=transform, compress="deflate",
                       tiled=True, blockxsize=512, blockysize=512) as dst:
        dst.write(arr)
    print(f"   {path.name}  {arr.shape[2]}x{arr.shape[1]}")


def s2dr4_chips(eid: str, tile: str, asked: str, acq: str, dry: bool,
                force: bool = False) -> None:
    """The 1 m pair, renamed to the acquisition it really holds.

    An existing chip is left alone. Three of these six dates are already in the
    imagery directory from the 2026-08 run, and they are what 114 label boxes
    were judged on; replacing them mid-pass would change the evidence under
    judgements already made. The 2026-10 versions of those three were compared
    instead, which is what Task 24 wanted to know.
    """
    ms = NEW / tile / f"S2L3Ax10_{tile}-{asked}_MS.tif"
    tci_src = NEW / tile / f"S2L3Ax10_{tile}-{asked}_TCI.tif"
    if not ms.exists():
        print(f"   missing {ms.name}")
        return
    if not force and (IMG / f"{eid}_swir_{acq}.tif").exists():
        print(f"   {eid}_swir_{acq}.tif already there, left alone (--force to replace)")
        return
    with rasterio.open(ms) as r:
        a = r.read(indexes=SWIR_BANDS).astype("float32")
        transform, crs = r.transform, r.crs
    write(IMG / f"{eid}_swir_{acq}.tif",
          np.stack([stretch_to_byte(b) for b in a]), transform, crs, dry)
    with rasterio.open(tci_src) as r:
        write(IMG / f"{eid}_tci_{acq}.tif", r.read()[:3].astype("uint8"),
              r.transform, r.crs, dry)


def native_chips(eid: str, bounds_utm, bounds_ll, acq: str, dry: bool) -> None:
    """The native Sentinel-2 pair over the same ground: what the sensor saw."""
    item = stac_item(bounds_ll, acq)
    if item is None:
        print(f"   {eid} {acq}: no Sentinel-2 scene in the catalogue, skipped")
        return
    cloud = item["properties"].get("eo:cloud_cover")
    print(f"   {eid} {acq}: {item['id']}, tile cloud {cloud}%")

    # True colour, 10 m, already 8-bit in the catalogue.
    vis_href = item["assets"]["visual"]["href"]
    with rasterio.open(f"/vsicurl/{vis_href}") as src:
        win = from_bounds(*bounds_utm, transform=src.transform)
        rgb = src.read(window=win, boundless=True, fill_value=0)
        write(IMG / f"{eid}_s2n_tci_{acq}.tif", rgb[:3],
              src.window_transform(win), src.crs, dry)

    # SWIR false colour on the 20 m grid of B12.
    shape = None
    bands, transform, crs = [], None, None
    for name in SWIR_ASSETS:
        arr, tr, crs = read_window(item["assets"][name]["href"], bounds_utm, shape)
        if shape is None:
            shape, transform = arr.shape, tr
        bands.append(arr)
    swir = np.stack([stretch_to_byte(b.astype("float32")) for b in bands])
    write(IMG / f"{eid}_s2n_swir_{acq}.tif", swir, transform, crs, dry)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="replace 1 m chips that already exist. Those are what "
                         "the judged boxes were seen on; think first")
    ap.add_argument("--only", nargs="*", default=None,
                    help="acquisition dates to do, YYYYMMDD. Default: all of them")
    args = ap.parse_args()

    IMG.mkdir(parents=True, exist_ok=True)
    wanted = {a: q for a, q in ASKED_FOR.items()
              if args.only is None or q in args.only}
    if not wanted:
        raise SystemExit(f"nothing to do; the run holds {sorted(ASKED_FOR.values())}")

    for eid, tile in TILE.items():
        ref = NEW / tile / f"S2L3Ax10_{tile}-20260828_MS.tif"
        if not ref.exists():
            raise SystemExit(f"the 2026-10 run is not where this expects it: {ref}")
        with rasterio.open(ref) as r:
            bounds_utm = r.bounds
            bounds_ll = rasterio.warp.transform_bounds(r.crs, "EPSG:4326", *r.bounds)
        for asked, acq in sorted(wanted.items(), key=lambda kv: kv[1]):
            note = "" if asked == acq else f"  (the run called it {asked})"
            print(f"{eid} {acq}{note}")
            s2dr4_chips(eid, tile, asked, acq, args.dry_run, args.force)
            native_chips(eid, bounds_utm, bounds_ll, acq, args.dry_run)
    return 0


if __name__ == "__main__":
    import rasterio.warp  # noqa: F401  - only needed in main()
    sys.exit(main())
