"""Check the hand-drawn labels before they are used as a reference (Task 22).

    python scripts/label_check.py

Reads data/labels/biak_labels.gpkg and reports what is there and what is wrong.
It changes nothing, and it never judges a label's class - only whether the
record is usable: one polygon per sample, the polygon holding its own point, a
sensible area, and the required fields filled in.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "data/labels/biak_labels.gpkg"
UTM = "EPSG:32753"
MIN_HA, MAX_HA = 0.1, 10.0          # a 20 m pixel is 0.04 ha; 10 ha is rarely uniform
CLASSES = {"burned", "unburned", "unsure"}
CONFIDENCE = {"high", "medium", "low"}


def main() -> int:
    import geopandas as gpd

    if not GPKG.exists():
        raise SystemExit(f"missing {GPKG}; run scripts/label_prepare.py first")

    samples = gpd.read_file(GPKG, layer="samples")
    labels = gpd.read_file(GPKG, layer="labels")
    # Two strata, checked differently. The footprint boxes each sit on a sample
    # point; the map stratum was drawn inside the dNBR+ polygons and has none.
    if "sampling" not in labels.columns:
        labels["sampling"] = "random_box"
    mapped = labels[labels.sampling == "map_burned"]
    labels = labels[labels.sampling != "map_burned"].copy()
    print(f"{len(labels)} footprint boxes of {len(samples)} sample points, "
          f"{len(mapped)} map-stratum boxes\n")
    if len(mapped):
        done = int(mapped["class"].notna().sum())
        print("map stratum:", mapped["class"].value_counts(dropna=False).to_dict(),
              f"({done} of {len(mapped)} judged)\n")
    if labels.empty:
        print("nothing drawn yet — open data/labels/biak_labels.qgz and see HOWTO.md")
        return 0

    problems: list[str] = []

    # one polygon per sample, and no stray ids
    drawn = [s for s in labels.sample_id.fillna("") if s]
    missing_id = int(labels.sample_id.isna().sum() + (labels.sample_id == "").sum())
    if missing_id:
        problems.append(f"{missing_id} polygons have no sample_id")
    unknown = sorted(set(drawn) - set(samples.sample_id))
    if unknown:
        problems.append(f"sample_id not in the sample list: {', '.join(unknown)}")
    duplicated = sorted({s for s in drawn if drawn.count(s) > 1})
    if duplicated:
        problems.append(f"more than one polygon for: {', '.join(duplicated)}")

    # each polygon should contain its own point
    pt = samples.set_index("sample_id").geometry
    for row in labels.itertuples():
        sid = getattr(row, "sample_id", None)
        if sid in pt.index and not row.geometry.contains(pt[sid]):
            problems.append(f"{sid}: the polygon does not contain its sample point")

    # areas, measured on the local UTM grid
    areas = labels.to_crs(UTM).area / 1e4
    for sid, ha in zip(labels.sample_id, areas):
        if ha < MIN_HA or ha > MAX_HA:
            problems.append(f"{sid}: {ha:.2f} ha, outside the {MIN_HA}-{MAX_HA} ha guide")

    # required fields
    for field, allowed in (("class", CLASSES), ("confidence", CONFIDENCE)):
        bad = sorted(set(labels[field].dropna()) - allowed)
        if bad:
            problems.append(f"{field}: unexpected values {bad}")
        blank = int(labels[field].isna().sum())
        if blank:
            problems.append(f"{field}: {blank} polygons left empty")

    # what has been judged, by stratum
    merged = labels.merge(samples[["sample_id", "stratum"]], on="sample_id", how="left")
    print(merged.groupby(["stratum", "class"]).size().to_string(), "\n")
    print(f"median polygon {areas.median():.2f} ha, "
          f"smallest {areas.min():.2f}, largest {areas.max():.2f}")
    usable = int((merged["class"] != "unsure").sum())
    print(f"{usable} usable polygons, {int((merged['class'] == 'unsure').sum())} marked unsure")

    left = sorted(set(samples.sample_id) - set(drawn))
    if left:
        print(f"\nstill to draw ({len(left)}): {', '.join(left)}")

    if problems:
        print("\nproblems:")
        for p in problems:
            print(" -", p)
        return 1
    print("\nno problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
