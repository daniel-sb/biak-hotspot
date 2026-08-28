"""Source-level checks for the dashboard page (Task 07). No browser, no
network: the page is a static file and its properties are asserted on the
source, plus the generated data files it serves.

Run with pytest:
    python -m pytest tests/test_dashboard.py
or directly:
    python tests/test_dashboard.py
"""
import codecs
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
DAILY = ROOT / "docs" / "data" / "daily_counts.json"
DESA = ROOT / "docs" / "data" / "biak_desa.geojson"
STORE = ROOT / "data" / "processed" / "detections.parquet"

ETHICS = "A hotspot is a thermal anomaly detected by a satellite sensor"


def test_index_exists_with_ethics_and_gap():
    assert INDEX.exists()
    html = INDEX.read_text(encoding="utf-8")
    # PLAN.md section 8 ethics text, in the page source itself (static
    # aside), before the brief container it must not be buried inside
    assert ETHICS in html
    assert html.index(ETHICS) < html.index('id="brief"')
    # observation gap, stated where a reader will find it
    assert "Nothing observes Biak between 15:00 and 00:31 WIT" in html
    assert "Himawari-9" in html and "2" in html


def test_no_all_clear_wording_in_page():
    """Check 4: nothing on the page may read as an all-clear for the
    evening. The mandated sentence is the strongest statement allowed."""
    html = INDEX.read_text(encoding="utf-8")
    assert ("No evening thermal anomaly above threshold after dark." in html)
    for banned in ("all-clear", "was clear", "the evening was clear",
                   "conditions improved", "nothing was burning",
                   "fire-free", "no fires were"):
        assert banned not in html, banned
    import re
    assert not re.search(r"\bsafe\b", html), "the word 'safe' appears"
    assert not re.search(r"\bclear\b", html), "the word 'clear' appears"


def test_confidence_not_used_for_encoding():
    """Check 5: confidence values are raw instrument codes, never comparable
    between VIIRS and MODIS - they appear only as popup text, never in a
    MapLibre paint expression."""
    html = INDEX.read_text(encoding="utf-8")
    assert '"confidence"' not in html          # maplibre ["get","confidence"]
    assert "get', 'confidence" not in html
    assert "circle-color" in html              # encoding exists...
    assert "frp" in html                       # ...and is driven by FRP


def test_pinned_cdn_only():
    html = INDEX.read_text(encoding="utf-8")
    assert "maplibre-gl@4.7.1" in html
    srcs = [l for l in html.split('"') if l.startswith("http")]
    assert srcs == [s for s in srcs if "maplibre-gl@4.7.1" in s or
                    "openfreemap" in s]


def test_data_files_referenced_with_error_handling():
    """Check 3 (source level): every published file is referenced and a
    load failure has a stated on-page error path."""
    html = INDEX.read_text(encoding="utf-8")
    for name in ("hotspots_latest.geojson", "summary_latest.json",
                 "recurrent_sites.json", "daily_counts.json",
                 "biak_desa.geojson"):
        assert name in html, name
    assert html.count("dataError(") >= 4
    assert "failed to load" in html


def test_daily_counts_dense_sorted_matches_store():
    """Check 1: daily_counts.json covers the full store span with no gaps,
    zeros included, and its totals match the store."""
    assert DAILY.exists()
    daily = json.loads(DAILY.read_text(encoding="utf-8"))
    dates = [d for d, _ in daily]
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
    # dense: every date is exactly one day after the previous one
    from datetime import date, timedelta
    for a, b in zip(dates, dates[1:]):
        assert (date.fromisoformat(b) - date.fromisoformat(a)) == \
            timedelta(days=1)
    if STORE.exists():
        store = pd.read_parquet(STORE)
        per_day = store.groupby("date_wit").size()
        for d, n in daily:
            assert n == int(per_day.get(d, 0))
        assert sum(n for _, n in daily) == len(store)


def test_simplified_boundaries_under_budget():
    """Check 2: the served boundary file is under 300 KB and keeps all 306
    desa."""
    assert DESA.exists()
    assert DESA.stat().st_size < 300 * 1024
    geo = json.loads(DESA.read_text(encoding="utf-8"))
    assert len(geo["features"]) == 306


def test_page_text_is_not_mojibake():
    """The page is the only public-facing file, and a cp1252/utf-8 round trip
    on Windows renders every em-dash as a stray sequence no terminal check
    catches. Guard the bytes, not the appearance."""
    raw = INDEX.read_bytes()
    assert not raw.startswith(codecs.BOM_UTF8), "byte-order mark before doctype"
    text = raw.decode("utf-8")
    suspect = re.compile("[" + chr(0xe2) + chr(0xc2) + "][" + chr(0x80) + "-" + chr(0xbf) + "]")
    assert not suspect.search(text), "double-encoded characters in docs/index.html"


def test_map_global_name_is_correct():
    """The library global is maplibregl. A bare `maplibre.` reference throws
    on load and kills every later fetch, so the page renders blank while all
    source-level checks still pass."""
    text = INDEX.read_text(encoding="utf-8")
    assert "maplibregl.Map(" in text
    stray = re.search(r"(?<!g)\bmaplibre\.", text)
    assert stray is None, "bare maplibre. reference; the global is maplibregl"


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
