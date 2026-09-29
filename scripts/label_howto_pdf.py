"""Render data/labels/HOWTO.md to PDF, for reading away from the screen QGIS is on.

    python scripts/label_howto_pdf.py [--out PATH]

Markdown to HTML with the standard library (the file uses headings, tables,
lists, bold, code and links, and nothing else), then Chrome in headless mode
prints it. Chrome is already on this machine, which is why no PDF library is
added for a one-page document (AGENTS never-7).
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/labels/HOWTO.md"
OUT = ROOT / "data/labels/panduan-digitasi-label.pdf"

CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font: 10.5pt/1.5 "Segoe UI", Arial, sans-serif; color: #1a1a1a; }
h1 { font-size: 19pt; margin: 0 0 4mm; }
h2 { font-size: 13pt; margin: 8mm 0 2mm; border-bottom: 1px solid #ddd;
     padding-bottom: 1mm; page-break-after: avoid; }
p, li { margin: 0 0 2mm; }
ul, ol { margin: 0 0 3mm 6mm; padding: 0; }
li > ul, li > ol { margin-top: 1mm; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0 4mm;
        page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 1.5mm 2mm; text-align: left;
         vertical-align: top; font-size: 10pt; }
th { background: #f2f2f2; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f4f4f4;
       padding: 0 1mm; border-radius: 2px; }
pre { background: #f4f4f4; padding: 2.5mm 3mm; border-radius: 3px;
      font-family: Consolas, monospace; font-size: 9.5pt; overflow-wrap: anywhere; }
strong { color: #000; }
"""


def inline(text: str) -> str:
    """`code`, **bold**, *italic* and [text](url), after escaping."""
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def to_html(md: str) -> str:
    body: list[str] = []
    lines = md.splitlines()
    i, in_list, in_code = 0, False, False
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            if in_code:
                body.append("</pre>")
            else:
                if in_list:
                    body.append("</ul>")
                    in_list = False
                body.append("<pre>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            body.append(html.escape(line))
            i += 1
            continue

        # a table: header row, separator, then rows
        if line.startswith("|") and i + 1 < len(lines) and set(lines[i + 1]) <= set("|-: "):
            if in_list:
                body.append("</ul>")
                in_list = False
            cells = [c.strip() for c in line.strip("|").split("|")]
            body.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells)
                        + "</tr>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                body.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            body.append("</table>")
            continue

        if m := re.match(r"^(#{1,3}) (.+)$", line):
            if in_list:
                body.append("</ul>")
                in_list = False
            level = len(m.group(1))
            body.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
        elif m := re.match(r"^(\s*)[-*] (.+)$", line):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(m.group(2))}</li>")
        elif m := re.match(r"^(\d+)\. (.+)$", line):
            if not in_list:
                body.append("<ol>")
                in_list = "ol"
            body.append(f"<li>{inline(m.group(2))}</li>")
        elif not line.strip():
            if in_list:
                body.append("</ol>" if in_list == "ol" else "</ul>")
                in_list = False
        else:
            if in_list:
                body.append(f"<li>{inline(line.strip())}</li>")
            else:
                body.append(f"<p>{inline(line)}</p>")
        i += 1
    if in_list:
        body.append("</ol>" if in_list == "ol" else "</ul>")

    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>Panduan digitasi label</title><style>{CSS}</style></head>"
            f"<body>{''.join(body)}</body></html>")


def find_chrome() -> str:
    for path in CHROME:
        if Path(path).exists():
            return path
    for name in ("chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("no Chrome or Edge found; install one or print the HTML by hand")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    if not SRC.exists():
        raise SystemExit(f"missing {SRC}")

    page = to_html(SRC.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        src_html = Path(tmp) / "howto.html"
        src_html.write_text(page, encoding="utf-8")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([find_chrome(), "--headless", "--disable-gpu",
                        "--no-pdf-header-footer", f"--print-to-pdf={args.out}",
                        src_html.as_uri()], check=True, capture_output=True)
    size = args.out.stat().st_size
    print(f"written {args.out.relative_to(ROOT)} ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
