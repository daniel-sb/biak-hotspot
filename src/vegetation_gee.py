"""NDVI and NDMI monthly series with their composite-quality confound made
visible (Task 11, PLAN.md 2.4 and 14).

Computes, per calendar month from 2001-01:
  - AOI land-mean NDVI from MOD13A1 (NDVI band, scale 1e-4)
  - the fraction of AOI land pixels with SummaryQA <= 1 in that month's
    composites (the observation-quality confound)
  - AOI land-mean NDMI from MOD09A1 (b02/b06 normalised difference)
  - the fraction of AOI land pixels whose MOD09A1 StateQA bits 0-1 == 0
    (not cloudy) — a different product, a different mask; never reuse the
    MOD13 QA share for NDMI
and writes docs/data/vegetation.json with calendar-month anomalies
(departure from the 2001-2025 mean) and Pearson r between each index and
its good-pixel share.

Run by hand, not by the daily cron: Earth Engine needs interactive
credentials and these composites move every 8-16 days.

    python src/vegetation_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import ee
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "vegetation.json"

SERIES_START = "2001-01-01"
BASELINE_LAST_YEAR = 2025
SCALE = 500
MOD13 = "MODIS/061/MOD13A1"
MOD09 = "MODIS/061/MOD09A1"


def month_starts(first: str, last_exclusive: str):
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last_exclusive[:4]), int(last_exclusive[5:7])
    while (y, m) < (ly, lm):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def last_day_of(ym: str) -> str:
    from calendar import monthrange
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{ym}-{monthrange(y, m)[1]:02d}"


def prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def land_mask():
    """WorldCover class 80 is permanent water. The AOI box is mostly ocean."""
    return ee.Image("ESA/WorldCover/v200/2021").select("Map").neq(80)


# ---------------------------------------------------------------------------
# Earth Engine per-month reducers — one getInfo per series, not per month
# ---------------------------------------------------------------------------
def monthly_mod13(coll, aoi, months):
    """Per month: NDVI land mean (scaled 1e-4) and the share of land pixels
    with SummaryQA <= 1, both over the same masked land pixels at the same
    scale."""

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")

        def per_image(img):
            good = img.select("SummaryQA").lte(1).rename("good")
            return img.select("NDVI").multiply(1e-4).rename("ndvi") \
                .addBands(good) \
                .addBands(img.select("SummaryQA").rename("total")) \
                .copyProperties(img, ["system:time_start"])

        stats = (fc.map(per_image)
                 .mean()
                 .updateMask(land_mask())
                 .rename(["ndvi_mean", "good_frac", "any_frac"])
                 .reduceRegion(ee.Reducer.mean(), aoi, SCALE,
                               bestEffort=True))
        return ee.Algorithms.If(
            fc.size().gt(0),
            ee.Dictionary({
                "ndvi": stats.get("ndvi_mean"),
                "good_share": stats.get("good_frac"),
            }),
            None)

    raw = ee.List([one(ym) for ym in months]).getInfo()
    return _parse(raw, months, "ndvi")


def monthly_mod09(coll, aoi, months):
    """Per month: NDMI land mean ((b02-b06)/(b02+b06)) and the share of
    land pixels whose StateQA bits 0-1 == 0 (not cloudy), both over the
    same masked land pixels at the same scale."""

    def per_image(img):
        ndmi = img.normalizedDifference(["sur_refl_b02",
                                         "sur_refl_b06"]).rename("ndmi")
        # StateQA bits 0-1: 0 = clear. Mask to those bits, check == 0.
        good = img.select("StateQA").bitwiseAnd(3).eq(0).rename("good")
        return ndmi.addBands(good) \
            .updateMask(land_mask()) \
            .copyProperties(img, ["system:time_start"])

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")
        stats = (fc.map(per_image)
                 .mean()
                 .rename(["ndmi_mean", "good_frac"])
                 .reduceRegion(ee.Reducer.mean(), aoi, SCALE,
                               bestEffort=True))
        return ee.Algorithms.If(
            fc.size().gt(0),
            ee.Dictionary({
                "ndmi": stats.get("ndmi_mean"),
                "good_share": stats.get("good_frac"),
            }),
            None)

    raw = ee.List([one(ym) for ym in months]).getInfo()
    return _parse(raw, months, "ndmi")


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------
def build_document(monthly, mod13_last, mod09_last):
    """Add anomalies and correlations to the monthly rows, return the doc."""
    baselines = {}       # {(index, "MM"): mean over 2001-2025}
    for row in monthly:
        if row["month"][:4] <= str(BASELINE_LAST_YEAR):
            mm = row["month"][5:7]
            for key in ("ndvi", "ndmi"):
                v = row.get(key)
                if v is not None:
                    baselines.setdefault((key, mm), []).append(v)
    means = {k: sum(v) / len(v) for k, v in baselines.items()}

    for row in monthly:
        mm = row["month"][5:7]
        for key in ("ndvi", "ndmi"):
            base = means.get((key, mm))
            row[f"{key}_anomaly"] = (round(row[key] - base, 4)
                                     if row.get(key) is not None
                                     and base is not None else None)

    pairs = {}
    for key in ("ndvi", "ndmi"):
        pairs[key] = [(r[key], r[f"{key}_good_share"]) for r in monthly
                      if r.get(key) is not None
                      and r.get(f"{key}_good_share") is not None]
    july = lambda key, r: (r[key], r[f"{key}_good_share"]) \
        if r["month"][5:7] == "07" and r.get(key) is not None \
        and r.get(f"{key}_good_share") is not None else None

    ndvi_all = pearson(pairs["ndvi"])
    ndmi_all = pearson(pairs["ndmi"])
    ndvi_jul = pearson([p for r in monthly
                        if (p := july("ndvi", r)) is not None])
    ndmi_jul = pearson([p for r in monthly
                        if (p := july("ndmi", r)) is not None])

    return {
        "monthly": monthly,
        "baselines": {f"{k[0]}_{k[1]}": round(v, 4)
                      for k, v in means.items()},
        "qa_correlation": {
            "ndvi_all": {"r": ndvi_all[0], "n": ndvi_all[1]},
            "ndvi_july": {"r": ndvi_jul[0], "n": ndvi_jul[1]},
            "ndmi_all": {"r": ndmi_all[0], "n": ndmi_all[1]},
            "ndmi_july": {"r": ndmi_jul[0], "n": ndmi_jul[1]},
        },
        "coverage": {
            "mod13a1_last_date": mod13_last,
            "mod09a1_last_date": mod09_last,
            "generated_utc": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sources": {
            "ndvi": "MODIS/061/MOD13A1 (NDVI band, scale 1e-4; "
                    "SummaryQA <= 1 = good pixel)",
            "ndmi": "MODIS/061/MOD09A1 (sur_refl_b02/b06 normalised "
                    "difference; StateQA bits 0-1 == 0 = not cloudy)",
            "land_mask": "ESA/WorldCover/v200 (class 80 = permanent water)",
            "baseline_period": f"2001-01 to {BASELINE_LAST_YEAR}-12",
        },
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def pearson(pairs):
    """Pearson r and n for (x, y) pairs; (None, n) when n < 3 or degenerate."""
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    n = len(pairs)
    if n < 3:
        return None, n
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    if sx == 0 or sy == 0:
        return None, n
    return round(sxy / (sx * sy), 3), n


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse(raw, months, key):
    out = []
    for ym, r in zip(months, raw):
        if r is None:
            out.append({"month": ym, key: None, "good_share": None})
        else:
            out.append({"month": ym,
                        key: round(r[key], 4) if r.get(key) is not None
                        else None,
                        "good_share": round(r["good_share"], 4)
                        if r.get("good_share") is not None else None})
    return out


def print_summary(doc):
    months = doc["monthly"]
    for key in ("ndvi", "ndmi"):
        n = sum(1 for r in months if r.get(key) is not None)
        print(f"  {key.upper()}: {n} months with data")
    cov = doc["coverage"]
    print(f"  MOD13A1 last {cov['mod13a1_last_date']}   "
          f"MOD09A1 last {cov['mod09a1_last_date']}")
    for key in ("ndvi_all", "ndvi_july", "ndmi_all", "ndmi_july"):
        c = doc["qa_correlation"][key]
        print(f"  r({key}) = {c['r']}  (n = {c['n']})")


def main(project: str) -> None:
    ee.Initialize(project=project)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    w, s, e, n = [float(v) for v in cfg["aoi_bbox_wsen"]]
    aoi = ee.Geometry.Rectangle([w, s, e, n])
    mask = land_mask()

    mod13 = ee.ImageCollection(MOD13)
    mod09 = ee.ImageCollection(MOD09)

    m13_last = ee.Date(mod13.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    m09_last = ee.Date(mod09.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    print(f"MOD13A1 latest {m13_last}   MOD09A1 latest {m09_last}")

    # A month is complete only when both products hold data past the month's
    # last day (16-day composites lag; publishing a partial month as a
    # monthly figure is the same class of error as reporting a failed fetch
    # as zero). Use the later of the two last dates.
    last_complete = max(m13_last[:7], m09_last[:7])
    if m13_last < last_day_of(last_complete) or \
            m09_last < last_day_of(last_complete):
        last_complete = prev_month(last_complete)
    months = list(month_starts(SERIES_START, next_month(last_complete)))
    print(f"series: {months[0]} .. {last_complete}  ({len(months)} months)")

    print("fetching MOD13A1 NDVI and good-pixel share ...")
    ndvi_series = monthly_mod13(mod13, aoi, months)
    print("fetching MOD09A1 NDMI and good-pixel share ...")
    ndmi_series = monthly_mod09(mod09, aoi, months)

    monthly = []
    for nd, nm in zip(ndvi_series, ndmi_series):
        monthly.append({
            "month": nd["month"],
            "ndvi": nd["ndvi"], "ndvi_good_share": nd["good_share"],
            "ndmi": nm["ndmi"], "ndmi_good_share": nm["good_share"],
        })

    doc = build_document(monthly, m13_last, m09_last)
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(monthly)} months)")
    print_summary(doc)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
