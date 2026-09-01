"""Drought context for the dashboard panel (Task 10, PLAN.md 2.5).

Computes the AOI land-mean monthly water balance (CHIRPS precipitation minus
MOD16A2 evapotranspiration) and the 1981-2025 precipitation climatology, and
writes docs/data/drought.json.

Run by hand, not by the daily cron: Earth Engine needs interactive credentials,
and CHIRPS lags real time by roughly a month, so a daily run would spend an API
call to republish an unchanged number.

    python src/drought_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import ee
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "drought.json"

# The water-balance series starts here because MOD16A2 v061 begins 2021-01-01.
# The precipitation climatology starts in 1981 because CHIRPS does.
SERIES_START = "2021-01-01"
CLIM_FIRST_YEAR, CLIM_LAST_YEAR = 1981, 2025


def month_starts(first: str, last_exclusive: str):
    """Every month start from `first` up to but excluding `last_exclusive`."""
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last_exclusive[:4]), int(last_exclusive[5:7])
    while (y, m) < (ly, lm):
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def next_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def land_mask():
    """WorldCover class 80 is permanent water. The AOI box is mostly ocean, so
    an unmasked mean is largely a mean of the sea."""
    return ee.Image("ESA/WorldCover/v200/2021").select("Map").neq(80)


def mean_over(image, aoi, scale, band):
    """AOI land mean of one band, or None where nothing was sampled."""
    return image.updateMask(land_mask()).reduceRegion(
        ee.Reducer.mean(), aoi, scale, bestEffort=True).get(band)


def main(project: str) -> None:
    ee.Initialize(project=project)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    w, s, e, n = [float(v) for v in cfg["aoi_bbox_wsen"]]
    aoi = ee.Geometry.Rectangle([w, s, e, n])

    chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
    mod16 = ee.ImageCollection("MODIS/061/MOD16A2")

    chirps_last = ee.Date(chirps.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    et_last = ee.Date(mod16.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()

    # A month is complete only when CHIRPS holds its last day. Taking the
    # month containing chirps_last would publish a partial total as if it
    # were a monthly figure - the same class of error as reporting a failed
    # fetch as zero.
    last_complete = chirps_last[:7]
    if chirps_last != last_day_of(last_complete):
        last_complete = prev_month(last_complete)
    print(f"CHIRPS latest   {chirps_last}   last complete month {last_complete}")
    print(f"MOD16A2 latest  {et_last}")

    months = list(month_starts(SERIES_START, next_month(last_complete)))

    # One getInfo per series, not one per month: 60+ round trips is minutes.
    def monthly_sum(coll, band, scale):
        def one(ym):
            img = coll.filterDate(ym + "-01", next_month(ym) + "-01").sum()
            return ee.Algorithms.If(
                coll.filterDate(ym + "-01", next_month(ym) + "-01").size().gt(0),
                mean_over(img, aoi, scale, band), None)
        return ee.List([one(ym) for ym in months]).getInfo()

    print("fetching precipitation ...")
    precip = monthly_sum(chirps, "precipitation", 5000)
    print("fetching evapotranspiration ...")
    # MOD16A2 ET is 8-day total in 0.1 mm; scale 0.1 gives mm per 8-day
    # composite, summed over the month.
    et_coll = mod16.select("ET").map(lambda i: i.multiply(0.1).rename("ET")
                                     .copyProperties(i, ["system:time_start"]))
    et = monthly_sum(et_coll, "ET", 500)

    monthly = []
    for ym, p, t in zip(months, precip, et):
        row = {"month": ym,
               "precip_mm": None if p is None else round(p, 1),
               "et_mm": None if t is None else round(t, 1)}
        row["p_minus_et_mm"] = (None if p is None or t is None
                                else round(row["precip_mm"] - row["et_mm"], 1))
        monthly.append(row)

    # Climatology: per calendar month, the AOI land-mean total for every year
    # 1981-2025, reduced to mean and standard deviation. Same mask, same
    # scale, same reducer as the series above, so the two are comparable.
    print("fetching 1981-2025 climatology ...")
    years = list(range(CLIM_FIRST_YEAR, CLIM_LAST_YEAR + 1))
    clim, current_rank = {}, None
    for m in range(1, 13):
        totals = ee.List([
            mean_over(chirps.filterDate(f"{y}-{m:02d}-01",
                                        next_month(f"{y}-{m:02d}") + "-01").sum(),
                      aoi, 5000, "precipitation")
            for y in years]).getInfo()
        vals = [v for v in totals if v is not None]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        clim[f"{m:02d}"] = {"mean_mm": round(mean, 1), "sd_mm": round(sd, 1),
                            "years": len(vals)}
        if m == int(last_complete[5:7]):
            current_rank = sorted(vals)          # ascending: driest first

    cur = next(r for r in monthly if r["month"] == last_complete)
    cm = clim[last_complete[5:7]]
    below = sum(1 for v in current_rank if v < cur["precip_mm"])
    current = {
        "month": last_complete,
        "precip_mm": cur["precip_mm"],
        "et_mm": cur["et_mm"],
        "p_minus_et_mm": cur["p_minus_et_mm"],
        "climatology_mean_mm": cm["mean_mm"],
        "z": round((cur["precip_mm"] - cm["mean_mm"]) / cm["sd_mm"], 2),
        "rank_driest": below + 1,
        "rank_of": len(current_rank) + 1,
    }

    doc = {
        "monthly": monthly,
        "climatology": clim,
        "current": current,
        "coverage": {
            "chirps_last_date": chirps_last,
            "chirps_last_complete_month": last_complete,
            "et_last_date": et_last,
            "generated_utc": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sources": {
            "precipitation": "UCSB-CHG/CHIRPS/DAILY",
            "evapotranspiration": "MODIS/061/MOD16A2",
            "land_mask": "ESA/WorldCover/v200 (class 80 = permanent water)",
        },
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(monthly)} months)")
    print(f"  {current['month']}  precipitation {current['precip_mm']} mm "
          f"vs climatology {current['climatology_mean_mm']} mm "
          f"(z {current['z']}, {current['rank_driest']} driest "
          f"of {current['rank_of']})")
    print(f"  {current['month']}  P-ET {current['p_minus_et_mm']} mm "
          f"(ET {current['et_mm']} mm)")
    neg = [r for r in monthly if r["p_minus_et_mm"] is not None
           and r["p_minus_et_mm"] < 0]
    print(f"  months with negative water balance since {SERIES_START[:7]}: "
          + (", ".join(r["month"] for r in neg) if neg else "none"))


def last_day_of(ym: str) -> str:
    from calendar import monthrange
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{ym}-{monthrange(y, m)[1]:02d}"


def prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
