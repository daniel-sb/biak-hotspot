"""Checks for the two interval estimators in scripts/label_accuracy.py.

Offline: the module's imports of geopandas and Earth Engine live inside
main(), so the estimators can be imported and checked on their own.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

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


def test_stratum_b_is_read_from_both_designs_and_kept_apart():
    """Task 23: stratum B is the random_box boxes inside a footprint the map
    does not claim PLUS the footprint_unmapped boxes. A mapped box is A even
    where its coverage is zero: membership follows the draw."""
    judged = pd.DataFrame([
        # A: drawn inside the map, whatever the box's coverage says
        {"sample_id": "MAP01", "sampling": "map_burned", "class": "burned",
         "map_share": 0.9, "in_footprint": True},
        {"sample_id": "MAP02", "sampling": "map_burned", "class": "burned",
         "map_share": 0.1, "in_footprint": True},
        # B by the first design: random_box, in a footprint, mostly unmapped
        {"sample_id": "E0301-IN01", "sampling": "random_box", "class": "unburned",
         "map_share": 0.0, "in_footprint": True},
        # random_box but the map claims most of it - neither stratum's design
        {"sample_id": "E0301-IN02", "sampling": "random_box", "class": "burned",
         "map_share": 0.8, "in_footprint": True},
        # random_box outside every footprint: counted, carries no area
        {"sample_id": "E0301-OUT01", "sampling": "random_box", "class": "unburned",
         "map_share": 0.0, "in_footprint": False},
        # B by the second design, drawn from the footprint frame by area alone
        {"sample_id": "B01", "sampling": "footprint_unmapped", "class": "burned",
         "map_share": 0.0, "in_footprint": True},
        {"sample_id": "B02", "sampling": "footprint_unmapped", "class": "unburned",
         "map_share": 0.0, "in_footprint": True},
    ])
    a, b_random, b_plain, out_fp = la.stratum_frames(judged)
    assert sorted(a.sample_id) == ["MAP01", "MAP02"]
    assert sorted(b_random.sample_id) == ["E0301-IN01"]
    assert sorted(b_plain.sample_id) == ["B01", "B02"]
    assert sorted(out_fp.sample_id) == ["E0301-OUT01"]
    # B01 is the only burned box of stratum B: IN01 and B02 come back unburned,
    # and the mapped IN02 belongs to neither design of B.
    assert int((pd.concat([b_random, b_plain])["class"] == "burned").sum()) == 1


def test_a_zero_count_stratum_still_has_an_upper_bound():
    """F22's whole correction: 0 of 50 is not 0."""
    lo, hi = la.wilson(0, 50)
    assert lo == 0.0
    assert 0.05 < hi < 0.08
    # and it tightens with n, which is why Task 23 drew more boxes
    assert la.wilson(0, 50)[1] < la.wilson(0, 10)[1]


def demo() -> None:
    test_wilson_survives_zero_successes()
    test_olofsson_matches_the_published_figures()
    test_olofsson_gives_a_zero_count_stratum_no_variance()
    test_stratum_b_is_read_from_both_designs_and_kept_apart()
    test_a_zero_count_stratum_still_has_an_upper_bound()
    print("label_accuracy estimators: ok")


if __name__ == "__main__":
    demo()
