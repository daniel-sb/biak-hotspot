"""Offline checks for the stale pre-look audit (Task 28).

The dates are synthetic; the real-input test reads the tracked files only
and skips when data/processed/burned_areas.json is absent. No Earth Engine
and no network.

    python -m pytest tests/test_pre_look_staleness.py
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pre_look_staleness as pls  # noqa: E402

FIRST = date(2026, 8, 19)
PRE = date(2026, 8, 10)


def test_direction_is_strict_on_both_sides():
    assert pls.direction(date(2026, 8, 5), PRE, FIRST) == "scar_in_pre"
    assert pls.direction(date(2026, 8, 15), PRE, FIRST) == \
        "earlier_burn_included"
    assert pls.direction(None, PRE, FIRST) == "no_prior_detection"
    # A detection exactly on the pre look date is not before it, and a
    # detection on first_seen is not before the event.
    assert pls.direction(PRE, PRE, FIRST) == "no_prior_detection"
    assert pls.direction(FIRST, PRE, FIRST) == "no_prior_detection"


def test_p50_and_p90_are_independent_and_differing_is_reported():
    p50 = date(2026, 8, 10)
    p90 = date(2026, 8, 15)
    d = date(2026, 8, 12)
    got = pls.classify(d, p50, p90, FIRST)
    assert got == ("earlier_burn_included", "scar_in_pre", True)

    same = pls.classify(date(2026, 8, 5), p50, p90, FIRST)
    assert same == ("scar_in_pre", "scar_in_pre", False)


def test_prior_rows_exclude_members_and_are_strictly_before_the_wit_day():
    det = pd.DataFrame([
        # the event's own member, inside and before: excluded
        {"detection_id": "m1", "acq_date_d": date(2026, 8, 15),
         "latitude": 0.005, "longitude": 0.005, "frp": 10.0,
         "confidence": "h"},
        # non-member, inside, before: included
        {"detection_id": "p1", "acq_date_d": date(2026, 8, 15),
         "latitude": 0.005, "longitude": 0.005, "frp": 5.0,
         "confidence": "n"},
        # non-member, inside, on first_seen's WIT day: excluded
        {"detection_id": "p2", "acq_date_d": FIRST,
         "latitude": 0.005, "longitude": 0.005, "frp": 7.0,
         "confidence": "l"},
        # non-member, outside: excluded
        {"detection_id": "p3", "acq_date_d": date(2026, 8, 15),
         "latitude": 0.02, "longitude": 0.02, "frp": 9.0,
         "confidence": "h"},
        # non-member, inside, one day earlier: included
        {"detection_id": "p4", "acq_date_d": date(2026, 8, 18),
         "latitude": 0.006, "longitude": 0.006, "frp": 3.0,
         "confidence": "n"},
    ])
    rows = pls.prior_rows(det, {"m1"}, box(0, 0, 0.01, 0.01), FIRST)
    assert {r.detection_id for r in rows} == {"p1", "p4"}


def test_latest_prior_uses_the_strongest_frp_on_the_latest_day():
    det = pd.DataFrame([
        {"detection_id": "a", "acq_date_d": date(2026, 8, 15),
         "latitude": 0.005, "longitude": 0.005, "frp": 4.0,
         "confidence": "n"},
        {"detection_id": "b", "acq_date_d": date(2026, 8, 15),
         "latitude": 0.006, "longitude": 0.006, "frp": 12.0,
         "confidence": "h"},
        {"detection_id": "c", "acq_date_d": date(2026, 8, 14),
         "latitude": 0.007, "longitude": 0.007, "frp": 20.0,
         "confidence": "l"},
    ])
    rows = pls.prior_rows(det, set(), box(0, 0, 0.01, 0.01), FIRST)
    d, frp, confidence, n = pls.latest_prior(rows)
    assert d == date(2026, 8, 15)
    assert frp == 12.0 and confidence == "h" and n == 2


def test_pre_look_dates_are_utc_then_wit():
    utc, wit = pls.pre_look_dates("2026-08-19T03:47:00Z", 12.2)
    assert utc == date(2026, 8, 6)
    assert wit == date(2026, 8, 7)


def test_real_inputs_have_23_assessed_and_the_seven_stale_events():
    if not pls.BURNED.exists():
        print("SKIP: burned_areas.json not present")
        return
    footprint_m, pre_days, radius_m = pls.load_config()
    doc = pls.build(footprint_m, pre_days, radius_m)

    assert doc["counts"]["assessed"] == 23
    assert doc["counts"]["no_local_reference"] == 8
    assert doc["counts"]["not_assessed"] == 457
    assert len(doc["events"]) == 23
    assert len(doc["no_local_reference"]) == 8
    assert {r["status"] for r in doc["no_local_reference"]} == {
        "no local reference"}
    assert all(r["changed_ha"] is None
               for r in doc["no_local_reference"])

    stale = doc["stale_pre_look_check"]
    assert stale["count"] == 7
    assert stale["changed_ha_total"] == 620.66
    assert set(stale["event_ids"]) == {
        "E0371", "E0322", "E0311", "E0079", "E0361", "E0315", "E0373"}

    for row in doc["events"]:
        assert row["pre_look_date_is_estimated"] is True
        assert row["direction_p50"] in pls.DIRECTIONS
        assert row["direction_p90"] in pls.DIRECTIONS
    assert doc["post_lag_check"]["count"] == 0
    assert doc["post_lag_check"]["p50_max_days"] < 14
    assert sum(g["n"] for g in doc["group_totals"].values()) == 23


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))