"""Task 15 checks on burn_indices.json.

The two places a later edit could silently reintroduce the errors this
task's revision exists to remove are asserted directly: the hotspot-
adjacent stratum must be built only from detections earlier than the post
scene (recounted here from the detections store), and the cloud stratum
must record which scene and date it came from, that date differing from
the primary post-image. Plus the file's internal consistency: the four
strata disjoint and non-empty, every distribution ordered, the recorded
reflectance range consistent with scaled surface reflectance rather than
raw integers.

The file is written by a by-hand Earth Engine run; skip cleanly when it
is absent, the way the task 11-14 checks do.

Run with pytest:
    python -m pytest tests/test_burn_indices.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BI = ROOT / "docs" / "data" / "burn_indices.json"
DET = ROOT / "data" / "processed" / "detections.parquet"
STATS = ("min", "p5", "p25", "p50", "p75", "p95", "max")


def test_burn_indices_internal_consistency():
    if not BI.exists():
        print("SKIP: burn_indices.json not present")
        return
    doc = json.loads(BI.read_text(encoding="utf-8"))

    # the four strata: disjoint and non-empty, on both scene pairs
    for pair in ("primary", "check"):
        counts = doc["strata"][pair]
        for s in ("water", "cloud", "adjacent", "far"):
            assert counts[s]["n"] > 0, (pair, s, "empty stratum")
        overlaps = doc["strata"][f"overlaps_{pair}"]
        assert overlaps, (pair, "no overlap record")
        for k, v in overlaps.items():
            a, b = k.split("__")
            assert a != b and v == 0, (pair, k, v)

    # every recorded distribution ordered, non-empty
    for block in ("indices_primary", "indices_check",
                  "indices_check_late_burning"):
        for form in doc.get(block, {}).values():
            for index_dists in form.values():
                for dist in index_dists.values():
                    vals = [dist[s] for s in STATS]
                    assert vals == sorted(vals), vals
                    assert dist["n"] > 0

    # reflectance range: scaled SR, not raw integers. Bright cloud tops
    # in S2 L2A legitimately exceed 1.0 (measured 2.17 on the 2026-08-28
    # scene), so the ceiling is 4 - raw integer counts (~1e4) fail it.
    for scene, rng in doc["reflectance_range"].items():
        for band, (lo, hi) in rng.items():
            assert -0.1 <= lo <= hi <= 4.0, (scene, band, lo, hi)

    # false-alarm shares are shares
    for pair in ("primary", "check"):
        for form in doc[f"false_alarm_{pair}"].values():
            for shares in form.values():
                for v in shares.values():
                    assert 0 <= v <= 1, (pair, v)


def test_adjacent_stratum_only_earlier_detections():
    """The hotspot-adjacent stratum must exclude every detection on or
    after the post scene: recount from the detections store and compare
    with what the file recorded."""
    if not BI.exists():
        print("SKIP: burn_indices.json not present")
        return
    doc = json.loads(BI.read_text(encoding="utf-8"))
    det = pd.read_parquet(DET)
    ev = det[(det.date_wit >= "2026-08-19") & (det.date_wit <= "2026-08-25")
             & det.on_land]
    for pair in ("primary", "check"):
        src = doc["strata"][f"{pair}_adjacent_source"]
        post = src["post_scene_date"]
        assert src["detection_date_range"][1] < post, (pair, src)
        want = int((ev.date_wit < post).sum())
        assert src["detections_used"] == want, \
            (pair, src["detections_used"], want)
    # the detections the primary post-image cannot show are exactly the
    # late-burning set the check pair exists for
    prim = doc["strata"]["primary_adjacent_source"]
    late = doc["strata"]["check_adjacent_source"]
    assert prim["detections_excluded_on_or_after_post_date"] == \
        late["late_burning_detections"]


def test_cloud_stratum_records_its_scene():
    """The cloud stratum comes from a different date than the primary
    post-image, and the file must say which scene and date, not hide the
    seam."""
    if not BI.exists():
        print("SKIP: burn_indices.json not present")
        return
    doc = json.loads(BI.read_text(encoding="utf-8"))
    cov = doc["coverage"]
    assert cov["cloud_stratum_scene"], "cloud stratum scene not recorded"
    assert cov["cloud_stratum_date"] == "2026-08-28"
    assert cov["cloud_stratum_date"] != \
        doc["strata"]["primary_adjacent_source"]["post_scene_date"]
    assert cov["cloud_stratum_scl_classes"] == [3, 8, 9]


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
