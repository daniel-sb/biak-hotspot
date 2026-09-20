"""Offline checks for the burned-area postmortem (Task 18).

Earth Engine is not reachable from a test, so this covers the parts that do
not need it: which events are assessed, the footprint geometry, the
land-cover year rule, the look windows, the bounds arithmetic, and the
refusal to invent a threshold when the reference ring is too small.

    python -m pytest tests/test_burned_area.py
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import burned_area_gee as ba  # noqa: E402

DEG = 1.0 / ba.M_PER_DEG      # one metre of latitude, in degrees


def test_only_events_above_the_size_bar_are_assessed_and_the_rest_are_named():
    doc = {"events": [{"event_id": "E0002", "n_detections": 9},
                      {"event_id": "E0001", "n_detections": 4},
                      {"event_id": "E0003", "n_detections": 5}]}
    chosen, skipped = ba.select_events(doc, 5)
    assert [e["event_id"] for e in chosen] == ["E0002", "E0003"]
    assert [s["event_id"] for s in skipped] == ["E0001"]
    assert "fewer than 5" in skipped[0]["reason"]


def test_footprint_merges_overlapping_circles_and_measures_them():
    """Two detections 200 m apart are one plot, not two: their 375 m
    circles overlap, so the union is smaller than two separate circles."""
    one, area_one = ba.footprint([-1.1], [136.0], 375.0)
    assert math.isclose(area_one, math.pi * 375 ** 2 / 1e4, rel_tol=0.01)

    pair, area_pair = ba.footprint([-1.1, -1.1 - 200 * DEG], [136.0, 136.0],
                                   375.0)
    assert area_one < area_pair < 2 * area_one
    assert pair.contains(one.centroid)
    # 200 m south of the first centre is inside the union.
    from shapely.geometry import Point
    assert pair.contains(Point(136.0, -1.1 - 200 * DEG))


def test_footprint_circles_are_round_on_the_ground_not_in_degrees():
    """Buffering in raw degrees would stretch east-west. A point 370 m east
    of the centre must be inside; one 380 m east must not."""
    from shapely.geometry import Point
    geo, _ = ba.footprint([-1.1], [136.0], 375.0)
    kx = ba.M_PER_DEG * math.cos(math.radians(-1.1))
    assert geo.contains(Point(136.0 + 370 / kx, -1.1))
    assert not geo.contains(Point(136.0 + 380 / kx, -1.1))


def test_land_cover_is_the_year_before_the_event():
    assert ba.land_cover_year("2026-08-19T12:47:00+09:00") == 2025
    assert ba.land_cover_year("2026-01-02T12:47:00+09:00") == 2025
    assert ba.land_cover_year("2023-11-30T13:00:00+09:00") == 2022


def test_windows_exclude_the_days_the_event_was_seen():
    event = {"first_seen_utc": "2026-08-19T03:47:00Z",
             "last_seen_utc": "2026-08-25T04:04:00Z"}
    pre_s, pre_e, post_s, post_e = ba.windows(event, 60, 30)
    assert (pre_s, pre_e) == ("2026-06-20", "2026-08-19")
    assert (post_s, post_e) == ("2026-08-26", "2026-09-25")


def test_bounds_publish_the_cloud_gap_and_the_false_alarm_allowance():
    got = ba.bounds(changed_ha=40.0, clear_ha=100.0, footprint_ha=160.0,
                    quantile=0.99)
    assert got["clear_fraction"] == 0.625
    assert got["expected_false_ha"] == 1.0          # 1% of the clear area
    assert got["changed_ha_upper"] == 100.0         # 40 + the 60 ha gap


def test_a_ring_too_small_gets_no_threshold_and_no_borrowed_one():
    stats = {"dn_count": 2499, "dn_p99": 0.21}
    t, reason = ba.reference_threshold(stats, 0.99, 2500)
    assert t is None and reason == "no local reference"

    t, reason = ba.reference_threshold({"dn_count": 2500, "dn_p99": 0.21},
                                       0.99, 2500)
    assert reason is None and t == 0.21

    # Ring pixels present but the percentile came back empty: still no area.
    t, reason = ba.reference_threshold({"dn_count": 9000, "dn_p99": None},
                                       0.99, 2500)
    assert t is None and reason == "no local reference"


def test_no_output_field_names_a_cause():
    banned = ("destroy", "deforest", "illegal", "arson", "ignition")
    text = " ".join(ba.CAVEATS).lower()
    assert not [w for w in banned if w in text]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
