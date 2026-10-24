"""Headless render check for the published pages (added after Task 07b, whose
structural tests could not catch runtime faults).

Serves docs/ over localhost, opens index.html, history.html and conditions.html
in headless Chromium, and asserts:
  - the page script runs to completion (no pageerror, no console errors)
  - the maplibre canvas exists and every local data file loads with no
    error banner (glyphs, recurrent FeatureCollection, fallback style)
  - the evening section states its result per the 06b/06c discipline
    (after-dark first, never an all-clear)
  - the status strip states its window without reading as an all-clear
  - the brief renders with identifiers intact
  - the timeline draws the detection-carrying days

Requires playwright and its chromium binary (both are dev-tooling, not repo
dependencies):
    python -m playwright install chromium
    python scripts/render_check.py
Skips with a clear message where playwright or the browser is unavailable.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PORT = 8137
BASE = f"http://127.0.0.1:{PORT}"
URLS = {n: f"{BASE}/{n}.html"
        for n in ("index", "conditions", "history", "brief", "results",
                  "methods", "gallery")}

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright not installed (pip install playwright)")
    sys.exit(0)


def main() -> int:
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=DOCS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for the port to answer rather than sleeping a fixed second: a
    # previous run's sockets sitting in TIME_WAIT delays the bind, and a race
    # lost here surfaces as ERR_CONNECTION_REFUSED on the first navigation,
    # which looks like a broken page rather than a server that was not up yet.
    import urllib.error
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{BASE}/index.html", timeout=1).read(1)
            break
        except urllib.error.HTTPError:
            break                       # answering, even if not with a 200
        except OSError:
            if server.poll() is not None:
                print(f"SKIP: http.server exited with {server.returncode} - "
                      f"port {PORT} may be in use")
                return 0
            time.sleep(0.2)
    else:
        server.terminate()
        print(f"SKIP: http.server did not answer on port {PORT}")
        return 0
    failures = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:
                print(f"SKIP: chromium unavailable ({exc}) - "
                      "run: python -m playwright install chromium")
                return 0
            page = browser.new_page(viewport={"width": 360, "height": 800})
            console_errors = []
            page.on("console", lambda m: console_errors.append(
                m.text + " @ " + (m.location or {}).get("url", ""))
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: failures.append(
                f"pageerror: {e}"))
            page.goto(URLS["index"], wait_until="networkidle",
                      timeout=60000)
            page.wait_for_timeout(4000)   # tiles, glyphs, timeline render

            def check(name, ok, detail=""):
                line = ("PASS " if ok else "FAIL ") + name
                if detail:
                    line += f" — {detail}"
                print(line.encode("ascii", "replace").decode())
                if not ok:
                    failures.append(name)

            check("no page errors (script ran to completion)",
                  not [f for f in failures if f.startswith("pageerror")])

            canvas = page.evaluate(
                "!!document.querySelector('.maplibregl-canvas')")
            check("map canvas exists (maplibre initialised)", canvas)

            # The project AOI is 2.5 degrees wide and reaches 300 km north-west
            # of Biak; opening on it put the island this page is about in the
            # middle third of the frame.
            view = page.evaluate("""() => {
              const b = map.getBounds();
              return { w: b.getWest(), e: b.getEast(),
                       s: b.getSouth(), n: b.getNorth() };
            }""")
            check("map opens on Biak island, not the whole AOI",
                  (view["e"] - view["w"]) < 1.6
                  and view["w"] > 135.0 and view["e"] < 137.2,
                  f"{view['w']:.2f}..{view['e']:.2f} E, "
                  f"{view['s']:.2f}..{view['n']:.2f} N")

            inside = page.evaluate("""() => {
              const m = document.getElementById('maparea');
              const p = document.getElementById('mappanel');
              return !!(m && p && m.contains(p));
            }""")
            check("the layer panel sits inside the map frame", inside)
            for ctrl, label in (
                    (".maplibregl-ctrl-scale", "scale bar"),
                    (".maplibregl-ctrl-fullscreen", "fullscreen control"),
                    (".maplibregl-ctrl-geolocate", "geolocate control"),
                    (".maplibregl-ctrl-zoom-in", "zoom control")):
                check(f"in-map {label} present",
                      page.evaluate(
                          f"!!document.querySelector('{ctrl}')"))

            err_text = page.inner_text("#data-errors")
            check("no data-error banners (all files loaded)",
                  err_text.strip() == "", err_text.strip()[:300])

            status = page.inner_text("#status")
            check("status strip rendered past 'Loading'",
                  "Loading" not in status,
                  status[:160].encode("ascii", "replace").decode())
            check("status strip names its window and the day it covers",
                  "days to" in status and "(WIT)" in status,
                  status[:160].encode("ascii", "replace").decode())
            check("status strip reports detections, never an absence of fire",
                  ("detection" in status)
                  and not any(w in status.lower()
                              for w in ("all-clear", "safe", "clear",
                                        "fire-free", "no fires")),
                  status[:160].encode("ascii", "replace").decode())

            for tile, label in (("fig-counts", "detections in events"),
                                ("fig-mapped", "mapped extent"),
                                ("fig-validated", "validated estimate")):
                txt = page.inner_text("#" + tile)
                check(f"headline tile drawn: {label}",
                      txt.strip() not in ("", "\u2014"), txt[:80])
            counts = page.inner_text("#fig-counts")
            check("count tile reports detections inside events, not fires",
                  " in " in counts and "fire" not in counts.lower(),
                  counts[:80])
            mapped_note = page.inner_text("#fig-mapped-note")
            check("mapped tile says unassessed events are not zero",
                  "not counted as zero" in mapped_note, mapped_note[:120])
            val = page.inner_text("#fig-validated")
            check("validated tile carries its interval",
                  "(" in val and "\u2013" in val, val[:80])
            marks = page.evaluate(
                "document.querySelectorAll('#fig-interval line,"
                " #fig-interval circle').length")
            check("interval bar drawn with its marks", marks >= 5, f"{marks}")
            vnote = page.inner_text("#fig-validated-note")
            check("validated tile names its narrower scope",
                  "footprints" in vnote and "under-maps" in vnote,
                  vnote[:140])

            first = page.inner_text("#read-first")
            check("front page says the two area figures differ",
                  "not the same quantity" in first, first[:120])
            for href in ("methods.html", "results.html"):
                check(f"front page links {href}",
                      page.evaluate(
                          f"!!document.querySelector('a[href=\"{href}\"]')"))

            # --- the panel, which is shut on a narrow viewport ---
            # This check runs at 360 px wide, where an open 17 rem panel is
            # the whole map. Everything below drives the panel explicitly:
            # open to reach a control, shut to reach the map under it.
            check("the panel starts shut on a phone-width viewport",
                  not page.evaluate(
                      "document.getElementById('mappanel').open"))

            def panel(open_it):
                page.evaluate(
                    "(v) => { document.getElementById('mappanel').open = v; }",
                    open_it)
                page.wait_for_timeout(250)

            panel(True)

            # --- layer switch and legend ---
            # The basemap upgrade calls setStyle, which wipes every layer and
            # re-adds them on a 400 ms timer, so a fixed sleep races it. Wait
            # for the layers themselves; that they appear at all within the
            # timeout is part of what this check is for.
            try:
                page.wait_for_function(
                    "() => ['desa-lines','hotspots','burned-fill',"
                    "'labels-fill'].every(id => map.getLayer(id))",
                    timeout=30000)
                check("every local layer exists after the basemap upgrade", True)
            except Exception as exc:
                missing = page.evaluate(
                    "['desa-lines','hotspots','burned-fill','labels-fill']"
                    ".filter(id => !map.getLayer(id))")
                check("every local layer exists after the basemap upgrade",
                      False, f"missing {missing} ({type(exc).__name__})")

            # Prove the layers survive a style REPLACEMENT, which is what
            # the basemap upgrade does. Waiting for the real upgrade only
            # tests whichever order the two fetches happened to finish in;
            # this forces the swap, and it is the check that would have
            # caught the re-apply listener unsubscribing itself one tick
            # before setStyle arrived.
            # NOT map.getStyle(): that returns the current style including
            # the layers the page added, so re-setting it restores them and
            # the check passes whether or not anything re-applies. Swap to a
            # bare background style, which genuinely wipes.
            page.evaluate("""() => map.setStyle({
              version: 8,
              glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
              sources: {},
              layers: [{ id: "swap-bg", type: "background",
                         paint: { "background-color": "#dfe7ee" } }],
            })""")
            try:
                page.wait_for_function(
                    "() => ['desa-lines','hotspots','burned-fill',"
                    "'labels-fill','survey-dot'].every(id => map.getLayer(id))",
                    timeout=20000)
                check("local layers come back after a forced style swap", True)
            except Exception:
                missing = page.evaluate(
                    "['desa-lines','hotspots','burned-fill','labels-fill',"
                    "'survey-dot'].filter(id => !map.getLayer(id))")
                check("local layers come back after a forced style swap",
                      False, f"missing {missing}")

            boxes = page.evaluate(
                "document.querySelectorAll('#layers input[data-layer]').length")
            check("layer switch rendered", boxes >= 5, f"{boxes} checkboxes")
            legend_before = page.evaluate(
                "document.querySelectorAll('#legend li').length")
            check("legend lists the layers that are on", legend_before >= 4,
                  f"{legend_before} entries")
            check("interpretation boxes start switched off",
                  not page.evaluate(
                      "document.querySelector('#layers "
                      "input[data-layer=\"labels\"]').checked"))
            vis = page.evaluate(
                "map.getLayer('labels-fill') ? "
                "map.getLayoutProperty('labels-fill','visibility') : 'absent'")
            check("a layer switched off is hidden on the map", vis == "none",
                  str(vis))
            page.check('#layers input[data-layer="labels"]')
            page.wait_for_timeout(600)
            check("switching a layer on shows it",
                  page.evaluate(
                      "map.getLayer('labels-fill') && "
                      "map.getLayoutProperty('labels-fill','visibility')")
                  == "visible")
            check("legend grew with it",
                  page.evaluate(
                      "document.querySelectorAll('#legend li').length")
                  > legend_before)
            page.uncheck('#layers input[data-layer="burned"]')
            page.wait_for_timeout(600)
            check("switching a layer off hides both of its map layers",
                  page.evaluate(
                      "['burned-fill','burned-line'].every(id => "
                      "map.getLayer(id) && "
                      "map.getLayoutProperty(id,'visibility')==='none')"))
            page.check('#layers input[data-layer="burned"]')
            page.wait_for_timeout(400)

            # --- identify ---
            panel(False)
            # A 60 m box is sub-pixel at the AOI-wide view in a 360 px
            # viewport, so nothing is rendered to click until the map is over
            # one. Take the coordinate from the source data, not the screen.
            pop = page.evaluate("""() => {
              const src = map.getSource('labels');
              const data = src && src._data;
              if (!data || !data.features.length) return null;
              // every box is a MultiPolygon, so coordinates[0] is a polygon
              // and not a ring: flatten to the position pairs before averaging
              const pts = [];
              (function walk(a) {
                if (typeof a[0] === "number") pts.push(a);
                else a.forEach(walk);
              })(data.features[0].geometry.coordinates);
              const lon = pts.reduce((a, c) => a + c[0], 0) / pts.length;
              const lat = pts.reduce((a, c) => a + c[1], 0) / pts.length;
              map.jumpTo({ center: [lon, lat], zoom: 16 });
              return { lon, lat };
            }""")
            if pop:
                page.wait_for_timeout(1200)
                pop = page.evaluate("""() => {
                  const f = map.queryRenderedFeatures({
                    layers: ['labels-fill'] });
                  if (!f.length) return null;
                  const c = map.project(map.getCenter());
                  const r = map.getCanvas().getBoundingClientRect();
                  return { x: r.left + c.x, y: r.top + c.y };
                }""")
            if pop:
                page.eval_on_selector(
                    "#maparea", "el => el.scrollIntoView({block: 'start'})")
                page.wait_for_timeout(400)
                pop = page.evaluate("""() => {
                  const c = map.project(map.getCenter());
                  const r = map.getCanvas().getBoundingClientRect();
                  return { x: r.left + c.x, y: r.top + c.y };
                }""")
                page.mouse.click(pop["x"], pop["y"])
                page.wait_for_timeout(700)
                txt = page.inner_text(".maplibregl-popup-content")
                check("identify on an interpretation box names its stratum "
                      "and its limitation",
                      "stratum" in txt and "No second interpreter" in txt,
                      txt[:160].encode("ascii", "replace").decode())
                check("identify does not state a verdict about the land",
                      "evidence about the product" in txt)
            else:
                check("interpretation boxes rendered for identify", False,
                      "no features returned")

            # --- the field survey, with its photographs ---
            panel(False)
            plot = page.evaluate("""() => {
              const src = map.getSource('survey');
              const data = src && src._data;
              if (!data || !data.features.length) return null;
              const c = data.features[0].geometry.coordinates;
              map.jumpTo({ center: c, zoom: 15 });
              return { lon: c[0], lat: c[1] };
            }""")
            check("the field survey layer loaded", bool(plot),
                  "" if plot else "no survey source")
            if plot:
                page.wait_for_timeout(1400)
                at = page.evaluate("""() => {
                  const f = map.queryRenderedFeatures({
                    layers: ['survey-dot'] });
                  if (!f.length) return null;
                  const c = map.project(map.getCenter());
                  const r = map.getCanvas().getBoundingClientRect();
                  return { x: r.left + c.x, y: r.top + c.y };
                }""")
                if at:
                    page.eval_on_selector(
                        "#maparea",
                        "el => el.scrollIntoView({block: 'start'})")
                    page.wait_for_timeout(400)
                    at = page.evaluate("""() => {
                      const c = map.project(map.getCenter());
                      const r = map.getCanvas().getBoundingClientRect();
                      return { x: r.left + c.x, y: r.top + c.y };
                    }""")
                    page.mouse.click(at["x"], at["y"])
                    page.wait_for_timeout(900)
                    txt = page.inner_text(".maplibregl-popup-content")
                    check("identify on a field plot names what was read "
                          "on the ground",
                          "Field plot" in txt and "Evidence:" in txt,
                          txt[:160].encode("ascii", "replace").decode())
                    check("the field plot popup states what three plots "
                          "cannot do",
                          "cannot validate a map" in txt)
                    shot = page.evaluate(
                        """() => {
                          const i = document.querySelector(
                            '.maplibregl-popup-content img.popup-photo');
                          return i ? { src: i.getAttribute('src'),
                                       w: i.naturalWidth } : null;
                        }""")
                    check("the field plot popup shows its photograph",
                          bool(shot) and shot["w"] > 0,
                          (shot or {}).get("src", "no img element"))
                else:
                    check("field plot rendered for identify", False,
                          "no features returned")
                page.keyboard.press("Escape")

            # --- the Sentinel-2 scenes from the labelling project ---
            panel(True)
            n_events = page.evaluate(
                "document.querySelectorAll('#scene-event option').length")
            check("the scene index offers every labelled event",
                  n_events >= 3, f"{n_events} events")
            page.check("#scene-on")
            page.wait_for_timeout(2500)
            check("a Sentinel-2 scene is draped on the map",
                  page.evaluate("!!map.getLayer('s2-scene')"))
            snote = page.inner_text("#scene-note")
            check("the scene says which band combination and which date",
                  "2026-" in snote
                  and ("colour" in snote or "infrared" in snote),
                  snote[:140].encode("ascii", "replace").decode())
            check("the false-colour scene is never called a fire detection",
                  "fire detection" not in snote
                  or "not a fire detection" in snote,
                  snote[:140].encode("ascii", "replace").decode())
            first_label = page.inner_text("#scene-date-label")
            page.evaluate(
                "() => { const s = document.getElementById('scene-date');"
                " s.value = '0';"
                " s.dispatchEvent(new Event('input', {bubbles: true})); }")
            page.wait_for_timeout(1500)
            check("moving the date slider changes the scene",
                  page.inner_text("#scene-date-label") != first_label,
                  f"{first_label} -> {page.inner_text('#scene-date-label')}")
            page.uncheck("#scene-on")
            page.wait_for_timeout(600)
            check("switching the scene off removes it",
                  not page.evaluate("!!map.getLayer('s2-scene')"))

            # --- task 09: GIBS imagery, including past its zoom ceiling ---
            gibs = []
            page.on("response", lambda r: gibs.append(
                (r.status, r.url)) if "gibs.earthdata.nasa.gov" in r.url
                else None)

            page.check('input[name="imagery"][value="truecolor"]')
            page.wait_for_timeout(6000)
            served = [s for s, u in gibs if s == 200]
            check("GIBS imagery tiles served", bool(served),
                  f"{len(served)} of {len(gibs)} responses ok")

            note = page.inner_text("#imagery-note")
            check("imagery labelled with product and date",
                  "Corrected Reflectance" in note and "2026-" in note,
                  note[:120].encode("ascii", "replace").decode())
            check("imagery carries the not-an-all-clear caveat",
                  "absence of visible smoke is not an absence" in note)

            # GIBS tops out at zoom 9; MapLibre must overzoom rather than
            # blank out, and the resulting tile errors must not raise the
            # honest-degradation banner (task 09).
            for _ in range(5):
                page.click(".maplibregl-ctrl-zoom-in")
                page.wait_for_timeout(400)
            page.wait_for_timeout(4000)
            over = page.inner_text("#data-errors").strip()
            check("no error banner after zooming past the GIBS z9 ceiling",
                  over == "", over[:200])

            page.check('input[name="imagery"][value="esri"]')
            page.wait_for_timeout(5000)
            esri_note = page.inner_text("#imagery-note")
            check("Esri imagery says it has no single date",
                  "many different dates" in esri_note
                  and "cannot date a change" in esri_note,
                  esri_note[:140])
            check("Esri raster layer added",
                  page.evaluate("!!map.getLayer('img-esri')"))

            page.check('input[name="imagery"][value="swir"]')
            page.wait_for_timeout(5000)
            swir = page.inner_text("#imagery-note")
            check("false colour is never called a fire detection",
                  "not a fire detection" in swir and "fires" not in swir.lower())

            # --- history.html: the full detection record ---
            page.goto(URLS["history"], wait_until="networkidle",
                      timeout=60000)
            page.wait_for_timeout(2500)
            tl = page.evaluate(
                "document.querySelectorAll('#timeline rect').length")
            check("timeline drawn (detection days present)", tl >= 150,
                  f"{tl} bars")

            # --- brief.html: the daily brief and the evening ---
            page.goto(URLS["brief"], wait_until="networkidle",
                      timeout=60000)
            page.wait_for_timeout(2500)
            evening = page.inner_text("#evening")
            check("evening panel rendered past 'Loading'",
                  "Loading" not in evening,
                  evening[:200].encode("ascii", "replace").decode())
            check("evening states its result per 06b/06c discipline",
                  ("No evening thermal anomaly above threshold after dark"
                   in evening) or ("Pixels flagged after dark" in evening)
                  or ("Evening product unavailable" in evening))
            check("evening carries the not-evidence caveat",
                  "not evidence that nothing burned" in evening)

            brief = page.inner_text("#brief")
            check("brief rendered past 'Loading'", "Loading" not in brief,
                  brief[:200].encode("ascii", "replace").decode())
            check("brief keeps identifiers intact (no eaten underscores)",
                  "VIIRS_SNPP_NRT" in brief
                  or "hotspots_latest.geojson" in brief
                  or "biak_desa.geojson" in brief)

            check("no data-error banners on brief.html",
                  page.inner_text("#data-errors").strip() == "",
                  page.inner_text("#data-errors").strip()[:300])

            # --- conditions.html: vegetation and water balance ---
            page.goto(URLS["conditions"], wait_until="networkidle",
                      timeout=60000)
            page.wait_for_timeout(2500)
            check("no data-error banners on conditions.html",
                  page.inner_text("#data-errors").strip() == "",
                  page.inner_text("#data-errors").strip()[:300])
            # vegetation panel (Task 11): both index anomaly and
            # ndvi_good_share / ndmi_good_share series drawn, plus
            # qa_correlation text with a number.
            # vegetation.json is written by an interactive Earth Engine run,
            # so it is legitimately absent on a fresh clone. Absent, the panel
            # must say so; it must never draw invented numbers under a MODIS
            # label.
            if (DOCS / "data" / "vegetation.json").exists():
                veg_svg = page.evaluate(
                    "!!document.querySelector('#veg polyline')")
                check("vegetation panel draws NDVI/NDMI anomalies and "
                      "ndvi_good_share + ndmi_good_share series", veg_svg)
                veg_corr = page.inner_text("#veg-corr")
                import re as _re
                has_num = bool(_re.search(r"r\s*=\s*[-+]?[\d.]+", veg_corr))
                check("vegetation qa_correlation text has a number", has_num,
                      veg_corr[:200])
            else:
                check("vegetation panel states its data is unavailable",
                      "unavailable" in page.inner_text("#veg-error"),
                      page.inner_text("#veg-error")[:200])
                check("vegetation panel draws nothing without data",
                      not page.evaluate(
                          "!!document.querySelector('#veg polyline')"))

            # --- task 10: drought panel ---
            dr = page.evaluate("document.querySelectorAll("
                               "'#drought rect, #drought polyline').length")
            check("drought panel drawn", dr >= 60, f"{dr} elements")
            check("no error banner from the drought panel",
                  page.inner_text("#drought-error").strip() == "")
            lag = page.inner_text("#drought-lag")
            check("drought panel names its CHIRPS date and states the lag",
                  "CHIRPS precipitation runs to" in lag and "-" in lag
                  and "before the day the brief above covers" in lag,
                  lag[:140])
            check("drought panel does not read as a cause",
                  "does not start a fire" in page.inner_text("#drought-wrap"))

            # --- results.html: the figures and the strata ---
            page.goto(URLS["results"], wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            rows = page.evaluate(
                "document.querySelectorAll('#area-table tbody tr').length")
            check("results lists all three area figures", rows == 3, f"{rows}")
            srows = page.evaluate(
                "document.querySelectorAll('#strata-table tbody tr').length")
            check("results lists the strata", srows >= 2, f"{srows}")
            check("results interval bar drawn",
                  page.evaluate(
                      "document.querySelectorAll('#res-interval line,"
                      " #res-interval circle').length") >= 5)
            rnote = page.inner_text("#res-interval-note")
            check("results interval names the omission",
                  "short of the estimate" in rnote, rnote[:140])
            check("no error banner on results.html",
                  page.inner_text("#results-error").strip() == "")

            # --- methods.html ---
            page.goto(URLS["methods"], wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            mtxt = page.inner_text("body")
            check("methods states the confidence-cast rule",
                  "never cast to a number" in mtxt)
            check("methods states the S2DR4 band order",
                  "B11, B12, B8A" in mtxt)
            check("methods says what is held back",
                  "notes written during interpretation are not published"
                  in mtxt)

            # --- gallery.html: the burn atlas ---
            page.goto(URLS["gallery"], wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            plates = page.evaluate(
                "document.querySelectorAll('#gallery figure').length")
            check("burn atlas renders a plate per labelled footprint",
                  plates >= 3, f"{plates} plates")
            drawn = page.evaluate(
                "[...document.querySelectorAll('#gallery img')]"
                ".every(i => i.naturalWidth > 100)")
            check("every atlas plate image actually loaded", drawn)
            gtxt = page.inner_text("#gallery")
            check("atlas captions say the hectares are a mapped extent",
                  "maps" in gtxt and "footprint" in gtxt, gtxt[:160])
            check("atlas says why these plates were not laid out in "
                  "Layout Composer",
                  "no command line" in page.inner_text("#layout-note"))
            check("every atlas plate links its GeoLibre project",
                  page.evaluate(
                      "document.querySelectorAll("
                      "'#gallery a[href$=\".geolibre.json\"]').length")
                  >= 3)
            check("no data-error banners on gallery.html",
                  page.inner_text("#data-errors").strip() == "",
                  page.inner_text("#data-errors").strip()[:300])

            # A 404 on vegetation.json is the expected state before anyone
            # has run src/vegetation_gee.py, and the panel says so on the page.
            # Every other console error is still a failure.
            expected_absent = ("favicon", "data/vegetation.json")
            console_real = [c for c in console_errors
                            if not any(x in c.lower() for x in expected_absent)]
            check("no console errors", not console_real,
                  "; ".join(console_real[:3]))

            browser.close()
    finally:
        server.terminate()

    print()
    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("HEADLESS RENDER CHECK: all pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
