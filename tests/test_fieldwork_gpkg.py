"""The GeoPackage is hand-written with sqlite3, so the format itself is the
thing that can silently break: QGIS and Mergin will simply refuse a file whose
header or registration tables are wrong, and the failure happens on a phone in
Biak rather than here.
"""

import sqlite3
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fieldwork_gpkg as fw  # noqa: E402


def build(tmp_path):
    out = tmp_path / "t.gpkg"
    con = fw.gpkg_create(out)
    fw.gpkg_layer(con, "pts", [("nama", "TEXT"), ("n", "INTEGER")],
                  [{"lon": 136.0, "lat": -1.0, "nama": "a", "n": 3}], "d")
    fw.gpkg_layer(con, "kosong", fw.SURVEY_FIELDS, [], "empty")
    con.commit()
    con.close()
    return out


def test_header_and_registration(tmp_path):
    con = sqlite3.connect(build(tmp_path))
    assert con.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47
    assert con.execute("PRAGMA user_version").fetchone()[0] == 10300
    listed = {r[0] for r in
              con.execute("SELECT table_name FROM gpkg_contents")}
    assert listed == {"pts", "kosong"}
    assert listed == {r[0] for r in
                      con.execute("SELECT table_name "
                                  "FROM gpkg_geometry_columns")}
    # An empty layer still has to be registered, or the surveyor opens the
    # project and has nothing to add points to.
    assert con.execute("SELECT min_x FROM gpkg_contents "
                       "WHERE table_name='kosong'").fetchone()[0] is None


def test_geometry_blob_roundtrips(tmp_path):
    con = sqlite3.connect(build(tmp_path))
    blob, nama = con.execute("SELECT geom, nama FROM pts").fetchone()
    assert nama == "a"
    assert blob[:2] == b"GP"
    assert struct.unpack("<i", blob[4:8])[0] == 4326
    order, gtype, lon, lat = struct.unpack("<BIdd", blob[8:])
    assert (order, gtype) == (1, 1)          # little endian, POINT
    assert (lon, lat) == (136.0, -1.0)       # lon first, not lat


def test_distance_is_metres():
    # One arc-minute of latitude is a nautical mile, near enough.
    assert fw.metres(-1.0, 136.0, -1.0 - 1 / 60, 136.0) == pytest.approx(
        1852, rel=0.01)


def test_clustering_merges_within_a_viirs_pixel():
    pd = pytest.importorskip("pandas")
    # 200 m apart in latitude: inside one 375 m pixel, so one target.
    near = 200 / 111_320
    det = pd.DataFrame({
        "latitude": [-1.0, -1.0 - near, -1.0 - 0.02],
        "longitude": [136.0, 136.0, 136.0],
        "frp": [9.0, 1.0, 5.0],
        "satellite": ["N20", "N21", "N20"],
        "date_wit": ["2026-08-21", "2026-08-22", "2026-08-21"],
        "confidence": ["n", "n", "n"],
        "instrument": ["VIIRS"] * 3,
        "desa": ["x"] * 3, "distrik": ["y"] * 3,
        "recurrent_site": [False] * 3,
    })
    tg = fw.targets(det)
    assert len(tg) == 2
    # Seeded on the strongest detection, so the pair centres on frp 9.0.
    pair = next(t for t in tg if t["n_deteksi"] == 2)
    assert pair["lat"] == pytest.approx(-1.0)
    assert pair["n_satelit"] == 2 and pair["n_hari"] == 2
    assert pair["prioritas"] == "sedang"      # two detections, not three


def test_controls_are_named_and_stay_in_the_corridor():
    """Two failures that produced a plausible-looking file.

    The BIG geodatabase names its columns WADMKD/WADMKC, so reading "desa"
    with .get() returned None for all 80 rows and nothing complained. And
    sampling across every desa put 46 of 80 controls on Numfor and Supiori,
    which is not only unreachable but confounds burned-against-unburned with
    which island.
    """
    pd = pytest.importorskip("pandas")
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    desa = ROOT / cfg["admin_polygon"]
    store = ROOT / cfg["output_paths"]["processed"]
    if not (desa.exists() and store.exists()):
        pytest.skip("boundary or detection store absent")

    det = pd.read_parquet(store)
    window = det[(det.date_wit >= fw.EVENT_FROM)
                 & (det.date_wit <= fw.EVENT_TO) & det.on_land]
    box = fw.target_box(fw.targets(window))
    ct = fw.controls(det, desa, 20, box)

    assert ct, "no controls generated"
    for c in ct:
        assert c["desa"] and c["distrik"], c
        assert box[0] <= c["lon"] <= box[2], c
        assert box[1] <= c["lat"] <= box[3], c


def test_confidence_is_never_read_as_a_number():
    """AGENTS never-3. MODIS grades confidence 0-100 and VIIRS l/n/h; a cast
    would turn every VIIRS row into a missing value and silently drop them."""
    src = (ROOT / "src" / "fieldwork_gpkg.py").read_text(encoding="utf-8")
    for bad in ("int(r.confidence", "float(r.confidence",
                'confidence"].astype', "confidence.astype"):
        assert bad not in src
