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
# MapLibre.
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
    ("results", "Results",
     "Biak hotspot monitor — results",
     "Results, and what they do not support",
     ["core.js", "results.js"], False),
    ("methods", "Methodology",
     "Biak hotspot monitor — methodology",
     "How these numbers were made",
     ["core.js", "methods.js"], False),
    ("gallery", "Burn atlas",
     "Biak hotspot monitor — the burn atlas",
     "Burn atlas: three footprints, six dates",
     ["core.js", "gallery.js"], False),
    ("brief", "Daily brief",
     "Biak hotspot monitor — the daily brief",
     "Daily brief and the previous evening",
     ["core.js", "brief.js"], False),
]


# The front page is the map and manages its own full-width layout. Every
# other page is prose, and gets one measured column with a shared type scale,
# so a new page does not have to restate it.
WIDE = {"index"}
PROSE_MAIN = ('<main class="mx-auto max-w-[72rem] px-4 pt-4 pb-2 '
              '[&_h2]:font-chrome [&_h2]:text-[1.1rem] [&_h2]:font-semibold '
              '[&_h2]:mt-6 [&_h2]:mb-1 [&_p]:my-2 [&_p]:max-w-[68ch]">')

NAV_LINK = ("inline-block border-b-2 px-2 py-1 font-chrome text-[0.82rem] "
            "no-underline")
NAV_REST = "border-transparent text-paper/70 hover:text-paper"
NAV_HERE = "border-ember text-paper font-semibold"


def nav_html(current):
    """Ordinary links, so the nav works with JavaScript switched off."""
    out = []
    for name, label, _title, _h1, _scripts, _map in PAGES:
        href = f"{name}.html"
        here = name == current
        mark = ' aria-current="page"' if here else ""
        cls = f"{NAV_LINK} {NAV_HERE if here else NAV_REST}"
        out.append(f'<a class="{cls}" href="{href}"{mark}>{label}</a>')
    return "\n  ".join(out)


def render(name, title, h1, scripts, needs_map, skeleton):
    body = (SITE / "pages" / f"{name}.body.html").read_text(encoding="utf-8")
    if name not in WIDE:
        body = PROSE_MAIN + "\n" + body.strip("\n") + "\n</main>"
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
        assert 'id="data-errors"' in page, name
        assert 'id="generated"' in page, name
        # MapLibre is pinned where it is loaded, and absent where it is not
        if "map.js" in page:
            assert "maplibre-gl@4.7.1" in page, name
        else:
            assert "maplibre" not in page, f"{name} loads MapLibre it cannot use"

    # the map and the status strip live on index, the brief and the evening
    # product on their own page, and neither appears anywhere else
    where = {'id="map"': "index", 'id="status"': "index",
             'id="layers"': "index", 'id="legend"': "index",
             'id="brief"': "brief", 'id="evening"': "brief"}
    for ident, home in where.items():
        assert ident in pages[home], f"{home} is missing {ident}"
        for name in pages:
            if name != home:
                assert ident not in pages[name], f"{name} also has {ident}"

    # the front page points at the pages its disclaimer names, and they exist,
    # so the disclaimer is never a link to nothing
    for target in ("methods.html", "results.html", "brief.html"):
        assert f'href="{target}"' in pages["index"], target
        assert target.removesuffix(".html") in pages, target

    # the panels landed where they were sent
    assert 'id="gallery"' in pages["gallery"]
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
