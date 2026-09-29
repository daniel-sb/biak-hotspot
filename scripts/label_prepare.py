"""Prepare the hand-labelling package: 1 m imagery, strata and a blank label layer.

Run in the `geolibre` conda environment:

    python scripts/label_prepare.py

Writes under data/labels/:
    imagery/<event>_swir.tif   B12/B8A/B4 from S2DR4, 2-98% stretch, 8-bit
    imagery/<event>_tci.tif    S2DR4 true colour
    biak_labels.gpkg           detections, footprints, samples, labels (empty)

**The dNBR+ polygons are deliberately absent.** These labels exist to judge the
dNBR+ product, so the person drawing them must not see it first. The strata come
from the VIIRS footprints instead, which are independent of any Sentinel-2
threshold.

Sampling: `n_per_stratum` points inside the footprint union and the same number
outside it but on land within the tile, at least `min_sep_m` apart, from a fixed
seed so the same sample can be drawn again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform as shp_transform, unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import events as ev  # noqa: E402
import burned_area_gee as ba  # noqa: E402

TILES = ROOT / "data/raw/s2dr4_biak_2026-08-28/output/ID/T53MPU"
TILE = {"E0301": "T53MPU-4e09bbfee", "E0313": "T53MPU-0c59f172e", "E0368": "T53MPU-c501689c0"}
OUT = ROOT / "data/labels"
IMG = OUT / "imagery"
GPKG = OUT / "biak_labels.gpkg"
UTM = "EPSG:32753"
# S2DR4 writes its ten bands as B2 B3 B4 B8 B5 B6 B7 B11 B12 B8A - the four 10 m
# bands first, then the 20 m ones - and labels none of them. Checked on 2026-09-29
# against native Sentinel-2 medians over water, canopy and burnt ground for the same
# date and tile: band 9 matches B12 to 5%, band 8 matches B11 to 7%, band 10 matches
# B8A. Reading them in the documented Sentinel-2 order puts NIR in the red channel,
# which is why an earlier version of this composite showed vegetation orange.
SWIR_BANDS = [9, 10, 3]          # B12, B8A, B4
REFLECTANCE_CEILING = 0.40       # fixed for all three channels
N_PER_STRATUM = 7                # 7 in + 7 out per event = 42 polygons
MIN_SEP_M = 150.0                # neighbouring pixels are correlated; keep samples apart
SEED = 20260928

to_utm = Transformer.from_crs("EPSG:4326", UTM, always_xy=True).transform
to_ll = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True).transform


def stretch_to_byte(band: np.ndarray) -> np.ndarray:
    """One fixed scale for every channel. A per-band percentile stretch rescales each
    band independently, which destroys the relation between them: over a scene that is
    mostly vegetation it blows a narrow SWIR range up to full red and inverts how a
    burn scar reads."""
    return np.clip(band / 10000.0 / REFLECTANCE_CEILING * 255, 0, 255).astype("uint8")


def write_imagery(eid: str, tile: str) -> tuple[dict, box]:
    """SWIR and true-colour 8-bit copies of the S2DR4 tile; returns its profile
    and footprint rectangle in UTM."""
    ms = TILES / tile / f"S2L3Ax10_{tile}-20260828_MS.tif"
    with rasterio.open(ms) as r:
        prof = r.profile.copy()
        a = r.read(indexes=SWIR_BANDS).astype("float32")
        bounds = r.bounds
    prof.update(count=3, dtype="uint8", nodata=None, compress="deflate",
            tiled=True, blockxsize=512, blockysize=512)
    with rasterio.open(IMG / f"{eid}_swir.tif", "w", **prof) as w:
        w.write(np.stack([stretch_to_byte(b) for b in a]))

    tci = TILES / tile / f"S2L3Ax10_{tile}-20260828_TCI.tif"
    with rasterio.open(tci) as r:
        a = r.read()[:3].astype("uint8")
    with rasterio.open(IMG / f"{eid}_tci.tif", "w", **prof) as w:
        w.write(a)
    return prof, box(*bounds)


def sample_points(rng, region, n, min_sep_m, tries=20000):
    """Random points inside `region` (UTM metres), at least min_sep_m apart."""
    minx, miny, maxx, maxy = region.bounds
    picked: list[Point] = []
    for _ in range(tries):
        if len(picked) == n:
            break
        p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if not region.contains(p):
            continue
        if any(p.distance(q) < min_sep_m for q in picked):
            continue
        picked.append(p)
    if len(picked) < n:
        print(f"   only {len(picked)} of {n} points fitted with {min_sep_m} m separation")
    return picked


def main() -> int:
    IMG.mkdir(parents=True, exist_ok=True)
    import geopandas as gpd

    doc = json.loads((ROOT / "data/processed/events.json").read_text(encoding="utf-8"))
    mem = ev.membership(doc)
    store = pd.read_parquet(ROOT / "data/processed/detections.parquet")
    land = unary_union([shape(f["geometry"]) for f in json.loads(
        (ROOT / "data/boundaries/biak_desa.geojson").read_text(encoding="utf-8"))["features"]])
    land_utm = shp_transform(to_utm, land)

    rng = np.random.default_rng(SEED)
    det_rows, fp_rows, sample_rows = [], [], []
    for eid, tile in TILE.items():
        _, tile_box = write_imagery(eid, tile)
        ids = [d for d, e in mem.items() if e == eid]
        pts = store[store.detection_id.isin(ids)]
        for r in pts.itertuples():
            det_rows.append({"event_id": eid, "detection_id": r.detection_id,
                             "satellite": r.satellite, "frp": r.frp,
                             "acq_wit": r.date_wit,
                             "geometry": Point(r.longitude, r.latitude)})

        fp_geo, fp_ha = ba.footprint(pts.latitude.tolist(), pts.longitude.tolist(), 375.0)
        fp_rows.append({"event_id": eid, "footprint_ha": round(fp_ha, 1), "geometry": fp_geo})

        fp_utm = shp_transform(to_utm, fp_geo)
        inside = fp_utm.intersection(tile_box)
        outside = tile_box.intersection(land_utm).difference(fp_utm)
        print(f"{eid}: footprint {fp_ha:.0f} ha | inside-tile {inside.area / 1e4:.0f} ha | "
              f"outside-on-land {outside.area / 1e4:.0f} ha")

        for stratum, region in (("inside_footprint", inside), ("outside_footprint", outside)):
            for i, p in enumerate(sample_points(rng, region, N_PER_STRATUM, MIN_SEP_M), 1):
                lon, lat = to_ll(p.x, p.y)
                sample_rows.append({
                    "sample_id": f"{eid}-{'IN' if stratum.startswith('inside') else 'OUT'}{i:02d}",
                    "event_id": eid, "stratum": stratum,
                    "geometry": Point(lon, lat)})

    gpd.GeoDataFrame(det_rows, crs="EPSG:4326").to_file(GPKG, layer="detections", driver="GPKG")
    gpd.GeoDataFrame(fp_rows, crs="EPSG:4326").to_file(GPKG, layer="footprints", driver="GPKG")
    samples = gpd.GeoDataFrame(sample_rows, crs="EPSG:4326")
    samples.to_file(GPKG, layer="samples", driver="GPKG")

    labels = gpd.GeoDataFrame(
        {"sample_id": pd.Series(dtype="str"), "event_id": pd.Series(dtype="str"),
         "class": pd.Series(dtype="str"), "confidence": pd.Series(dtype="str"),
         "notes": pd.Series(dtype="str"), "drawn_on": pd.Series(dtype="str")},
        geometry=gpd.GeoSeries([], crs="EPSG:4326"))
    labels.to_file(GPKG, layer="labels", driver="GPKG")

    print(f"\n{len(det_rows)} detections, {len(fp_rows)} footprints, {len(samples)} samples")
    print(f"gpkg  {GPKG}")
    print(f"images {IMG}")
    print("next: build the project with QGIS's own python:")
    print('  "C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" '
          "scripts/label_qgis_project.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
