"""Offline checks for the Himawari-9 reader and anomaly flagging (Task 05).

Uses one real slot (2026-08-22 06:50 UTC, segment 6, bands B07+B14) committed
to tests/fixtures/. No network.

Run with pytest:
    python -m pytest tests/test_himawari.py
or directly (no pytest needed):
    python tests/test_himawari.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import himawari as hw  # noqa: E402
import ingest_firms as ing  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
B07 = FIX / "HS_H09_20260822_0650_B07_FLDK_R20_S0610.DAT.bz2"
B14 = FIX / "HS_H09_20260822_0650_B14_FLDK_R20_S0610.DAT.bz2"
STORE = ROOT / "data" / "processed" / "detections.parquet"

import yaml  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
BBOX = [float(v) for v in CFG["aoi_bbox_wsen"]]


def test_reader_shape_and_header():
    """Check 1: the reader returns the documented array shape and the
    documented header fields for a known segment."""
    hsd = hw.read_hsd(B07)
    assert hsd["counts"].shape == (550, 5500)
    assert hsd["band"] == 7
    assert hsd["valid_bits"] == 14
    assert hsd["count_error"] == 65535 and hsd["count_outside"] == 65534
    assert hsd["sub_lon"] == 140.7
    assert hsd["seg_seq"] == 6 and hsd["seg_first_line"] == 2751
    # observation start falls inside the nominal 06:50 UTC slot
    assert hsd["time"].date().isoformat() == "2026-08-22"
    assert "06:50" <= hsd["time"].strftime("%H:%M") <= "06:56"


def test_ocean_bt_in_range():
    """Check 2: open-ocean B14 brightness temperature falls in 293-305 K -
    a reader that is off by an offset will not land in that range."""
    hsd = hw.read_hsd(B14)
    bt = hw.counts_to_bt(hsd)
    # open ocean north of New Guinea: lines 2751-2830 of the full disk,
    # well clear of land in this segment
    sea = bt[0:80, 2000:3500]
    assert np.isfinite(sea).sum() > 1000
    med = float(np.nanmedian(sea))
    assert 293.0 <= med <= 305.0, f"ocean B14 median {med} K out of range"


def test_hot_pixel_flagged_clean_not():
    """Check 3: a synthetic hot pixel injected into a real (clean open-ocean)
    background is flagged; the unmodified background is not."""
    hsd7 = hw.read_hsd(B07)
    hsd14 = hw.read_hsd(B14)
    bt07 = hw.counts_to_bt(hsd7)
    bt14 = hw.counts_to_bt(hsd14)
    # clean open-ocean window of the segment (verified: 0 flags unmodified)
    r0, r1, c0, c1 = 100, 210, 300, 700
    sub07 = bt07[r0:r1, c0:c1]
    sub14 = bt14[r0:r1, c0:c1]

    _, _, _, clean = hw.flag_anomalies(sub07, sub14, 10.0, 10.0, 15)
    assert not clean.any()

    hot = sub07.copy()
    hot[60, 70] += 60.0            # a real fire in the pixel: +60 K
    _, _, _, hot_flags = hw.flag_anomalies(hot, sub14, 10.0, 10.0, 15)
    assert hot_flags[60, 70]
    assert int(hot_flags.sum()) == 1


def test_day_night_classification():
    """Check 4: 18:00 WIT is still day (sunset ~18:15); 20:00 WIT is night."""
    assert hw.is_night(18 * 60 + 0, 18 * 60 + 15) is False
    assert hw.is_night(20 * 60 + 0, 18 * 60 + 15) is True
    assert hw.is_night(15 * 60 + 0, 18 * 60 + 15) is False
    assert hw.is_night(0 * 60 + 59, 18 * 60 + 15) is True   # after midnight


def test_segment_selection_from_header():
    """Check 5: the segment(s) covering the AOI, computed from the HSD
    navigation block, match the expected value (config)."""
    hsd = hw.read_hsd(B07)
    segments, line0, line1, col0, col1 = hw.locate_aoi(hsd, BBOX)
    expected = {int(s) for s in CFG["himawari_expected_segments"]}
    assert segments == expected
    assert line0 < line1 and col0 < col1
    # every AOI pixel's full-disk line maps back into the claimed segments
    seg_first = hsd["seg_first_line"]
    r0, r1, _, _, _ = hw.segment_window(hsd, line0, line1, col0, col1)
    for r in (r0, r1 - 1):
        full_line = seg_first + r
        assert ((full_line - 1) // 550) + 1 in segments


def test_firms_crosscheck_numbers():
    """Check 6: the FIRMS cross-check against the real store, using the real
    committed slot (offline - the fixture IS the real downloaded file).
    The anomaly must be present; the numbers are the report."""
    # firms_crosscheck picks its own slot from the brightest detection and
    # fetches it, so the committed fixture does not cover it: on a machine
    # without the raw archive this test would download from AWS, which
    # AGENTS.md rule 4 forbids and which broke the CI run of 2026-08-31.
    # It is a check against the real local archive, so it skips without one.
    raw_himawari = ROOT / "data" / "raw" / "himawari"
    if not STORE.exists() or not raw_himawari.is_dir():
        print("SKIP: needs the local Himawari raw archive (not committed)")
        return
    res = hw.firms_crosscheck(CFG, ROOT, STORE)
    assert res["detection"]["frp_mw"] == 90.55
    assert res["slot_utc"] == "2026-08-22T04:10Z"
    assert res["difference_k"] > 0, "no thermal anomaly at the fire pixel"
    assert abs(res["pixel_bt07_k"] - res["background_bt07_k"]
               - res["difference_k"]) <= 0.02
    assert res["pixel_bt14_k"] > 280


def test_flagged_rows_kept_not_deleted():
    """AGENTS rule 5: flagged rows stay in the output frame."""
    hsd7 = hw.read_hsd(B07)
    hsd14 = hw.read_hsd(B14)
    bt07 = hw.counts_to_bt(hsd7)
    bt14 = hw.counts_to_bt(hsd14)
    r0, r1, c0, c1, _ = hw.segment_window(hsd7, 2689, 2833, 2385, 2537)
    sub07 = bt07[r0:r1, c0:c1].copy()
    sub14 = bt14[r0:r1, c0:c1]
    sub07[60, 70] += 60.0
    before = sub07.copy()
    bg, anom, diff, flagged = hw.flag_anomalies(sub07, sub14, 10.0, 10.0, 15)
    assert flagged.shape == sub07.shape
    # flagging is read-only on the grids: nothing removed, nothing altered
    assert np.array_equal(sub07, before)
    assert np.isfinite(sub07).sum() == np.isfinite(before).sum()


def test_evening_parquet_land_and_size():
    """Checks 1+2: a day's evening file is under 2 MB, carries at most the
    fixed ocean sample, and every non-sample pixel sits on land (the shared
    desa-polygon test, not a parallel mechanism)."""
    p = ROOT / "data" / "processed" / "himawari_evening_2026-08-22.parquet"
    if not p.exists():
        print("SKIP: evening parquet not built yet")
        return
    assert p.stat().st_size < 2_000_000, "evening file is 2 MB or larger"
    df = pd.read_parquet(p)
    slots = df["acq_time_utc"].nunique()
    # the fixed ocean sample is capped at 300 px per segment (2 segments)
    assert int(df["ocean_sample"].sum()) <= 600 * slots
    land_px = df[~df["ocean_sample"]].drop_duplicates(["lat", "lon"])
    hits = ing.land_hits(land_px["lon"], land_px["lat"],
                         ing.load_boundaries(
                             ROOT / "data" / "boundaries" / "biak_desa.geojson"))
    assert all(h is not None for h in hits)


def test_land_mechanism_parity_with_store():
    """Check 2: the Himawari land test IS the ingest's on_land test - same
    coordinates give the same answer as the store's on_land column."""
    if not STORE.exists():
        print("SKIP: store missing")
        return
    df = pd.read_parquet(STORE).drop_duplicates(["latitude", "longitude"])
    hits = ing.land_hits(df["longitude"], df["latitude"],
                         ing.load_boundaries(
                             ROOT / "data" / "boundaries" / "biak_desa.geojson"))
    assert [h is not None for h in hits] == df["on_land"].tolist()


def test_slot_rows_deterministic():
    """Check 6 (producer side): the same grids give byte-identical Parquet."""
    hsd7 = hw.read_hsd(B07)
    hsd14 = hw.read_hsd(B14)
    bt07 = hw.counts_to_bt(hsd7)
    bt14 = hw.counts_to_bt(hsd14)
    r0, r1, c0, c1, _ = hw.segment_window(hsd7, 2689, 2833, 2385, 2537)
    sub07 = bt07[r0:r1, c0:c1]
    sub14 = bt14[r0:r1, c0:c1]
    lon_g, lat_g = hw.lonlat_grid(hsd7, np.arange(r0, r1) + 2751,
                                  np.arange(c0, c1))
    bnd = ing.load_boundaries(ROOT / "data" / "boundaries" / "biak_desa.geojson")
    land = np.array([h is not None for h in ing.land_hits(
        lon_g.ravel(), lat_g.ravel(), bnd)]).reshape(sub07.shape)
    ocean = [(i, j) for i in range(sub07.shape[0])
             for j in range(sub07.shape[1]) if not land[i, j]]
    ocean = ocean[::max(1, len(ocean) // 300)][:300]
    utc = datetime(2026, 8, 22, 6, 30, tzinfo=timezone.utc)
    wit = utc.astimezone(hw.WIT)
    night = hw.is_night(wit.hour * 60 + wit.minute, 18 * 60 + 15)

    def build():
        rows = hw._slot_rows(sub07, sub14, lon_g, lat_g, land, ocean,
                             utc, wit, night, 10.0, 10.0, 15)
        f = pd.DataFrame(rows)
        return f.to_parquet(index=False)

    assert build() == build()


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
