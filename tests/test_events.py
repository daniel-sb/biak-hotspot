"""Offline checks for event clustering (Task 16).

Synthetic stores with unambiguous answers. No network, no road file: the
road distance is exercised by the real build, not here.

    python -m pytest tests/test_events.py
"""
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import events as ev  # noqa: E402

DEG = 1.0 / ev.M_PER_DEG          # one metre of latitude, in degrees
P = {"eps_m": 1000, "eps_hours": 24, "min_samples": 2}


def synth(rows):
    """rows: (detection_id, lat, lon, 'YYYY-MM-DD HH:MM' UTC)."""
    t = pd.to_datetime([r[3] for r in rows], utc=True)
    return pd.DataFrame({
        "detection_id": [r[0] for r in rows],
        "latitude": [r[1] for r in rows],
        "longitude": [r[2] for r in rows],
        "datetime_utc": t,
        "date_wit": t.tz_convert("Asia/Jayapura").strftime("%Y-%m-%d"),
        "satellite": "N20", "frp": 3.0, "desa": "Anjareuw",
        "distrik": "Samofa", "on_land": True, "recurrent_site": False,
    })


def events_of(doc):
    m = ev.membership(doc)
    return {e["event_id"]: sorted(d for d, eid in m.items()
                                  if eid == e["event_id"])
            for e in doc["events"]}


def test_space_and_time_both_have_to_be_close():
    base = ("a", -1.10, 136.0, "2026-08-21 04:00")
    near = ev.build(synth([base, ("b", -1.10 - 800 * DEG, 136.0,
                                  "2026-08-21 14:00")]), P)
    assert len(near["events"]) == 1
    far = ev.build(synth([base, ("b", -1.10 - 1200 * DEG, 136.0,
                                 "2026-08-21 14:00")]), P)
    assert len(far["events"]) == 2
    late = ev.build(synth([base, ("b", -1.10, 136.0, "2026-08-22 10:00")]), P)
    assert len(late["events"]) == 2


def test_consecutive_days_chain_into_one_event():
    rows = [("d%d" % i, -1.10, 136.0, "2026-08-2%d 04:30" % i)
            for i in (1, 2, 3)]
    doc = ev.build(synth(rows), P)
    assert len(doc["events"]) == 1
    e = doc["events"][0]
    assert e["n_detections"] == 3 and e["duration_hours"] == 48.0


def test_isolated_detection_is_a_singleton_not_a_dropped_row():
    doc = ev.build(synth([("a", -1.10, 136.0, "2026-08-21 04:00"),
                          ("b", -1.10, 136.0, "2026-08-21 04:10"),
                          ("lone", -1.30, 136.3, "2026-08-21 04:00")]), P)
    single = [e for e in doc["events"] if e["singleton"]]
    assert len(single) == 1 and single[0]["n_detections"] == 1


def test_every_detection_lands_in_exactly_one_event():
    rows = [("d%02d" % i, -1.10 - (i % 4) * 300 * DEG, 136.0 + (i // 4) * 0.02,
             "2026-08-%02d 04:00" % (20 + i % 3)) for i in range(24)]
    doc = ev.build(synth(rows), P)
    assert sorted(ev.membership(doc)) == sorted(r[0] for r in rows)
    assert sum(e["n_detections"] for e in doc["events"]) == len(rows)


def test_growth_keeps_the_id():
    rows = [("a", -1.10, 136.0, "2026-08-21 04:00"),
            ("b", -1.10, 136.0, "2026-08-21 05:00"),
            ("x", -1.30, 136.3, "2026-08-21 04:00"),
            ("y", -1.30, 136.3, "2026-08-21 05:00")]
    first = ev.build(synth(rows), P)
    eid = ev.membership(first)["a"]
    grown = ev.build(synth(rows + [("c", -1.10, 136.0, "2026-08-22 03:00")]),
                     P, prior=first)
    g = ev.membership(grown)
    assert g["c"] == eid and g["a"] == eid
    assert g["x"] == ev.membership(first)["x"]


def test_merge_keeps_the_larger_id_and_never_reuses_the_other():
    big = [("b%d" % i, -1.10, 136.0, "2026-08-21 0%d:00" % i) for i in range(3)]
    small = [("s%d" % i, -1.10 - 1400 * DEG, 136.0, "2026-08-21 0%d:00" % i)
             for i in range(2)]
    first = ev.build(synth(big + small), P)
    big_id = ev.membership(first)["b0"]
    small_id = ev.membership(first)["s0"]
    assert big_id != small_id

    bridge = ("m", -1.10 - 700 * DEG, 136.0, "2026-08-21 01:30")
    merged = ev.build(synth(big + small + [bridge]), P, prior=first)
    assert ev.membership(merged)["s0"] == big_id
    assert merged["retired"][small_id] == {"merged_into": big_id}

    later = ev.build(synth(big + small + [bridge,
                                          ("z", -1.40, 136.4,
                                           "2026-08-25 04:00")]),
                     P, prior=merged)
    assert ev.membership(later)["z"] not in (small_id, big_id)


def test_changing_parameters_rebuilds_and_says_so():
    rows = [("a", -1.10, 136.0, "2026-08-21 04:00")]
    first = ev.build(synth(rows), P)
    again = ev.build(synth(rows), dict(P, eps_hours=30), prior=first)
    assert again["registry_version"] == first["registry_version"] + 1
    assert again["notes"]


def test_same_input_writes_identical_bytes():
    rows = [("a", -1.10, 136.0, "2026-08-21 04:00"),
            ("b", -1.10, 136.0, "2026-08-21 05:00"),
            ("c", -1.30, 136.3, "2026-08-22 04:00")]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        ev.write(ev.build(synth(rows), P), out)
        one = (out / "events.json").read_bytes()
        ev.write(ev.build(synth(list(reversed(rows))), P), out)
        assert (out / "events.json").read_bytes() == one
        json.loads(one)


def test_no_field_claims_ignition():
    doc = ev.build(synth([("a", -1.10, 136.0, "2026-08-21 04:00")]), P)
    assert not [k for k in doc["events"][0] if "ignit" in k]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
