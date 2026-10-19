"""Offline checks for ATBI, the seventh burn index (Task 25 A1).

`indices_of()` is arithmetic over band images, so this test calls the real
function with a stand-in `ee` module whose bands are plain floats plus a
validity flag. It never re-implements the formula: the expected numbers are
the paper's worked example (Bilal 2025, section 2.4.1) and BAIS2's
typeset grouping from Alcaras eq (5). No Earth Engine and no network.

    python -m pytest tests/test_atbi.py
"""
import importlib
import sys
import types
from pathlib import Path

import pytest
from pytest import approx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def _drop_fake_modules():
    """The fake `ee` is only for this file's imports: do not leave a module
    bound to it for later tests in the same session."""
    yield
    sys.modules.pop("burn_indices_gee", None)
    sys.modules.pop("s2_scene_survey", None)


class Band:
    """Stand-in for an ee.Image band: a float and a validity flag.
    Division by zero yields 0, as ee.Image.divide does."""

    def __init__(self, value, valid=True):
        self.value = float(value)
        self.valid = bool(valid)

    def _pair(self, other, fn):
        other = other if isinstance(other, Band) else Band(other)
        return Band(fn(self.value, other.value), self.valid and other.valid)

    def add(self, other):
        return self._pair(other, lambda a, b: a + b)

    def subtract(self, other):
        return self._pair(other, lambda a, b: a - b)

    def multiply(self, other):
        return self._pair(other, lambda a, b: a * b)

    def divide(self, other):
        return self._pair(other, lambda a, b: a / b if b else 0.0)

    def sqrt(self):
        # ee.Image.sqrt returns NaN where the input is negative.
        root = self.value ** 0.5 if self.value >= 0 else float("nan")
        return Band(root, self.valid)

    def gt(self, other):
        return self._pair(other, lambda a, b: float(a > b))

    def updateMask(self, mask):
        return Band(self.value, self.valid and bool(mask.value))

    def rename(self, *names):
        return self


def load(monkeypatch):
    """Import the real module with `ee` replaced before it is imported:
    s2_scene_survey imports ee at module level."""
    fake = types.ModuleType("ee")
    fake.Image = Band
    monkeypatch.setitem(sys.modules, "ee", fake)
    sys.modules.pop("burn_indices_gee", None)
    sys.modules.pop("s2_scene_survey", None)
    return importlib.import_module("burn_indices_gee")


def bands(bi, **overrides):
    """Scaled reflectances: the paper's worked example by default, plus a
    mid-range B4/B6/B7 so BAIS2 is defined."""
    values = {name: 0.1 for name in bi.BANDS}
    values.update({"B4": 0.5, "B6": 0.1, "B7": 0.2, "B8A": 0.5, "B12": 0.2})
    values.update(overrides)
    return {name: Band(value) for name, value in values.items()}


def test_atbi_sign_and_scale_match_the_published_worked_example(monkeypatch):
    """pre NIR 0.5 / SWIR 0.2 and post NIR 0.1 / SWIR 0.3: this file's ATBI
    is -0.1714 and +1.5, and post-minus-pre is the published dATBI 1.67."""
    bi = load(monkeypatch)
    pre = bi.indices_of(bands(bi))["ATBI"]
    post = bi.indices_of(bands(bi, B8A=0.1, B12=0.3))["ATBI"]

    assert pre.value == approx(-0.17142857142857146, abs=1e-12)
    assert post.value == approx(1.5, abs=1e-12)
    assert round(pre.value, 4) == -0.1714
    d_atbi = post.subtract(pre)          # index_bands' bi-temporal form
    assert d_atbi.value == approx(1.671428571428571, abs=5e-4)
    assert round(d_atbi.value, 2) == 1.67

    # eq (5) of Alcaras typesets the "+ 1" outside the fraction; the other
    # grouping would give -0.1975 on these bands.
    bais2 = bi.indices_of(bands(bi))["BAIS2"]
    assert bais2.value == approx(0.5507193162460834, abs=1e-12)


def test_atbi_masks_a_non_positive_b8a_rather_than_flooring_it(monkeypatch):
    bi = load(monkeypatch)
    assert bi.indices_of(bands(bi))["ATBI"].valid
    assert not bi.indices_of(bands(bi, B8A=0.0))["ATBI"].valid
    assert not bi.indices_of(bands(bi, B8A=-0.1))["ATBI"].valid


def test_indices_of_and_indices_list_the_same_seven(monkeypatch):
    """One name in INDICES and one entry in indices_of(), so they cannot
    drift apart. ATBI is appended, leaving the six published columns in
    their existing order."""
    bi = load(monkeypatch)
    got = bi.indices_of(bands(bi))
    assert len(bi.INDICES) == 7
    assert set(bi.INDICES) == set(got)
    assert bi.INDICES[-1] == "ATBI"
    assert bi.INDICES[:6] == ("NBR", "NBRSWIR", "NDSWIR", "MIRBI",
                              "BAIS2", "NBR+")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))