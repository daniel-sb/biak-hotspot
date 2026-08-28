"""Offline checks for the daily report. No network, no real repo outputs:
the store and all three published files live in a temp directory.

Run with pytest:
    python -m pytest tests/test_report_daily.py
or directly (no pytest needed):
    python tests/test_report_daily.py
"""
import json
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ingest_firms as ing          # noqa: E402
import report_daily as rep          # noqa: E402

BBOX = [134.60, -1.45, 136.70, -0.55]
BOUNDARIES = ing.load_boundaries(ROOT / "data" / "boundaries" / "biak_desa.geojson")
ALL_DISTRIKS = {n[1] for n in BOUNDARIES[2] if n[1]}
assert len(ALL_DISTRIKS) == 24

HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
          "satellite,instrument,confidence,version,bright_ti5,frp,daynight")

# Three satellites observed the AOI on WIT day 2026-08-26; MODIS_NRT is
# deliberately absent from that day. Row 3 crosses the UTC->WIT boundary
# (2026-08-25 16:00 UTC is already 2026-08-26 01:00 WIT). The first three
# rows below are reshuffled into an earlier day to exercise the window.
DAY_ROWS = (
    "-1.1853,136.1297,320,0.5,0.5,2026-08-25,2130,N,VIIRS,n,2.0NRT,290,4.0,D\n"
    "-1.1274,136.0440,320,0.5,0.5,2026-08-26,0630,N20,VIIRS,l,2.0NRT,292,9.5,D\n"
    "-1.3000,136.4000,320,0.5,0.5,2026-08-25,1600,N21,VIIRS,n,2.0NRT,288,0.5,D\n")


def make_store(root: Path) -> Path:
    """Tiny deterministic store: one earlier day plus the covered day."""
    earlier = ing.prepare(HEADER + "\n"
                          + DAY_ROWS.replace("2026-08-25", "2026-08-23")
                          .replace("2026-08-26", "2026-08-23"),
                          BBOX, BOUNDARIES)
    covered = ing.prepare(HEADER + "\n" + DAY_ROWS, BBOX, BOUNDARIES)
    merged = ing.merge_tables(earlier, covered)
    path = root / "processed" / "detections.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(path, index=False)
    return path


def make_cfg(root: Path, build_store: bool = True) -> dict:
    cfg = rep.load_config(ROOT / "config.yaml")
    # Absolute boundary path passes through resolve() unchanged; the store and
    # published outputs stay inside the temp root.
    cfg["admin_polygon"] = ROOT / "data" / "boundaries" / "biak_desa.geojson"
    processed = make_store(root) if build_store \
        else root / "processed" / "detections.parquet"
    cfg["output_paths"] = {
        **cfg["output_paths"],
        "processed": processed,
        "geojson": root / "docs" / "data" / "hotspots_latest.geojson",
        "summary_json": root / "docs" / "data" / "summary_latest.json",
        "brief_dir": root / "docs" / "briefs",
    }
    return cfg


def build_in(td_root: str, now: datetime, day: str | None = None,
             build_store: bool = True):
    return rep.build(make_cfg(Path(td_root), build_store=build_store),
                     Path(td_root), now_utc=now, day=day)


NOW = datetime(2026, 8, 27, 7, 0, 0, tzinfo=timezone.utc)
BRIEF = "docs/briefs/2026-08-26.md"
GEO = "docs/data/hotspots_latest.geojson"
SUMMARY = "docs/data/summary_latest.json"


def test_brief_lists_all_24_districts():
    with tempfile.TemporaryDirectory() as td:
        summary, [brief_path, _, _] = build_in(td, NOW)
        text = brief_path.read_text(encoding="utf-8")
        assert summary["covered_wit_date"] == "2026-08-26"
        for distrik in ALL_DISTRIKS:
            assert f"| {distrik} |" in text, f"{distrik} missing from brief"
        zero_rows = sum(r["detections"] == 0 for r in summary["districts"])
        assert zero_rows == 22  # 24 minus Samofa and Biak Kota
        assert "| 0 |" in text


def test_totals_and_offshore_kept():
    with tempfile.TemporaryDirectory() as td:
        summary, [brief_path, geo_path, _] = build_in(td, NOW)
        assert summary["detections"] == 3
        assert summary["on_land"] == 2
        assert summary["offshore"] == 1
        text = brief_path.read_text(encoding="utf-8")
        assert "offshore/water (kept" in text
        gj = json.loads(geo_path.read_text(encoding="utf-8"))
        # The rolling window also contains the earlier-day clones; scope to
        # the covered WIT day.
        covered_feats = [f for f in gj["features"]
                         if f["properties"]["date_wit"] == "2026-08-26"]
        assert len(covered_feats) == 3
        offshore = [f for f in covered_feats
                    if f["properties"]["on_land"] is False]
        assert len(offshore) == 1
        # Null name columns survive the export as absent/null.
        props = offshore[0]["properties"]
        assert props.get("desa") is None
        assert props.get("kabupaten") is None


def test_silent_source_reported_differently():
    """Three-state provenance (Task 02b): a source whose queries succeeded but
    found nothing renders differently from a source whose query failed or has
    no record - and all three differ from a district's plain zero."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        # No manifest next to the store: observation status is unknown.
        summary, [brief_path, _, _] = build_in(td, NOW)
        by_src = {s["source"]: s for s in summary["sources"]}
        assert by_src["VIIRS_SNPP_NRT"]["status"] == "observed"
        assert by_src["MODIS_NRT"]["detections"] == 0
        assert by_src["MODIS_NRT"]["status"] == "norecord"
        text = brief_path.read_text(encoding="utf-8")
        assert rep.T["state_norecord"] in text          # distinct wording,
        assert rep.T["state_empty"] not in text         # not 'observed-none',
        assert "| 0 |" in text                          # not a plain zero.
        assert rep.T["manifest_missing"] in text


def test_observed_no_detections_vs_failed_vs_counts():
    """One run: counts for observed sources, 'observed, no detections' for a
    successfully queried empty source, 'not observed (fetch failed)' for a
    failed one - plus the incomplete-coverage warning naming exactly the
    unobserved sources. Uses WIT day 2026-08-24, where the synthetic store
    has data from S-NPP and NOAA-21 only."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = make_cfg(root)
        stamp = "2026-08-27T06:00:00Z"

        def m(src, outcome):
            return {"source": src, "chunk_start": "2026-08-22", "days": 4,
                    "outcome": outcome,
                    "rows": None if outcome == "failed" else 0,
                    "utc": stamp}

        entries = [m("MODIS_NRT", "failed"), m("VIIRS_NOAA20_NRT", "cached")]
        (root / "processed" / ing.MANIFEST_FILENAME).write_text(
            json.dumps({"runs": entries}), encoding="utf-8")

        summary, paths = build_in(td, NOW, day="2026-08-24")
        brief_path, sum_path = paths[0], paths[2]
        by_src = {s["source"]: s for s in summary["sources"]}
        assert by_src["VIIRS_SNPP_NRT"] == {"source": "VIIRS_SNPP_NRT",
                                            "detections": 1,
                                            "status": "observed"}
        assert by_src["VIIRS_NOAA21_NRT"]["status"] == "observed"
        assert by_src["VIIRS_NOAA20_NRT"]["status"] == "empty"
        assert by_src["MODIS_NRT"]["status"] == "failed"

        text = brief_path.read_text(encoding="utf-8")
        assert re.search(r"\|\s*VIIRS_NOAA20_NRT\s*\|\s*"
                         r"observed, no detections\s*\|", text)
        assert re.search(r"\|\s*MODIS_NRT\s*\|\s*not observed "
                         r"\(fetch failed\)\s*\|", text)
        assert re.search(r"\|\s*VIIRS_SNPP_NRT\s*\|\s*1\s*\|", text)
        # Incomplete-coverage warning names only the truly unobserved source.
        warn = rep.T["coverage_incomplete"].format(list="MODIS_NRT")
        assert warn in text
        assert rep.T["manifest_missing"] not in text
        published = json.loads(sum_path.read_text(encoding="utf-8"))
        assert published["manifest_found"] is True
        assert [s["status"] for s in published["sources"]] == \
            ["observed", "empty", "observed", "failed"]


def test_unrelated_manifest_leaves_day_unknown():
    """A manifest that exists but does not cover this WIT day is still 'not
    observed (no record)' - just without claiming the whole file is missing."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = make_cfg(root)
        (root / "processed" / ing.MANIFEST_FILENAME).write_text(
            json.dumps({"runs": [{"source": "MODIS_NRT",
                                  "chunk_start": "2026-07-01", "days": 5,
                                  "outcome": "fetched", "rows": 7,
                                  "utc": "2026-07-02T00:00:00Z"}]}),
            encoding="utf-8")
        summary, [brief_path, _, _] = build_in(td, NOW)
        modis = {s["source"]: s for s in summary["sources"]}["MODIS_NRT"]
        assert modis == {"source": "MODIS_NRT", "detections": 0,
                         "status": "norecord"}
        text = brief_path.read_text(encoding="utf-8")
        assert rep.T["state_norecord"] in text
        assert rep.T["manifest_missing"] not in text
        assert rep.T["coverage_incomplete"].format(list="MODIS_NRT") in text


def test_geojson_rfc7946_shape():
    with tempfile.TemporaryDirectory() as td:
        _, [_, geo_path, _] = build_in(td, NOW)
        gj = json.loads(geo_path.read_text(encoding="utf-8"))
        assert gj["type"] == "FeatureCollection"
        feats = gj["features"]
        ids = [f["properties"]["detection_id"] for f in feats]
        assert ids == sorted(ids)                  # deterministic order
        pt = feats[0]["geometry"]
        assert pt["type"] == "Point"
        lon, lat = pt["coordinates"]
        assert isinstance(lon, float) and isinstance(lat, float)
        confidences = {f["properties"]["confidence"] for f in feats}
        assert all(isinstance(c, str) for c in confidences)   # never coerced
        assert any(f["properties"]["frp"] == 9.5 for f in feats)


def test_deterministic_apart_from_timestamp():
    stamp = re.compile(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
        r"|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def snapshot(td_root, now):
        build_in(td_root, now)
        root = Path(td_root)
        return {rel: (root / rel).read_bytes()
                for rel in (BRIEF, GEO, SUMMARY)}

    with tempfile.TemporaryDirectory() as ta, \
            tempfile.TemporaryDirectory() as tb:
        a = snapshot(ta, NOW)
        b = snapshot(tb, NOW + timedelta(hours=3, minutes=17))
    for name in a:
        raw_a, raw_b = a[name], b[name]
        assert raw_a != raw_b, f"{name}: timestamp did not change"
        norm_a = stamp.sub("<STAMP>", raw_a.decode("utf-8"))
        norm_b = stamp.sub("<STAMP>", raw_b.decode("utf-8"))
        assert norm_a == norm_b, f"{name}: non-timestamp content drifted"


def test_brief_surfaces_recurrent_sites_neutrally():
    """Task 04: flagged rows get their own section with neutral wording, and
    are never silently excluded from the counts (they are not excluded from
    any count by construction - this pins the wording and the visibility)."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        store = Path(td) / "processed" / "detections.parquet"
        df = pd.read_parquet(store)
        day = df["date_wit"] == "2026-08-26"
        on_biak_kota = day & (df["distrik"] == "Biak Kota")
        df["recurrent_site_id"] = pd.Series(
            ["R001" if m else None for m in on_biak_kota], index=df.index,
            dtype=object)
        df["recurrent_site_days"] = pd.Series(
            [74 if m else pd.NA for m in on_biak_kota], index=df.index,
            dtype="Int64")
        df["recurrent_site"] = pd.Series(on_biak_kota.tolist(),
                                         index=df.index, dtype=bool)
        df.to_parquet(store, index=False)

        summary, [brief_path, _, sum_path] = build_in(td, NOW,
                                                      build_store=False)
        assert summary["recurrent_today"] == [
            {"site_id": "R001", "distrik": "Biak Kota",
             "detections_today": 1, "days_total": 74}]
        text = brief_path.read_text(encoding="utf-8")
        assert rep.T["recurrent_heading"] in text
        assert "R001" in text and "(Biak Kota)" in text
        # Published prose: the singular must read "1 detection today".
        assert "1 detection today" in text
        assert "detection(s)" not in text
        assert rep.T["recurrent_note"] in text
        # The brief counts stay whole: the flagged detection is still in the
        # total and in its district row.
        assert "**3 thermal anomaly detections**" in text
        assert "| Biak Kota | Biak Numfor | 1 |" in text
        for banned in ("false positive", "industrial", "non-fire"):
            assert banned not in text, banned
        published = json.loads(sum_path.read_text(encoding="utf-8"))
        assert published["recurrent_today"][0]["site_id"] == "R001"

        # Plural: a second flagged detection at the same site renders
        # "2 detections today".
        m2 = df["distrik"] == "Samofa"
        df.loc[m2, "recurrent_site_id"] = "R001"
        df.loc[m2, "recurrent_site_days"] = 74
        df.loc[m2, "recurrent_site"] = True
        df.to_parquet(store, index=False)
        summary, [brief_path, _, _] = build_in(td, NOW, build_store=False)
        assert summary["recurrent_today"][0]["detections_today"] == 2
        assert "2 detections today" in \
            brief_path.read_text(encoding="utf-8")

        # A store without the flag columns (pre-Task-04) renders no section.
        df = df.drop(columns=["recurrent_site_id", "recurrent_site_days",
                              "recurrent_site"])
        df.to_parquet(store, index=False)
        summary, [brief_path, _, _] = build_in(td, NOW, build_store=False)
        assert summary["recurrent_today"] == []
        assert rep.T["recurrent_heading"] not in \
            brief_path.read_text(encoding="utf-8")


def _write_evening(root: Path, brief_day: str, rows):
    """Write the Himawari evening parquet for the night before brief_day."""
    prev = (datetime.fromisoformat(brief_day) - timedelta(days=1)) \
        .date().isoformat()
    p = Path(root) / "processed" / f"himawari_evening_{prev}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


def _evening_row(wit, lat, lon, flagged, night, ocean=False, anom=25.0,
                 utc="2026-08-25T15:30:00Z"):
    return {"acq_time_utc": utc,
            "acq_time_wit": wit,
            "lat": lat, "lon": lon,
            "bt07": 310.0, "bt14": 296.0,
            "bt07_minus_bt14": 14.0,
            "bt07_background": 296.0,
            "bt07_anomaly": anom,
            "is_night": night, "flagged": flagged,
            "ocean_sample": ocean}


def test_evening_zero_flags_wording():
    """Task 06 check 3+5, restated by 06b: zero AFTER-DARK flags -> the exact
    mandated sentence (regardless of daylight flags), the not-evidence
    caveat, and missing slots counted, never a silent zero. Forbidden
    all-clear phrasings must not appear."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T15:30:00+09:00", -1.14, 136.03,
                         False, True, ocean=True, utc="2026-08-25T06:30:00Z"),
            _evening_row("2026-08-25T16:00:00+09:00", -1.14, 136.04,
                         False, True, utc="2026-08-25T07:00:00Z"),
        ])
        summary, [brief_path, _, _] = build_in(td, NOW)
        text = brief_path.read_text(encoding="utf-8")
        assert "No evening thermal anomaly above threshold after dark." in text
        assert "not evidence that nothing burned" in text
        assert "Slots retrieved: 2 of 21 expected" in text
        assert "19 expected slot(s) missing" in text
        for banned in ("all-clear", "no fire", "the evening was clear",
                       "conditions improved"):
            assert banned not in text, banned
        ev = json.loads((Path(td) / "docs/data/summary_latest.json")
                        .read_text(encoding="utf-8"))["evening"]
        assert ev["state"] == "ok"
        assert ev["slots_missing"] == 19
        assert ev["night_flags"] == 0
        assert ev["flags"] == []


def test_after_dark_zero_with_daylight_flags_still_leads_with_null():
    """06b check 1: daylight flags alone do not suppress the mandated
    after-dark sentence, and daylight rows are summarised on one line,
    never enumerated."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T16:30:00+09:00", -1.14, 136.03,
                         True, False, anom=12.5,
                         utc="2026-08-25T07:30:00Z"),
            _evening_row("2026-08-25T17:00:00+09:00", -1.15, 136.04,
                         True, False, anom=20.0,
                         utc="2026-08-25T08:00:00Z"),
        ])
        summary, [brief_path, _, _] = build_in(td, NOW)
        assert summary["evening"]["night_flags"] == 0
        assert summary["evening"]["daylight_flags"] == 2
        text = brief_path.read_text(encoding="utf-8")
        assert "No evening thermal anomaly above threshold after dark." in text
        assert "Daylight flags before sunset (unreliable - reflected " \
               "sunlight): 2 pixels, 16:30-17:00 WIT, peak anomaly +20.0 K" \
               in text
        # never enumerated, never a combined headline
        assert "16:30 WIT, -1.14" not in text
        assert "Pixels flagged above threshold: 2" not in text


def test_after_dark_flag_listed_individually():
    """06b check 3: an after-dark flag is its own bullet and is never
    summarised away."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T19:30:00+09:00", -1.14, 136.03,
                         True, True, anom=15.0,
                         utc="2026-08-25T10:30:00Z"),
        ])
        summary, [brief_path, _, _] = build_in(td, NOW)
        assert summary["evening"]["night_flags"] == 1
        assert summary["evening"]["flags"][0]["anomaly_k"] == 15.0
        text = brief_path.read_text(encoding="utf-8")
        assert "- 19:30 WIT, -1.14, 136.03: B07 anomaly +15.0 K" in text


def test_largest_after_dark_anomaly_line():
    """06b: with nothing flagged after dark, the largest sub-threshold
    after-dark anomaly is reported with the mandatory 'not a detection'
    clause."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T18:30:00+09:00", -1.1857, 136.1186,
                         False, True, anom=5.6,
                         utc="2026-08-25T09:30:00Z"),
            _evening_row("2026-08-25T20:00:00+09:00", -1.1857, 136.1186,
                         False, True, anom=1.2,
                         utc="2026-08-25T11:00:00Z"),
        ])
        summary, [brief_path, _, _] = build_in(td, NOW)
        la = summary["evening"]["largest_after_dark"]
        assert la["anomaly_k"] == 5.6 and la["wit"] == "18:30"
        text = brief_path.read_text(encoding="utf-8")
        assert ("Largest after-dark anomaly: +5.6 K at 18:30 WIT "
                "(-1.1857, 136.1186). Below the 10 K flag threshold and "
                "not a detection.") in text


def test_evening_presunset_flag_labelled_daylight():
    """Task 06 check 4, restated by 06b: a pre-sunset flag is daylight and
    unreliable, summarised on one line, and the after-dark result still
    leads."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T16:30:00+09:00", -1.1449, 136.0353,
                         True, False, anom=12.5),
        ])
        summary, [brief_path, _, _] = build_in(td, NOW)
        assert summary["evening"]["daylight_flags"] == 1
        assert summary["evening"]["night_flags"] == 0
        text = brief_path.read_text(encoding="utf-8")
        assert "No evening thermal anomaly above threshold after dark." in text
        assert ("Daylight flags before sunset (unreliable - reflected "
                "sunlight): 1 pixel, 16:30-16:30 WIT, peak anomaly +12.5 K"
                in text)
        # the daylight row itself is never enumerated
        assert "- 16:30 WIT, -1.1449" not in text


def test_evening_unavailable_state():
    """A missing evening file is a stated gap, never a zero."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))     # no evening parquet written
        summary, [brief_path, _, _] = build_in(td, NOW)
        assert summary["evening"]["state"] == "unavailable"
        text = brief_path.read_text(encoding="utf-8")
        assert "Evening product unavailable" in text
        assert "not a zero" in text
        assert "No evening thermal anomaly" not in text


def test_evening_section_deterministic():
    """Check 6 (brief side): the same evening parquet renders identical
    section lines."""
    with tempfile.TemporaryDirectory() as td:
        cfg = make_cfg(Path(td))
        _write_evening(td, "2026-08-26", [
            _evening_row("2026-08-25T16:30:00+09:00", -1.1449, 136.0353,
                         True, False),
        ])
        _, lines1 = rep.evening_section(cfg, Path(td), "2026-08-26")
        _, lines2 = rep.evening_section(cfg, Path(td), "2026-08-26")
        assert lines1 == lines2


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
