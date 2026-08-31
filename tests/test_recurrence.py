"""Offline checks for recurrent-location flagging (Task 04).

Synthetic stores with unambiguous answers, plus the pinned PLAN.md 11.2
expectations against the real store where it is present. No network.

Run with pytest:
    python -m pytest tests/test_recurrence.py
or directly (no pytest needed):
    python tests/test_recurrence.py
"""
import json
import math
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import recurrence as rec  # noqa: E402

STORE = ROOT / "data" / "processed" / "detections.parquet"
M_PER_DEG = rec.M_PER_DEG


def synth(rows) -> pd.DataFrame:
    """rows: (lat, lon, date_wit, distrik) -> minimal store frame."""
    return pd.DataFrame({
        "detection_id": [f"id{i:03d}" for i in range(len(rows))],
        "latitude": [r[0] for r in rows],
        "longitude": [r[1] for r in rows],
        "date_wit": [r[2] for r in rows],
        "distrik": [r[3] for r in rows],
    })


DEG = 1.0 / M_PER_DEG   # one metre in degrees, good enough near the equator


def test_radius_spacing_makes_one_cluster():
    """Check 1: three detections at 375 m spacing on different days are one
    cluster, not three."""
    df = synth([(-1.0, 136.0, "2023-09-01", "Yendidori"),
                (-1.0 - 375 * DEG, 136.0, "2023-12-01", "Yendidori"),
                (-1.0 - 750 * DEG, 136.0, "2024-03-01", "Yendidori")])
    out, sites, reason, _, _ = rec.compute(df, radius_m=750.0, min_days=1,
                                           min_span_days=0, min_history_days=0)
    assert reason is None
    assert len(sites) == 1
    assert (out["recurrent_site"] == [True, True, True]).all()
    assert out["recurrent_site_id"].tolist() == ["R001"] * 3
    assert out["recurrent_site_days"].tolist() == [3, 3, 3]


def test_span_condition_excludes_short_bursts():
    """Check 2: 10 distinct days inside a week is a fire that burned for a
    week, not a recurrent site; the same count spread over 200 days is."""
    burst = [(-1.0, 136.0, f"2024-01-0{d}", "Yendidori") for d in range(1, 7)]
    burst += [(-1.0, 136.0, f"2024-01-1{d}", "Yendidori") for d in range(5)]
    spread = [(-2.0, 136.5, (date(2023, 9, 1)
                             + timedelta(days=20 * i)).isoformat(),
               "Biak Timur") for i in range(10)]
    df = synth(burst + spread)
    out, sites, _, _, _ = rec.compute(df, radius_m=750.0, min_days=10,
                                      min_span_days=90, min_history_days=0)
    burst_site = out.loc[out["distrik"] == "Yendidori", "recurrent_site"]
    spread_site = out.loc[out["distrik"] == "Biak Timur", "recurrent_site"]
    assert not burst_site.any()          # 10 days, span 6 -> no
    assert spread_site.all()             # 10 days, span 180 -> yes
    assert len(sites) == 1 and sites[0]["distrik"] == "Biak Timur"


def test_short_history_refuses_to_flag():
    """Check 3: a store spanning under 365 days produces zero flags and
    records the reason."""
    rows = [(-1.0, 136.0, f"2026-01-{d:02d}", "Yendidori") for d in
            range(1, 29)]
    rows += [(-1.0, 136.0, f"2026-02-{d:02d}", "Yendidori") for d in
             range(1, 29)]
    rows += [(-1.0, 136.0, f"2026-03-{d:02d}", "Yendidori") for d in
             range(1, 32)]
    df = synth(rows)   # 89 consecutive days, dense -> would flag if unguarded
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        out, sites, reason, _ = rec.flag(df, {"min_history_days": 365}, mask)
        assert reason is not None and "365" in reason
        assert sites == []
        assert not out["recurrent_site"].any()
        doc = json.loads(mask.read_text(encoding="utf-8"))
        assert doc["status"] == "skipped" and doc["reason"] == reason
        assert doc["sites"] == []


def test_flagging_preserves_rows_and_ids():
    """Check 4: flagging never changes the row count or any detection_id."""
    df = pd.read_parquet(STORE) if STORE.exists() else synth(
        [(-1.0, 136.0, "2024-01-01", "Yendidori")])
    out, _, reason, _, _ = rec.compute(df, 750.0, 10, 90, 365)
    assert len(out) == len(df)
    assert list(out["detection_id"]) == list(df["detection_id"])
    assert reason is None or not out["recurrent_site"].any()


def test_mask_file_deterministic():
    """Check 5: the same input regenerates a byte-identical mask file."""
    df = synth([(-1.1449, 136.0353, f"2024-{m:02d}-01", "Yendidori")
                for m in range(1, 13)])
    with tempfile.TemporaryDirectory() as td:
        params = {"radius_m": 750.0, "min_days": 10, "min_span_days": 90,
                  "min_history_days": 365}
        out1, sites1, r1, _ = rec.flag(df, params, Path(td) / "a.json")
        out2, sites2, r2, _ = rec.flag(df, params, Path(td) / "b.json")
        a = (Path(td) / "a.json").read_bytes()
        b = (Path(td) / "b.json").read_bytes()
        assert a == b
        assert sites1 == sites2
        assert out1["recurrent_site_id"].tolist() == \
            out2["recurrent_site_id"].tolist()


def _hav_m(lat, lon, lat0=-1.190, lon0=136.108):
    p1, p2 = math.radians(lat0), math.radians(lat)
    a = math.sin((p2 - p1) / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon - lon0) / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))


def test_real_store_pinned_values():
    """PLAN.md 11.2 / Task 04 pins against the backfilled store (skipped
    where the store file is absent)."""
    if not STORE.exists():
        print("SKIP: real store not present")
        return
    df = pd.read_parquet(STORE)
    out, sites, reason, _, _ = rec.compute(df, 750.0, 10, 90, 365)
    assert reason is None
    # Pin the invariant, not the row count: recurrence annotates and never
    # adds or drops a row (AGENTS rule 5). An absolute count would fail on
    # every day the daily job finds a new detection -- inside the daily job
    # itself, gating the publish step, so the pipeline would break precisely
    # when there is something to report. It already had to be hand-edited
    # from 1,078 to 1,089, and CI then hit 1,091.
    assert len(out) == len(df) and \
        list(out["detection_id"]) == list(df["detection_id"])

    # The Saramom source (66-day core + 11/7-day neighbours) is one flagged
    # site, not three fragments.
    near = out[(out["latitude"] - -1.1449).abs() < 750 / M_PER_DEG]
    near = near[(near["longitude"] - 136.0353).abs() < 750 / M_PER_DEG]
    assert len(near) >= 66 and near["recurrent_site"].all()
    site_ids = set(near["recurrent_site_id"].dropna())
    assert len(site_ids) == 1
    days = int(near["recurrent_site_days"].dropna().iloc[0])
    assert days >= 66
    site = next(s for s in sites if s["id"] == site_ids.pop())
    assert site["distinct_days"] == days and site["distrik"] == "Yendidori"

    # The airport cluster is NOT flagged. PLAN.md 11.4: the day-span
    # condition does not protect it -- 10 distinct days spanning 1,018 days
    # meets both thresholds. Only the 750 m radius does, by keeping any one
    # cluster below min_days. Widening radius_m publishes Frans Kaisiepo as
    # a recurrent location, so this assertion is the guard on that.
    # Counts are lower bounds: the daily job adds detections continuously.
    dists = df.apply(lambda r: _hav_m(r["latitude"], r["longitude"]), axis=1)
    air = out[dists <= 3_000]
    assert len(air) >= 39 and air["date_wit"].nunique() >= 10
    assert not air["recurrent_site"].any()


def test_site_id_survives_count_changes():
    """Check 1: a site keeps its ID when its detection and distinct-day
    counts change."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        rows = [(-1.0, 136.0, (date(2024, 1, 1)
                               + timedelta(days=20 * i)).isoformat(),
                 "Yendidori") for i in range(10)]
        out1, sites1, _, v1 = rec.flag(synth(rows), {"min_history_days": 0}, mask)
        assert [s["id"] for s in sites1] == ["R001"] and v1 == 1

        rows2 = rows + [(-1.0, 136.0, f"2025-0{m}-15", "Yendidori")
                        for m in range(1, 6)]
        out2, sites2, _, v2 = rec.flag(synth(rows2), {"min_history_days": 0}, mask)
        assert [s["id"] for s in sites2] == ["R001"]
        assert sites2[0]["distinct_days"] == 15 > sites1[0]["distinct_days"]
        assert v2 == v1
        assert out2["recurrent_site_id"].tolist() == ["R001"] * 15


def test_site_id_survives_overtaking():
    """Check 2: when site B overtakes site A in distinct days, IDs stay with
    their places instead of following the rank."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        a = [(-1.0, 136.0, (date(2024, 1, 1)
                            + timedelta(days=15 * i)).isoformat(),
              "Yendidori") for i in range(12)]
        b = [(-2.0, 136.5, (date(2024, 1, 1)
                            + timedelta(days=20 * i)).isoformat(),
              "Biak Timur") for i in range(10)]
        _, sites1, _, _ = rec.flag(synth(a + b), {"min_history_days": 0}, mask)
        m1 = {s["distrik"]: s["id"] for s in sites1}
        assert len(set(m1.values())) == 2
        d1 = {s["distrik"]: s["distinct_days"] for s in sites1}
        assert d1["Yendidori"] > d1["Biak Timur"]

        # B grows to 20 days, overtaking A's 10. Ranks would swap the IDs;
        # the registry must not.
        b2 = [(-2.0, 136.5, (date(2024, 1, 1)
                             + timedelta(days=10 * i)).isoformat(),
               "Biak Timur") for i in range(20)]
        _, sites2, _, _ = rec.flag(synth(a + b2), {"min_history_days": 0}, mask)
        m2 = {s["distrik"]: s["id"] for s in sites2}
        assert m2 == m1
        d2 = {s["distrik"]: s["distinct_days"] for s in sites2}
        assert d2["Biak Timur"] > d2["Yendidori"]


def test_rebuild_after_deletion_increments_registry_version():
    """Check 3: with both mask copies gone, IDs are reassigned and
    registry_version increments past the value the deleted files carried.
    The hint stands in for the durable manifest ledger the ingest uses."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        publish = Path(td) / "docs" / rec.RECURRENT_SITES_FILENAME
        rows = [(-1.0, 136.0, (date(2024, 1, 1)
                               + timedelta(days=20 * i)).isoformat(),
                 "Yendidori") for i in range(10)]
        _, _, _, v1 = rec.flag(synth(rows), {"min_history_days": 0}, mask, publish_path=publish)
        assert v1 == 1
        mask.unlink()
        publish.unlink()
        _, _, _, v2 = rec.flag(synth(rows), {"min_history_days": 0}, mask, publish_path=publish,
                               prior_version_hint=v1)
        assert v2 == 2
        doc = json.loads(mask.read_text(encoding="utf-8"))
        assert doc["registry_version"] == 2


def test_published_copy_preserves_ids_when_working_copy_deleted():
    """Registry matching falls back to the published copy, so clearing
    data/processed/ does not renumber anything and does not bump."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        publish = Path(td) / "docs" / rec.RECURRENT_SITES_FILENAME
        rows = [(-1.0, 136.0, (date(2024, 1, 1)
                               + timedelta(days=20 * i)).isoformat(),
                 "Yendidori") for i in range(10)]
        rec.flag(synth(rows), {"min_history_days": 0}, mask, publish_path=publish)
        mask.unlink()
        _, sites, _, v = rec.flag(synth(rows), {"min_history_days": 0}, mask,
                                  publish_path=publish)
        assert [s["id"] for s in sites] == ["R001"]
        assert v == 1
        assert json.loads(publish.read_text(encoding="utf-8")) \
            ["registry_version"] == 1


def test_split_keeps_id_with_larger_fragment():
    """A site splitting in two: the larger fragment keeps the ID, the other
    is new, and the file says so."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        rows = [(-1.0, 136.0, (date(2024, 1, 1)
                               + timedelta(days=20 * i)).isoformat(),
                 "Yendidori") for i in range(10)]
        rec.flag(synth(rows), {"min_history_days": 0}, mask)

        # Two clusters now: each 675 m from the old centroid (inside its
        # radius) but 1.35 km apart from each other, so centroid clustering
        # keeps them separate. The northern one has more detections.
        north = [(-1.0 - 675 * DEG, 136.0, (date(2024, 1, 1)
                  + timedelta(days=20 * i)).isoformat(), "Yendidori")
                 for i in range(12)]
        south = [(-1.0 + 675 * DEG, 136.0, (date(2024, 1, 1)
                  + timedelta(days=20 * i)).isoformat(), "Yendidori")
                 for i in range(10)]
        out, sites, _, _ = rec.flag(synth(north + south), {"min_history_days": 0}, mask)
        ids = {s["id"] for s in sites}
        assert len(ids) == 2
        doc = json.loads(mask.read_text(encoding="utf-8"))
        assert any("split" in n for n in doc["notes"])
        inherited = [s["id"] for s in sites if s["detections"] == 12]
        north_ids = set(out[out["latitude"] < -1.0]
                        ["recurrent_site_id"].dropna())
        assert north_ids == set(inherited)


def test_numbers_never_reused():
    """A site that stops qualifying does not free its number: the next new
    site takes the next unused number."""
    with tempfile.TemporaryDirectory() as td:
        mask = Path(td) / rec.RECURRENT_SITES_FILENAME
        a = [(-1.0, 136.0, (date(2024, 1, 1)
                            + timedelta(days=20 * i)).isoformat(),
              "Yendidori") for i in range(10)]
        b = [(-2.0, 136.5, (date(2024, 1, 1)
                            + timedelta(days=15 * i)).isoformat(),
              "Biak Timur") for i in range(10)]
        rec.flag(synth(a + b), {"min_history_days": 0}, mask)
        # Site A goes quiet; a brand-new site appears far away.
        c = [(-3.0, 137.0, (date(2024, 1, 1)
                            + timedelta(days=20 * i)).isoformat(),
              "Numfor Timur") for i in range(10)]
        _, sites, _, _ = rec.flag(synth(b + c), {"min_history_days": 0}, mask)
        # Biak Timur keeps its inherited ID (whichever of R001/R002 the
        # first run gave it); the new site takes the next unused number.
        bt = next(s for s in sites if s["distrik"] == "Biak Timur")
        nt = next(s for s in sites if s["distrik"] == "Numfor Timur")
        assert bt["id"] in ("R001", "R002")
        assert nt["id"] == "R003"


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
