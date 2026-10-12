"""Measure the Task 18 burned-area product against the hand labels.

    python scripts/label_accuracy.py

Writes data/processed/label_accuracy.json.

Two strata, two jobs. The `map_burned` boxes were drawn at random inside the
dNBR+ polygons, so they estimate how much of the mapped area really burned:
the user's accuracy, and with it a corrected area. The `random_box` boxes were
drawn from the VIIRS footprints, so they say whether burning was missed near
the events, which bounds omission there and nowhere else.

The two designs are not pooled. Their inclusion probabilities differ, and a
figure that mixes them is an accuracy of nothing.

Intervals are Wilson score intervals at 95%. They are wide, and saying so is
the point: the sample is 20 judged boxes in one stratum and 36 in the other.
"""
from __future__ import annotations

import json
import sys
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "data/labels/biak_labels.gpkg"
BURNED = ROOT / "data/processed/burned_areas.geojson"
OUT = ROOT / "data/processed/label_accuracy.json"
EVENTS = ("E0301", "E0313", "E0368")      # the events that have 1 m imagery
UTM = "EPSG:32753"
Z = 1.96


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% Wilson score interval. Exact binomial would do as well; what matters
    is not quoting a bare proportion from twenty boxes."""
    if n == 0:
        return 0.0, 0.0
    p, d = k / n, 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def main() -> int:
    import geopandas as gpd

    labels = gpd.read_file(GPKG, layer="labels").to_crs(UTM)
    burned = gpd.read_file(BURNED).to_crs(UTM)
    burned = burned[burned.event_id.isin(EVENTS)]
    mapped_ha = float(burned.union_all().area) / 1e4

    judged = labels[labels["class"] != "unsure"].copy()
    judged["map_share"] = [float(burned.intersection(g).area.sum() / g.area)
                           for g in judged.geometry]

    # user's accuracy: of the boxes drawn inside the map, how many burned
    m = judged[judged.sampling == "map_burned"]
    k, n = int((m["class"] == "burned").sum()), len(m)
    lo, hi = wilson(k, n)

    # omission near the events: footprint boxes the map does not claim
    f = judged[(judged.sampling == "random_box") & (judged.map_share < 0.5)]
    missed, n_f = int((f["class"] == "burned").sum()), len(f)
    o_lo, o_hi = wilson(missed, n_f)

    doc = {
        "what": ("The Task 18 dNBR+ product measured against hand labels on 1 m imagery, "
                 f"over {len(EVENTS)} events: {', '.join(EVENTS)}."),
        "mapped_area_ha": round(mapped_ha, 1),
        "users_accuracy": {
            "stratum": "map_burned", "burned": k, "judged": n,
            "estimate": round(k / n, 3) if n else None,
            "ci95": [round(lo, 3), round(hi, 3)],
        },
        "corrected_area_ha": {
            "estimate": round(mapped_ha * k / n, 1) if n else None,
            "ci95": [round(mapped_ha * lo, 1), round(mapped_ha * hi, 1)],
            "mapped": round(mapped_ha, 1),
        },
        "omission_near_events": {
            "stratum": "random_box, boxes the map does not claim",
            "burned": missed, "judged": n_f,
            "estimate": round(missed / n_f, 3) if n_f else None,
            "ci95": [round(o_lo, 3), round(o_hi, 3)],
        },
        "unsure_dropped": int((labels["class"] == "unsure").sum()),
        "caveats": [
            ("The reference is one interpreter's reading of S2DR4 1 m imagery, which is "
             "model output rather than observation. These are agreement figures, not "
             "accuracy against the ground."),
            ("The corrected area covers three events of August 2026, not the 23 events "
             "F11 reports."),
            ("Omission is estimated from boxes drawn around the VIIRS footprints, so it "
             "bounds missed burning near the events and says nothing about the rest of "
             "the island."),
            ("Boxes are 60 m and the product is 20 m, so a box can hold both classes; "
             "those were judged by majority and the doubtful ones marked unsure."),
        ],
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")

    ua = doc["users_accuracy"]
    ca = doc["corrected_area_ha"]
    om = doc["omission_near_events"]
    print(f"mapped area, {len(EVENTS)} events: {mapped_ha:.0f} ha")
    print(f"user's accuracy: {ua['burned']}/{ua['judged']} = {ua['estimate']:.0%}"
          f"  95% CI {ua['ci95'][0]:.0%} to {ua['ci95'][1]:.0%}")
    print(f"corrected area:  {ca['estimate']:.0f} ha"
          f"  95% CI {ca['ci95'][0]:.0f} to {ca['ci95'][1]:.0f} ha")
    print(f"omission near the events: {om['burned']}/{om['judged']}"
          f"  95% CI {om['ci95'][0]:.0%} to {om['ci95'][1]:.0%}")
    print(f"\nwritten {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
