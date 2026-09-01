"""Task 12 checks on vegetation_controls.json: month-aligned with
vegetation.json (same month strings over the overlap, none invented),
aerosol shares in [0, 1], zenith angles physically possible. The OLS
solver in src/vegetation_controls_gee.py is checked on a known plane, and
the committed pair of files must reproduce the base-model July 2026 NDMI
residual (+0.0206) that the whole question rests on.

The controls file is written by a by-hand Earth Engine run and is
legitimately absent until someone with credentials runs
src/vegetation_controls_gee.py; skip cleanly the way
test_vegetation_json_internal_consistency does for vegetation.json.

Run with pytest:
    python -m pytest tests/test_vegetation_controls.py
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTRL = ROOT / "docs" / "data" / "vegetation_controls.json"
VEG = ROOT / "docs" / "data" / "vegetation.json"


def _load():
    return (json.loads(CTRL.read_text(encoding="utf-8")),
            json.loads(VEG.read_text(encoding="utf-8")))


def test_controls_month_aligned_with_vegetation():
    if not CTRL.exists():
        print("SKIP: vegetation_controls.json not present")
        return
    ctrl, veg = _load()
    cm = [r["month"] for r in ctrl["monthly"]]
    vm = [r["month"] for r in veg["monthly"]]
    assert cm == sorted(cm) and len(cm) == len(set(cm))
    # none invented: every controls month exists in vegetation.json ...
    assert set(cm) <= set(vm), "month not present in vegetation.json"
    # ... and the overlap is the same strings in the same order
    assert [m for m in vm if m in set(cm)] == cm, "overlap misaligned"
    # dense, no gap in the controls file itself
    for a, b in zip(cm, cm[1:]):
        da = date(int(a[:4]), int(a[5:7]), 1)
        db = date(int(b[:4]), int(b[5:7]), 1)
        assert (db - da).days in (28, 29, 30, 31), f"gap between {a} and {b}"


def test_controls_values_physical():
    if not CTRL.exists():
        print("SKIP: vegetation_controls.json not present")
        return
    ctrl, _ = _load()
    for r in ctrl["monthly"]:
        for k in ("aerosol_high_share", "aerosol_climatology_share"):
            if r.get(k) is not None:
                assert 0 <= r[k] <= 1, (r["month"], k, r[k])
        v = r.get("view_zenith_deg")
        if v is not None:
            # a satellite cannot look below the horizon; MODIS scans to ~65
            assert 0 <= v <= 90, (r["month"], v)
        s = r.get("solar_zenith_deg")
        if s is not None:
            # catalog range 0-180 deg at scale 0.01
            assert 0 <= s <= 180, (r["month"], s)


def test_ols_solver():
    """The solver recovers a known plane exactly, gives the far-from-
    centroid point the largest leverage, and the hat matrix traces to p."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import vegetation_controls_gee as vc
    except ImportError as exc:
        print(f"SKIP: vegetation_controls_gee not importable ({exc})")
        return
    rows = [{"a": float(i), "b": float(i % 4),
             "y": 2.0 + 3.0 * i - (i % 4)} for i in range(10)]
    rows.append({"a": 100.0, "b": 1.0, "y": 2.0 + 300.0 - 1.0})
    fit = vc.ols(rows, ["a", "b"], "y")
    for nm, b, want in zip(fit["names"], fit["coef"], (2.0, 3.0, -1.0)):
        assert abs(b - want) < 1e-6, (nm, b)
    assert max(abs(v) for v in fit["residuals"]) < 1e-9
    assert fit["leverage"][-1] == max(fit["leverage"])
    assert all(v >= -1e-9 for v in fit["leverage"])
    assert abs(sum(fit["leverage"]) - 3.0) < 1e-6    # trace = p


def test_base_model_july2026_residual_reproduced():
    """With both committed files present, refit ndmi on its good-pixel
    share over the Julys and confirm the July 2026 residual is the
    +0.0206 the task hangs on — the check that the controls series and
    the published series describe the same months."""
    if not CTRL.exists() or not VEG.exists():
        print("SKIP: vegetation_controls.json / vegetation.json not present")
        return
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import vegetation_controls_gee as vc
    except ImportError as exc:
        print(f"SKIP: vegetation_controls_gee not importable ({exc})")
        return
    ctrl, veg = _load()
    rows = [r for r in vc.july_rows(veg["monthly"], ctrl["monthly"])
            if r.get("ndmi") is not None and r.get("ndmi_good_share") is not None]
    fit = vc.ols(rows, ["ndmi_good_share"], "ndmi")
    jul = next(i for i, r in enumerate(rows) if r["month"] == "2026-07")
    assert abs(fit["residuals"][jul] - 0.0206) < 0.002, fit["residuals"][jul]


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
