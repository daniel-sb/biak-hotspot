"""Offline checks for METAR corroboration (Task 19). Synthetic CSV rows
and synthetic events built inside the test; the real raw archive is
touched only by the determinism check, and nothing ever fetches.

Run with pytest:
    python -m pytest tests/test_metar.py
or directly (no pytest needed):
    python tests/test_metar.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import metar as mt  # noqa: E402


def tiny_csv(rows):
    """rows: (valid, vsby, wxcodes, drct, sknt, metar) -> CSV text."""
    head = "station,valid,vsby,wxcodes,drct,sknt,metar"
    return head + "\n" + "\n".join(
        f"WABB,{v},{s},{w},{d},{k},{m}" for v, s, w, d, k, m in rows) + "\n"


def parse_rows(rows, tmp):
    p = Path(tmp) / "tiny.csv"
    p.write_text(tiny_csv(rows), encoding="utf-8")
    return mt.parse_observations([p])


def unit_events(*pairs):
    """pairs: (event_id, first_seen_utc, last_seen_utc) -> events doc."""
    return {"events": [
        {"event_id": eid, "first_seen_utc": f, "last_seen_utc": l,
         "centroid_lat": -1.14, "centroid_lon": 136.03}
        for eid, f, l in pairs], "params": {}}


METAR_CFG = {"lag_hours": 48, "sector_half_width_deg": 45,
             "lat": -1.190, "lon": 136.108, "max_km": 50,
             "min_coverage": 0.5, "station": "WABB",
             "archive_start": "2023-09-01"}


def test_unit_parsing_vsby(tmp_path):
    """Check 1: 6.21 is the ceiling; 2.49 is not; vsby = M is missing and
    never becomes a number."""
    obs = parse_rows([
        ("2024-03-01 06:45", "6.21", "M", "M", "0", "x"),
        ("2024-03-01 07:15", "2.49", "FU", "320", "8", "x"),
        ("2024-03-01 07:45", "M", "M", "180", "5", "x"),
    ], tmp_path)
    r = obs.sort_values("valid_utc").reset_index(drop=True)
    assert bool(r.at_ceiling[0]) is True
    assert bool(r.at_ceiling[1]) is False
    assert pd.isna(r.vsby_sm[2]) and not r.at_ceiling[2]   # missing, not 0
    assert r.vsby_sm[2] != r.vsby_sm[2]                    # NaN


def test_wxcodes_tokens(tmp_path):
    """Check 2: `M` is no present-weather group at all; `FU HZ` is both;
    a token that merely contains the letters is not a match."""
    obs = parse_rows([
        ("2024-03-01 06:45", "5.00", "M", "M", "0", "x"),
        ("2024-03-01 07:15", "5.00", "FU HZ", "320", "8", "x"),
        ("2024-03-01 07:45", "5.00", "XFUZ", "320", "8", "x"),
        ("2024-03-01 08:15", "5.00", "FUHZ", "320", "8", "x"),
    ], tmp_path)
    r = obs.sort_values("valid_utc").reset_index(drop=True)
    assert not r.fu[0] and not r.hz[0]      # M: nothing, not missing
    assert r.fu[1] and r.hz[1]
    assert not r.fu[2] and not r.hz[2]      # letters inside a token
    assert not r.fu[3] and not r.hz[3]      # FUHZ without a space


def test_calm_and_variable_are_never_from_event():
    """Check 3: calm (drct 0, sknt 0) and variable (drct M) never count as
    wind from any event, including one at bearing 0."""
    assert not mt.wind_from_event(0.0, 0.0, 0.0, 45)     # calm
    assert not mt.wind_from_event(float("nan"), 8.0, 0.0, 45)  # variable
    assert not mt.wind_from_event(float("nan"), 0.0, 0.0, 45)
    assert mt.wind_from_event(0.0, 5.0, 0.0, 45)         # real northerly


def test_worked_example_and_north_crossing():
    """Check 4: bearing 315 with drct 320 -> from the event; bearing 135
    -> not; 355 against 5 crosses north (10 degrees, not 350)."""
    assert mt.wind_from_event(320.0, 8.0, 315.0, 45)
    assert not mt.wind_from_event(320.0, 8.0, 135.0, 45)
    assert mt.wind_from_event(355.0, 8.0, 5.0, 45)
    assert mt.wind_from_event(5.0, 8.0, 355.0, 45)
    assert mt.angdiff(355.0, 5.0) == 10.0


def test_window_lag_boundaries(tmp_path):
    """Check 5: the window reaches last_seen + lag_hours exactly and
    excludes a report just after it."""
    events = unit_events(("E1", "2024-03-01T00:00:00Z",
                          "2024-03-02T00:00:00Z"))
    at_lag = parse_rows(
        [("2024-03-04 00:00", "3.00", "FU", "320", "8", "x")], tmp_path)
    rec = mt.join_events(at_lag, events, METAR_CFG, 1.0)[0]
    assert rec["n_fu"] == 1 and rec["n_obs"] == 1

    after_lag = parse_rows(
        [("2024-03-04 00:01", "3.00", "FU", "320", "8", "x")], tmp_path)
    rec2 = mt.join_events(after_lag, events, METAR_CFG, 1.0)[0]
    assert rec2["n_fu"] == 0 and rec2["n_obs"] == 0


def test_class_order(tmp_path):
    """Check 6: beyond_range beats corroborated; unobserved beats
    everything."""
    rec = {"coverage": 1.0, "distance_km": 140.0, "n_fu": 3,
           "n_fu_from_event": 2}
    assert mt.classify(rec, 0.5, 50.0) == "beyond_range"
    rec2 = {"coverage": 0.3, "distance_km": 5.0, "n_fu": 4,
            "n_fu_from_event": 4}
    assert mt.classify(rec2, 0.5, 50.0) == "unobserved"


def test_concurrent_events_share_reports(tmp_path):
    """Check 7: two overlapping events whose windows both contain the one
    FU report count 1 for each."""
    events = unit_events(
        ("E1", "2024-03-01T00:00:00Z", "2024-03-02T00:00:00Z"),
        ("E2", "2024-03-01T12:00:00Z", "2024-03-03T00:00:00Z"))
    obs = parse_rows([("2024-03-01 18:00", "3.00", "FU", "320", "8", "x")],
                     tmp_path)
    recs = mt.join_events(obs, events, METAR_CFG, 1.0)
    assert recs[0]["n_fu"] == 1 and recs[1]["n_fu"] == 1
    assert recs[0]["n_concurrent_events"] == 1
    assert recs[1]["n_concurrent_events"] == 1


def test_validate_year_csv(tmp_path):
    """Check 8: a year with no data rows, and an HTML page, both exit
    non-zero naming the year; a good CSV returns its row count."""
    import pytest
    with pytest.raises(SystemExit) as e:
        mt.validate_year_csv("station,valid,vsby\n", 2024)
    assert "2024" in str(e.value)
    with pytest.raises(SystemExit) as e2:
        mt.validate_year_csv("<html><body>error</body></html>", 2023)
    assert "2023" in str(e2.value)
    good = mt.validate_year_csv(
        "station,valid,vsby,wxcodes,drct,sknt,metar\n"
        "WABB,2024-03-01 06:45,6.21,M,M,0,x\n", 2024)
    assert good == 1


def test_deterministic(tmp_path):
    """Check 9: the same raw files give byte-identical JSON. Skips when
    the raw archive has not been fetched on this machine."""
    raws = sorted((ROOT / "data" / "raw" / "metar").glob("WABB_*.csv"))
    if not raws:
        print("SKIP: no raw METAR files (run src/metar.py --fetch)")
        return
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    obs = mt.parse_observations(raws)
    doc_a = mt.evaluate(obs, cfg)
    doc_b = mt.evaluate(obs, cfg)
    assert json.dumps(doc_a, sort_keys=True, indent=1).encode() == \
        json.dumps(doc_b, sort_keys=True, indent=1).encode()


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
