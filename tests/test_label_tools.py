"""Checks for the Task 23 label tools, offline and without geopandas.

Covers: the draw never overlapping an existing box or repeating a sample_id,
the second-pass copy carrying the same geometries with empty judgements and
leaving the first pass byte-identical, and Cohen's kappa on a hand-worked
table. The scripts need geopandas to run; the rules they apply live in
functions with no geo imports, so these tests still run in .venv.

    python -m pytest tests/test_label_tools.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import Point, box

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _load("label_add_boxes", ROOT / "scripts/label_add_boxes.py")
sp = _load("label_second_pass", ROOT / "scripts/label_second_pass.py")

GPKG = ROOT / "data/labels/biak_labels.gpkg"


# --------------------------------------------------------------------------
# 1. the draw

FRAME = box(0, 0, 2000, 2000)                      # 4 km square, metres
EXISTING = box(480, 480, 540, 540)                 # one 60 m box already placed


def test_draw_never_overlaps_an_existing_box_and_never_repeats_itself():
    squares = lab.draw_boxes(FRAME, EXISTING, 50, 20261014, 60.0, 150.0)
    assert len(squares) == 50
    # The centre is what has to be in the frame, not the whole box: see
    # test_the_centre_decides_not_the_box for why, and F22 for what filtering
    # the overhanging boxes out did to the area estimate.
    assert all(FRAME.contains(s.centroid) for s in squares)
    assert all(abs(s.area - 3600) < 1e-6 for s in squares)
    for s in squares:
        assert not s.intersects(EXISTING)
    for i, a in enumerate(squares):
        for b in squares[i + 1:]:
            assert a.centroid.distance(b.centroid) >= 150.0


def test_the_same_seed_gives_the_same_boxes():
    first = lab.draw_boxes(FRAME, EXISTING, 10, 20261014, 60.0, 150.0)
    second = lab.draw_boxes(FRAME, EXISTING, 10, 20261014, 60.0, 150.0)
    assert [s.wkt for s in first] == [s.wkt for s in second]


def test_the_next_sample_id_continues_the_existing_numbers():
    """MAP25 is the last box of the first map draw; the next must be MAP26,
    and a fresh stratum must start at its own 1 without colliding."""
    labels = pd.DataFrame({"sample_id": ["MAP01", "MAP09", "MAP25", None, "B01"]})
    assert lab.next_number(labels, "MAP") == 26
    assert lab.next_number(labels, "B") == 2
    assert lab.next_number(pd.DataFrame({"sample_id": []}), "B") == 1


def test_a_draw_with_no_room_adds_nothing_rather_than_a_placeholder():
    """An empty frame yields nothing, and a cramped one yields what fits.

    Never a padded-out list: scripts/label_add_boxes.py reports the shortfall
    and writes only the boxes it really drew.
    """
    assert lab.draw_boxes(box(0, 0, 0, 0), box(0, 0, 0, 0), 5,
                          1, 60.0, 150.0, tries=1000) == []
    # 500 m square, 150 m apart: a handful fit, nowhere near 50
    cramped = lab.draw_boxes(box(0, 0, 500, 500), box(0, 0, 0, 0), 50,
                             1, 60.0, 150.0, tries=20_000)
    assert 0 < len(cramped) < 50


def test_the_centre_decides_not_the_box():
    """A box whose centre is in the frame counts, even where it overhangs.

    F22 removed a filter that kept only boxes at least half covered by the map
    and the estimate moved from 614 to 683 ha, because the filter dropped the
    edge cases the assessment exists to measure. All three strata follow the
    draw, not the box, so this rule must not be tightened without saying what
    it does to the published area.
    """
    frame = box(0, 0, 100, 100)
    squares = lab.draw_boxes(frame, box(0, 0, 0, 0), 1, 7, 60.0, 150.0)
    assert len(squares) == 1
    assert frame.contains(squares[0].centroid)
    assert not frame.contains(squares[0])


def test_the_committed_box_layer_holds_no_duplicate_id_and_no_stray_stratum():
    """Read through sqlite alone: the layer is small and this runs in .venv."""
    con = sqlite3.connect(f"file:{GPKG.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT sample_id, sampling FROM labels").fetchall()
    finally:
        con.close()
    ids = [r[0] for r in rows]
    assert len(ids) == len(set(ids))
    assert {r[1] for r in rows} <= {"random_box", "map_burned",
                                    "footprint_unmapped", "purposive"}


# --------------------------------------------------------------------------
# 2. the second-pass copy

def make_pair(tmp_path: Path):
    """A miniature first pass: the real schema shape, two judged boxes, one
    rtree row, and a trigger, so the copy runs what the real file runs."""
    src = tmp_path / "pass1.gpkg"
    con = sqlite3.connect(src)
    con.executescript(
        "CREATE TABLE labels (fid INTEGER PRIMARY KEY, geom BLOB, sample_id TEXT,"
        " sampling TEXT, \"class\" TEXT, confidence TEXT, notes TEXT);"
        "CREATE VIRTUAL TABLE rtree_labels_geom USING rtree("
        " id, minx, maxx, miny, maxy);")
    con.execute("INSERT INTO rtree_labels_geom VALUES (1, 0, 0, 1, 1)")
    con.execute("INSERT INTO labels VALUES (1, x'00', 'MAP01', 'map_burned',"
                " 'burned', 'high', 'looks clear')")
    con.execute("INSERT INTO labels VALUES (2, x'01', 'B01', 'footprint_unmapped',"
                " NULL, NULL, NULL)")
    con.execute(
        "CREATE TRIGGER rt AFTER UPDATE OF \"geom\" ON labels "
        "WHEN ST_IsEmpty(NEW.geom) BEGIN SELECT 1; END")
    con.commit()
    con.close()
    return src


def test_the_second_pass_blanks_every_judgement_and_keeps_the_boxes(tmp_path):
    src = make_pair(tmp_path)
    dst = tmp_path / "pass2.gpkg"
    sp.copy_boxes(src, dst)
    con = sqlite3.connect(dst)
    try:
        got = con.execute("SELECT sample_id, sampling, \"class\", confidence,"
                          " notes FROM labels ORDER BY sample_id").fetchall()
        geom = con.execute("SELECT hex(geom) FROM labels ORDER BY sample_id").fetchall()
        triggers = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")]
        rtree = con.execute("SELECT * FROM rtree_labels_geom").fetchall()
    finally:
        con.close()
    assert got == [("B01", "footprint_unmapped", None, None, None),
                   ("MAP01", "map_burned", None, None, None)]
    assert geom == [("01",), ("00",)]          # both geometries, unreordered
    assert triggers == ["rt"]           # restored, not lost with the drop
    assert rtree == [(1, 0.0, 0.0, 1.0, 1.0)]


def test_the_first_pass_is_byte_identical_after_a_copy(tmp_path):
    src = make_pair(tmp_path)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    sp.copy_boxes(src, tmp_path / "pass2.gpkg")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_a_surviving_judgement_stops_the_copy(tmp_path):
    """The blanking is checked, not assumed: a class that comes back must
    stop the run rather than reach the second interpreter."""
    dst = tmp_path / "leaky.gpkg"
    con = sqlite3.connect(dst)
    con.execute('CREATE TABLE labels (sample_id TEXT, "class" TEXT,'
                " confidence TEXT, notes TEXT)")
    con.execute("INSERT INTO labels VALUES ('MAP01', 'burned', NULL, NULL)")
    con.commit()
    try:
        assert sp.judgements_left(con) == 1
    finally:
        con.close()


# --------------------------------------------------------------------------
# 3. kappa

def test_kappa_matches_a_hand_worked_table():
    """Thirty boxes: 12 both burned, 13 both unburned, 3 pass1-only,
    2 pass2-only.

    p1 burned 15/30 (a 50/50 split, so p_e is exactly 0.5), p2 burned 14/30.
    p_o = 25/30 = 0.8333, kappa = (0.8333 - 0.5) / 0.5 = 0.6667.
    """
    pairs = ([("burned", "burned")] * 12 + [("burned", "unburned")] * 3
             + [("unburned", "burned")] * 2 + [("unburned", "unburned")] * 13)
    k, agreement, n = sp.kappa(pairs)
    assert n == 30
    assert round(agreement, 3) == 0.833
    assert round(k, 3) == 0.667


def test_kappa_is_one_not_a_division_by_zero_when_they_agree_everywhere():
    k, agreement, n = sp.kappa([("burned", "burned")] * 4
                               + [("unburned", "unburned")] * 6)
    assert (k, agreement, n) == (1.0, 1.0, 10)


def test_kappa_is_none_when_there_is_nothing_to_compare():
    assert sp.kappa([]) == (None, None, 0)


def demo() -> None:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    test_draw_never_overlaps_an_existing_box_and_never_repeats_itself()
    test_the_same_seed_gives_the_same_boxes()
    test_the_next_sample_id_continues_the_existing_numbers()
    test_a_draw_with_no_room_adds_nothing_rather_than_a_placeholder()
    test_the_committed_box_layer_holds_no_duplicate_id_and_no_stray_stratum()
    test_the_second_pass_blanks_every_judgement_and_keeps_the_boxes(tmp)
    test_the_first_pass_is_byte_identical_after_a_copy(tmp)
    test_a_surviving_judgement_stops_the_copy(tmp)
    test_kappa_matches_a_hand_worked_table()
    test_kappa_is_one_not_a_division_by_zero_when_they_agree_everywhere()
    test_kappa_is_none_when_there_is_nothing_to_compare()
    print("label tools: ok")


if __name__ == "__main__":
    demo()
