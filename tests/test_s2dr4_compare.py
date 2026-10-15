"""Checks for the S2DR4 route comparison, offline and on rasters built here.

The real tiles are 2.8 GB and untracked, so these build small ones with the
same shape: EPSG:32753, 1 m pixels, uint16, ten bands.

    python -m pytest tests/test_s2dr4_compare.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cmp = _load("s2dr4_compare", ROOT / "scripts/s2dr4_compare.py")

UTM = "EPSG:32753"
N = 120


def write(path: Path, arr: np.ndarray, left: float = 500_000, top: float = 9_875_000):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2],
                       count=arr.shape[0], dtype="uint16", crs=UTM,
                       transform=from_origin(left, top, 1.0, 1.0)) as dst:
        dst.write(arr)
    return path


def ten_bands(seed: int = 1) -> np.ndarray:
    """Ten bands with their own levels, built on one shared ground pattern so
    they correlate the way real reflectance bands do."""
    rng = np.random.default_rng(seed)
    ground = rng.normal(0, 1, (N, N))
    out = []
    for i in range(10):
        level = 300 + 220 * i
        out.append(np.clip(level + 150 * ground + rng.normal(0, 20, (N, N)), 1, 9999))
    return np.stack(out).astype("uint16")


def test_a_file_against_itself_is_identical_in_every_band(tmp_path):
    arr = ten_bands()
    a = write(tmp_path / "a.tif", arr)
    with rasterio.open(a) as src:
        box = cmp.overlap(src, src)
        ref, _ = cmp.read_window(src, box)
    rows = cmp.per_band(cmp.subsample(ref), cmp.subsample(ref))
    assert all(r["rmse"] == 0 for r in rows)
    assert all(r["identical_pixels_pct"] == 100 for r in rows)
    assert not any(m["decisive"] for m in
                   cmp.best_matches(cmp.subsample(ref), cmp.subsample(ref)))


def test_a_swapped_pair_of_bands_is_caught(tmp_path):
    """The defect this script exists to catch: one route writing its bands in a
    different order, which F19 found had been publishing a near-infrared
    composite labelled SWIR."""
    arr = ten_bands()
    swapped = arr.copy()
    swapped[[0, 9]] = swapped[[9, 0]]
    ref, cand = cmp.subsample(arr.astype("float64")), cmp.subsample(swapped.astype("float64"))
    matches = cmp.best_matches(ref, cand)
    decisive = {m["candidate_band"]: m["best_reference_band"] for m in matches if m["decisive"]}
    assert decisive == {1: 10, 10: 1}


def test_bands_that_merely_correlate_do_not_count_as_a_permutation(tmp_path):
    """Two dates of the same ground. The levels all move, but no band has
    actually changed place, and the script must not say one has."""
    ref = cmp.subsample(ten_bands(1).astype("float64"))
    cand = cmp.subsample(ten_bands(2).astype("float64"))
    assert not any(m["decisive"] for m in cmp.best_matches(ref, cand))


def test_rasters_that_do_not_touch_are_refused(tmp_path):
    a = write(tmp_path / "a.tif", ten_bands())
    b = write(tmp_path / "b.tif", ten_bands(), left=900_000, top=9_000_000)
    with rasterio.open(a) as sa, rasterio.open(b) as sb:
        with pytest.raises(SystemExit):
            cmp.overlap(sa, sb)


def test_the_overlap_of_two_offset_tiles_is_their_common_ground(tmp_path):
    a = write(tmp_path / "a.tif", ten_bands())
    b = write(tmp_path / "b.tif", ten_bands(), left=500_060, top=9_875_000)
    with rasterio.open(a) as sa, rasterio.open(b) as sb:
        box = cmp.overlap(sa, sb)
    assert round(box[2] - box[0]) == N - 60
    assert round(box[3] - box[1]) == N


def demo() -> None:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    test_a_file_against_itself_is_identical_in_every_band(tmp)
    test_a_swapped_pair_of_bands_is_caught(tmp)
    test_bands_that_merely_correlate_do_not_count_as_a_permutation(tmp)
    test_rasters_that_do_not_touch_are_refused(tmp)
    test_the_overlap_of_two_offset_tiles_is_their_common_ground(tmp)
    print("s2dr4 compare: ok")


if __name__ == "__main__":
    demo()
