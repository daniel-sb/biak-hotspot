"""Checks for the HOWTO renderer, offline and with no geo imports.

Both cases here were real defects in data/labels/panduan-digitasi-label.pdf: a
bold span broken across two source lines printed its asterisks, and a fenced
block printed as one long line that ran off the page.

    python -m pytest tests/test_label_howto_pdf.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


hp = _load("label_howto_pdf", ROOT / "scripts/label_howto_pdf.py")


def test_a_bold_span_broken_across_lines_still_comes_out_bold():
    html = hp.to_html("Judge the box **as it changed\nbetween the dates**, not as it looks.")
    assert "<strong>as it changed between the dates</strong>" in html
    assert "**" not in html


def test_a_wrapped_bullet_stays_one_bullet():
    html = hp.to_html("- `unsure` is a real answer.\n  Mark it and move on.\n- Do not move a box.")
    assert html.count("<li>") == 2
    assert "is a real answer. Mark it and move on." in html


def test_a_fenced_block_keeps_its_line_breaks():
    html = hp.to_html("```\nGDAL_DATA=/share/gdal\nPROJ_LIB=/share/proj\n```")
    assert "GDAL_DATA=/share/gdal\nPROJ_LIB=/share/proj\n" in html


def test_a_table_row_is_never_joined_to_the_paragraph_above_it():
    html = hp.to_html("The strata:\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html and "<th>a</th>" in html
    assert "<p>The strata:</p>" in html


def test_the_committed_howto_renders_with_no_stray_markup():
    html = hp.to_html((ROOT / "data/labels/HOWTO.md").read_text(encoding="utf-8"))
    assert "**" not in html, "a bold span did not close"
    assert "</table>" in html and "<h2>" in html


def demo() -> None:
    test_a_bold_span_broken_across_lines_still_comes_out_bold()
    test_a_wrapped_bullet_stays_one_bullet()
    test_a_fenced_block_keeps_its_line_breaks()
    test_a_table_row_is_never_joined_to_the_paragraph_above_it()
    test_the_committed_howto_renders_with_no_stray_markup()
    print("howto renderer: ok")


if __name__ == "__main__":
    demo()
