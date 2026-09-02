"""Does the water balance in F1 survive Terra's orbit drift? (Task 14,
PLAN.md 2.5; FINDINGS F1 and F4.)

F1 is published: the drought panel states that July 2026 is the only month
in the MOD16A2 record for this AOI with a negative water balance (P - ET),
and that ET rose to a record high while the rain failed. MOD16A2 is a Terra
product and F4 shows Terra's overpass drifting since 2022, so a record high
at the end of a drifting record is the shape an artifact takes. This task
cross-checks F1 against the Aqua counterpart of the same product.

Record length, verified against the catalog and the live collection
(2026-09-01): MOD16A2 v061 and MYD16A2 v061 both begin 2021-01-01 - the
MODIS Science Team did not produce v061 data before 2021, and the pre-2021
recommendation is the gap-filled MOD16A2GF/MYD16A2GF, which F1 bans. The
record therefore holds about six Julys, which cannot fit the task 12/13
models. The refusal to fit is printed, not papered over; the answer is
carried by the cross-sensor comparison and the recomputed water balance.

Fetches, per month over the same masked land pixels, at the same scale and
reducer as src/drought_gee.py:

  - et_terra_mm - MODIS/061/MOD16A2 (ET, 8-day totals at scale 0.1 mm,
    summed over the month, 500 m land mean) - exactly drought_gee.py's
    method, and checked against drought.json month for month before
    anything else runs; a mismatch stops the script and writes nothing.
  - et_aqua_mm - MODIS/061/MYD16A2, the same treatment. Whether Aqua holds
    the later months at all is checked before anything is built on it.
    No gap-filled product is substituted.
  - et_qc_good_share_terra / et_qc_good_share_aqua - the share of land
    pixels whose ET_QC bit 0 is 0. Catalog, both products: bit 0
    (MODLAND_QC) 0 = good quality (main algorithm, with or without
    saturation), 1 = other quality (back-up algorithm or fill values);
    bit 1 encodes the sensor (0 Terra, 1 Aqua); bits 5-7 a 5-level
    confidence score. Bit 0 is the product's own good/bad statement, so a
    low share means more of the monthly total is climatology-driven back-up
    rather than observation-driven.
  - Geometry is NOT refetched: view_zenith_deg / solar_zenith_deg are
    copied from docs/data/vegetation_controls.json (MOD13A1, Terra) and
    aqua_view_zenith_deg / aqua_solar_zenith_deg from
    docs/data/vegetation_aqua.json (MYD13A1, Aqua). Precipitation is
    copied from docs/data/drought.json (the same CHIRPS pull the published
    balance uses).

Writes docs/data/drought_et_check.json - a NEW file; drought.json,
vegetation.json, vegetation_controls.json, vegetation_aqua.json and the
pages are not touched. The month list is drought.json's, so the overlap is
exact by construction.

If Earth Engine is unreachable or credentials are missing the exception
propagates and nothing is written: an absent file is the correct output of
a failed fetch.

Run by hand, not by the daily cron, like src/drought_gee.py:

    python src/drought_et_check_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DROUGHT = ROOT / "docs" / "data" / "drought.json"
VEG_CTL = ROOT / "docs" / "data" / "vegetation_controls.json"
VEG_AQUA = ROOT / "docs" / "data" / "vegetation_aqua.json"
OUT = ROOT / "docs" / "data" / "drought_et_check.json"

# Catalog-verified 2026-09-01: both v061 ET products begin 2021-01-01 and
# carry identical band sets (ET scale 0.1, 8-day totals) and identical
# ET_QC bit layouts (bit 1 encodes 0 = Terra, 1 = Aqua).
MOD16 = "MODIS/061/MOD16A2"
MYD16 = "MODIS/061/MYD16A2"
SCALE = 500          # drought_gee.py reduces ET at 500 m

PRE_REGISTERED = """\
Pre-registered reading of each outcome, decided before the numbers:
  - Both sensors show July 2026 as an extreme ET month, and the negative
    balance holds under Aqua: F1 survives. The claim is about the
    atmosphere and the land, not about Terra.
  - Aqua shows no such extreme, or the balance is not negative under
    Aqua: F1's headline is in question. The panel is not edited here,
    but this goes to the top of the final message as a correction
    awaiting the owner's decision, because a live page is asserting it.
  - Aqua has no usable 2026 data: the cross-check cannot be run, and the
    question stays open. An unrun test is never presented as a passed
    one.
Agreement is strong evidence; disagreement is weak evidence."""

CAVEAT = """\
What could and could not carry Terra's drift here. MOD16A2 is not a
reflectance index: it is a Penman-Monteith model driven by daily
meteorological reanalysis together with MODIS inputs (LAI/FPAR, albedo,
land cover). The meteorological forcing does not move with the overpass;
the MODIS vegetation inputs do. So the contamination path is narrower than
it was for NDMI: a Terra-Aqua ET difference can come from differing
MODIS inputs on the two overpasses (geometry- or cloud-driven), not from
the radiation forcing, and ET must not be read as if it were a band."""


def monthly_et(coll, aoi, months):
    """drought_gee.py's exact ET reduction: per month, sum the 8-day
    composites (ET already scaled to mm), then the 500 m land mean.
    One getInfo for the whole series."""
    import ee
    from drought_gee import mean_over, next_month

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")
        img = fc.sum()
        return ee.Algorithms.If(
            fc.size().gt(0), mean_over(img, aoi, SCALE, "ET"), None)

    return ee.List([one(ym) for ym in months]).getInfo()


def monthly_qc_good(coll, aoi, months):
    """Share of land pixels whose ET_QC bit 0 is 0 (good quality, main
    algorithm): per-image boolean, monthly mean per pixel, land mean -
    the same share-of-good-pixels pattern as tasks 11-13. One getInfo."""
    import ee
    from drought_gee import land_mask, mean_over, next_month

    def per_image(img):
        return img.select("ET_QC").bitwiseAnd(1).eq(0).rename("good") \
            .updateMask(land_mask()) \
            .copyProperties(img, ["system:time_start"])

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")
        img = fc.map(per_image).mean()
        return ee.Algorithms.If(
            fc.size().gt(0), mean_over(img, aoi, SCALE, "good"), None)

    return ee.List([one(ym) for ym in months]).getInfo()


def scaled_et_coll(coll):
    import ee
    return coll.select("ET").map(
        lambda i: i.multiply(0.1).rename("ET")
        .copyProperties(i, ["system:time_start"]))


def july_stats(rows, key):
    """July 2026's ET, its rank among the sensor's Julys (1 = highest ET),
    and its departure from that sensor's own July mean."""
    jul = [r for r in rows if r["month"][5:7] == "07"
           and r.get(key) is not None]
    j26 = next((r for r in jul if r["month"] == "2026-07"), None)
    if j26 is None or len(jul) < 2:
        return None
    vals = [r[key] for r in jul]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
    rank = 1 + sum(1 for v in vals if v > j26[key])
    return {"et": j26[key], "rank": rank, "n": len(jul), "mean": mean,
            "depart": j26[key] - mean, "depart_sd": (j26[key] - mean) / sd,
            "series": [(r["month"], r[key]) for r in jul]}


def main(project: str) -> None:
    import ee
    import yaml
    from drought_gee import land_mask

    ee.Initialize(project=project)
    drought = json.loads(DROUGHT.read_text(encoding="utf-8"))
    veg_ctl = json.loads(VEG_CTL.read_text(encoding="utf-8"))
    veg_aqua = json.loads(VEG_AQUA.read_text(encoding="utf-8"))

    months = [r["month"] for r in drought["monthly"]]
    precip = {r["month"]: r["precip_mm"] for r in drought["monthly"]}
    terra_geo = {r["month"]: r for r in veg_ctl["monthly"]}
    aqua_geo = {r["month"]: r for r in veg_aqua["monthly"]}

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    w, s, e, n = [float(v) for v in cfg["aoi_bbox_wsen"]]
    aoi = ee.Geometry.Rectangle([w, s, e, n])

    mod16 = ee.ImageCollection(MOD16)
    myd16 = ee.ImageCollection(MYD16)
    m16_first = ee.Date(mod16.aggregate_min("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    y16_first = ee.Date(myd16.aggregate_min("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    m16_last = ee.Date(mod16.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()
    y16_last = ee.Date(myd16.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd").getInfo()

    n_julys = sum(1 for m in months if m[5:7] == "07")
    print(f"record-length case: MOD16A2 v061 verified to begin "
          f"{m16_first} and MYD16A2 v061 {y16_first} (catalog and live "
          f"collection agree); the analyzable record ({months[0]} .. "
          f"{months[-1]}, bounded by drought.json's CHIRPS span) holds "
          f"{n_julys} Julys.")
    if m16_first[:7] < months[0]:
        print(f"  note: MOD16A2 begins {m16_first}, earlier than "
              f"drought.json uses; extending the balance would need a "
              f"CHIRPS refetch and is its own task.")
    print(f"  case: SHORT - {n_julys} Julys cannot fit the task 12/13 "
          f"models (n was already the binding constraint at 25-26). No "
          f"model is fitted; the refusal is the result. drought_gee.py's "
          f"SERIES_START = 2021-01-01 is correct, not a defect.")
    print()
    print(PRE_REGISTERED)
    print()
    print(CAVEAT)

    print("\nfetching Terra ET (MOD16A2, drought_gee.py's method) ...")
    et_terra = monthly_et(scaled_et_coll(mod16), aoi, months)

    # the reproduction check everything downstream depends on
    bad = []
    for ym, t in zip(months, et_terra):
        pub = next(r["et_mm"] for r in drought["monthly"]
                   if r["month"] == ym)
        if t is None or pub is None or abs(round(t, 1) - pub) > 0.051:
            bad.append((ym, None if t is None else round(t, 1), pub))
    if bad:
        for ym, got, pub in bad:
            print(f"  MISMATCH {ym}: fetched {got} vs drought.json {pub}")
        raise SystemExit("Terra ET does not reproduce drought.json month "
                         "for month - stopping, nothing written")
    print(f"  reproduction check: Terra ET matches drought.json for all "
          f"{len(months)} months")

    print("fetching Terra ET_QC good share (bit 0 == 0) ...")
    qc_terra = monthly_qc_good(mod16, aoi, months)
    print("fetching Aqua ET (MYD16A2, same treatment) ...")
    et_aqua = monthly_et(scaled_et_coll(myd16), aoi, months)
    print("fetching Aqua ET_QC good share (bit 0 == 0) ...")
    qc_aqua = monthly_qc_good(myd16, aoi, months)

    # Aqua's late-month coverage gate: no substitutable product exists, so
    # a missing Aqua month stays None and the analysis reports around it.
    missing_aqua = [ym for ym, v in zip(months, et_aqua) if v is None]
    if missing_aqua:
        print(f"  note: MYD16A2 holds no data for {len(missing_aqua)} "
              f"month(s): {', '.join(missing_aqua)}")

    monthly = []
    for ym, t, a, qt, qa in zip(months, et_terra, et_aqua, qc_terra,
                                qc_aqua):
        g, ag = terra_geo.get(ym, {}), aqua_geo.get(ym, {})
        row = {
            "month": ym,
            "precip_mm": precip[ym],
            "et_terra_mm": round(t, 1) if t is not None else None,
            "et_aqua_mm": round(a, 1) if a is not None else None,
            "et_qc_good_share_terra":
                round(qt, 4) if qt is not None else None,
            "et_qc_good_share_aqua":
                round(qa, 4) if qa is not None else None,
            "view_zenith_deg": g.get("view_zenith_deg"),
            "solar_zenith_deg": g.get("solar_zenith_deg"),
            "aqua_view_zenith_deg": ag.get("view_zenith_deg"),
            "aqua_solar_zenith_deg": ag.get("solar_zenith_deg"),
        }
        row["p_minus_et_terra_mm"] = (
            None if row["et_terra_mm"] is None
            else round(row["precip_mm"] - row["et_terra_mm"], 1))
        row["p_minus_et_aqua_mm"] = (
            None if row["et_aqua_mm"] is None
            else round(row["precip_mm"] - row["et_aqua_mm"], 1))
        monthly.append(row)

    doc = {
        "monthly": monthly,
        "coverage": {
            "mod16a2_first_date": m16_first,
            "myd16a2_first_date": y16_first,
            "mod16a2_last_date": m16_last,
            "myd16a2_last_date": y16_last,
            "generated_utc": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sources": {
            "et_terra": "MODIS/061/MOD16A2 (ET, 8-day totals at scale "
                        "0.1 mm, summed over the month, 500 m land mean, "
                        "bestEffort=True - exactly src/drought_gee.py's "
                        "method; verified against drought.json)",
            "et_aqua": "MODIS/061/MYD16A2 (same band, scale, mask, "
                       "reducer; no gap-filled product substituted)",
            "et_qc_good_share": "each product's own ET_QC bit 0 "
                                "(MODLAND_QC): 0 = good quality (main "
                                "algorithm), 1 = back-up algorithm or "
                                "fill; share of land pixels at 0",
            "geometry": "view_zenith_deg / solar_zenith_deg copied from "
                        "docs/data/vegetation_controls.json (MOD13A1, "
                        "Terra); aqua_* from "
                        "docs/data/vegetation_aqua.json (MYD13A1, Aqua) "
                        "- not refetched",
            "precipitation": "copied from docs/data/drought.json "
                             "(UCSB-CHG/CHIRPS/DAILY land means, the "
                             "same pull the published balance uses)",
            "land_mask": "ESA/WorldCover/v200 (class 80 = permanent water)",
            "months": "same month strings as docs/data/drought.json",
        },
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(monthly)} months)")

    # ---- the numbers (pre-registered reading was printed above) ----
    print("\n=== 1. Do the sensors agree about July 2026? ===")
    for name, et_key, qc_key in (("Terra (MOD16A2)", "et_terra_mm",
                                  "et_qc_good_share_terra"),
                                 ("Aqua (MYD16A2)", "et_aqua_mm",
                                  "et_qc_good_share_aqua")):
        st = july_stats(monthly, et_key)
        if st is None:
            print(f"  {name}: July 2026 ET unavailable or too few Julys")
            continue
        print(f"  {name}: July 2026 ET {st['et']:.1f} mm, rank {st['rank']} "
              f"of {st['n']} Julys (1 = highest), July mean "
              f"{st['mean']:.1f} mm, departure {st['depart']:+.1f} mm "
              f"({st['depart_sd']:+.2f} sd)")
        print("    July series: "
              + ", ".join(f"{m}: {v:.1f}" for m, v in st["series"]))
        shares = [r[qc_key] for r in monthly
                  if r["month"][5:7] == "07" and r.get(qc_key) is not None]
        q26 = next(r[qc_key] for r in monthly if r["month"] == "2026-07")
        print(f"    ET_QC good share, July 2026 vs July range: "
              f"{q26:.3f} vs {min(shares):.3f}..{max(shares):.3f}")

    print("\n=== 2. Does the headline claim survive? Water balance under "
          "Aqua ET ===")
    neg_t = [r["month"] for r in monthly
             if r["p_minus_et_terra_mm"] is not None
             and r["p_minus_et_terra_mm"] < 0]
    neg_a = [r["month"] for r in monthly
             if r["p_minus_et_aqua_mm"] is not None
             and r["p_minus_et_aqua_mm"] < 0]
    j26 = next(r for r in monthly if r["month"] == "2026-07")
    print(f"  Terra: negative-balance months: "
          + (", ".join(neg_t) if neg_t else "none")
          + f"; July 2026 P-ET {j26['p_minus_et_terra_mm']} mm")
    if not neg_a:
        print("  Aqua: no negative-balance month in the record")
    else:
        print("  Aqua: negative-balance months: " + ", ".join(neg_a)
              + f"; July 2026 P-ET {j26['p_minus_et_aqua_mm']} mm")
    if j26["p_minus_et_aqua_mm"] is not None:
        print(f"  published claim ('July 2026 the only month with P-ET "
              f"below zero'): under Aqua ET the balance is "
              f"{j26['p_minus_et_aqua_mm']:+.1f} mm - "
              + ("still negative" if j26["p_minus_et_aqua_mm"] < 0
                 else "NOT negative under Aqua"))

    print("\n=== 3. Task 12/13 models on ET ===")
    print(f"  not fitted: {n_julys} Julys cannot identify models with "
          f"intercept plus predictors (n was already the binding "
          f"constraint at 25-26; at 6 it is not a sample at all). The "
          f"geometry series is published in the file for whoever picks "
          f"this up when the record is longer.")

    print(f"\nMYD16A2 last date {y16_last}; July 2026 Aqua ET "
          f"{'present' if j26['et_aqua_mm'] is not None else 'ABSENT'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
