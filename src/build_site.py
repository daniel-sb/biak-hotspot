"""Assemble docs/*.html from the sources under site/ (adr/0002).

The site used to be one hand-written docs/index.html. It is now five pages that
share a head, a nav, a footer and three script files, so something has to stamp
the shared chrome into each one. That something is this script rather than
Eleventy or Astro: the duplication being removed is about thirty lines a page,
and a JavaScript toolchain in the daily cron would be a second language runtime
installed every evening to save them.

Sources:
    site/partials/page.html   the skeleton, with {{SLOT}} placeholders
    site/pages/<name>.body.html   one body fragment per page
    site/assets/*              css and js, copied verbatim to docs/assets/

Outputs, all overwritten on every run:
    docs/<name>.html
    docs/assets/*

Nothing under docs/data/ or docs/briefs/ is read or written here. Those belong
to the ingest pipeline, and this script must never be the reason a published
number changes (adr/0003).

    python src/build_site.py

The self-check runs with no arguments too:

    python src/build_site.py --check
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = ROOT / "docs"

SUB = ("Thermal anomalies detected from satellite around Biak, Supiori and "
       "Numfor, Papua, Indonesia. Data: NASA FIRMS (VIIRS and MODIS) and "
       "Himawari-9.")

MAPLIBRE = (
    '<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" '
    'rel="stylesheet">\n'
    '<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js">'
    "</script>\n")

# name, nav label, <title>, <h1>, the scripts it loads, and whether it needs
# MapLibre. burned-area and methods are deliberately absent: they have no
# content until step 3 of the rebuild, and an empty page on a public site is
# worse than a nav that grows by one line later.
PAGES = [
    ("index", "The 2026 season",
     "Biak hotspot monitor — the 2026 season",
     "Biak 2026: the fire season",
     ["core.js", "map.js", "index.js"], True),
    # "Fuel and drought" once the fuel map lands in step 3; the page carries
    # only the water balance and the vegetation indices today, and a nav label
    # must not promise a panel that is not there.
    ("conditions", "Drought and vegetation",
     "Biak hotspot monitor — drought and vegetation",
     "Drought and vegetation",
     ["core.js", "climate.js", "conditions.js"], False),
    ("history", "Detection record",
     "Biak hotspot monitor — the detection record",
     "The detection record",
     ["core.js", "timeline.js", "history.js"], False),
]


def nav_html(current):
    """Ordinary links, so the nav works with JavaScript switched off."""
    out = []
    for name, label, _title, _h1, _scripts, _map in PAGES:
        href = f"{name}.html"
        mark = ' aria-current="page"' if name == current else ""
        out.append(f'<a href="{href}"{mark}>{label}</a>')
    return "\n  ".join(out)


def render(name, title, h1, scripts, needs_map, skeleton):
    body = (SITE / "pages" / f"{name}.body.html").read_text(encoding="utf-8")
    tags = "\n".join(f'<script src="assets/{s}"></script>' for s in scripts)
    page = skeleton
    for slot, value in (("{{TITLE}}", title),
                        ("{{HEAD_EXTRA}}", MAPLIBRE if needs_map else ""),
                        ("{{H1}}", h1),
                        ("{{SUB}}", SUB),
                        ("{{NAV}}", nav_html(name)),
                        ("{{BODY}}", body.strip("\n")),
                        ("{{SCRIPTS}}", tags)):
        page = page.replace(slot, value)
    assert "{{" not in page, f"{name}: unfilled slot"
    return page


def build():
    skeleton = (SITE / "partials" / "page.html").read_text(encoding="utf-8")
    written = []
    for name, _label, title, h1, scripts, needs_map in PAGES:
        page = render(name, title, h1, scripts, needs_map, skeleton)
        dest = OUT / f"{name}.html"
        dest.write_text(page, encoding="utf-8", newline="\n")
        written.append(dest)
    assets = OUT / "assets"
    assets.mkdir(exist_ok=True)
    for src in sorted((SITE / "assets").iterdir()):
        if src.is_file():
            shutil.copyfile(src, assets / src.name)
            written.append(assets / src.name)
    return written


def demo():
    """Assert the properties a broken build would quietly violate."""
    skeleton = (SITE / "partials" / "page.html").read_text(encoding="utf-8")
    pages = {n: render(n, t, h, s, m, skeleton)
             for n, _l, t, h, s, m in PAGES}

    for name, page in pages.items():
        # every page carries the whole nav, including a link to itself
        for other, label, *_ in PAGES:
            assert f'href="{other}.html"' in page, f"{name} lost {other}"
        assert page.count('aria-current="page"') == 1, name
        # the chrome every page needs
        assert '<ul id="data-errors"></ul>' in page, name
        assert 'id="generated"' in page, name
        # MapLibre is pinned where it is loaded, and absent where it is not
        if "map.js" in page:
            assert "maplibre-gl@4.7.1" in page, name
        else:
            assert "maplibre" not in page, f"{name} loads MapLibre it cannot use"

    # the map, the brief and the evening product live on index and nowhere else
    for ident in ('id="map"', 'id="brief"', 'id="evening"', 'id="status"'):
        assert ident in pages["index"], ident
        for name in ("conditions", "history"):
            assert ident not in pages[name], f"{name} still has {ident}"

    # the panels landed where they were sent
    assert 'id="timeline"' in pages["history"]
    assert 'id="drought"' in pages["conditions"]
    assert 'id="veg"' in pages["conditions"]

    # every script a page loads exists under site/assets/
    for name, _l, _t, _h, scripts, _m in PAGES:
        for s in scripts:
            assert (SITE / "assets" / s).is_file(), s

    print(f"all checks passed for {len(pages)} pages")


if __name__ == "__main__":
    if "--check" in sys.argv:
        demo()
    else:
        for p in build():
            print(p.relative_to(ROOT).as_posix())
        demo()
