"""Checks for the Gamma Earth job script, offline and with no key.

The three things worth pinning: the area arithmetic that decides what a request
costs, the masking that keeps the key out of anything printed, and the product
paths taken from a response rather than guessed.

    python -m pytest tests/test_s2dr4_api.py
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


api = _load("s2dr4_api", ROOT / "scripts/s2dr4_api.py")

# The two boxes Task 24 plans, both around the E0313 wheel tile's centre.
PROBE = "136.035105 -1.138913 136.044089 -1.129864"
COMPARE = "136.030613 -1.143438 136.048581 -1.125340"


def test_the_planned_boxes_cost_what_the_task_says():
    assert round(api.aoi_km2(PROBE)[0], 2) == 1.00
    assert round(api.aoi_km2(COMPARE)[0], 2) == 4.00


def test_a_box_given_backwards_is_refused_rather_than_billed():
    """maxx before minx would otherwise give a negative area and sail through."""
    with pytest.raises(SystemExit):
        api.aoi_km2("136.05 -1.12 136.03 -1.14")
    with pytest.raises(SystemExit):
        api.aoi_km2("136.03 -1.14 136.05")


def test_the_key_never_survives_into_a_printed_line():
    key = "abc123secret"
    url = f"{api.BASE}/{key}?aoi=1+2+3+4"
    assert key not in api.mask(url, key)
    assert "<GE_API_KEY>" in api.mask(url, key)


def test_product_paths_come_from_the_response():
    """Both namings are tried because the v1.0 page documents S2L2Ax10 while the
    wheel writes S2L3Ax10, and which one this endpoint returns is unknown until
    a job has run."""
    job = {"pid": "T53MPU-abc", "job_id": "j1",
           "save_path_S3_TCI": "https://example.org/out/S2L2Ax10_T53MPU-abc_TCI.tif"}
    urls = api.product_urls(job)
    assert "https://example.org/out/S2L2Ax10_T53MPU-abc_MS.tif" in urls
    assert "https://example.org/out/S2L3Ax10_T53MPU-abc_MS.tif" in urls
    assert len(urls) == len(set(urls))


def test_the_submission_body_always_pins_the_date_range():
    """The server's own default is 7 days, so a body that leaves date_range out
    asks for a week-wide search and gets back a date nobody requested - the same
    silent substitution the wheel does."""
    args = argparse.Namespace(aoi=PROBE, date="2026-08-28", date_range=0, max_clouds=None)
    assert api.job_body(args) == {"aoi": PROBE, "date": "2026-08-28", "date_range": 0}
    args.max_clouds = 10
    assert api.job_body(args)["max_clouds"] == 10


def test_a_response_with_no_paths_yields_nothing_rather_than_a_guess():
    assert api.product_urls({"job_id": "j1", "state": "completed"}) == []


def demo() -> None:
    test_the_planned_boxes_cost_what_the_task_says()
    test_a_box_given_backwards_is_refused_rather_than_billed()
    test_the_key_never_survives_into_a_printed_line()
    test_product_paths_come_from_the_response()
    test_the_submission_body_always_pins_the_date_range()
    test_a_response_with_no_paths_yields_nothing_rather_than_a_guess()
    print("s2dr4 api: ok")


if __name__ == "__main__":
    demo()
