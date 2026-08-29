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
import shutil
import tempfile
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


def test_page_script_structural_integrity():
    """Task 07b item 4: structural inspection catches the fault class that
    only breaks at runtime - unknown library globals, getElementById targets
    missing from the markup, and fetch paths that do not exist under docs/.
    No browser, no JS execution."""
    import re
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"<script>\n(.*)\n</script>", html, re.S)
    assert m, "inline script block not found"
    script = m.group(1)

    # the map initialises with the inline fallback style, not a remote URL,
    # and an error handler surfaces basemap/tile failures
    assert 'style: FALLBACK_STYLE' in script
    assert not re.search(r'style:\s*"http', script)
    assert 'map.on("error"' in script

    # every maplibregl global used is one the pinned library defines
    used = set(re.findall(r"new maplibregl\.(\w+)", script))
    used |= set(re.findall(r"maplibregl\.(\w+)\(", script))
    known = {"Map", "Popup", "NavigationControl"}
    assert used <= known, f"unknown maplibregl members: {used - known}"

    # every $()/getElementById target exists in the markup
    ids_used = set(re.findall(r'\$\("([^"]+)"\)', script))
    ids_used |= set(re.findall(r'getElementById\("([^"]+)"\)', script))
    ids_defined = set(re.findall(r'id="([^"]+)"', html))
    assert ids_used <= ids_defined, f"missing ids: {ids_used - ids_defined}"

    # every literal fetch path exists under docs/
    paths = re.findall(r'(?:loadJSON|loadText)\("([^"]+)"\)', script)
    assert paths, "no literal data paths found"
    for p in paths:
        assert (ROOT / "docs" / p).exists(), f"fetch path missing: {p}"
    assert (ROOT / "docs" / "briefs").is_dir(), "dynamic briefs/ path"


def test_minimarkdown_renders_via_node():
    """06b checks 5+6: execute the page's ACTUAL miniMarkdown function (via
    node, no browser) - underscores inside identifiers survive, and table
    rows with an empty cell or a lone '-' land in the right columns.
    Skipped where node is unavailable; everything else runs regardless."""
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        print("SKIP: node not on PATH - converter not executed")
        return
    harness = Path(tempfile.mkdtemp()) / "md_harness.js"
    harness.write_text(
        'const fs = require("fs");\n'
        'const html = fs.readFileSync(process.argv[2], "utf8");\n'
        'const m = html.match(/function miniMarkdown\\([\\s\\S]*?\\n\\}/);\n'
        'if (!m) { console.error("miniMarkdown not found"); process.exit(100); }\n'
        '(0, eval)(m[0]);\n'
        'const inputs = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'console.log(JSON.stringify(inputs.map((md) => miniMarkdown(md))));\n',
        encoding="utf-8")
    header = "| source | detections |"
    separator = "|---|---|"
    rows = [
        "| VIIRS_SNPP_NRT | 3 |",                      # underscores survive
        "|  | x |",                                    # empty first cell
        "| a | - |",                                   # lone '-' cell
    ]
    md = header + "\n" + separator + "\n" + "\n".join(rows) + "\n"
    r = subprocess.run(
        [node, str(harness), str(INDEX)],
        input=json.dumps([md]), capture_output=True, text=True,
        encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    rendered = json.loads(r.stdout)[0]
    # identifiers keep every underscore
    assert "VIIRS_SNPP_NRT" in rendered
    # header row rendered as th...
    assert "<tr><th>source</th><th>detections</th></tr>" in rendered
    # ...and each body row lands in the right columns
    assert "<tr><td></td><td>x</td></tr>" in rendered
    assert "<tr><td>a</td><td>-</td></tr>" in rendered
    # no underscore was eaten anywhere in the table
    assert "VIIRS SNPP NRT" not in rendered


def test_minimarkdown_real_brief_tables():
    """The real latest brief renders as two well-formed tables: the sources
    table keeps its four body rows as td (the 'observed, no detections' row
    included), and the district table keeps all 24 distrik rows."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("SKIP: node not on PATH - converter not executed")
        return
    briefs = sorted((ROOT / "docs" / "briefs").glob("*.md"),
                    key=lambda p: p.stat().st_mtime)
    assert briefs, "no brief files under docs/briefs/"
    harness = Path(tempfile.mkdtemp()) / "md_harness.js"
    harness.write_text(
        'const fs = require("fs");\n'
        'const html = fs.readFileSync(process.argv[2], "utf8");\n'
        'const m = html.match(/function miniMarkdown\\([\\s\\S]*?\\n\\}/);\n'
        'if (!m) { console.error("miniMarkdown not found"); process.exit(100); }\n'
        '(0, eval)(m[0]);\n'
        'const inputs = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'console.log(JSON.stringify(inputs.map((md) => miniMarkdown(md))));\n',
        encoding="utf-8")
    latest = briefs[-1]
    r = subprocess.run(
        [node, str(harness), str(INDEX)],
        input=json.dumps([latest.read_text(encoding="utf-8")]),
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    rendered = json.loads(r.stdout)[0]
    assert rendered.count("<table>") == 2, "tables fragmented"
    assert "<tr><td>MODIS_NRT</td>" in rendered, \
        "a sources-table body row rendered as something else"
    assert "<th>MODIS_NRT</th>" not in rendered
    district_rows = rendered.count("<tr><td>")
    assert district_rows >= 24, "district body rows lost"


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
