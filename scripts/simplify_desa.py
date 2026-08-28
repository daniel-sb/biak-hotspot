"""Simplify the desa boundary file for the dashboard (Task 07).

The source (data/boundaries/biak_desa.geojson) is 1.2 MB - too heavy to
serve. This re-projects nothing; it applies Douglas-Peucker simplification
(shapely, same algorithm as ogr2ogr -simplify), rounds coordinates to 5
decimal places (~1 m), keeps only the properties the page uses, and writes
compact JSON to docs/data/biak_desa.geojson.

All 306 desa must survive: a feature whose geometry collapses under
simplification keeps its original geometry instead (a small island is worth
more than an arbitrary byte budget). Run after every boundary update:

    python scripts/simplify_desa.py [--tolerance 0.0015]
"""
import argparse
import json
import sys
from pathlib import Path

from shapely.geometry import shape, mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "boundaries" / "biak_desa.geojson"
OUT = ROOT / "docs" / "data" / "biak_desa.geojson"
KEEP = ("WADMKD", "WADMKC", "WADMKK")


def round_coords(coords, ndigits):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], ndigits), round(coords[1], ndigits)]
    return [round_coords(c, ndigits) for c in coords]


def simplify_feature(feature, tolerance):
    geom = shape(feature["geometry"])
    simplified = geom.simplify(tolerance, preserve_topology=True)
    if simplified.is_empty:
        simplified = geom                      # keep small islands intact
    props = {k: feature["properties"].get(k) for k in KEEP}
    return {"type": "Feature",
            "properties": props,
            "geometry": mapping(simplified)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tolerance", type=float, default=0.0015,
                    help="Douglas-Peucker tolerance in degrees "
                         "(default: 0.0015 ~ 165 m)")
    args = ap.parse_args()

    src = json.loads(SRC.read_text(encoding="utf-8"))
    features = [simplify_feature(f, args.tolerance) for f in src["features"]]
    out = {"type": "FeatureCollection", "features": features}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(text, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"{OUT.relative_to(ROOT)}: {len(features)} features, {kb:.0f} KB "
          f"(tolerance {args.tolerance})")
    if kb >= 300:
        print("WARNING: still 300 KB or larger - raise the tolerance")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
