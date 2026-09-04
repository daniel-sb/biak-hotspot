"""Road distance decides which targets a morning can actually reach, so the
number has to be right in the two ways it can quietly be wrong: measuring to
a line's vertices instead of the line itself, and the bounding-box rejection
that makes 361 points against 40k segments finish in seconds skipping a
segment that was in fact the nearest.
"""

import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fieldwork_gpkg as fw  # noqa: E402


def seg(x1, y1, x2, y2, cls="residential"):
    return (x1, y1, x2, y2, cls)


def test_perpendicular_foot_not_vertex():
    # A 1000 m segment along y = 0. The point sits above its midpoint, so the
    # answer is 30 m; measuring to the nearer vertex would say 500.09 m.
    s = seg(0.0, 0.0, 1000.0, 0.0)
    assert fw.point_seg_m(500.0, 30.0, s) == 30.0


def test_clamps_past_the_end():
    s = seg(0.0, 0.0, 100.0, 0.0)
    assert fw.point_seg_m(-40.0, 30.0, s) == 50.0     # beyond the start
    assert fw.point_seg_m(140.0, 30.0, s) == 50.0     # beyond the end


def test_degenerate_segment_is_a_point():
    s = seg(10.0, 10.0, 10.0, 10.0)
    assert fw.point_seg_m(13.0, 14.0, s) == 5.0


def brute(lat, lon, segs):
    kx = math.radians(1.0) * fw.EARTH_R * math.cos(math.radians(fw.ROAD_PROJ_LAT))
    ky = math.radians(1.0) * fw.EARTH_R
    px, py = lon * kx, lat * ky
    best, cls = float("inf"), None
    for s in segs:
        d = fw.point_seg_m(px, py, s)
        if d < best:
            best, cls = d, s[4]
    return best, cls


def test_bbox_rejection_never_changes_the_answer():
    """The prune is an optimisation; it must be invisible in the result.

    A segment can be far in x and y from a point and still be the closest one
    when everything else is further, which is exactly the case a too-eager
    rejection gets wrong.
    """
    rng_segs = []
    step = 137.0
    for i in range(60):
        a = i * step
        rng_segs.append(seg(a, a * 0.5, a + 400.0, a * 0.5 - 250.0,
                            "track" if i % 3 else "trunk"))
    for lat in (-1.20, -1.10, -1.00):
        for lon in (135.90, 136.05, 136.20):
            assert fw.nearest_road(lat, lon, rng_segs) == brute(
                lat, lon, rng_segs)


def test_empty_road_file_reports_unknown_not_zero():
    # AGENTS never-2 in miniature: no roads is not a road at 0 m.
    assert fw.nearest_road(-1.1, 136.0, []) == (None, None)


def test_tracked_road_file_loads_and_filters_classes():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    path = ROOT / cfg["road_lines"]
    assert path.exists(), "run scripts/fetch_osm_roads.py"
    segs = fw.load_roads(path)
    assert len(segs) > 10_000
    assert {s[4] for s in segs} <= set(fw.ROAD_DRIVEABLE)
    # Footways and paths are kept in the tracked file on purpose, but they
    # must not be counted as roads a motorbike reaches.
    assert "footway" not in fw.ROAD_DRIVEABLE
    on_foot = fw.load_roads(path, classes={"footway", "path"})
    assert not ({s[4] for s in on_foot} & set(fw.ROAD_DRIVEABLE))


def test_a_target_on_the_road_reads_near_zero():
    """A point taken from the road file itself must measure ~0 m from it."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    import json
    feats = json.loads((ROOT / cfg["road_lines"]).read_text(encoding="utf-8"))
    line = next(f for f in feats["features"]
                if f["properties"]["highway"] in fw.ROAD_DRIVEABLE
                and len(f["geometry"]["coordinates"]) >= 3)
    lon, lat = line["geometry"]["coordinates"][1]
    segs = fw.load_roads(ROOT / cfg["road_lines"])
    d, _ = fw.nearest_road(lat, lon, segs)
    assert d < 1.0, d


def test_update_road_columns_keeps_survey_points(tmp_path):
    """The migration exists so the columns can arrive after the GeoPackage has
    been to the field. If it loses a survey point it is worse than useless -
    a rebuild at least fails the guard."""
    import sqlite3

    out = tmp_path / "t.gpkg"
    con = fw.gpkg_create(out)
    fw.gpkg_layer(con, "target_bakar",
                  [("target_id", "TEXT"), ("desa", "TEXT")],
                  [{"lon": 136.02991, "lat": -1.11230, "target_id": "T044",
                    "desa": "Yendidori"}], "d")
    fw.gpkg_layer(con, "target_kontrol", [("target_id", "TEXT")],
                  [{"lon": 136.05, "lat": -1.15, "target_id": "K001"}], "d")
    fw.gpkg_layer(con, "survei", fw.SURVEY_FIELDS, [], "d")
    con.execute("INSERT INTO survei (uuid, kelas) VALUES ('u1', 'bakar')")
    con.commit()
    con.close()

    segs = [seg(0.0, 0.0, 1.0, 0.0)]           # far away, but a real answer
    done = fw.update_road_columns(out, segs)
    assert done == {"target_bakar": 1, "target_kontrol": 1}

    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM survei").fetchone()[0] == 1
    for table in ("target_bakar", "target_kontrol"):
        cols = {r[1] for r in con.execute(
            'PRAGMA table_info("{}")'.format(table))}
        assert {"jarak_jalan_m", "kelas_jalan"} <= cols
        d, cls = con.execute(
            'SELECT jarak_jalan_m, kelas_jalan FROM "{}"'.format(
                table)).fetchone()
        assert d is not None and cls == "residential"
    con.close()

    # Running it twice must not duplicate the columns or change the answer.
    again = fw.update_road_columns(out, segs)
    assert again == done


def test_gpkg_point_read_round_trips():
    blob = fw.gpkg_point(136.0626332, -1.1624014)
    lon, lat = fw.gpkg_point_read(blob)
    assert (round(lon, 7), round(lat, 7)) == (136.0626332, -1.1624014)
