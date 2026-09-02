"""Task 14 checks on drought_et_check.json: the Terra ET column must
reproduce the published drought.json month for month, the copied
precipitation must match it too, the recomputed balances must equal their
two terms, months dense and sorted, shares in [0, 1], and no month
invented beyond either product's coverage.

The file is written by a by-hand Earth Engine run and is legitimately
absent until someone with credentials runs src/drought_et_check_gee.py;
skip cleanly the way the task 11-13 checks do.

Run with pytest:
    python -m pytest tests/test_drought_et_check.py
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ETCHK = ROOT / "docs" / "data" / "drought_et_check.json"
DROUGHT = ROOT / "docs" / "data" / "drought.json"


def test_drought_et_check_internal_consistency():
    if not ETCHK.exists():
        print("SKIP: drought_et_check.json not present")
        return
    doc = json.loads(ETCHK.read_text(encoding="utf-8"))
    monthly = doc["monthly"]

    months = [r["month"] for r in monthly]
    assert months == sorted(months) and len(months) == len(set(months))
    # dense, no gap
    for a, b in zip(months, months[1:]):
        da = date(int(a[:4]), int(a[5:7]), 1)
        db = date(int(b[:4]), int(b[5:7]), 1)
        assert (db - da).days in (28, 29, 30, 31), f"gap between {a} and {b}"
    # no month invented beyond either product's coverage
    cov = doc["coverage"]
    first = max(cov["mod16a2_first_date"][:7], cov["myd16a2_first_date"][:7])
    last = min(cov["mod16a2_last_date"][:7], cov["myd16a2_last_date"][:7])
    assert months[0] >= first and months[-1] <= last, (months[0], months[-1])

    # shares in [0, 1]
    for r in monthly:
        for k in ("et_qc_good_share_terra", "et_qc_good_share_aqua"):
            if r.get(k) is not None:
                assert 0 <= r[k] <= 1, (r["month"], k, r[k])

    # each recomputed balance equals its two terms, and a None balance
    # only ever follows a None term
    for r in monthly:
        for et_key, bal_key in (("et_terra_mm", "p_minus_et_terra_mm"),
                                ("et_aqua_mm", "p_minus_et_aqua_mm")):
            if r["precip_mm"] is None or r.get(et_key) is None:
                assert r.get(bal_key) is None, r["month"]
                continue
            want = round(r["precip_mm"] - r[et_key], 1)
            assert abs(r[bal_key] - want) < 0.051, (r["month"], bal_key)


def test_terra_et_reproduces_drought_json():
    """The whole cross-check rests on et_terra_mm being drought.json's
    series fetched again: month-for-month equality over the overlap, and
    the copied precipitation with it."""
    if not ETCHK.exists():
        print("SKIP: drought_et_check.json not present")
        return
    doc = json.loads(ETCHK.read_text(encoding="utf-8"))
    drought = json.loads(DROUGHT.read_text(encoding="utf-8"))
    pub = {r["month"]: r for r in drought["monthly"]}
    overlap = [r for r in doc["monthly"] if r["month"] in pub]
    assert overlap, "no month overlap with drought.json"
    for r in overlap:
        p = pub[r["month"]]
        if r.get("et_terra_mm") is not None and p.get("et_mm") is not None:
            assert abs(r["et_terra_mm"] - p["et_mm"]) < 0.051, \
                (r["month"], r["et_terra_mm"], p["et_mm"])
        if r.get("precip_mm") is not None and p.get("precip_mm") is not None:
            assert abs(r["precip_mm"] - p["precip_mm"]) < 0.051, \
                (r["month"], r["precip_mm"], p["precip_mm"])


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
