"""The date rule, checked against the three Colab runs that were observed.

No network: scene_dates() is the only part that reaches the catalogue, and
nothing here calls it.

    python -m pytest tests/test_s2dr4_dates.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("s2dr4_dates", ROOT / "scripts/s2dr4_dates.py")
dates = importlib.util.module_from_spec(spec)
sys.modules["s2dr4_dates"] = dates
spec.loader.exec_module(dates)

# The real catalogue over the E0313 tile, read 2026-10-15. 5 August is left out:
# at 99.4% cloud S2DR4 would not consider it.
HAVE = ["2026-08-03", "2026-08-08", "2026-08-13", "2026-08-18",
        "2026-08-23", "2026-08-25", "2026-08-28"]


def test_the_rule_reproduces_what_colab_actually_returned():
    assert dates.resolve("2026-08-23", HAVE) == "2026-08-25"
    assert dates.resolve("2026-08-20", HAVE) == "2026-08-23"
    assert dates.resolve("2026-08-28", HAVE) == "2026-08-28"


def test_every_scene_is_reachable_by_asking_for_the_computed_date():
    for wanted in HAVE:
        assert dates.resolve(dates.request_date(wanted, HAVE), HAVE) == wanted


def test_a_date_the_catalogue_does_not_hold_is_refused():
    """Asking for a scene that does not exist must fail rather than silently
    return a neighbouring date, which is the whole defect being worked around."""
    with pytest.raises(SystemExit):
        dates.request_date("2026-08-20", HAVE)


def test_nothing_in_the_window_yields_nothing_rather_than_a_guess():
    assert dates.resolve("2026-01-01", HAVE) is None


def demo() -> None:
    dates.demo()


if __name__ == "__main__":
    demo()
