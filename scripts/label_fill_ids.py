"""Fill sample_id and event_id on drawn polygons from the sample point each contains.

    python scripts/label_fill_ids.py [--dry-run]

Close QGIS first: this rewrites the `labels` layer of data/labels/biak_labels.gpkg.

Two of the four fields are bookkeeping, not judgement, and typing them by hand is
both slow and a way to introduce mistakes. Each polygon is drawn around exactly
one sample point, so the point inside it says which sample it is. What the script
never touches is `class` and `confidence`: those are the judgement, and nothing
should guess them.

A polygon holding no point, or more than one, is reported and left alone.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "data/labels/biak_labels.gpkg"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report, change nothing")
    args = ap.parse_args()

    import geopandas as gpd

    labels = gpd.read_file(GPKG, layer="labels")
    samples = gpd.read_file(GPKG, layer="samples")
    if labels.empty:
        print("no polygons drawn yet")
        return 0

    filled, problems = 0, []
    for i, row in labels.iterrows():
        inside = samples[samples.geometry.within(row.geometry)]
        if len(inside) != 1:
            problems.append(f"row {i + 1}: contains {len(inside)} sample points, left alone")
            continue
        sid = inside.iloc[0]["sample_id"]
        eid = inside.iloc[0]["event_id"]
        if row.get("sample_id") == sid and row.get("event_id") == eid:
            continue
        if row.get("sample_id") and row["sample_id"] != sid:
            problems.append(f"row {i + 1}: says {row['sample_id']} but holds {sid}, left alone")
            continue
        labels.at[i, "sample_id"] = sid
        labels.at[i, "event_id"] = eid
        filled += 1
        print(f"row {i + 1}: {sid} ({eid})")

    print(f"\n{filled} of {len(labels)} polygons filled")
    for p in problems:
        print(" -", p)

    blank = labels[labels["class"].isna() | (labels["class"] == "")]
    if len(blank):
        ids = ", ".join(str(s) for s in blank.sample_id.fillna("?"))
        print(f"\nstill need a class ({len(blank)}): {ids}")

    if args.dry_run:
        print("\ndry run, nothing written")
        return 0
    if filled:
        labels.to_file(GPKG, layer="labels", driver="GPKG")
        print(f"\nwritten to {GPKG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
