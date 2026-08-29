"""Headless render check for docs/index.html (added after Task 07b, whose
structural tests could not catch runtime faults).

Serves docs/ over localhost, opens the page in headless Chromium, and asserts:
  - the page script runs to completion (no pageerror, no console errors)
  - the maplibre canvas exists and every local data file loads with no
    error banner (glyphs, recurrent FeatureCollection, fallback style)
  - the evening section states its result per the 06b/06c discipline
    (after-dark first, never an all-clear)
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
URL = f"http://127.0.0.1:{PORT}/index.html"

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP: playwright not installed (pip install playwright)")
    sys.exit(0)


def main() -> int:
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT)],
        cwd=DOCS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
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
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: failures.append(
                f"pageerror: {e}"))
            page.goto(URL, wait_until="networkidle", timeout=60000)
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

            err_text = page.inner_text("#data-errors")
            check("no data-error banners (all files loaded)",
                  err_text.strip() == "", err_text.strip()[:300])

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

            tl = page.evaluate(
                "document.querySelectorAll('#timeline rect').length")
            check("timeline drawn (detection days present)", tl >= 150,
                  f"{tl} bars")

            console_real = [c for c in console_errors
                            if "favicon" not in c.lower()]
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
