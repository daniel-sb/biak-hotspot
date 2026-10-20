"""Offline checks for the fuel map (Task 27 A).

The reclass is arithmetic over band images, so this calls the real
functions with a stand-in `ee` module whose bands are plain floats and a
validity flag. It does not re-implement the reclass table. No Earth Engine
and no network.

    python -m pytest tests/test_fuel_map.py
"""
import importlib
import sys
import types
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The complete WorldCover v200 class list, from the product, not from the
# module's table: the test is what catches a missing class.
WC_PRODUCT_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)


@pytest.fixture(autouse=True)
def _drop_fake_modules():
    yield
    sys.modules.pop("fuel_map_gee", None)
    sys.modules.pop("s2_scene_survey", None)


class Band:
    """Stand-in for an ee.Image band: a float and a validity flag, with the
    operations the reclass uses."""

    def __init__(self, value, valid=True):
        self.value = float(value)
        self.valid = bool(valid)

    def _pair(self, other, fn):
        other = other if isinstance(other, Band) else Band(other)
        return Band(fn(self.value, other.value), self.valid and other.valid)

    def eq(self, other):
        return self._pair(other, lambda a, b: float(a == b))

    def And(self, other):
        return self._pair(other, lambda a, b: float(bool(a) and bool(b)))

    def Or(self, other):
        return self._pair(other, lambda a, b: float(bool(a) or bool(b)))

    def where(self, condition, value):
        value = value if isinstance(value, Band) else Band(value)
        if not condition.valid:
            return Band(self.value, self.valid)
        if condition.value:
            return Band(value.value, self.valid and value.valid)
        return Band(self.value, self.valid)

    def rename(self, *names):
        return self

    def toInt(self):
        return Band(int(self.value), self.valid)

    def mask(self):
        return Band(1.0 if self.valid else 0.0)

    def updateMask(self, mask):
        return Band(self.value, self.valid and bool(mask.value))


def load(monkeypatch):
    """Import the real module with `ee` replaced before it is imported:
    s2_scene_survey imports ee at module level."""
    fake = types.ModuleType("ee")
    fake.Image = Band
    monkeypatch.setitem(sys.modules, "ee", fake)
    sys.modules.pop("fuel_map_gee", None)
    sys.modules.pop("s2_scene_survey", None)
    return importlib.import_module("fuel_map_gee")


def cfg():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def test_every_worldcover_class_maps_to_a_fuel_code(monkeypatch):
    bi = load(monkeypatch)
    assert set(WC_PRODUCT_CLASSES) <= set(bi.WC_TO_FUEL)
    assert all(1 <= code <= 6 for code in bi.WC_TO_FUEL.values())
    for wc in WC_PRODUCT_CLASSES:
        got = bi.worldcover_fuel(Band(wc), Band(1))
        assert 1 <= int(got.value) <= 6, (wc, got.value)


def test_tree_cover_splits_by_tmf(monkeypatch):
    bi = load(monkeypatch)
    assert int(bi.worldcover_fuel(Band(10), Band(1)).value) == 4
    assert int(bi.worldcover_fuel(Band(10), Band(2)).value) == 4
    assert int(bi.worldcover_fuel(Band(10), Band(3)).value) == 2
    assert int(bi.worldcover_fuel(Band(10), Band(4)).value) == 2
    assert int(bi.worldcover_fuel(Band(10), Band(5)).value) == 4
    assert int(bi.worldcover_fuel(Band(10), Band(6)).value) == 4
    assert int(bi.worldcover_fuel(Band(10), Band(0)).value) == 4


def test_fallback_and_judgement_masks(monkeypatch):
    bi = load(monkeypatch)
    for tmf in (0, 5, 6):
        assert bi.tmf_unresolved(Band(10), Band(tmf)).value == 1
    for tmf in (1, 2, 3, 4):
        assert bi.tmf_unresolved(Band(10), Band(tmf)).value == 0
    assert bi.tmf_unresolved(Band(20), Band(5)).value == 0
    assert bi.tmf_degraded(Band(10), Band(2)).value == 1
    assert bi.tmf_degraded(Band(10), Band(1)).value == 0
    assert bi.wetland(Band(90)).value == 1
    assert bi.wetland(Band(10)).value == 0


def test_dynamicworld_classes_and_missing_scene(monkeypatch):
    bi = load(monkeypatch)
    assert set(bi.DW_CLASSES) == set(bi.DW_TO_FUEL)
    assert all(1 <= code <= 6 for code in bi.DW_TO_FUEL.values())
    for dw in bi.DW_CLASSES:
        got = bi.dynamicworld_fuel(Band(dw), Band(1))
        assert 1 <= int(got.value) <= 6, (dw, got.value)
    assert int(bi.dynamicworld_fuel(Band(1), Band(4)).value) == 2
    assert int(bi.dynamicworld_fuel(Band(1), Band(1)).value) == 4
    # no scene in the window: no class, rather than a silent nonfuel
    assert not bi.dynamicworld_fuel(Band(2, valid=False), Band(1)).valid


def test_dynamicworld_window_ends_before_first_august_detection(monkeypatch):
    bi = load(monkeypatch)
    window = bi.dynamicworld_window(cfg())
    det = pd.read_parquet(ROOT / "data/processed/detections.parquet")
    first = bi.first_august_detection(det)
    assert first == date(2026, 8, 7)
    assert window[0] < window[1] <= first
    bi.check_window(window, first)
    with pytest.raises(SystemExit):
        bi.check_window((window[0], date(2026, 9, 1)), first)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))