"""Checks for the two interval estimators in scripts/label_accuracy.py.

Offline: the module's imports of geopandas and Earth Engine live inside
main(), so the estimators can be imported and checked on their own.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "label_accuracy", ROOT / "scripts/label_accuracy.py")
la = importlib.util.module_from_spec(_spec)
sys.modules["label_accuracy"] = la
_spec.loader.exec_module(la)


def test_wilson_survives_zero_successes():
    """0 of 10 is not 0: the whole of F22 rests on this upper bound."""
    lo, hi = la.wilson(0, 10)
    assert lo == 0.0
    assert 0.27 < hi < 0.29


def test_olofsson_matches_the_published_figures():
    """The two strata of F20, through Eqs. 9 to 11 of Olofsson et al. 2014."""
    p, se, (lo, hi) = la.olofsson([819.1, 812.8], [(15, 20), (0, 10)])
    assert round(p, 4) == 0.3764
    assert round(se, 4) == 0.0499
    assert round(lo) == 455 and round(hi) == 774
    # and the point of F23: the map's 819 ha falls outside that interval
    # although it falls inside the Wilson one.
    assert hi < 819.1


def test_olofsson_gives_a_zero_count_stratum_no_variance():
    """Why F23 says the Wilson interval is the one to quote."""
    _, se_zero, _ = la.olofsson([800.0, 800.0], [(15, 20), (0, 10)])
    _, se_one, _ = la.olofsson([800.0, 800.0], [(15, 20), (1, 10)])
    assert se_one > se_zero


def demo() -> None:
    test_wilson_survives_zero_successes()
    test_olofsson_matches_the_published_figures()
    test_olofsson_gives_a_zero_count_stratum_no_variance()
    print("label_accuracy estimators: ok")


if __name__ == "__main__":
    demo()
