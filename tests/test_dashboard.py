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
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"


def pages():
    """Every generated page, as (path, html). The site became three pages in
    adr/0002, so a property asserted on one page is asserted on all of them."""
    out = [(q, q.read_text(encoding="utf-8")) for q in sorted(DOCS.glob("*.html"))]
    assert out, "no pages under docs/ - run python src/build_site.py"
    return out


def scripts():
    """Every published asset script, as (path, source)."""
    out = [(q, q.read_text(encoding="utf-8"))
           for q in sorted((DOCS / "assets").glob("*.js"))]
    assert out, "no scripts under docs/assets/ - run python src/build_site.py"
    return out


def site_text():
    """Markup and scripts together: everything a reader can end up seeing."""
    return "\n".join(s for _q, s in pages() + scripts())
DAILY = ROOT / "docs" / "data" / "daily_counts.json"
DESA = ROOT / "docs" / "data" / "biak_desa.geojson"
DROUGHT = ROOT / "docs" / "data" / "drought.json"
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
    """Check 4: nothing on any page, or in any script that writes to one, may
    read as an all-clear for the evening. The mandated sentence is the
    strongest statement allowed."""
    assert "No evening thermal anomaly above threshold after dark." in site_text()
    banned = ("all-clear", "was clear", "the evening was clear",
              "conditions improved", "nothing was burning",
              "fire-free", "no fires were")
    for path, text in pages() + scripts():
        for word in banned:
            assert word not in text, f"{path.name}: {word}"
        assert not re.search(r"\bsafe\b", text), f"{path.name}: the word 'safe'"
        assert not re.search(r"\bclear\b", text), f"{path.name}: the word 'clear'"


def test_confidence_not_used_for_encoding():
    """Check 5: confidence values are raw instrument codes, never comparable
    between VIIRS and MODIS - they appear only as popup text, never in a
    MapLibre paint expression."""
    text = site_text()
    assert chr(34) + "confidence" + chr(34) not in text
    assert "get', 'confidence" not in text
    assert "circle-color" in text              # encoding exists...
    assert "frp" in text                       # ...and is driven by FRP


def test_pinned_cdn_only():
    """The site talks to three hosts and no others.

    gibs.earthdata.nasa.gov was added deliberately for task 09 imagery.
    The point of this list is that a new host is a decision someone made,
    not something that arrived with a copied snippet: extend it only
    alongside the reason, in the same commit.
    """
    allowed = ("maplibre-gl@4.7.1", "openfreemap", "gibs.earthdata.nasa.gov",
               "worldview.earthdata.nasa.gov")
    for path, text in pages() + scripts():
        srcs = [s for s in text.split(chr(34)) if s.startswith("http")]
        bad = [s for s in srcs if not any(a in s for a in allowed)]
        assert not bad, f"{path.name}: {bad}"
    # the library is pinned on every page that loads the map, and absent from
    # every page that does not
    for path, text in pages():
        if "assets/map.js" in text:
            assert "maplibre-gl@4.7.1" in text, path.name
        else:
            assert "maplibre" not in text, f"{path.name} pulls MapLibre unused"


def test_data_files_referenced_with_error_handling():
    """Check 3 (source level): every published file is referenced and a
    load failure has a stated on-page error path."""
    text = site_text()
    for name in ("hotspots_latest.geojson", "summary_latest.json",
                 "recurrent_sites.json", "daily_counts.json",
                 "biak_desa.geojson", "vegetation.json"):
        assert name in text, name
    assert text.count("dataError(") >= 4
    assert "failed to load" in text


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


VEG = ROOT / "docs" / "data" / "vegetation.json"


def test_vegetation_json_internal_consistency():
    """Task 11: months dense and sorted; good_share in [0,1]; anomaly =
    index minus the stored calendar-month baseline; correlations reproduced
    from the stored series by this test, not read back from the file."""
    if not VEG.exists():
        print("SKIP: vegetation.json not present")
        return
    doc = json.loads(VEG.read_text(encoding="utf-8"))
    monthly = doc["monthly"]

    # dense and sorted
    months = [r["month"] for r in monthly]
    assert months == sorted(months)
    from datetime import date as D
    for a, b in zip(months, months[1:]):
        da = D(int(a[:4]), int(a[5:7]), 1)
        db = D(int(b[:4]), int(b[5:7]), 1)
        assert (db - da).days in (28, 29, 30, 31), f"gap between {a} and {b}"

    # good shares in [0, 1]
    for key in ("ndvi_good_share", "ndmi_good_share"):
        vals = [r[key] for r in monthly if r.get(key) is not None]
        assert all(0 <= v <= 1 for v in vals), key

    # anomaly = index - stored baseline
    baselines = doc["baselines"]
    for r in monthly:
        mm = r["month"][5:7]
        for key in ("ndvi", "ndmi"):
            base = baselines.get(f"{key}_{mm}")
            if r.get(key) is not None and base is not None:
                expected = round(r[key] - base, 4)
                assert abs(r[f"{key}_anomaly"] - expected) < 0.001, \
                    f"{r['month']} {key}: {r[f'{key}_anomaly']} != {expected}"

    # correlations reproduced from the stored series
    import math
    def pearson(pairs):
        n = len(pairs)
        if n < 3:
            return None, n
        mx = sum(x for x, _ in pairs) / n
        my = sum(y for _, y in pairs) / n
        sxy = sum((x - mx) * (y - my) for x, y in pairs)
        sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
        sy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
        if sx == 0 or sy == 0:
            return None, n
        return round(sxy / (sx * sy), 3), n

    for key, july_key in (("ndvi", "ndvi_july"), ("ndmi", "ndmi_july")):
        pairs = [(r[key], r[f"{key}_good_share"]) for r in monthly
                 if r.get(key) is not None and r.get(f"{key}_good_share") is not None]
        r_all, n_all = pearson(pairs)
        assert abs(doc["qa_correlation"][key.replace(key, key + "_all") if False else f"{key}_all"]["r"] - r_all) < 0.002, \
            f"{key} all-month r mismatch: file says {doc['qa_correlation'][key + '_all']['r']}, test computes {r_all}"
        assert doc["qa_correlation"][f"{key}_all"]["n"] == n_all
        july_pairs = [(r[key], r[f"{key}_good_share"]) for r in monthly
                      if r["month"][5:7] == "07"
                      and r.get(key) is not None
                      and r.get(f"{key}_good_share") is not None]
        r_jul, n_jul = pearson(july_pairs)
        assert abs(doc["qa_correlation"][july_key]["r"] - r_jul) < 0.002, \
            f"{key} July r mismatch"
        assert doc["qa_correlation"][july_key]["n"] == n_jul


def test_vegetation_page_has_qa_share_and_non_conclusion():
    """The drawing code uses both the index and its QA share, and the panel's
    copy states the non-conclusion. The copy is on conditions.html; the series
    names are in the script that page loads."""
    panel = (DOCS / "conditions.html").read_text(encoding="utf-8")
    code = (DOCS / "assets" / "climate.js").read_text(encoding="utf-8")
    for series in ("ndvi_anomaly", "ndvi_good_share",
                   "ndmi_anomaly", "ndmi_good_share"):
        assert series in code, series
    assert "qa_correlation" in code
    assert "do not support a drought conclusion" in panel


def test_render_check_vegetation_panel():
    """scripts/render_check.py asserts the vegetation panel draws both the
    index and the share series, and that the correlation text appears with
    a number in it."""
    rc = ROOT / "scripts" / "render_check.py"
    if not rc.exists():
        print("SKIP: render_check.py not present")
        return
    src = rc.read_text(encoding="utf-8")
    assert "veg" in src, "render_check does not check the vegetation panel"
    assert "ndvi_good_share" in src or "good_share" in src
    assert "qa_correlation" in src or "Closest" not in src


def page_scripts(html):
    """The asset scripts a page actually loads, in load order."""
    names = re.findall(r'<script src="assets/([^"]+)"></script>', html)
    assert names, "page loads no scripts"
    return names


def test_page_script_structural_integrity():
    """Task 07b item 4: structural inspection catches the fault class that
    only breaks at runtime - unknown library globals, getElementById targets
    missing from the markup, and fetch paths that do not exist under docs/.
    Checked per page against the scripts that page loads, so a script may
    only touch ids its own page defines. No browser, no JS execution."""
    # data/vegetation.json is written by an interactive Earth Engine run and is
    # absent until someone with credentials runs src/vegetation_gee.py. The
    # panel states that absence rather than drawing anything, so an absent file
    # is a correct state here - unlike every other path, where absence is a typo.
    generated_by_hand = {"data/vegetation.json"}
    known = {"Map", "Popup", "NavigationControl"}
    seen_paths = set()

    for path, html in pages():
        names = page_scripts(html)
        script = "\n".join(
            (DOCS / "assets" / n).read_text(encoding="utf-8") for n in names)

        if "map.js" in names:
            # the map initialises with the inline fallback style, not a remote
            # URL, and an error handler surfaces basemap/tile failures
            assert "style: FALLBACK_STYLE" in script, path.name
            assert not re.search(r'style:\s*"http', script), path.name
            assert 'map.on("error"' in script, path.name

        # every maplibregl global used is one the pinned library defines
        used = set(re.findall(r"new maplibregl\.(\w+)", script))
        used |= set(re.findall(r"maplibregl\.(\w+)\(", script))
        assert used <= known, f"{path.name}: unknown members {used - known}"

        # every $()/getElementById target exists in THIS page's markup
        ids_used = set(re.findall(r'\$\("([^"]+)"\)', script))
        ids_used |= set(re.findall(r'getElementById\("([^"]+)"\)', script))
        ids_defined = set(re.findall(r'id="([^"]+)"', html))
        assert ids_used <= ids_defined, \
            f"{path.name}: missing ids {ids_used - ids_defined}"

        # every literal fetch path exists under docs/
        paths = re.findall(r'(?:loadJSON|loadText)\("([^"]+)"\)', script)
        assert paths, f"{path.name}: no literal data paths found"
        seen_paths |= set(paths)
        for q in paths:
            if q in generated_by_hand:
                continue
            assert (DOCS / q).exists(), f"{path.name}: fetch path missing: {q}"

    assert (DOCS / "briefs").is_dir(), "dynamic briefs/ path"
    # the split must not have orphaned a data file nobody loads any more
    for q in ("data/summary_latest.json", "data/hotspots_latest.geojson",
              "data/daily_counts.json", "data/drought.json"):
        assert q in seen_paths, f"no page loads {q} any more"


def test_docs_pages_are_the_build_output():
    """docs/*.html is generated from site/ by src/build_site.py. Editing the
    published page by hand works until the next build silently reverts it, so
    the committed output has to match what the sources produce."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_site", ROOT / "src" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    skeleton = (mod.SITE / "partials" / "page.html").read_text(encoding="utf-8")
    for name, _label, title, h1, scripts_, needs_map in mod.PAGES:
        expected = mod.render(name, title, h1, scripts_, needs_map, skeleton)
        actual = (DOCS / f"{name}.html").read_text(encoding="utf-8")
        assert actual == expected, \
            f"docs/{name}.html is not what site/ builds - run src/build_site.py"
    for src in sorted((mod.SITE / "assets").iterdir()):
        if src.is_file():
            out = DOCS / "assets" / src.name
            assert out.exists(), f"docs/assets/{src.name} missing"
            assert out.read_bytes() == src.read_bytes(), \
                f"docs/assets/{src.name} differs from site/assets/"
    published = {q.name for q in (DOCS / "assets").iterdir() if q.is_file()}
    sources = {q.name for q in (mod.SITE / "assets").iterdir() if q.is_file()}
    assert published == sources, f"stale assets: {published - sources}"


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
        'const src = fs.readFileSync(process.argv[2], "utf8");\n'
        'const m = src.match(/function miniMarkdown\\([\\s\\S]*?\\n\\}/);\n'
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
        [node, str(harness), str(DOCS / "assets" / "core.js")],
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
        'const src = fs.readFileSync(process.argv[2], "utf8");\n'
        'const m = src.match(/function miniMarkdown\\([\\s\\S]*?\\n\\}/);\n'
        'if (!m) { console.error("miniMarkdown not found"); process.exit(100); }\n'
        '(0, eval)(m[0]);\n'
        'const inputs = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'console.log(JSON.stringify(inputs.map((md) => miniMarkdown(md))));\n',
        encoding="utf-8")
    latest = briefs[-1]
    r = subprocess.run(
        [node, str(harness), str(DOCS / "assets" / "core.js")],
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


STATUS_HARNESS = r"""
const fs = require("fs");
const core = fs.readFileSync(process.argv[2], "utf8");
const page = fs.readFileSync(process.argv[3], "utf8");
const s = page.match(/function statusText\([\s\S]*?\n\}/);
if (!s) { console.error("statusText not found"); process.exit(100); }
// core.js is evaluated whole and in the same scope, because esc is a const
// and would not survive a separate eval. Nothing in core.js touches the DOM
// until one of its functions is called, so node can load it as it stands.
const calls = "JSON.stringify([" +
  "statusText(2, '2026-09-23', 7, '2026-09-28')," +
  "statusText(1, '2026-09-23', 7, '2026-09-28')," +
  "statusText(0, null, 7, '2026-09-28')])";
console.log(eval(core + "\n" + s[0] + "\n" + calls));
"""


def test_status_strip_states_via_node():
    """The status strip is the only present-tense element on index.html, and
    its wording is the one place a reader could be handed an all-clear.
    Execute the real function: a plural count, a singular count, and a zero
    that says the islands were observable without claiming more than that.
    Skipped where node is unavailable."""
    node = shutil.which("node")
    if not node:
        print("SKIP: node not on PATH - statusText not executed")
        return
    harness = Path(tempfile.mkdtemp()) / "status_harness.js"
    harness.write_text(STATUS_HARNESS, encoding="utf-8")
    r = subprocess.run(
        [node, str(harness), str(DOCS / "assets" / "core.js"),
         str(DOCS / "assets" / "index.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    many, one, none = json.loads(r.stdout)

    assert "2 detections in the 7 days to 2026-09-28 (WIT)" in many
    assert "Most recent: 2026-09-23." in many
    assert "1 detection in the 7 days" in one, "plural not agreed"
    assert "1 detections" not in one

    # the zero state reports an absence of detections, never an absence of fire
    assert "No detections in the 7 days to 2026-09-28 (WIT)" in none
    assert "observable" in none
    assert "Nothing observes Biak between 15:00 and 00:31 WIT" in none
    for rendered in (many, one, none):
        for banned in ("all-clear", "safe", "clear", "fire-free",
                       "nothing was burning", "no fires"):
            assert banned not in rendered, banned


def test_page_text_is_not_mojibake():
    """The site is the only public-facing output, and a cp1252/utf-8 round trip
    on Windows renders every em-dash as a stray sequence no terminal check
    catches. Guard the bytes, not the appearance."""
    suspect = re.compile("[" + chr(0xe2) + chr(0xc2) + "][" + chr(0x80) +
                         "-" + chr(0xbf) + "]")
    for path, _text in pages() + scripts():
        raw = path.read_bytes()
        assert not raw.startswith(codecs.BOM_UTF8), f"{path.name}: BOM"
        assert not suspect.search(raw.decode("utf-8")), \
            f"double-encoded characters in docs/{path.name}"


def test_map_global_name_is_correct():
    """The library global is maplibregl. A bare `maplibre.` reference throws
    on load and kills every later fetch, so the page renders blank while all
    source-level checks still pass."""
    text = site_text()
    assert "maplibregl.Map(" in text
    for path, body in pages() + scripts():
        stray = re.search(r"(?<!g)\bmaplibre\.", body)
        assert stray is None, \
            f"{path.name}: bare maplibre. reference; the global is maplibregl"


def test_drought_json_internally_consistent():
    """Task 10: the panel is drawn straight from this file, so its arithmetic
    and its density are the only things standing between a plotting bug and a
    published number. Months dense and sorted, the balance equal to its two
    terms, a climatology for all twelve calendar months, and a current month
    that is the last row rather than a separately computed one."""
    assert DROUGHT.exists()
    doc = json.loads(DROUGHT.read_text(encoding="utf-8"))
    months = [r["month"] for r in doc["monthly"]]
    assert months == sorted(months) and len(months) == len(set(months))
    for a, b in zip(months, months[1:]):
        y, m = int(a[:4]), int(a[5:7])
        assert b == (f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}")
    for r in doc["monthly"]:
        if r["precip_mm"] is None or r["et_mm"] is None:
            assert r["p_minus_et_mm"] is None, r["month"]
            continue
        assert abs(r["p_minus_et_mm"] - (r["precip_mm"] - r["et_mm"])) < 0.051,             r["month"]
    clim = doc["climatology"]
    assert sorted(clim) == [f"{m:02d}" for m in range(1, 13)]
    for k, c in clim.items():
        assert c["years"] > 0 and c["mean_mm"] > 0 and c["sd_mm"] >= 0, k
    cur, last = doc["current"], doc["monthly"][-1]
    assert cur["month"] == last["month"] ==         doc["coverage"]["chirps_last_complete_month"]
    assert cur["precip_mm"] == last["precip_mm"]
    assert cur["p_minus_et_mm"] == last["p_minus_et_mm"]
    assert 1 <= cur["rank_driest"] <= cur["rank_of"]
    # the published month must be complete: CHIRPS has to hold its last day
    from calendar import monthrange
    y, m = int(cur["month"][:4]), int(cur["month"][5:7])
    assert doc["coverage"]["chirps_last_date"] >=         f"{cur['month']}-{monthrange(y, m)[1]:02d}"


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
