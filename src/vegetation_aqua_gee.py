"""Does the July 2026 NDMI excess appear on Aqua as well? (Task 13,
PLAN.md 2.4 and 14.)

Task 12 left the July 2026 NDMI excess standing (+1.64 sd out of sample
under all four controls), with one caveat: the only control that looked
like it explained the year — solar zenith — is Terra-specific. July solar
zenith over the AOI rose monotonically from 29.6-32.8 deg (2001-2022) to
54.55 deg in 2026 as Terra's overpass drifted earlier after orbit
maintenance ended, and July 2026 sits at 100% of that predictor's range.
Aqua carries the same instrument on a different orbit whose drift runs
the other way. If July 2026 is anomalously moist on Aqua too, a
Terra-specific drift cannot be the explanation.

Fetches, per month over the same masked land pixels at the same 500 m
scale and monthly-mean reducer as tasks 11-12, entirely from the Aqua
products (band and bit layouts verified identical to the Terra products
in the Earth Engine catalog, 2026-09-01):

  - MODIS/061/MYD09A1 (2002-07-04 onward): ndmi (sur_refl_b02/b06
    normalised difference), ndmi_good_share (StateQA bits 0-1 == 0, the
    same cloud-state test task 11 used on MOD09A1), aerosol_high_share
    and aerosol_climatology_share (StateQA bits 6-7 = aerosol quantity,
    level 3 = high, level 0 = climatology fallback).
  - MODIS/061/MYD13A1 (2002-07-04 onward): ndvi (band scale 1e-4),
    ndvi_good_share (SummaryQA <= 1), view_zenith_deg and solar_zenith_deg
    (stored in hundredths of a degree, scale 0.01).

Writes docs/data/vegetation_aqua.json — a NEW file; vegetation.json,
vegetation_controls.json and the panel are not touched. The month list is
Aqua's own: it starts where MYD09A1 starts, not where vegetation.json
starts, and ends at the last month both Aqua products hold complete.

The analysis is fitted entirely within Aqua: Aqua NDMI on Aqua's
good-pixel share and Aqua's own controls, with the same leave-2026-out
prediction task 12 used (the report is imported from
src/vegetation_controls_gee.py). The two sensors are never pooled,
differenced or compared in absolute terms — only each sensor's departure
within its own record is printed, side by side.

The reading of each outcome is pre-registered below and printed before
the numbers, because deciding after seeing them is how a result gets
talked into existence.

If Earth Engine is unreachable or credentials are missing the exception
propagates and nothing is written: an absent file is the correct output of
a failed fetch.

Run by hand, not by the daily cron, like src/vegetation_gee.py:

    python src/vegetation_aqua_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from vegetation_controls_gee import july_rows, monthly_mod09_aerosol, \
    monthly_mod13_angles, report

ROOT = Path(__file__).resolve().parents[1]
TERRA_VEG = ROOT / "docs" / "data" / "vegetation.json"
TERRA_CTL = ROOT / "docs" / "data" / "vegetation_controls.json"
OUT = ROOT / "docs" / "data" / "vegetation_aqua.json"

# Catalog-verified 2026-09-01: same band names, StateQA/SummaryQA bit
# layouts and scales as the Terra products; MYD09A1 and MYD13A1 both
# start 2002-07-04.
MYD09 = "MODIS/061/MYD09A1"
MYD13 = "MODIS/061/MYD13A1"

PRE_REGISTERED = """\
Pre-registered reading of each outcome, decided before the numbers:
  - Aqua shows a comparable July 2026 excess (out of sample, against
    Aqua's own controls, same direction and roughly the same magnitude
    in sd): Terra orbit drift is out. What remains is that the canopy
    did not dry, and the water balance describes the surface rather
    than the tree crowns. This is the informative outcome.
  - Aqua shows no excess: this does NOT establish that Terra drift
    caused it, and must not be written as if it does. Aqua crosses in
    the early afternoon and Terra in the morning; canopy water content,
    illumination and the cloud field all differ by time of day, so a
    disagreement has at least two explanations and this design cannot
    separate them. The honest report is that the sensors disagree and
    why that is not decisive.
  - Aqua's own July series is too short or too gappy to fit: say so and
    stop. MYD09A1 begins mid-2002, so there are fewer Julys than Terra
    has, and n was already the binding constraint.
The asymmetry is the point: agreement is strong evidence, disagreement
is weak evidence."""


def print_solar_side_by_side(aqua_monthly, terra_solar):
    print("\nJuly solar zenith over the AOI, Terra (MOD13A1) beside "
          "Aqua (MYD13A1), degrees")
    print("  year     Terra    Aqua")
    for r in aqua_monthly:
        if r["month"][5:7] != "07" or r.get("solar_zenith_deg") is None:
            continue
        t = terra_solar.get(r["month"])
        ts = f"{t:7.2f}" if t is not None else "      -"
        print(f"  {r['month']}  {ts}  {r['solar_zenith_deg']:7.2f}")


def main(project: str) -> None:
    import ee
    import yaml
    from vegetation_gee import last_day_of, month_starts, monthly_mod09, \
        monthly_mod13, next_month, prev_month

    print(PRE_REGISTERED)

    ee.Initialize(project=project)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    w, s, e, n = [float(v) for v in cfg["aoi_bbox_wsen"]]
    aoi = ee.Geometry.Rectangle([w, s, e, n])

    myd09 = ee.ImageCollection(MYD09)
    myd13 = ee.ImageCollection(MYD13)
    m09_first = ee.Date(myd09.aggregate_min("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    m13_first = ee.Date(myd13.aggregate_min("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    m09_last = ee.Date(myd09.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    m13_last = ee.Date(myd13.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    print(f"\nMYD09A1 {m09_first} .. {m09_last}   "
          f"MYD13A1 {m13_first} .. {m13_last}")

    # A month is in the list only when both Aqua products hold data past
    # the month's last day (task 11's completeness rule); the first month
    # is where the later of the two Aqua products starts.
    first = max(m09_first[:7], m13_first[:7])
    last_complete = max(m09_last[:7], m13_last[:7])
    if m09_last < last_day_of(last_complete) or \
            m13_last < last_day_of(last_complete):
        last_complete = prev_month(last_complete)
    months = list(month_starts(first, next_month(last_complete)))
    n_julys = sum(1 for m in months if m[5:7] == "07")
    print(f"months: {months[0]} .. {last_complete}  ({len(months)} months, "
          f"{n_julys} Julys; Terra's series has 26)")

    print("fetching MYD09A1 NDMI and good-pixel share ...")
    ndmi_s = monthly_mod09(myd09, aoi, months)
    print("fetching MYD09A1 aerosol-quantity shares (StateQA bits 6-7) ...")
    aero_s = monthly_mod09_aerosol(myd09, aoi, months)
    print("fetching MYD13A1 NDVI and good-pixel share ...")
    ndvi_s = monthly_mod13(myd13, aoi, months)
    print("fetching MYD13A1 view and solar zenith (scale 0.01) ...")
    ang_s = monthly_mod13_angles(myd13, aoi, months)

    monthly = []
    for nd, ae, nv, an in zip(ndmi_s, aero_s, ndvi_s, ang_s):
        row = {"month": nd["month"],
               "ndmi": nd["ndmi"], "ndmi_good_share": nd["good_share"],
               "ndvi": nv["ndvi"], "ndvi_good_share": nv["good_share"]}
        for other in (ae, an):
            row.update({k: v for k, v in other.items() if k != "month"})
        monthly.append(row)

    doc = {
        "monthly": monthly,
        "coverage": {
            "myd09a1_first_date": m09_first,
            "myd13a1_first_date": m13_first,
            "myd09a1_last_date": m09_last,
            "myd13a1_last_date": m13_last,
            "generated_utc": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sources": {
            "ndmi": "MODIS/061/MYD09A1 (sur_refl_b02/b06 normalised "
                    "difference; StateQA bits 0-1 == 0 = not cloudy; "
                    "bit layout verified identical to MOD09A1)",
            "aerosol": "MODIS/061/MYD09A1 StateQA bits 6-7 = aerosol "
                       "quantity (0 = climatology, 1 = low, 2 = average, "
                       "3 = high; layout verified identical to MOD09A1); "
                       "aerosol_high_share = land-mean monthly frequency "
                       "at level 3, aerosol_climatology_share = at level 0",
            "ndvi": "MODIS/061/MYD13A1 (NDVI band, scale 1e-4; "
                    "SummaryQA <= 1 = good pixel)",
            "geometry": "MODIS/061/MYD13A1 ViewZenith and SolarZenith, "
                        "stored in hundredths of a degree (scale 0.01); "
                        "land means in degrees",
            "land_mask": "ESA/WorldCover/v200 (class 80 = permanent water)",
            "months": "own month list, from MYD09A1's first month to the "
                      "last month both Aqua products hold complete",
            "reduction": "500 m, monthly mean of composites, "
                         "bestEffort=True, same as tasks 11-12",
        },
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(monthly)} months)")

    # ---- the numbers (pre-registered reading was printed above) ----
    aqua = json.loads(OUT.read_text(encoding="utf-8"))["monthly"]
    terra_veg = json.loads(TERRA_VEG.read_text(encoding="utf-8"))
    terra_ctl = json.loads(TERRA_CTL.read_text(encoding="utf-8"))
    terra_solar = {r["month"]: r.get("solar_zenith_deg")
                   for r in terra_ctl["monthly"]}

    print_solar_side_by_side(aqua, terra_solar)

    print("\n=== Terra July NDMI residuals (task 12's series, refit with "
          "the leave-one-out step) ===")
    report(july_rows(terra_veg["monthly"], terra_ctl["monthly"]))

    print("\n=== Aqua July NDMI residuals, fitted entirely within Aqua "
          "(Aqua NDMI on Aqua's own good-pixel share and controls) ===")
    report(july_rows(aqua, aqua),
           base_note="Aqua, fitted entirely within Aqua")


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
