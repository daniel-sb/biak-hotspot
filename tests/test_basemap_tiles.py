"""Tile arithmetic for the field basemap.

The failure this guards against is quiet: a wrong y flip produces an MBTiles
file that opens, renders, and is vertically mirrored, which nobody notices
until they are standing in the wrong village with no signal.
"""

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import basemap_mbtiles as bm  # noqa: E402


def test_zoom_zero_is_one_tile():
    assert bm.deg2tile(0, 0, 0) == (0, 0)
    assert bm.deg2tile(-1.0, 136.0, 0) == (0, 0)


def test_quadrants_at_zoom_one():
    # x grows eastward from -180, y grows southward from the north pole
    assert bm.deg2tile(45, -90, 1) == (0, 0)      # north-west
    assert bm.deg2tile(45, 90, 1) == (1, 0)       # north-east
    assert bm.deg2tile(-45, -90, 1) == (0, 1)     # south-west
    assert bm.deg2tile(-45, 90, 1) == (1, 1)      # south-east


def test_biak_lands_where_the_built_basemap_put_it():
    # The z12 tiles actually written for the corridor spanned columns
    # 3593-3598; Biak town sits inside that range, just south of the equator.
    x, y = bm.deg2tile(-1.0, 136.0, 12)
    assert 3593 <= x <= 3598
    assert y == 2059
    # and one row south of the equator, which is the midpoint at every zoom
    assert bm.deg2tile(0.0, 136.0, 12)[1] == 2048
    assert y > bm.deg2tile(0.0, 136.0, 12)[1]


def test_mercator_clamp_keeps_the_index_in_range():
    for z in (0, 3, 12):
        for lat in (90, -90, 89.9, -89.9):
            x, y = bm.deg2tile(lat, 0, z)
            assert 0 <= y < 2 ** z
            assert 0 <= x < 2 ** z


def test_tms_flip_is_its_own_inverse():
    for z in (0, 1, 8, 16):
        n = 1 << z
        for y in (0, n // 2, n - 1):
            assert (n - 1) - ((n - 1) - y) == y
    # and it really does move the top row to the bottom
    assert (1 << 12) - 1 - 0 == 4095


def test_tiles_for_covers_the_box_and_nothing_else():
    box = [135.8358, -1.2333, 136.2938, -0.8241]
    got = bm.tiles_for(box, 12)
    assert len(got) == 36                       # what the real run produced
    assert all(t[0] == 12 for t in got)
    xs = {t[1] for t in got}
    ys = {t[2] for t in got}
    assert xs == set(range(min(xs), max(xs) + 1)), "column range has a gap"
    assert ys == set(range(min(ys), max(ys) + 1)), "row range has a gap"
    # every corner of the box must fall inside a tile that was requested
    for lat in (box[1], box[3]):
        for lon in (box[0], box[2]):
            assert (12,) + bm.deg2tile(lat, lon, 12) in got


def test_tile_count_grows_toward_four_per_zoom_level():
    """Halving the tile size should roughly quadruple the count, but only
    once the box is many tiles wide. At z11 the corridor spans 4x4 tiles and
    a partly covered edge tile counts the same as a full one, so the ratio
    there is 2.25 - an edge effect, not a bug. It settles near 4 by z13."""
    box = [135.8358, -1.2333, 136.2938, -0.8241]
    counts = {z: len(bm.tiles_for(box, z)) for z in range(10, 17)}
    for z in range(10, 16):
        assert counts[z + 1] > counts[z], z
        assert counts[z + 1] <= 4 * counts[z] + 4 * (2 ** z), z
    for z in range(13, 16):
        assert 3.0 <= counts[z + 1] / counts[z] <= 4.5, (z, counts)


def test_transparent_tile_is_dropped():
    Image = pytest.importorskip("PIL.Image")
    import io
    buf = io.BytesIO()
    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, format="PNG")
    assert bm.to_jpeg(buf.getvalue(), 75) is None

    buf = io.BytesIO()
    Image.new("RGBA", (256, 256), (10, 200, 30, 255)).save(buf, format="PNG")
    out = bm.to_jpeg(buf.getvalue(), 75)
    assert out and out[:2] == b"\xff\xd8"       # JPEG start of image


def test_mbtiles_metadata_is_complete(tmp_path):
    import sqlite3
    box = [135.8, -1.2, 136.3, -0.8]
    con = bm.mbtiles_open(tmp_path / "t.mbtiles", "x", box, 8, 16)
    con.commit()
    meta = dict(con.execute("SELECT name, value FROM metadata"))
    # readers reject a file missing any of these
    for k in ("name", "type", "version", "description", "format",
              "bounds", "minzoom", "maxzoom"):
        assert k in meta, k
    assert meta["format"] == "jpg"
    assert [float(v) for v in meta["bounds"].split(",")] == box
