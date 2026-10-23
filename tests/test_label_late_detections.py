"""Offline checks for the late-detection lookup (Task 26).

The distance and date rules are tested on synthetic boxes and detections;
the real-input test reads the tracked GeoPackage and store only, and skips
when the GeoPackage is absent. No network, no Earth Engine, no writes to
the GeoPackage.

    python -m pytest tests/test_label_late_detections.py
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import label_late_detections as lld  # noqa: E402

CHIPS = [date(2026, 8, 13), date(2026, 8, 23)]


def one_box():
    return {
        "fid": 1,
        "sample_id": "S1",
        "event_id": "E1",
        "sampling": "random_box",
        "class": "burned",
        "notes": None,
        "geometry": box(136.0, -1.0, 136.0006, -0.9994),
    }


def one_detection(day, lat=-0.9997, lon=136.0003):
    return pd.DataFrame([{
        "acq_date": day,
        "acq_date_d": date.fromisoformat(day),
        "latitude": lat,
        "longitude": lon,
        "frp": 7.5,
        "confidence": "n",
    }])


def test_distance_inside_is_zero_and_band_inside():
    box_row = one_box()
    poly = box_row["geometry"]
    lat0, lon0, local = lld.local_box(poly)
    distance = lld.distance_to_box(poly, local, lat0, lon0,
                                   -0.9997, 136.0003)
    assert distance == 0.0
    assert lld.band(distance, 750.0) == "inside"


def test_band_edges_are_inclusive():
    assert lld.band(0.0, 750.0) == "inside"
    assert lld.band(375.0, 750.0) == "<=375"
    assert lld.band(375.01, 750.0) == "<=750"
    assert lld.band(750.0, 750.0) == "<=750"
    assert lld.band(750.01, 750.0) == "<=1500"
    assert lld.band(1500.0, 750.0) == "<=1500"
    assert lld.band(1500.01, 750.0) == ">1500"


def test_detection_on_a_chip_date_is_not_later_than_that_chip():
    record = lld.box_record(one_box(), one_detection("2026-08-23"),
                            CHIPS, 750.0)
    # Later than 13 August, so it is a late detection for that chip.
    assert record["by_chip"]["2026-08-13"]["band"] == "inside"
    assert record["by_chip"]["2026-08-13"]["acq_date"] == "2026-08-23"
    # Not later than 23 August: strictly greater.
    assert record["by_chip"]["2026-08-23"]["distance_m"] is None
    assert record["by_chip"]["2026-08-23"]["acq_date"] is None
    assert record["nearest_within_375m"]["acq_date"] == "2026-08-23"
    assert record["chips_before_nearest_within_375m"] == ["2026-08-13"]
    assert record["chips_before_latest_within_375m"] == ["2026-08-13"]


def test_no_later_detection_is_null_not_zero():
    record = lld.box_record(one_box(), one_detection("2026-08-10"),
                            CHIPS, 750.0)
    assert record["nearest_within_375m"] is None
    assert record["latest_within_375m"] is None
    assert record["chips_before_nearest_within_375m"] == []
    assert record["chips_before_latest_within_375m"] == []
    for chip in CHIPS:
        assert record["by_chip"][chip.isoformat()]["distance_m"] is None


def test_chip_dates_follow_the_imagery_and_a_seventh_file_changes_them(
        tmp_path):
    for token in ("20260813", "20260823", "20260917"):
        (tmp_path / f"E0301_swir_{token}.tif").write_bytes(b"")
    before = lld.chip_dates(tmp_path)
    assert before == [date(2026, 8, 13), date(2026, 8, 23),
                      date(2026, 9, 17)]
    (tmp_path / "E0301_swir_20261024.tif").write_bytes(b"")
    after = lld.chip_dates(tmp_path)
    assert after == before + [date(2026, 10, 24)]
    assert len(after) == 4


def test_real_inputs_have_all_boxes_and_every_chip():
    if not (ROOT / "data/labels/biak_labels.gpkg").exists():
        print("SKIP: biak_labels.gpkg not present")
        return
    box_m, gpkg, mid_m = lld.load_config()
    doc = lld.build(box_m, gpkg, mid_m)

    assert doc["counts"]["boxes_total"] == 142
    assert doc["counts"]["detections_total"] == 1166
    assert len(doc["boxes"]) == 142
    assert len(doc["parameters"]["chip_dates"]) == 6
    assert all(len(row["by_chip"]) == 6 for row in doc["boxes"])
    assert doc["counts"]["by_stratum"]["random_box"]["boxes"] == 42
    assert doc["counts"]["by_stratum"]["map_burned"]["boxes"] == 50
    assert doc["counts"]["by_stratum"]["footprint_unmapped"]["boxes"] == 50
    assert sum(c["boxes"] for c in
               doc["counts"]["by_stratum"].values()) == 142
    assert sum(c["shortlist"] for c in
               doc["counts"]["by_stratum"].values()) == \
        doc["counts"]["boxes_shortlist"]

    named = doc["named_box"]
    assert named is not None
    assert named["sample_id"] == "E0301-IN03"
    assert named["notes"] == "1709 anjereuw very obviously burned"
    assert named["latest_within_375m"] is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))