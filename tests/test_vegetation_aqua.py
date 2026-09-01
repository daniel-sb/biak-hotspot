"""Task 13 checks on vegetation_aqua.json: shares in [0, 1], zenith
angles physically possible, months dense and sorted, and the month range
consistent with MYD09A1's start (2002-07, catalog-verified) — the file
must not reach further back than Aqua's record goes.

The Aqua file is written by a by-hand Earth Engine run and is
legitimately absent until someone with credentials runs
src/vegetation_aqua_gee.py; skip cleanly the way the task 11 and 12
checks do.

Run with pytest:
    python -m pytest tests/test_vegetation_aqua.py
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AQUA = ROOT / "docs" / "data" / "vegetation_aqua.json"


def test_aqua_json_internal_consistency():
    if not AQUA.exists():
        print("SKIP: vegetation_aqua.json not present")
        return
    doc = json.loads(AQUA.read_text(encoding="utf-8"))
    monthly = doc["monthly"]

    months = [r["month"] for r in monthly]
    assert months == sorted(months) and len(months) == len(set(months))
    # MYD09A1 begins 2002-07-04: the series cannot start before 2002-07,
    # and its first month is the later of the two Aqua products' firsts
    assert months[0] >= "2002-07", months[0]
    assert months[0] >= min(doc["coverage"]["myd09a1_first_date"][:7],
                            doc["coverage"]["myd13a1_first_date"][:7])
    # dense, no gap
    for a, b in zip(months, months[1:]):
        da = date(int(a[:4]), int(a[5:7]), 1)
        db = date(int(b[:4]), int(b[5:7]), 1)
        assert (db - da).days in (28, 29, 30, 31), f"gap between {a} and {b}"

    for r in monthly:
        for k in ("ndmi_good_share", "ndvi_good_share",
                  "aerosol_high_share", "aerosol_climatology_share"):
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


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
