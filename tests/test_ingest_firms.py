"""Offline checks for the FIRMS ingest, using committed fixtures in data/raw/.

Never touches the network. Run with pytest:
    python -m pytest tests/test_ingest_firms.py
or directly (no pytest needed):
    python tests/test_ingest_firms.py
"""
import hashlib
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ingest_firms as ing  # noqa: E402

RAW = ROOT / "tests" / "fixtures"
BBOX = [134.60, -1.45, 136.70, -0.55]

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


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
