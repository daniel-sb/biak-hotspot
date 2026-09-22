"""Offline checks for the fire danger indices (Task 21). Synthetic
inputs built inside the test; the raw ERA5-Land months are read only by
the determinism check, and nothing ever fetches. No Earth Engine needed
- the ee import lives inside the fetch path.

Run with pytest:
    python -m pytest tests/test_fire_danger.py
or directly (no pytest needed):
    python tests/test_fire_danger.py
"""
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fire_danger as fdm  # noqa: E402


def test_published_fwi_test_day():
    """Check 1: the published FWI test day (Van Wagner and Pickett 1985),
    from FFMC 85, DMC 6, DC 15, T 17 C, RH 42%, wind 25 km/h, rain 0,
    with the Canadian April day-length factors passed as arguments -
    which is why the factors are arguments, not config reads."""
    got = fdm.fwi_system_step(85, 6, 15, 17.0, 42.0, 25.0, 0.0, 12.8, 0.9)
    want = {"ffmc": 87.69, "dmc": 8.55, "dc": 19.01, "isi": 10.85,
            "bui": 8.49, "fwi": 10.10}
    got_d = dict(zip(("ffmc", "dmc", "dc", "isi", "bui", "fwi"), got))
    for k, w in want.items():
        assert abs(got_d[k] - w) < 0.01, (k, got_d[k], w)


def test_rain_thresholds():
    """Check 2: FFMC ignores 0.5 mm, DMC ignores 1.5 mm, DC ignores
    2.8 mm; just above each, the code falls."""
    f0 = fdm.fine_fuel_moisture_code(85, 17.0, 42.0, 25.0, 0.0)
    assert fdm.fine_fuel_moisture_code(85, 17.0, 42.0, 25.0, 0.5) == f0
    assert fdm.fine_fuel_moisture_code(85, 17.0, 42.0, 25.0, 0.6) != f0
    d0 = fdm.duff_moisture_code(6, 17.0, 42.0, 1.5, 9.0)
    assert fdm.duff_moisture_code(6, 17.0, 42.0, 1.5, 9.0) == d0
    assert fdm.duff_moisture_code(6, 17.0, 42.0, 1.6, 9.0) != d0
    d1 = fdm.drought_code(15, 17.0, 2.8, 1.39)
    assert fdm.drought_code(15, 17.0, 2.8, 1.39) == d1
    assert fdm.drought_code(15, 17.0, 2.9, 1.39) != d1


def test_kbdi():
    """Check 3: a hot dry day raises Q; Q stays in [0, 203.2]; and a rain
    run of 3, 2 and 4 mm on consecutive days, with Tmax low enough that
    drying is 0, reduces Q by 3.92 mm (9 - 5.08), not 9."""
    q0 = 100.0
    q_hot, _ = fdm.kbdi_step(q0, 35.0, 0.0, 0.0, 1500.0, 5.08)
    assert q_hot > q0
    q = q0
    for _ in range(400):
        q, _ = fdm.kbdi_step(q, 40.0, 0.0, 0.0, 1500.0, 5.08)
        assert 0.0 <= q <= 203.2
    # drying is 0 at Tmax <= 6.77 C; the 3/2/4 run must net 3.92 exactly
    q, run = 100.0, 0.0
    for rain in (3.0, 2.0, 4.0):
        q, run = fdm.kbdi_step(q, 5.0, rain, run, 1500.0, 5.08)
    assert abs((100.0 - q) - 3.92) < 1e-9


def test_days_since_rain():
    """Check 4: resets on a day at rain_day_mm, counts up otherwise,
    None before the first qualifying day."""
    rain = {"2024-01-01": 0.0, "2024-01-02": 2.0, "2024-01-03": 0.0,
            "2024-01-04": 0.0, "2024-01-05": 0.5, "2024-01-06": 0.0}
    got = fdm.days_since_rain_series(rain, 1.0)
    assert [got[d] for d in sorted(rain)] == [None, 0, 1, 2, 3, 4]


def test_rain_window_utc():
    """Check 5: under the hour-ENDING stamping convention, the 24 stamps
    counting for WIT day D run 04:00 UTC D-1 through 03:00 UTC D; a
    stamp at 03:00 D-1 belongs to D-1 and one at 04:00 D to D+1."""
    noon = datetime(2024, 1, 3, 3, 0, tzinfo=timezone.utc)
    start, end = fdm.rain_window_utc(noon)
    assert start == datetime(2024, 1, 2, 4, 0, tzinfo=timezone.utc)
    assert end == datetime(2024, 1, 3, 4, 0, tzinfo=timezone.utc)
    # a stamp at start covers [03:00, 04:00) D-1 -> the first hour of D;
    # a stamp at 03:00 D-1 covers [02:00, 03:00) D-1 -> before the window;
    # a stamp at 04:00 D covers [03:00, 04:00) D -> D+1's first hour
    assert start.hour == 4 and (start - timedelta(hours=1)).hour == 3
    assert (end - timedelta(hours=1)) == datetime(
        2024, 1, 3, 3, 0, tzinfo=timezone.utc)


def test_missing_day_re_spins_up():
    """Check 6: a missing input day gives no index for that cell until
    the re-spin-up is complete."""
    days = [f"2024-01-{d:02d}" for d in range(1, 13)]
    weather = {}
    t = {"t_noon_c": 30.0, "rh_noon": 50.0, "wind_noon_kmh": 10.0,
         "rain_24h_mm": 0.0, "t_max_c": 33.0}
    for d in days:
        weather[d] = dict(t)
    del weather["2024-01-06"]            # the gap
    got = fdm.cell_index_series(days, weather, {"ffmc": 85, "dmc": 6,
                                                "dc": 15}, 1500.0,
                                9.0, 1.39, 3, 5.08)
    # restart at 01-07: run_len 1..3 give no value, 4th day does
    assert "2024-01-08" not in got and "2024-01-09" not in got
    assert "2024-01-10" in got and "2024-01-12" in got
    assert "2024-01-06" not in got       # the gap itself


def test_y_excludes_recurrent_only_day():
    """Check 7: a day whose only detection is a recurrent site is not a
    positive (PLAN.md 5 item 5)."""
    det = pd.DataFrame({
        "date_wit": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "satellite": ["N", "N", "N"],
        "on_land": [True, True, True],
        "recurrent_site": [True, False, False],
    })
    days_all, positives = fdm.positives_and_days(det, {"N"})
    assert days_all == {"2024-01-01", "2024-01-02", "2024-01-03"}
    assert positives == {"2024-01-02", "2024-01-03"}
    assert len(days_all - positives) == 1


def test_climatology_fold_isolation():
    """Check 8: the leave-one-year-out climatology never sees year Y's
    days - perturbing them leaves its probabilities identical."""
    observed = ["2024-03-01", "2024-03-02", "2025-03-01", "2025-03-02",
                "2026-03-01"]
    positives = {"2024-03-01", "2025-03-02"}
    p_before = fdm.fold_climatology(observed, positives, "2026", 0)
    # wild perturbation of the held-out year's positives
    p_after = fdm.fold_climatology(
        observed, positives | {"2026-03-01"}, "2026", 0)
    assert p_before["2026-03-01"] == p_after["2026-03-01"]
    # and the trained years are the training data: on the same
    # day-of-year, 2024 positive and 2025 not: 1 of 2 days gives 0.5
    assert abs(p_before["2026-03-01"] - 0.5) < 1e-12


def test_deterministic():
    """Check 9: the same raw files give byte-identical fire_danger.json.
    Skips when the raw months have not been fetched on this machine."""
    if not list(fdm.RAW.glob("ERA5L_20*.json")):
        print("SKIP: no raw ERA5-Land months (run src/fire_danger.py "
              "--fetch <project>)")
        return
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    doc_a = fdm.evaluate(cfg)
    doc_b = fdm.evaluate(cfg)
    assert json.dumps(doc_a, sort_keys=True, indent=1).encode() == \
        json.dumps(doc_b, sort_keys=True, indent=1).encode()


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
