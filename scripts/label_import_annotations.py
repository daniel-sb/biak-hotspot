"""Move polygons drawn on the QGIS annotation layer into the `labels` layer.

    python scripts/label_import_annotations.py [--dry-run]

Close QGIS first: this writes to data/labels/biak_labels.gpkg.

QGIS has two polygon tools side by side. "Add Polygon Feature" writes a feature
into the editable layer; "Add Polygon Annotation" draws decoration stored in the
project file, with no attributes and no form. The second is easy to hit by
mistake, and the drawing looks identical on screen. This reads those annotations
out of the .qgz and writes them in as label features, so the work is not redone.

They come in marked `sampling = purposive`: chosen by eye because a scar was
visible there, not drawn from the random sample. Task 22 may train on them, but
the agreement figure is computed on the `random_box` rows alone - a sample picked
for being obvious measures the easy cases and nothing else.

`class` and `confidence` are left empty, as they are everywhere else: the script
knows where a polygon is, never what it shows.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QGZ = ROOT / "data/labels/biak_labels.qgz"
GPKG = ROOT / "data/labels/biak_labels.gpkg"


def annotation_polygons(qgz: Path) -> list[str]:
    """WKT of every polygon annotation item in the project."""
    with zipfile.ZipFile(qgz) as z:
        name = next(n for n in z.namelist() if n.endswith(".qgs"))
        xml = z.read(name).decode("utf-8", errors="ignore")
    # QGIS writes curve geometry even for straight rings; shapely wants Polygon.
    return [w.replace("CurvePolygon", "Polygon")
            for w in re.findall(r'<item type="polygon"[^>]*wkt="([^"]+)"', xml)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = ap.parse_args()

    import geopandas as gpd
    from shapely import wkt as shapely_wkt

    found = annotation_polygons(QGZ)
    print(f"{len(found)} polygon annotations in {QGZ.name}")
    if not found:
        print("nothing to import — save the project in QGIS first, then re-run")
        return 0

    labels = gpd.read_file(GPKG, layer="labels")
    samples = gpd.read_file(GPKG, layer="samples")

    rows = []
    for i, w in enumerate(found, 1):
        geom = shapely_wkt.loads(w)
        if any(geom.equals(g) for g in labels.geometry):
            print(f"  {i}: already in the labels layer, skipped")
            continue
        inside = samples[samples.geometry.within(geom)]
        sid = inside.iloc[0]["sample_id"] if len(inside) == 1 else None
        eid = inside.iloc[0]["event_id"] if len(inside) == 1 else None
        area_ha = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs("EPSG:32753").area.iloc[0] / 1e4
        print(f"  {i}: {area_ha:6.2f} ha  {sid or f'holds {len(inside)} sample points'}")
        rows.append({"sample_id": sid, "event_id": eid, "sampling": "purposive",
                     "class": None, "confidence": None, "notes": None,
                     "drawn_on": None, "geometry": geom})

    if not rows:
        print("nothing new to add")
        return 0
    if args.dry_run:
        print("\ndry run, nothing written")
        return 0

    out = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    if not labels.empty:
        out = gpd.GeoDataFrame(
            __import__("pandas").concat([labels.drop(columns=["fid"], errors="ignore"), out],
                                        ignore_index=True), crs="EPSG:4326")
    out.to_file(GPKG, layer="labels", driver="GPKG")
    print(f"\n{len(rows)} added, {len(out)} polygons now in the labels layer")
    print("next: fill class and confidence in the attribute table, then "
          "python scripts/label_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
