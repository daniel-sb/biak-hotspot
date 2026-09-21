"""Offline checks for Himawari-9 onset brackets (Task 20). Synthetic
arrays and state lists built inside the test; raw Himawari files are
gitignored and never read. fetch_slot_file's HTTP behaviour is checked
with requests.get replaced - no network.

Run with pytest:
    python -m pytest tests/test_himawari_onset.py
or directly (no pytest needed):
    python tests/test_himawari_onset.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import himawari_onset as ho  # noqa: E402
import himawari as hm  # noqa: E402

CLOUD = 285.0


def grids(bt14_px, flagged_px=None, anomaly_px=0.0, diff_px=20.0,
          shape=(5, 5)):
    """Synthetic segment grids for one slot: uniform B14, one pixel
    (2, 2) carrying the given flag/anomaly/diff."""
    g = {
        "bt14": np.full(shape, 295.0),
        "flagged": np.zeros(shape, dtype=bool),
        "anomaly": np.zeros(shape),
        "diff": np.full(shape, 5.0),
    }
    if bt14_px is not None:
        g["bt14"] = np.full(shape, bt14_px)
    if flagged_px:
        g["flagged"][2, 2] = True
        g["anomaly"][2, 2] = anomaly_px
        g["diff"][2, 2] = diff_px
    return g


PX = {5: [(2, 2)]}


def test_states_stay_apart():
    """Check 1: a 404 band is missing; all pixels below the cloud
    threshold is obscured even when one is flagged; one clear flagged
    pixel is flagged; one clear pixel and no flag is quiet."""
    segs = {5: None}
    assert ho.slot_state(PX, segs, CLOUD)[0] == "missing"
    cold = {5: {"bt14": np.full((5, 5), 280.0),
                "flagged": np.zeros((5, 5), dtype=bool),
                "anomaly": np.full((5, 5), 30.0),
                "diff": np.full((5, 5), 25.0)}}
    # even a flagged reading cannot surface through cloud: obscured wins
    cold[5]["flagged"][2, 2] = True
    st, a, d, b14 = ho.slot_state(PX, cold, CLOUD)
    assert st == "obscured" and a is None and d is None
    assert b14 == 280.0
    hot = {5: {"bt14": np.full((5, 5), 295.0),
               "flagged": np.zeros((5, 5), dtype=bool),
               "anomaly": np.zeros((5, 5)), "diff": np.full((5, 5), 5.0)}}
    assert ho.slot_state(PX, hot, CLOUD)[0] == "quiet"
    hot[5]["flagged"][2, 2] = True
    hot[5]["anomaly"][2, 2] = 12.5
    hot[5]["diff"][2, 2] = 20.0
    st, a, d, b14 = ho.slot_state(PX, hot, CLOUD)
    assert st == "flagged" and a == 12.5 and d == 20.0 and b14 == 295.0


def test_bracket():
    """Check 2: quiet, obscured, obscured, flagged -> last_quiet at slot
    0, gap 30 minutes, gap_states {obscured: 2}."""
    t0 = datetime(2026, 8, 19, 16, 40, tzinfo=timezone.utc)
    slots = [t0 + timedelta(minutes=10 * k) for k in range(4)]
    ff, lq, minutes, gap = ho.bracket_from_states(
        ["quiet", "obscured", "obscured", "flagged"], slots)
    assert (ff, lq) == (3, 0)
    assert minutes == 30.0 and gap == {"obscured": 2}
    # open on the left: no quiet anywhere before the flag
    ff2, lq2, m2, g2 = ho.bracket_from_states(
        ["obscured", "missing", "flagged"], slots[:3])
    assert (ff2, lq2, m2, g2) == (2, None, None, {})


def test_readings_in_order():
    """Check 3: not flagged at the VIIRS slots is not_resolved even with
    earlier flags; a window whose first slot is flagged is
    flagged_from_window_start; missing above the share makes
    too_few_slots whatever else holds."""
    states = ["quiet", "flagged", "flagged", "obscured"]
    assert ho.reading_of(states, False, 0.8) == "not_resolved"
    assert ho.reading_of(["flagged", "quiet", "quiet"], True,
                         0.8) == "flagged_from_window_start"
    mostly_missing = ["missing"] * 6 + ["quiet", "flagged"]
    assert ho.reading_of(mostly_missing, True, 0.8) == "too_few_slots"
    assert ho.reading_of(["quiet", "quiet", "quiet", "missing", "flagged"],
                         True, 0.8) == "bracketed"
    assert ho.reading_of(["obscured", "obscured", "obscured", "missing",
                          "flagged"], True, 0.8) == "no_quiet_slot"


def test_fetch_slot_file_semantics(tmp_path, monkeypatch):
    """Check 4: 404 returns None; 503 raises; a 200 with 500 bytes
    raises. requests.get is replaced inside the test - no network."""
    import himawari as hm

    class Resp:
        def __init__(self, status, n_bytes):
            self.status_code = status
            self.content = b"x" * n_bytes

    captured = {}

    def fake_get(url, timeout):
        return Resp(fake_get.status, fake_get.n_bytes)

    monkeypatch.setattr(hm.requests, "get", fake_get)
    slot = datetime(2026, 8, 19, 4, 40, tzinfo=timezone.utc)

    fake_get.status = 404
    fake_get.n_bytes = 0
    assert hm.fetch_slot_file(slot, "B07", 5, tmp_path) is None

    fake_get.status = 503
    fake_get.n_bytes = 12
    with pytest.raises(RuntimeError) as e:
        hm.fetch_slot_file(slot, "B07", 5, tmp_path)
    assert "503" in str(e.value) and "B07" in str(e.value)

    fake_get.status = 200
    fake_get.n_bytes = 500
    with pytest.raises(RuntimeError) as e2:
        hm.fetch_slot_file(slot, "B07", 5, tmp_path)
    assert "500 bytes" in str(e2.value)


def test_two_detections_one_pixel():
    """Check 5: two detections inside one AHI pixel give one pixel, not
    two."""
    n = 8
    lon_g, lat_g = np.meshgrid(np.linspace(135.9, 136.1, n),
                               np.linspace(-1.3, -1.1, n), indexing="xy")
    seg_ll = {5: (lon_g, lat_g)}
    ev = {"event_id": "E1"}
    member = {"d1": "E1", "d2": "E1"}
    # both detections land inside the same synthetic pixel
    lat0, lon0 = float(lat_g[3, 3]), float(lon_g[3, 3])
    det_pos = {"d1": (lat0, lon0),
               "d2": (lat0 + 0.0005, lon0 + 0.0005)}
    px = ho.match_pixels([ev], member, det_pos, seg_ll)
    assert sum(len(v) for v in px["E1"].values()) == 1
    assert (3, 3) in px["E1"][5]


def test_floor10_and_window_edges():
    """Check 6: first_seen 04:47 UTC gives slots 16:40 the previous day
    to 05:10."""
    f = datetime(2026, 8, 19, 4, 47, tzinfo=timezone.utc)
    assert ho.floor10(f) == datetime(2026, 8, 19, 4, 40, tzinfo=timezone.utc)
    first, last, slots = ho.event_window(f, 12, 30, 10)
    assert first == datetime(2026, 8, 18, 16, 40, tzinfo=timezone.utc)
    assert last == datetime(2026, 8, 19, 5, 10, tzinfo=timezone.utc)
    assert len(slots) == 76
    assert slots[0] == first and slots[-1] == last


def _synthetic_doc():
    on = {"min_detections": 5, "lookback_hours": 12, "after_minutes": 30,
          "cadence_minutes": 10, "cloud_bt14_k": 285.0, "min_slot_share": 0.8,
          "diurnal_days": ["2026-08-21", "2026-08-24"],
          "named_case": {"event_id": "E0463", "wit_day": "2026-09-04"}}
    th = {"min_anomaly_k": 10.0, "min_bt_diff_k": 10.0,
          "background_window_px": 15, "cloud_bt14_k": 285.0}
    cfg = {"himawari_expected_segments": [5, 6]}
    t0 = datetime(2026, 8, 19, 16, 40, tzinfo=timezone.utc)
    slots = [t0 + timedelta(minutes=10 * k) for k in range(4)]
    iso = [s.strftime("%Y-%m-%dT%H:%MZ") for s in slots]
    rec = {
        "event_id": "E0100", "n_detections": 9, "pixel_count": 2,
        "window_first_slot_utc": iso[0], "window_last_slot_utc": iso[-1],
        "state_counts": {"missing": 0, "obscured": 2, "flagged": 1,
                         "quiet": 1},
        "first_flag_utc": iso[3], "first_flag_wit": "2026-08-19T13:40+09:00",
        "last_quiet_utc": iso[0], "last_quiet_wit": "2026-08-19T01:40+09:00",
        "gap_minutes": 30.0, "gap_states": {"obscured": 2},
        "seen_at_viirs": True, "lead_minutes": -6.9, "reading": "bracketed",
        "slot_states": [
            {"slot_utc": i, "state": s, "max_anomaly_k": 2.5,
             "max_bt_diff_k": 3.0, "min_b14_k": 295.1}
            for i, s in zip(iso, ("quiet", "obscured", "obscured",
                                  "flagged"))],
    }
    diurnal = [{"slot_utc": "2026-08-21T00:00Z", "wit_day": "2026-08-21",
                "wit_hour": 9, "is_night": False, "n_land_px": 700,
                "n_obscured": 10, "n_flagged": 3}]
    named = {"event_id": "E0463", "wit_day": "2026-09-04",
             "pixel_count": 3, "slot_states": [
                 {"slot_utc": "2026-09-04T03:00Z", "state": "obscured",
                  "max_anomaly_k": None, "max_bt_diff_k": None,
                  "min_b14_k": 282.0}],
             "by_wit_hour": {22: {"obscured": 144}}}
    return on, th, cfg, rec, diurnal, named


def _keys(obj, acc=None):
    acc = [] if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.append(k)
            _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def test_output_keys_and_determinism():
    """Checks 7+8: no key in the output contains the banned fragments,
    and the same state lists give byte-identical JSON."""
    on, th, cfg, rec, diurnal, named = _synthetic_doc()
    chosen = [{"event_id": "E0100", "n_detections": 9}]
    below = [{"event_id": "E0001", "n_detections": 1}]
    doc_a = ho.build_document(on, th, chosen, below, {"E0100": {5: [(2, 2)]}},
                              [rec], diurnal, named, cfg)
    doc_b = ho.build_document(on, th, chosen, below, {"E0100": {5: [(2, 2)]}},
                              [rec], diurnal, named, cfg)
    a = json.dumps(doc_a, sort_keys=True, indent=1).encode()
    b = json.dumps(doc_b, sort_keys=True, indent=1).encode()
    assert a == b
    for k in _keys(doc_a):
        low = str(k).lower()
        for banned in ("ignit", "cause", "start"):
            assert banned not in low, k


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
