"""Aerosol and view-geometry controls on the July NDMI residual (Task 12,
PLAN.md 2.4 and 14).

Task 11 published NDVI and NDMI beside their good-pixel shares. After
controlling July NDMI on its own good-pixel share, July 2026 keeps the
largest residual of 26 Julys (+0.0206) while the equivalent NDVI residual
dissolves — and physically the NDMI excess runs the wrong way: a canopy
losing water should raise SWIR reflectance and lower NDMI. This script
fetches two families of confounder the pipeline already downloads past,
over the same masked land pixels, at the same 500 m scale and with the
same monthly-mean reducer as task 11, so the new series are comparable
with the published ones:

  - MOD09A1 StateQA (the same bitmask task 11 read bits 0-1 of for cloud
    state), bits 6-7 = aerosol quantity: 0 = climatology (the correction
    could not retrieve an aerosol optical depth and fell back to a
    climatological estimate), 1 = low, 2 = average, 3 = high. Published
    per month as the share of land pixels at level 3 (aerosol_high_share)
    and at level 0 (aerosol_climatology_share — a different kind of bad).
  - MOD13A1 per-composite observation geometry: ViewZenith and
    SolarZenith, stored in hundredths of a degree (scale 0.01), published
    as land means in degrees (view_zenith_deg, solar_zenith_deg).

Writes docs/data/vegetation_controls.json — a NEW file; task 11's
vegetation.json and its panel are not touched. The monthly array is keyed
by the same month strings as vegetation.json, which is where the month
list is read from. After writing the file the script reads vegetation.json
and, for July only, refits NDMI on good_share alone (reproducing the task
11 residual — the check that the two series match), then with each new
control added one at a time, then all four together, reporting
coefficients, n, residual sd, July 2026's residual rank and its leverage
in every model, and finally refitting each model with July 2026 removed to
predict it out of sample. That last step is the one that separates a
control which explains the year from a fit that has bent onto it: with
h = 0.68, an in-sample residual is partly a measure of the model
reproducing a point it was built from. The least-squares solve is plain
arithmetic on the normal equations, no statistics package. ee is imported lazily inside main() so
the solver can be checked by the tests in an environment without Earth
Engine.

If Earth Engine is unreachable or credentials are missing the exception
propagates and nothing is written: an absent file is the correct output of
a failed fetch.

Run by hand, not by the daily cron, like src/vegetation_gee.py:

    python src/vegetation_controls_gee.py <google-cloud-project-id>

Run inside the `geolibre` conda environment, after `earthengine authenticate`.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VEG = ROOT / "docs" / "data" / "vegetation.json"
OUT = ROOT / "docs" / "data" / "vegetation_controls.json"

# MOD09A1 StateQA bits 6-7, aerosol quantity (catalog: 0 = climatology,
# 1 = low, 2 = average, 3 = high). Bits 0-1 (cloud state) are task 11's
# good-pixel test; bits 8-9 (cirrus) are a third question, not read here.
AEROSOL_MASK = 192        # 0b11000000
AEROSOL_SHIFT = 6
AEROSOL_HIGH = 3
AEROSOL_CLIM = 0

CONTROLS = ["aerosol_high_share", "aerosol_climatology_share",
            "view_zenith_deg", "solar_zenith_deg"]


# ---------------------------------------------------------------------------
# Earth Engine per-month reducers — one getInfo per series, same mask,
# same scale, same reducer as task 11
# ---------------------------------------------------------------------------
def monthly_mod09_aerosol(coll, aoi, months):
    """Per month: share of land pixels whose MOD09A1 StateQA aerosol
    quantity (bits 6-7) is 3 (high) and 0 (climatology fallback), over
    the same masked land pixels at the same scale as task 11's NDMI."""
    import ee
    from vegetation_gee import SCALE, land_mask, next_month

    def per_image(img):
        aerosol = img.select("StateQA").bitwiseAnd(AEROSOL_MASK) \
            .rightShift(AEROSOL_SHIFT)
        return aerosol.eq(AEROSOL_HIGH).rename("high") \
            .addBands(aerosol.eq(AEROSOL_CLIM).rename("clim")) \
            .updateMask(land_mask()) \
            .copyProperties(img, ["system:time_start"])

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")
        stats = (fc.map(per_image)
                 .mean()
                 .rename(["high_frac", "clim_frac"])
                 .reduceRegion(ee.Reducer.mean(), aoi, SCALE,
                               bestEffort=True))
        return ee.Algorithms.If(
            fc.size().gt(0),
            ee.Dictionary({
                "aerosol_high_share": stats.get("high_frac"),
                "aerosol_climatology_share": stats.get("clim_frac"),
            }),
            None)

    raw = ee.List([one(ym) for ym in months]).getInfo()
    return _rows(raw, months, ("aerosol_high_share",
                               "aerosol_climatology_share"))


def monthly_mod13_angles(coll, aoi, months):
    """Per month: land-mean MOD13A1 ViewZenith and SolarZenith (stored in
    hundredths of a degree, scale 0.01), over the same masked land pixels
    at the same scale as task 11's NDVI."""
    import ee
    from vegetation_gee import SCALE, land_mask, next_month

    def per_image(img):
        return img.select(["ViewZenith", "SolarZenith"]).multiply(0.01) \
            .updateMask(land_mask()) \
            .copyProperties(img, ["system:time_start"])

    def one(ym):
        fc = coll.filterDate(ym + "-01", next_month(ym) + "-01")
        stats = (fc.map(per_image)
                 .mean()
                 .rename(["view_deg", "solar_deg"])
                 .reduceRegion(ee.Reducer.mean(), aoi, SCALE,
                               bestEffort=True))
        return ee.Algorithms.If(
            fc.size().gt(0),
            ee.Dictionary({
                "view_zenith_deg": stats.get("view_deg"),
                "solar_zenith_deg": stats.get("solar_deg"),
            }),
            None)

    raw = ee.List([one(ym) for ym in months]).getInfo()
    return _rows(raw, months, ("view_zenith_deg", "solar_zenith_deg"))


def _rows(raw, months, keys):
    out = []
    for ym, r in zip(months, raw):
        row = {"month": ym}
        for k in keys:
            row[k] = (round(r[k], 4)
                      if r is not None and r.get(k) is not None else None)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Least squares, plain arithmetic (no statistics package)
# ---------------------------------------------------------------------------
def _solve(a, b):
    """Gauss-Jordan with partial pivoting; raises on a singular system."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-10:
            raise ValueError("singular normal equations")
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c and m[r][c] != 0:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(rows, predictors, target):
    """OLS with intercept on the normal equations. Returns named
    coefficients, residuals and hat diagonals (leverage)."""
    X = [[1.0] + [r[p] for p in predictors] for r in rows]
    y = [r[target] for r in rows]
    n, p = len(X), len(X[0])
    xtx = [[sum(X[k][i] * X[k][j] for k in range(n)) for j in range(p)]
           for i in range(p)]
    xty = [sum(X[k][i] * y[k] for k in range(n)) for i in range(p)]
    beta = _solve(xtx, xty)
    inv = [_solve(xtx, [1.0 if i == j else 0.0 for i in range(p)])
           for j in range(p)]                     # columns of (X'X)^-1
    leverage = []
    for xk in X:
        w = [sum(inv[j][i] * xk[j] for j in range(p)) for i in range(p)]
        leverage.append(sum(xk[i] * w[i] for i in range(p)))
    fitted = [sum(b * v for b, v in zip(beta, xk)) for xk in X]
    return {"names": ["intercept"] + list(predictors), "coef": beta,
            "n": n, "residuals": [yi - fi for yi, fi in zip(y, fitted)],
            "leverage": leverage}


# ---------------------------------------------------------------------------
# The July residual analysis
# ---------------------------------------------------------------------------
MODELS = [
    ("base: ndmi on its own good-pixel share", ["ndmi_good_share"]),
    ("+ aerosol_high_share", ["ndmi_good_share", "aerosol_high_share"]),
    ("+ aerosol_climatology_share",
     ["ndmi_good_share", "aerosol_climatology_share"]),
    ("+ view_zenith_deg", ["ndmi_good_share", "view_zenith_deg"]),
    ("+ solar_zenith_deg", ["ndmi_good_share", "solar_zenith_deg"]),
    ("all controls together", ["ndmi_good_share"] + CONTROLS),
]


def july_rows(veg_monthly, ctrl_monthly):
    """July rows joining vegetation.json's NDMI series to the controls."""
    ctrl = {r["month"]: r for r in ctrl_monthly}
    rows = []
    for r in veg_monthly:
        if r["month"][5:7] != "07":
            continue
        c = ctrl.get(r["month"], {})
        row = {"month": r["month"], "ndmi": r.get("ndmi"),
               "ndmi_good_share": r.get("ndmi_good_share")}
        for k in CONTROLS:
            row[k] = c.get(k)
        rows.append(row)
    return rows


def report(rows, focus="2026-07", base_note="reproduces task 11"):
    print("\nNDMI July residuals under observation-quality controls")
    print("(each control added one at a time, then all four together; "
          "residual sd = sqrt(SSR/n), the convention behind the task 11 "
          "z values)")
    for label, preds in MODELS:
        use = [r for r in rows if r.get("ndmi") is not None
               and all(r.get(p) is not None for p in preds)]
        jul = next((i for i, r in enumerate(use) if r["month"] == focus),
                   None)
        if jul is None or len(use) < 3:
            print(f"\nmodel: {label}\n  not reportable "
                  f"(n = {len(use)}, no {focus} row)")
            continue
        # a control constant across July carries no information and makes
        # the normal equations singular — say so instead of crashing
        dropped = [p for p in preds if len({r[p] for r in use}) == 1]
        preds_eff = [p for p in preds if p not in dropped]
        fit = ols(use, preds_eff, "ndmi")
        res = fit["residuals"]
        n = fit["n"]
        sd = math.sqrt(sum(v * v for v in res) / n)
        r26 = res[jul]
        rank = 1 + sum(1 for v in res if v < r26)
        mean_h = len(fit["names"]) / n
        h = fit["leverage"][jul]
        print(f"\nmodel: {label}"
              + (f" ({base_note})" if label.startswith("base") else ""))
        print("  ndmi ~ " + " + ".join(fit["names"][1:]))
        print("  coefficients: " + "  ".join(
            f"{nm} {b:+.4f}" for nm, b in zip(fit["names"], fit["coef"])))
        print(f"  n = {n}   resid sd = {sd:.4f}")
        print(f"  {focus}: residual {r26:+.4f}   z {r26 / sd:+.2f}   "
              f"rank {rank} of {n} (1 = smallest residual)")
        print(f"  leverage: {focus} h = {h:.3f}   mean h = {mean_h:.3f} "
              f"({h / mean_h:.1f}x mean)")
        for p in preds:
            vals = [r[p] for r in use]
            lo, hi = min(vals), max(vals)
            x = use[jul][p]
            if hi > lo:
                span = (x - lo) / (hi - lo)
                edge = ("   <- AT THE EDGE of the predictor range"
                        if span >= 0.95 or span <= 0.05 else "")
                print(f"    {p}: {focus} = {x:.3f}   July range "
                      f"{lo:.3f}..{hi:.3f} ({span:.0%} of range){edge}")
            else:
                print(f"    {p}: {focus} = {x:.3f}   constant across July")
        if dropped:
            print("  dropped (constant across July, no information): "
                  + ", ".join(dropped))

        # Leave the focus year out, refit, and predict it. Leverage says a
        # point could be pulling the fit onto itself; this says whether it
        # did. An in-sample residual at h = 0.68 partly measures how well the
        # model reproduces a point it was built from. Out of sample there is
        # no such circularity: if the controls explain the year, a fit that
        # has never seen it still predicts it.
        rest = [r for i, r in enumerate(use) if i != jul]
        try:
            loo = ols(rest, preds_eff, "ndmi")
        except ValueError:
            print(f"  leave-one-out: singular without {focus}")
            continue
        pred = loo["coef"][0] + sum(
            b * use[jul][pr] for b, pr in zip(loo["coef"][1:], preds_eff))
        err = use[jul]["ndmi"] - pred
        sd_loo = math.sqrt(
            sum(v * v for v in loo["residuals"]) / len(rest))
        print(f"  leave-{focus}-out: predicted {pred:.4f}   "
              f"actual {use[jul]['ndmi']:.4f}   error {err:+.4f}   "
              f"= {err / sd_loo:+.2f} sd of the {len(rest)} it was fitted on")
        print("  coefficient shift when " + focus + " is removed: "
              + "   ".join(
                  f"{nm} {b_in:+.5f} -> {b_out:+.5f}"
                  for nm, b_in, b_out in zip(fit["names"][1:], fit["coef"][1:],
                                             loo["coef"][1:])))


# ---------------------------------------------------------------------------
def main(project: str) -> None:
    import ee
    import yaml
    from vegetation_gee import MOD09, MOD13

    ee.Initialize(project=project)
    # vegetation.json is read once and never written: it supplies the month
    # strings (keeping the two files aligned) and the NDMI series the
    # residuals are computed from.
    veg = json.loads(VEG.read_text(encoding="utf-8"))
    months = [r["month"] for r in veg["monthly"]]
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    w, s, e, n = [float(v) for v in cfg["aoi_bbox_wsen"]]
    aoi = ee.Geometry.Rectangle([w, s, e, n])

    print(f"months: {months[0]} .. {months[-1]}  ({len(months)} months; "
          "read from vegetation.json so the two files stay aligned)")
    print("fetching MOD09A1 aerosol-quantity shares (StateQA bits 6-7) ...")
    aero = monthly_mod09_aerosol(ee.ImageCollection(MOD09), aoi, months)
    print("fetching MOD13A1 view and solar zenith (scale 0.01) ...")
    ang = monthly_mod13_angles(ee.ImageCollection(MOD13), aoi, months)

    monthly = []
    for a, b in zip(aero, ang):
        row = dict(a)
        row.update({k: v for k, v in b.items() if k != "month"})
        monthly.append(row)

    doc = {
        "monthly": monthly,
        "coverage": {
            # last dates of the span the month list was drawn from
            "mod13a1_last_date": veg["coverage"]["mod13a1_last_date"],
            "mod09a1_last_date": veg["coverage"]["mod09a1_last_date"],
            "generated_utc": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "sources": {
            "aerosol": "MODIS/061/MOD09A1 StateQA bits 6-7 = aerosol "
                       "quantity (0 = climatology, 1 = low, 2 = average, "
                       "3 = high); aerosol_high_share = land-mean monthly "
                       "frequency at level 3, aerosol_climatology_share = "
                       "at level 0 (no retrieval, climatological fallback)",
            "geometry": "MODIS/061/MOD13A1 ViewZenith and SolarZenith, "
                        "stored in hundredths of a degree (scale 0.01); "
                        "land means in degrees",
            "land_mask": "ESA/WorldCover/v200 (class 80 = permanent water)",
            "months": "same month strings as docs/data/vegetation.json",
            "reduction": "500 m, monthly mean of composites, "
                         "bestEffort=True, same as task 11",
        },
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}  ({len(monthly)} months)")

    report(july_rows(veg["monthly"], monthly))


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
