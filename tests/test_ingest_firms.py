"""Offline checks for the FIRMS ingest, using committed fixtures in data/raw/.

Never touches the network. Run with pytest:
    python -m pytest tests/test_ingest_firms.py
or directly (no pytest needed):
    python tests/test_ingest_firms.py
"""
import hashlib
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ingest_firms as ing  # noqa: E402

RAW = ROOT / "tests" / "fixtures"
BBOX = [134.60, -1.45, 136.70, -0.55]
BOUNDARIES = ing.load_boundaries(ROOT / "data" / "boundaries" / "biak_desa.geojson")

FAMILIES = ["MODIS_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT",
            "VIIRS_NOAA21_NRT"]

# Availability table exactly as observed on 2026-08-27 (task statement).
# Dates roll forward continuously; production fetches this live, tests inject.
def d(s):
    return date.fromisoformat(s)


AVAIL = {
    "MODIS_SP": (d("2000-11-01"), d("2026-04-30")),
    "MODIS_NRT": (d("2026-05-01"), d("2026-08-27")),
    "VIIRS_SNPP_SP": (d("2012-01-20"), d("2026-04-27")),
    "VIIRS_SNPP_NRT": (d("2026-04-28"), d("2026-08-27")),
    "VIIRS_NOAA20_SP": (d("2018-04-01"), d("2026-05-31")),
    "VIIRS_NOAA20_NRT": (d("2026-06-01"), d("2026-08-27")),
    "VIIRS_NOAA21_NRT": (d("2024-01-17"), d("2026-08-27")),
}


def coverage(jobs) -> dict[str, set]:
    """(source -> set of requested dates served by it) from planned jobs."""
    out: dict[str, set] = {}
    for src, start, days in jobs:
        s = d(start)
        for i in range(days):
            out.setdefault(src, set()).add(s + timedelta(days=i))
    return out


def window_days(win, lo: date, hi: date) -> set:
    return {lo + timedelta(days=i)
            for i in range((hi - lo).days + 1)
            if win[0] <= lo + timedelta(days=i) <= win[1]}

# Minimal realistic VIIRS/MODIS bodies for edge cases the committed fixtures
# do not cover (21:00 UTC day boundary, rows outside the bbox).
HEADER = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
          "satellite,instrument,confidence,version,bright_ti5,frp,daynight")


def fixture(name: str) -> str:
    return (RAW / name).read_text()


def test_detection_id_stable_and_correct():
    first = ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX)
    second = ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX)
    assert list(first["detection_id"]) == list(second["detection_id"])
    # Anchor to the specified algorithm: satellite|instrument|acq_date|acq_time|lat|lon,
    # lat/lon formatted to exactly 5 decimals.
    expected = hashlib.sha1(
        b"N20|VIIRS|2026-08-18|404|-1.13279|135.99571").hexdigest()
    assert first.iloc[0]["detection_id"] == expected


def test_parse_merge_is_idempotent():
    once = ing.prepare(fixture("VIIRS_SNPP_NRT_2026-08-18.csv"), BBOX)
    twice = ing.merge_tables(once, ing.prepare(
        fixture("VIIRS_SNPP_NRT_2026-08-18.csv"), BBOX))
    assert len(twice) == len(once) > 0
    assert sorted(twice["detection_id"]) == sorted(once["detection_id"])


def test_cache_filename_encodes_day_range():
    five = ing.cache_path(Path("d"), "VIIRS_SNPP_NRT", "2026-08-13", 5)
    three = ing.cache_path(Path("d"), "VIIRS_SNPP_NRT", "2026-08-13", 3)
    assert five.name == "VIIRS_SNPP_NRT_2026-08-13_5d.csv"
    assert three.name == "VIIRS_SNPP_NRT_2026-08-13_3d.csv"
    assert five != three


def test_windows_touching_today_or_yesterday_refetch():
    today = date(2026, 8, 27)
    assert ing.should_refetch("2026-08-23", 5, today)     # ends today
    assert ing.should_refetch("2026-08-22", 5, today)     # ends yesterday
    assert not ing.should_refetch("2026-08-20", 5, today)  # ended 2+ days ago
    assert not ing.should_refetch("2026-08-13", 5, today)  # wholly past


def test_utc_to_wit_day_boundary():
    raw = HEADER + ("\n"
                    "-0.90,135.50,320,0.5,0.5,2026-08-25,2100,N20,VIIRS,n,"
                    "2.0NRT,290,5,D\n"
                    "-0.90,135.50,320,0.5,0.5,2026-08-25,1300,N20,VIIRS,n,"
                    "2.0NRT,290,5,D\n")
    df = ing.prepare(raw, BBOX)
    late = df[df["acq_time"] == "2100"].iloc[0]
    early = df[df["acq_time"] == "1300"].iloc[0]
    assert late["datetime_utc"] == pd.Timestamp("2026-08-25 21:00:00+00:00")
    # 21:00 UTC + 9h is 06:00 WIT on the next day.
    assert late["date_wit"] == "2026-08-26"
    assert late["datetime_wit"] == pd.Timestamp("2026-08-26 06:00:00+09:00")
    assert early["date_wit"] == "2026-08-25"


def test_confidence_not_coerced():
    viirs = ing.prepare(fixture("VIIRS_NOAA21_NRT_2026-08-23.csv"), BBOX)
    modis = ing.prepare(fixture("MODIS_NRT_2026-08-18.csv"), BBOX)
    both = ing.merge_tables(viirs, modis)
    confidences = set(both["confidence"])
    assert {"n", "l"} <= confidences
    assert any(str(c).isdigit() for c in confidences), \
        "MODIS numeric confidence values were lost or coerced"
    assert confidences == {str(c) for c in confidences}


def test_cross_satellite_and_frp_survive():
    viirs = ing.prepare(fixture("VIIRS_NOAA21_NRT_2026-08-23.csv"), BBOX)
    modis = ing.prepare(fixture("MODIS_NRT_2026-08-18.csv"), BBOX)
    both = ing.merge_tables(viirs, modis)
    assert len(both) == len(viirs) + len(modis)
    assert set(both["satellite"]) >= {"N21", "Aqua"}
    assert both["frp"].dtype.kind == "f"
    aqua = both.loc[both["satellite"] == "Aqua", "frp"]
    assert (aqua == 4.7).any()


def test_coordinates_numeric():
    df = ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX)
    assert df["latitude"].dtype.kind == "f"
    assert df["longitude"].dtype.kind == "f"


def test_clip_to_bbox():
    row = "-0.90,{lon},320,0.5,0.5,2026-08-25,2100,N20,VIIRS,n,2.0NRT,290,5,D"
    raw = HEADER + "\n" + row.format(lon=136.00) + "\n" + row.format(lon=139.00) + "\n"
    df = ing.prepare(raw, BBOX)
    assert len(df) == 1
    assert float(df.iloc[0]["longitude"]) == 136.0


def test_rerun_roundtrip_with_parquet_store():
    """The path that can actually break: write Parquet, read back, merge,
    write again. Must not duplicate rows or drift any stored value."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "detections.parquet"

        ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX) \
            .to_parquet(path, index=False)

        first = pd.read_parquet(path)
        fresh = ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX)
        ing.merge_tables(first, fresh).to_parquet(path, index=False)

        second = pd.read_parquet(path)
        assert len(second) == len(first) > 0
        a = first.set_index("detection_id").sort_index()
        b = second.set_index("detection_id").sort_index()
        assert list(b.index) == list(a.index)
        assert (b["date_wit"] == a["date_wit"]).all()


def test_fixture_corpus_matches_reference_counts():
    """PLAN.md 10.4 reference pull: 653 detections, peak 283 on WIT day
    2026-08-22. Committed fixtures cover only part of the window via three
    chunk starts per source; parsing all of them must reproduce the totals."""
    merged = ing.merge_tables(*[ing.prepare(f.read_text(), BBOX)
                                for f in sorted(RAW.glob("*.csv"))])
    counts = merged.groupby("date_wit").size()
    assert len(merged) == 653
    assert counts.get("2026-08-22", 0) == 283


def test_pinned_admin_assignments():
    raw = HEADER + (
        "\n"
        "-1.1274,136.0440,320,0.5,0.5,2026-08-25,0630,N,VIIRS,n,2.0NRT,290,5,D\n"
        "-1.1853,136.1297,320,0.5,0.5,2026-08-25,0700,N20,VIIRS,n,2.0NRT,290,5,D\n"
        "-1.3000,136.4000,320,0.5,0.5,2026-08-25,0730,N21,VIIRS,n,2.0NRT,290,5,D\n")
    df = ing.prepare(raw, BBOX, BOUNDARIES)

    def at(lat, lon):
        m = df[(df["latitude"] == lat) & (df["longitude"] == lon)]
        assert len(m) == 1
        return m.iloc[0]

    p1, p2, p3 = at(-1.1274, 136.0440), at(-1.1853, 136.1297), \
        at(-1.3000, 136.4000)
    assert (p1["desa"], p1["distrik"], p1["kabupaten"]) == \
        ("Sambawofuar", "Samofa", "Biak Numfor")
    assert (p2["desa"], p2["distrik"], p2["kabupaten"]) == \
        ("Swapodibo", "Biak Kota", "Biak Numfor")
    assert bool(p3["on_land"]) is False
    for col in ("desa", "distrik", "kabupaten"):
        assert pd.isna(p3[col]), f"outside-polygon detection got a {col}"


def test_offshore_detection_kept_not_dropped():
    """A detection outside every polygon must survive ingest (AGENTS rule 5):
    flagged on_land=False with null names, never deleted."""
    raw = HEADER + ("\n"
                    "-1.3000,136.4000,320,0.5,0.5,2026-08-25,0730,N21,"
                    "VIIRS,n,2.0NRT,290,5,D\n")
    df = ing.prepare(raw, BBOX, BOUNDARIES)
    assert len(df) == 1
    row = df.iloc[0]
    assert bool(row["on_land"]) is False
    assert all(pd.isna(row[c]) for c in ("desa", "distrik", "kabupaten"))
    assert row["detection_id"]  # otherwise-normal row


def test_fixture_corpus_admin_counts():
    """Independently verified: 651 of the 653 fixture detections fall inside
    a desa polygon, 2 offshore (NOAA-20 pixels in Biak bay), across 18 of the
    24 distrik."""
    merged = ing.merge_tables(*[ing.prepare(f.read_text(), BBOX, BOUNDARIES)
                                for f in sorted(RAW.glob("*.csv"))])
    assert len(merged) == 653                     # nothing lost to assignment
    assert int(merged["on_land"].sum()) == 651
    assert int((~merged["on_land"]).sum()) == 2
    assert merged.loc[merged["on_land"], "distrik"].nunique() == 18


def test_normalise_idempotent_and_contract_holding():
    raw = HEADER + ("\n"
                    "-0.90,135.50,320,0.5,0.5,2026-08-25,2100,N20,VIIRS,"
                    "31,2.0NRT,290,7,D\n")
    df = ing.prepare(raw, BBOX)          # no boundaries -> on_land absent
    once = ing.normalise(df)
    twice = ing.normalise(once)
    pd.testing.assert_frame_equal(once, twice)
    # Dtypes enforced...
    assert once["latitude"].dtype.kind == "f"
    assert once["longitude"].dtype.kind == "f"
    assert once["frp"].dtype.kind == "f"
    assert once["on_land"].dtype == "boolean"
    assert once["detection_id"].dtype == "string"
    # ...confidence stays textual, including the MODIS numeric-as-string...
    conf = once["confidence"].iloc[0]
    assert isinstance(conf, str) and conf == "31"
    # ...and acq fields are untouched.
    assert once["acq_date"].iloc[0] == "2026-08-25"
    assert once["acq_time"].iloc[0] == "2100"


def test_merge_retroactively_fixes_stored_string_coordinates():
    """A legacy store written before the float fix must come out of
    merge_tables() with float coordinates, unchanged IDs, and working
    arithmetic - without any rows being dropped."""
    fresh = ing.prepare(fixture("VIIRS_NOAA20_NRT_2026-08-18.csv"), BBOX,
                        BOUNDARIES)
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "legacy.parquet"
        legacy = fresh.copy()
        for col in ("latitude", "longitude", "frp"):
            legacy[col] = legacy[col].astype(str)
        legacy.to_parquet(path, index=False)
        stored = pd.read_parquet(path)
        assert stored["latitude"].dtype.kind not in "f"   # reproduces defect

        merged = ing.merge_tables(stored, fresh)
        assert len(merged) == len(fresh)
        assert list(merged["detection_id"]) == \
            sorted(fresh["detection_id"])                 # ids untouched
        assert merged["latitude"].dtype.kind == "f"
        assert merged["longitude"].dtype.kind == "f"
        assert merged["frp"].dtype.kind == "f"
        diff = merged["latitude"] - 0.1                   # must not raise
        assert abs(float(diff.sum())) > 0


def test_manifest_appends_across_runs():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / ing.MANIFEST_FILENAME
        first = {"source": "MODIS_NRT", "chunk_start": "2026-08-25",
                 "days": 3, "outcome": "failed", "rows": None,
                 "utc": "2026-08-27T00:00:00Z"}
        second = {"source": "MODIS_NRT", "chunk_start": "2026-08-25",
                  "days": 3, "outcome": "fetched", "rows": 4,
                  "utc": "2026-08-27T06:00:00Z"}
        ing.append_manifest(path, [first])
        ing.append_manifest(path, [second])
        runs = json.loads(path.read_text(encoding="utf-8"))["runs"]
        assert runs == [first, second]   # history accumulates, never overwritten


def test_parse_availability_table():
    text = ("data_id,min_date,max_date\n"
            "VIIRS_SNPP_SP , 2012-01-20 , 2026-04-27\n"
            "VIIRS_SNPP_NRT,2026-04-28,2026-08-27\n")
    table = ing.parse_availability(text)
    assert table["VIIRS_SNPP_SP"] == (d("2012-01-20"), d("2026-04-27"))
    assert table["VIIRS_SNPP_NRT"] == (d("2026-04-28"), d("2026-08-27"))
    # A header-only body is a valid (if alarming) empty table; garbage is not.
    assert ing.parse_availability("data_id,min_date,max_date\n") == {}
    for bad in ("no header here\n",
                "data_id,min_date,max_date\nX,bogus,2026-01-01\n"):
        try:
            ing.parse_availability(bad)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass


def test_backfill_unique_source_per_satellite_day():
    """Check 1 + determinism: every requested day gets exactly one source per
    satellite - _SP where the archive window covers it, else _NRT."""
    lo, hi = d("2024-01-01"), d("2026-08-27")
    jobs1, _ = ing.plan_backfill(AVAIL, FAMILIES, lo, hi)
    jobs2, _ = ing.plan_backfill(AVAIL, FAMILIES, lo, hi)
    assert jobs1 == jobs2                       # deterministic plan

    cov = coverage(jobs1)
    for fam in FAMILIES:
        sp_id = fam[:-4] + "_SP"
        per_day: dict[date, set] = {}
        for s in (fam, sp_id):
            for dt in cov.get(s, set()):
                per_day.setdefault(dt, set()).add(s)
        assert all(len(v) == 1 for v in per_day.values()), \
            f"{fam}: a date resolved to multiple sources"
        expect_sp = window_days(AVAIL[sp_id], lo, hi) if sp_id in AVAIL \
            else set()
        assert cov.get(sp_id, set()) == expect_sp
        assert cov.get(fam, set()) == window_days(AVAIL[fam], lo, hi)


def test_straddle_split_at_boundary():
    """Check 2: a range crossing VIIRS S-NPP's SP->NRT boundary splits at it,
    never sending one satellite-day to both sources."""
    jobs, gaps = ing.plan_backfill(
        AVAIL, ["VIIRS_SNPP_NRT"], d("2026-04-20"), d("2026-05-02"))
    assert gaps == []
    # SP run 04-20..04-27 (8 days) tiles as 5+3; NRT run 04-28..05-02 (5d).
    assert jobs == [("VIIRS_SNPP_SP", "2026-04-20", 5),
                    ("VIIRS_SNPP_SP", "2026-04-25", 3),
                    ("VIIRS_SNPP_NRT", "2026-04-28", 5)]


def test_unavailable_recorded_not_zero():
    """Check 3: NOAA-21 has no data before its window opens; those days are
    gap records, not silently-empty fetches."""
    jobs, gaps = ing.plan_backfill(AVAIL, FAMILIES,
                                   d("2024-01-01"), d("2026-08-27"))
    assert gaps == [{"source": "VIIRS_NOAA21_NRT",
                     "chunk_start": "2024-01-01", "days": 16}]
    n21_dates = set()
    for src, start, days in jobs:
        if src.startswith("VIIRS_NOAA21"):
            s = d(start)
            n21_dates |= {s + timedelta(days=i) for i in range(days)}
    assert min(n21_dates) == d("2024-01-17")

    # Synthetic hole: with MODIS archive missing entirely and NRT starting
    # later than requested, the whole prefix is one contiguous gap.
    avail2 = {k: v for k, v in AVAIL.items() if k != "MODIS_SP"}
    avail2["MODIS_NRT"] = (d("2026-05-20"), d("2026-08-27"))
    jobs2, gaps2 = ing.plan_backfill(avail2, ["MODIS_NRT"],
                                     d("2024-06-10"), d("2026-08-27"))
    assert gaps2 == [{"source": "MODIS_NRT",
                      "chunk_start": "2024-06-10", "days": 709}]
    cov2 = coverage(jobs2)
    hole = {d("2024-06-10") + timedelta(days=i) for i in range(709)}
    assert not (cov2["MODIS_NRT"] & hole), "a chunk reached into the gap"
    assert min(cov2["MODIS_NRT"]) == d("2026-05-20")


def test_noaa21_no_sp_counterpart_resolves_to_nrt():
    """Check 4: a satellite without an archive twin uses NRT across its whole
    available range."""
    jobs, gaps = ing.plan_backfill(AVAIL, ["VIIRS_NOAA21_NRT"],
                                   d("2023-12-01"), d("2026-08-27"))
    assert all(src == "VIIRS_NOAA21_NRT" for src, _, _ in jobs)
    cov = coverage(jobs)
    want = window_days(AVAIL["VIIRS_NOAA21_NRT"], d("2023-12-01"),
                       d("2026-08-27"))
    assert cov["VIIRS_NOAA21_NRT"] == want
    assert len(gaps) == 1   # only the pre-window prefix of the request


def test_tiling_exact_bounded_gapless():
    """Check 5: over long ranges chunks stay <=5 days, tile each same-source
    run exactly (contiguous starts, no gaps, no overlaps), and the union of
    chunk dates equals the covered part of the requested range."""
    lo, hi = d("2019-01-01"), d("2026-08-27")   # crosses all boundaries twice
    jobs, gaps = ing.plan_backfill(AVAIL, FAMILIES, lo, hi)

    for fam in FAMILIES:
        sp_id = fam[:-4] + "_SP"
        fam_jobs = [(s, st, n) for s, st, n in jobs if s in (fam, sp_id)]
        assert fam_jobs, f"{fam} produced no jobs"

        by_src: dict[str, list] = {}
        for src, start, n in fam_jobs:
            by_src.setdefault(src, []).append((d(start), n))
        for src, runs in by_src.items():
            runs.sort()
            for _, n in runs:
                assert 0 < n <= ing.DAY_RANGE_MAX
            for (s1, n1), (s2, _) in zip(runs, runs[1:]):
                assert s1 + timedelta(days=n1) <= s2, \
                    f"{src}: chunks overlap between {s1} and {s2}"

        # Union across this family's sources covers exactly window∩range.
        want = set()
        if sp_id in AVAIL:
            want |= window_days(AVAIL[sp_id], lo, hi)
        want |= window_days(AVAIL[fam], lo, hi)
        got = coverage(fam_jobs)
        assert got.get(fam, set()) | got.get(sp_id, set()) == want

    # Gap accounting matches the uncovered leftovers, and tiling growth is
    # append-only so interrupted runs resume from cache.
    assert {g["source"]: g["days"] for g in gaps} == \
        {"VIIRS_NOAA21_NRT": (d("2024-01-17") - lo).days}
    base = ing.tile_forward(d("2026-01-01"), 5)
    grown = ing.tile_forward(d("2026-01-01"), 8)
    assert grown[:len(base)] == base and len(grown) == 2


def test_env_file_is_read_but_never_overrides_the_environment():
    """A .env is read when present; a real environment variable still wins.

    The precedence matters more than the parsing: CI supplies the key from
    Actions secrets, and a .env left in a checkout must not shadow it.
    """
    import os

    names = ("FIRMS_TEST_QUOTED", "FIRMS_TEST_PLAIN", "FIRMS_TEST_WINS")
    with tempfile.TemporaryDirectory() as td:
        env = Path(td) / ".env"
        ing.load_env_file(env)          # an absent file is not an error

        env.write_text(chr(10).join([
            "# a comment",
            "",
            'FIRMS_TEST_QUOTED="quoted-value"',
            "FIRMS_TEST_PLAIN = plain-value ",
            "NOT_AN_ASSIGNMENT",
        ]), encoding="utf-8")

        for name in names:
            os.environ.pop(name, None)
        os.environ["FIRMS_TEST_WINS"] = "from-environment"
        try:
            ing.load_env_file(env)
            assert os.environ["FIRMS_TEST_QUOTED"] == "quoted-value"
            assert os.environ["FIRMS_TEST_PLAIN"] == "plain-value"
            # a line with no "=" is skipped rather than crashing the run
            assert "NOT_AN_ASSIGNMENT" not in os.environ

            # the environment wins over the file
            env.write_text("FIRMS_TEST_WINS=from-file", encoding="utf-8")
            ing.load_env_file(env)
            assert os.environ["FIRMS_TEST_WINS"] == "from-environment"
        finally:
            for name in names:
                os.environ.pop(name, None)

if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
