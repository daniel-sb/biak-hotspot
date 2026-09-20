"""Offline checks for the detection climatology baseline (Task 17,
PLAN.md Phase 5 step 2). Synthetic frames and a synthetic manifest built
inside the test, in the style of test_recurrence.py; the real store and
manifest are touched only by the determinism check. No network.

Run with pytest:
    python -m pytest tests/test_baseline.py
or directly (no pytest needed):
    python tests/test_baseline.py
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import baseline as bl  # noqa: E402

DEG = 1.0 / bl.M_PER_DEG
GROUPS = [["VIIRS_SNPP_NRT"], ["VIIRS_NOAA20_NRT"], ["MODIS_NRT"]]


def tiny_grid():
    """Four columns by two rows of 1000 m cells from (136.0, -1.0)."""
    return bl.Grid([136.0, -1.0, 136.0 + 4 * 1000 * DEG,
                    -1.0 + 2 * 1000 * DEG], 1000)


def run_entry(source, outcome="fetched", utc="2024-03-01T16:00:00Z",
              chunk_start="2024-03-01", days=1):
    return {"source": source, "outcome": outcome, "utc": utc,
            "chunk_start": chunk_start, "days": days}


def test_point_to_cell_and_land_cells():
    """Check 1: a point maps to the expected cell; a land polygon covering
    exactly one cell makes only that cell a land cell."""
    g = tiny_grid()
    i, j = g.index_arrays([136.0 + 10 * DEG, 136.0 + 2500 * DEG],
                          [-1.0 + 10 * DEG, -1.0 + 1500 * DEG])
    assert (int(i[0]), int(j[0])) == (0, 0)      # south-west corner cell
    assert (int(i[1]), int(j[1])) == (2, 1)      # third column, second row

    import shapely.geometry as sg
    tmp = Path(tempfile.mkdtemp()) / "tiny.geojson"
    tmp.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": sg.mapping(g.cell_box(0, 0))}]}),
        encoding="utf-8")
    cells = bl.land_cells(g, tmp)
    assert (0, 0) in cells
    assert (1, 0) not in cells and (2, 1) not in cells


def test_doy_365_and_window_wrap():
    """Check 2: 29 February takes 28 February's number on the 365-day
    circle; the window wraps across 31 December and 1 January."""
    assert bl.day_of_year_365(date(2024, 2, 29)) == \
        bl.day_of_year_365(date(2023, 2, 28))
    assert bl.day_of_year_365(date(2024, 3, 1)) == \
        bl.day_of_year_365(date(2023, 3, 1))
    assert bl.day_of_year_365(date(2024, 12, 31)) == 365
    assert bl.day_of_year_365(date(2024, 1, 1)) == 1
    assert bl.doy_window(365, 1) == {364, 365, 1}
    assert bl.doy_window(1, 1) == {365, 1, 2}


def test_known_probability():
    """Check 3: a cell with a detection on one of two observed years' same
    day, half window 0, gives probability 0.5."""
    det = pd.DataFrame({"cell_i": [0, 0], "cell_j": [0, 0],
                        "date_wit": ["2024-03-01", "2025-03-01"]})
    days = ["2024-03-01", "2025-03-01"]
    probs = bl.climatology(det.iloc[[0]], days, [(0, 0)], half_window=0)
    k = bl.day_of_year_365(date(2024, 3, 1)) - 1
    assert abs(probs[(0, 0)][k] - 0.5) < 1e-12
    # the same cell on a day-of-year with no observed training day stays 0
    assert probs[(0, 0)][0] == 0.0


def test_missing_manifest_day_leaves_denominator():
    """Check 4: a day with no manifest entry is not observed. It leaves
    the denominator: the training window counts only the observed day, so
    a detection that exists only on the unobserved day contributes no
    zero and the probability over the observed day alone is 1.0."""
    runs = [run_entry(s) for s in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT",
                                   "MODIS_NRT")]
    obs, unobs = bl.observed_days(["2024-03-01", "2024-03-02"], runs,
                                  GROUPS)
    assert obs == ["2024-03-01"] and unobs == ["2024-03-02"]
    det = pd.DataFrame({"cell_i": [0, 0], "cell_j": [0, 0],
                        "date_wit": ["2024-03-01", "2024-03-02"]})
    probs = bl.climatology(det, obs, [(0, 0)], half_window=0)
    assert probs[(0, 0)][bl.day_of_year_365(date(2024, 3, 1)) - 1] == 1.0


def test_partial_instrument_failure_not_observed():
    """Check 5: MODIS fetched and closed but S-NPP failed and NOAA-20
    absent: the day is not the day the other years saw."""
    runs = [run_entry("MODIS_NRT"),
            run_entry("VIIRS_SNPP_NRT", outcome="failed")]
    obs, unobs = bl.observed_days(["2024-03-01"], runs, GROUPS)
    assert obs == [] and unobs == ["2024-03-01"]


def test_n21_excluded_and_counted():
    """Check 6: an N21 detection is set aside and counted, and a cell-day
    positive only through N21 is reported as lost."""
    det = pd.DataFrame({
        "cell_i": [1, 2, 2], "cell_j": [1, 2, 2],
        "date_wit": ["2024-03-01", "2024-03-01", "2024-03-01"],
        "satellite": ["N21", "N21", "N"]})
    kept, counts, lost = bl.constellation_split(
        det, keys={"N", "N20"}, observed_set={"2024-03-01"})
    assert len(kept) == 1 and counts == {"N21": 2}
    # cell (1,1) was positive only through N21: lost. (2,2) keeps its N row.
    assert lost == 1


def test_brier_and_average_precision():
    """Check 7: hand-computed Brier and average precision, including a
    case with tied scores where ranking order must not matter."""
    p = np.array([0.8, 0.6, 0.4, 0.2])
    y = np.array([1, 0, 1, 0])
    assert abs(np.mean((p - y) ** 2) - 0.2) < 1e-12  # (0.04+0.36+0.36+0.04)/4
    # thresholds 0.8 (P 1.0, R 0.5), 0.6 (P 0.5, R 0.5), 0.4 (P 2/3, R 1.0)
    assert abs(bl.average_precision(p, y) - (0.5 + 0.5 * 2 / 3)) < 1e-12
    # ties are one threshold: precision = prevalence, recall = 1
    assert abs(bl.average_precision([0.5, 0.5], [1, 0]) - 0.5) < 1e-12
    # [0.9, 0.5, 0.5, 0.1] / [0, 1, 1, 0]: the 0.9 threshold has precision
    # 0, the 0.5 tie is one threshold at P 2/3 R 1, the 0.1 threshold adds 0
    tied = ([0.9, 0.5, 0.5, 0.1], [0, 1, 1, 0])
    assert abs(bl.average_precision(*tied) - 2 / 3) < 1e-12
    # permuting rows WITHIN the tie must not move the result - that is what
    # "tied scores are one threshold" buys; a per-row step function would
    # give 7/12 here and would shift with the permutation
    reordered = ([0.5, 0.9, 0.1, 0.5], [1, 0, 0, 1])
    assert abs(bl.average_precision(*reordered)
               - bl.average_precision(*tied)) < 1e-12


def test_no_leakage_across_folds():
    """Check 8: perturbing the held-out year's detections leaves that
    fold's training climatology identical."""
    train = pd.DataFrame({
        "cell_i": [0], "cell_j": [0], "date_wit": ["2024-03-01"]})
    held = pd.DataFrame({
        "cell_i": [0, 0], "cell_j": [0, 0],
        "date_wit": ["2026-03-01", "2026-03-02"]})
    days = ["2024-03-01", "2025-03-01"]
    before = bl.climatology(train, days, [(0, 0)], half_window=0)
    k = bl.day_of_year_365(date(2024, 3, 1)) - 1
    assert before[(0, 0)][k] == 0.5     # detection on one of two years
    # wild perturbation of the held-out year, order shuffled; the fold's
    # training fit must not move
    perturbed = pd.concat([train, held]).sample(frac=1.0, random_state=1)
    after = bl.climatology(
        perturbed[~perturbed.date_wit.str[:4].eq("2026")],
        days, [(0, 0)], half_window=0)
    assert np.array_equal(before[(0, 0)], after[(0, 0)])


def test_eval_deterministic():
    """Check 9: the same inputs give byte-identical baseline_eval.json."""
    doc_a = bl.evaluate()
    doc_b = bl.evaluate()
    assert json.dumps(doc_a, sort_keys=True, indent=1).encode() == \
        json.dumps(doc_b, sort_keys=True, indent=1).encode()


if __name__ == "__main__":
    fns = [(name, obj) for name, obj in sorted(globals().items())
           if name.startswith("test_") and callable(obj)]
    for name, fn in fns:
        fn()
        print(f"PASS {name}")
    print(f"all {len(fns)} checks passed")
