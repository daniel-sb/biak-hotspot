"""Export the vector layers the web map needs: detections, roads, boundaries.

    "$CONDA/envs/geolibre/python.exe" scripts/export_vector_layers.py
    "$CONDA/envs/geolibre/python.exe" scripts/export_vector_layers.py --check

Outputs, all overwritten on every run:

    docs/data/detections.geojson   the whole detection store, date-filterable
    docs/data/roads.geojson        OpenStreetMap roads, rounded
    docs/data/admin_lines.geojson  kabupaten / distrik / desa boundary lines

WHY THE DETECTIONS ARE HERE AT ALL

docs/data/hotspots_latest.geojson is a seven-day rolling window. In a quiet
week that is two points, so the front page said "905 detections in 312 events"
above a map showing two dots, and the honest reading of that map was that the
layer had failed. It had not: it was doing what it was built for, which is the
status strip, not the record of a season.

This writes the whole store - every detection the project holds, 2023 onward -
so the map can show the season the page is about. The seven-day file stays as
it is, because the status strip and the brief are about now.

WHY THE BOUNDARIES ARE THREE LAYERS

SNI 6502.2:2010 Lampiran A(e) gives a different line for each administrative
level, and section 6.3 says that where two boundaries coincide the lower level
is left undrawn. A desa edge that is also a distrik edge is therefore a distrik
line here, and a distrik edge that is also the kabupaten edge is a kabupaten
line. That is done by subtracting the higher level from the lower, which is
what this script spends most of its time on.

The same section says in as many words that administrative boundaries on a
rupabumi map are not an official reference. The methodology page repeats it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PROCESSED = ROOT / "data" / "processed"
BOUNDARIES = ROOT / "data" / "boundaries"

# Five decimal places is about 1 m at this latitude, finer than any source
# here and a third of the bytes of the raw float.
NDIGITS = 5

# A boundary shared between two units is one line, not two stacked; buffering
# the higher level by this much before subtracting absorbs the coordinate
# noise between two polygons that are meant to share an edge. 1e-6 degrees is
# about 0.1 m.
SHARED_EDGE_TOL = 1e-6

# What a detection popup and the date filter need. frp is never dropped and
# confidence is never cast to a number (AGENTS rules 3 and 4).
DETECTION_COLS = ["date_wit", "datetime_wit", "satellite", "instrument",
                  "confidence", "frp", "distrik", "desa", "on_land"]

# OSM highway classes, grouped for symbolisation. Anything not listed is
# dropped rather than lumped in with a class it is not.
ROAD_CLASSES = {
    "trunk": "arteri", "trunk_link": "arteri",
    "primary": "arteri", "primary_link": "arteri",
    "secondary": "kolektor", "secondary_link": "kolektor",
    "tertiary": "lokal", "tertiary_link": "lokal",
    "unclassified": "lokal", "residential": "lokal",
    "service": "lain", "track": "lain", "path": "lain", "footway": "lain",
}


def round_coords(coords, ndigits=NDIGITS):
    if coords and isinstance(coords[0], (int, float)):
        return [round(c, ndigits) for c in coords[:2]]
    return [round_coords(c, ndigits) for c in coords]


def write(path, features, **extra):
    doc = {"type": "FeatureCollection", "features": features}
    doc.update(extra)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


# ------------------------------------------------------------ detections ----

def export_detections():
    df = pd.read_parquet(PROCESSED / "detections.parquet")
    feats = []
    for row in df.itertuples(index=False):
        props = {}
        for col in DETECTION_COLS:
            value = getattr(row, col, None)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                props[col] = None
            elif col == "datetime_wit":
                props[col] = str(value)
            elif col == "confidence":
                # VIIRS returns l/n/h and MODIS 0-100 in the same column.
                props[col] = str(value)
            else:
                props[col] = value.item() if hasattr(value, "item") else value
        # The one derived field the filter needs, so the page does no date
        # parsing of its own: days since the store's first WIT day.
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [
                round(float(row.longitude), NDIGITS),
                round(float(row.latitude), NDIGITS)]},
            "properties": props,
        })
    days = sorted({f["properties"]["date_wit"] for f in feats})
    return write(DOCS / "data" / "detections.geojson", feats,
                 first_day=days[0], last_day=days[-1], count=len(feats))


# ----------------------------------------------------------------- roads ----

def export_roads():
    src = json.loads((BOUNDARIES / "biak_roads.geojson").read_text("utf-8"))
    feats, dropped = [], 0
    for f in src["features"]:
        klass = ROAD_CLASSES.get(f["properties"].get("highway"))
        if klass is None:
            dropped += 1
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": f["geometry"]["type"],
                         "coordinates": round_coords(
                             f["geometry"]["coordinates"])},
            "properties": {"kelas": klass,
                           "highway": f["properties"]["highway"]},
        })
    return write(DOCS / "data" / "roads.geojson", feats,
                 attribution="(c) OpenStreetMap contributors, ODbL",
                 dropped_classes=dropped)


# ------------------------------------------------------------ boundaries ----

def dissolve(features, key):
    """One geometry per distinct value of `key`."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    groups = {}
    for f in features:
        groups.setdefault(f["properties"][key], []).append(
            shape(f["geometry"]))
    return {k: unary_union(v) for k, v in groups.items()}


def boundary_lines(geoms):
    from shapely.ops import unary_union
    return unary_union([g.boundary for g in geoms.values()])


def export_admin_lines():
    """Three line layers, with the SNI rule that a shared edge is drawn once.

    SNI 6502.2:2010 section 6.3 and Lampiran A(e): where boundaries of two
    levels coincide the lower level is omitted, so each level here has the
    level above it subtracted before it is written.
    """
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    src = json.loads((DOCS / "data" / "biak_desa.geojson").read_text("utf-8"))
    feats = src["features"]
    kab = boundary_lines(dissolve(feats, "WADMKK"))
    dis = boundary_lines(dissolve(feats, "WADMKC"))
    desa = boundary_lines(dissolve(feats, "WADMKD"))

    # Every higher level is subtracted, not just the one above: a desa in
    # the middle of a distrik still meets the sea, and that edge is the
    # kabupaten boundary even though it is not a distrik boundary.
    dis_only = dis.difference(kab.buffer(SHARED_EDGE_TOL))
    desa_only = desa.difference(
        unary_union([kab, dis]).buffer(SHARED_EDGE_TOL))

    out = []
    for level, geom, label in (
            # On Biak this line IS the coast: Biak Numfor and Supiori are
            # separate islands and share no land boundary, so drawing it over
            # a basemap that already renders the shoreline only doubles it.
            # Kept in the data, switched off on the map.
            ("kabupaten", kab, "Batas kabupaten/kota"),
            ("distrik", dis_only, "Batas kecamatan/distrik"),
            ("desa", desa_only, "Batas kelurahan/desa")):
        if geom.is_empty:
            continue
        out.append({
            "type": "Feature",
            "geometry": {
                "type": mapping(geom)["type"],
                "coordinates": round_coords(mapping(geom)["coordinates"]),
            },
            "properties": {"level": level, "label": label},
        })
    return write(DOCS / "data" / "admin_lines.geojson", out,
                 source="SNI 6502.2:2010 Lampiran A(e); boundaries on a "
                        "rupabumi map are not an official reference "
                        "(SNI 6502.2:2010 section 6.3).")


# ----------------------------------------------------------------- check ----

def demo():
    det = json.loads((DOCS / "data" / "detections.geojson").read_text("utf-8"))
    store = pd.read_parquet(PROCESSED / "detections.parquet")
    assert len(det["features"]) == len(store), \
        f"{len(det['features'])} published vs {len(store)} in the store"
    assert det["count"] == len(store)
    years = {f["properties"]["date_wit"][:4] for f in det["features"]}
    assert len(years) >= 3, f"only {years} on the map"
    for f in det["features"][:50]:
        p = f["properties"]
        assert "frp" in p, "frp dropped"
        assert isinstance(p["confidence"], str), \
            "confidence cast away from its raw instrument code"
    # The seven-day file still exists and is still the smaller thing: the
    # status strip reads it, and swapping the two would put a three-year
    # record behind a sentence about this week.
    latest = json.loads(
        (DOCS / "data" / "hotspots_latest.geojson").read_text("utf-8"))
    assert len(latest["features"]) < len(det["features"])

    roads = json.loads((DOCS / "data" / "roads.geojson").read_text("utf-8"))
    assert roads["features"], "no roads"
    classes = {f["properties"]["kelas"] for f in roads["features"]}
    assert {"arteri", "kolektor", "lokal"} <= classes, classes

    from shapely.geometry import shape

    adm = json.loads((DOCS / "data" / "admin_lines.geojson").read_text("utf-8"))
    levels = [f["properties"]["level"] for f in adm["features"]]
    assert levels == ["kabupaten", "distrik", "desa"], levels
    # The SNI rule: a shared edge belongs to the higher level only, so the
    # desa layer must be shorter than the raw desa boundary it came from.
    desa_len = shape(adm["features"][2]["geometry"]).length
    raw = json.loads((DOCS / "data" / "biak_desa.geojson").read_text("utf-8"))
    full = boundary_lines(dissolve(raw["features"], "WADMKD")).length
    assert desa_len < full, "nothing was subtracted; shared edges drawn twice"

    print(f"detections: {len(det['features'])} over {sorted(years)}")
    print(f"roads: {len(roads['features'])} in {sorted(classes)}")
    print(f"admin lines: {levels}, desa {desa_len:.3f} of {full:.3f} degrees")
    print("all assertions passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="assert the existing output, write nothing")
    ap.add_argument("--only", choices=("detections", "roads", "admin"),
                    help="rebuild one layer. The daily job passes "
                         "'detections', because that is the only one of the "
                         "three whose input changes: roads and boundaries "
                         "come from files that a scheduled run must never "
                         "rewrite.")
    args = ap.parse_args()
    if args.check:
        demo()
        return 0
    steps = {"detections": export_detections, "roads": export_roads,
             "admin": export_admin_lines}
    chosen = [steps[args.only]] if args.only else list(steps.values())
    for fn in chosen:
        path = fn()
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1e6:.2f} MB")
    if not args.only:
        demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
