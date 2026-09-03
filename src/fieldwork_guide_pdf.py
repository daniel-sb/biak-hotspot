"""Render the field survey guide to PDF.

    python src/fieldwork_guide_pdf.py [--out PATH]

Source is src/fieldwork_guide.html. The PDF lands in fieldwork/ so it syncs
to the phone with the rest of the Mergin project and is readable offline,
which is where it is actually needed.

The guide describes the form and the photo workflow that
src/fieldwork_qgis_project.py builds. The two are written together and go
stale together: change the schema or a widget there and this has to be
re-read, not just re-rendered. That coupling is the reason the guide is
generated from a tracked file rather than typed once into a chat window.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "fieldwork_guide.html"
OUT = ROOT / "fieldwork" / "panduan-survei-lapangan.pdf"

HEADER = ('<div style="font-size:7pt;color:#8a8a8a;width:100%;padding:0 15mm;">'
          'Panduan Survei Lapangan &mdash; Ground Truth Bekas Bakar Biak</div>')
FOOTER = ('<div style="font-size:7pt;color:#8a8a8a;width:100%;padding:0 15mm;'
          'text-align:right;">hal <span class="pageNumber"></span> / '
          '<span class="totalPages"></span></div>')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not SRC.exists():
        raise SystemExit("{} is missing".format(SRC))
    args.out.parent.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(SRC.as_uri())
        page.wait_for_load_state("networkidle")
        page.pdf(path=str(args.out), format="A4", print_background=True,
                 display_header_footer=True,
                 header_template=HEADER, footer_template=FOOTER,
                 margin={"top": "18mm", "bottom": "16mm",
                         "left": "0", "right": "0"})
        browser.close()

    size = args.out.stat().st_size
    print("wrote {} ({:.0f} KB)".format(args.out, size / 1024))
    if size < 20_000:
        raise SystemExit("the PDF is suspiciously small - did the page render?")


if __name__ == "__main__":
    raise SystemExit(main())
