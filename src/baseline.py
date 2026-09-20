"""Detection climatology: the baseline any model must beat (Task 17,
PLAN.md Phase 5 step 2).

For each land grid cell and each observed WIT day: did at least one
detection fall in that cell on that day. Binary; counts are not predicted.

The baseline is p(cell, day-of-year): the share of observed training days
in a window around that day-of-year on which the cell had a detection. It
is scored OUT OF SAMPLE, one calendar year held out at a time, because a
climatology scored on the years it was fitted on flatters itself and every
model later compared against it inherits the flattery. PLAN.md Phase 5 is
explicit that splits are temporal, by season, never random; the baseline
gets the same treatment the model will.

Two structural facts shape it:

- The satellites watching this AOI changed mid-record. NOAA-21 contributes
  nothing before 2024-02-16, so the baseline sees every year through a
  fixed constellation set in config.yaml; detections outside it are
  counted and set aside, and the positive cell-days that exist only
  through them are reported.
- An unobserved day is not a zero (AGENTS never-2). A day counts as
  observed only when report_daily._is_observed_closed holds for every
  instrument group - the project's one definition of a covered day, reused
  here rather than copied. Cloud is not detected from this data: a cloudy
  observed day stays a zero.

No model is built here, no probability array is written to disk (it is
regenerated from the store in seconds, and a stored copy is one that goes
stale), and no entry is added to FINDINGS.md: these numbers are the bar
every later model is held to, and the finding is written at review from
baseline_eval.json.

Offline only: the inputs are the tracked detections store, the run
manifest and the desa polygons. Nothing is fetched.

    python src/baseline.py

Wording note (PLAN.md section 8): this is a climatology of satellite
detections - the probability of a detection. It is not a forecast of
burning, not a danger rating, and it says nothing about cause.
"""
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from recurrence import M_PER_DEG
from report_daily import _is_observed_closed

ROOT = Path(__file__).resolve().parents[1]
DET = ROOT / "data" / "processed" / "detections.parquet"
MANIFEST = ROOT / "data" / "processed" / "run_manifest.json"
OUT = ROOT / "data" / "processed" / "baseline_eval.json"

CAVEATS = [
    "A day is observed when every constellation instrument was successfully "
    "fetched for it. Cloud is not detected: a cloudy observed day counts as "
    "a day without detection.",
    "The constellation excludes NOAA-21, which contributes nothing before "
    "16 February 2024, so that the baseline sees each year through the same "
    "satellites.",
    "Three years of history is the minimum PLAN.md Phase 5 names. "
    "Probabilities are pooled over a 31-day window and remain small-sample "
    "estimates.",
    "A climatology fitted on 2023-2025 under-predicts August 2026 by "
    "construction; that fold measures how unusual 2026 was as much as how "
    "good the baseline is.",
    "This is a climatology of satellite detections. It is not a forecast of "
    "fire, not a fire danger rating, and it says nothing about why land is "
    "burned or who burns it (PLAN.md section 8).",
]


def day_of_year_365(day: date) -> int:
    """Day-of-year on a 365-day circle: 29 February takes 28 February's
    number, so every year shares one calendar."""
    if day.month == 2 and day.day == 29:
        return date(2001, 2, 28).timetuple().tm_yday
    return date(2001, day.month, day.day).timetuple().tm_yday


def doy_window(center: int, half: int) -> set:
    """Day-of-year set within `half` days of `center` on the 365-day
    circle. Wraps: 31 December is 1 day from 1 January."""
    return {(center + s - 1) % 365 + 1 for s in range(-half, half + 1)}


class Grid:
    """Regular grid anchored at the bbox south-west corner. Cell side is
    grid_m / M_PER_DEG in degrees on BOTH axes: the longitude scale differs
    from the latitude scale by under 0.05% at |lat| < 1.6 (about 0.4 m per
    cell edge), far inside FIRMS geolocation jitter, and is not corrected
    for - the same trade recurrence.py already makes."""

    def __init__(self, bbox_wsen, grid_m):
        self.x0, self.y0, self.x1, self.y1 = (float(v) for v in bbox_wsen)
        self.d = grid_m / M_PER_DEG
        self.nx = max(1, math.ceil((self.x1 - self.x0) / self.d))
        self.ny = max(1, math.ceil((self.y1 - self.y0) / self.d))

    def index_arrays(self, lon, lat):
        """Cell indices (i, j) per point. A point exactly on the east or
        north bbox edge belongs to the last cell, hence the clip."""
        i = np.clip(np.floor((np.asarray(lon) - self.x0) / self.d),
                    0, self.nx - 1).astype(np.int64)
        j = np.clip(np.floor((np.asarray(lat) - self.y0) / self.d),
                    0, self.ny - 1).astype(np.int64)
        return i, j

    def cell_box(self, i, j):
        from shapely.geometry import box as sbox
        return sbox(self.x0 + i * self.d, self.y0 + j * self.d,
                    self.x0 + (i + 1) * self.d, self.y0 + (j + 1) * self.d)


def land_cells(grid, admin_path):
    """Cells whose square overlaps the desa union on positive area:
    `intersects and not touches`, so a cell that only shares a boundary
    line or corner with the union - and contains no desa land at all -
    is not a land cell. Prepared geometry, bounds pre-filter. Read with
    json + shapely: geopandas is not a dependency here."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.prepared import prep

    doc = json.loads(admin_path.read_text(encoding="utf-8"))
    u = unary_union([shape(f["geometry"]) for f in doc["features"]])
    ux0, uy0, ux1, uy1 = u.bounds
    union = prep(u)
    cells = []
    for i in range(grid.nx):
        for j in range(grid.ny):
            b = grid.cell_box(i, j)
            if b.bounds[2] < ux0 or b.bounds[0] > ux1 or \
                    b.bounds[3] < uy0 or b.bounds[1] > uy1:
                continue
            if union.intersects(b) and not union.touches(b):
                cells.append((int(i), int(j)))
    return sorted(cells)


def observed_days(day_list, runs, groups):
    """A day is observed when _is_observed_closed holds for EVERY
    instrument group. One definition, reused not copied (Task 08c); the
    runs lists are pre-filtered per group, which the predicate's own
    source filter makes equivalent."""
    observed, unobserved = [], []
    filtered = [[e for e in runs if e.get("source") in set(srcs)]
                for srcs in groups]
    for day in day_list:
        d = date.fromisoformat(day)
        if all(_is_observed_closed(d, filtered[k], groups[k])
               for k in range(len(groups))):
            observed.append(day)
        else:
            unobserved.append(day)
    return observed, unobserved


def instrument_groups(constellation):
    """The three instrument groups the observed-day rule requires: S-NPP,
    NOAA-20 and MODIS (Terra and Aqua share their source names). NOAA-21
    is deliberately absent - it covers nothing before 2024-02-16."""
    modis = sorted(set(constellation["Terra"]) | set(constellation["Aqua"]))
    return [list(constellation["N"]), list(constellation["N20"]), modis]


def assign_cells(det, grid):
    i, j = grid.index_arrays(det.longitude.values, det.latitude.values)
    det = det.copy()
    det["cell_i"] = i
    det["cell_j"] = j
    return det


def constellation_split(det, keys, observed_set):
    """Keep only detections from the fixed constellation. Returns the kept
    frame, excluded detection counts by satellite, and the number of
    positive cell-days (land cell x observed day) that exist only through
    the excluded satellites - what the exclusion costs. The caller passes
    a frame already restricted to land cells."""
    keep = det.satellite.isin(list(keys))
    kept = det[keep]
    excl = det[~keep]
    excl = excl[excl.date_wit.isin(observed_set)]
    excl_cd = set(zip(excl.cell_i, excl.cell_j, excl.date_wit))
    kept_cd = set(zip(kept.cell_i, kept.cell_j, kept.date_wit))
    counts = excl.satellite.value_counts().to_dict()
    return kept, counts, len(excl_cd - kept_cd)


def climatology(train_det, train_days, cells, half_window):
    """The detection climatology: p(cell, doy) = (observed training days
    in the doy's window with a detection in the cell) / (observed training
    days in the window), day-of-year on the 365-day circle, no spatial
    smoothing and no pseudo-count - exact zeros are the honest estimate.

    train_det carries columns cell_i, cell_j, date_wit and is already
    constellation- and land-filtered; train_days are ISO strings of the
    observed training days. Returns {(i, j): np.ndarray(365,)} for every
    land cell, so Phase 5 step 3 can import it as-is."""
    if not train_days:
        return {c: np.zeros(365) for c in cells}
    day_set = set(train_days)
    day_doy = np.array([day_of_year_365(date.fromisoformat(d))
                        for d in train_days])
    cnt = np.bincount(day_doy, minlength=366)[1:366].astype(float)
    # window membership: W[k-1, d-1] True when the circular distance
    # between day-of-year k and d is within the half window
    doys = np.arange(1, 366)
    circ = np.abs(doys[:, None] - doys[None, :])
    circ = np.minimum(circ, 365 - circ)
    W = circ <= half_window
    den = W @ cnt
    cell_pos = {c: k for k, c in enumerate(cells)}
    num = np.zeros((len(cells), 365))
    for day, sub in train_det.groupby("date_wit"):
        if day not in day_set:
            continue
        k = day_of_year_365(date.fromisoformat(day))
        ks = np.array(sorted(doy_window(k, half_window))) - 1
        rows = np.array([cell_pos[c] for c in
                         sorted(set(zip(sub.cell_i, sub.cell_j)))])
        num[np.ix_(rows, ks)] += 1.0
    p = np.divide(num, den[None, :], out=np.zeros_like(num),
                  where=den[None, :] > 0)
    return {c: p[r] for r, c in enumerate(cells)}


def average_precision(scores, labels):
    """AP = sum_k (R_k - R_{k-1}) * P_k over UNIQUE score thresholds in
    descending order - sklearn's average_precision_score definition, with
    tied scores treated as one threshold so ranking ties cannot change
    the result. All-equal scores give one threshold: precision = positive
    prevalence, recall = 1."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=int)
    total_pos = labels.sum()
    if total_pos == 0:
        return None
    order = np.argsort(-scores, kind="stable")
    s_sorted = scores[order]
    y_sorted = labels[order]
    ap, tp, fp, r_prev = 0.0, 0, 0, 0.0
    i, n = 0, len(scores)
    while i < n:
        j = i
        while j < n and s_sorted[j] == s_sorted[i]:
            tp += y_sorted[j]
            fp += 1 - y_sorted[j]
            j += 1
        precision = tp / (tp + fp)
        recall = tp / total_pos
        ap += (recall - r_prev) * precision
        r_prev = recall
        i = j
    return float(ap)


def reliability(pooled_p, pooled_y, edges):
    """Pooled reliability table: per bin, count, mean predicted p, and the
    observed positive rate. Phase 5's reliability curve, as data."""
    edges = np.asarray(edges, dtype=float)
    idx = np.searchsorted(edges, pooled_p, side="right") - 1
    idx = np.clip(idx, 0, len(edges) - 2)
    table = []
    for b in range(len(edges) - 1):
        m = idx == b
        n = int(m.sum())
        table.append({
            "bin": f"[{edges[b]:g}, {edges[b + 1]:g})"
            if b < len(edges) - 2 else f"[{edges[b]:g}, {edges[b + 1]:g}]",
            "n": n,
            "mean_p": round(float(pooled_p[m].mean()), 8) if n else 0.0,
            "observed_rate": round(float(pooled_y[m].mean()), 8) if n
            else 0.0,
        })
    return table


def evaluate() -> dict:
    for path in (DET, MANIFEST, ROOT / "data/boundaries/biak_desa.geojson"):
        if not Path(path).exists():
            raise SystemExit(f"missing input: {path}")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    bl = cfg["baseline"]
    det = pd.read_parquet(DET)
    runs = json.loads(MANIFEST.read_text(encoding="utf-8"))["runs"]

    first, last = det.date_wit.min(), det.date_wit.max()
    span = []
    cur = date.fromisoformat(first)
    end = date.fromisoformat(last)
    while cur <= end:
        span.append(cur.isoformat())
        cur += timedelta(days=1)

    groups = instrument_groups(bl["constellation"])
    observed, unobserved = observed_days(span, runs, groups)
    observed_set = set(observed)
    obs_by_year = {}
    for d in observed:
        obs_by_year[d[:4]] = obs_by_year.get(d[:4], 0) + 1

    grid = Grid(cfg["aoi_bbox_wsen"], bl["grid_m"])
    cells = land_cells(grid, ROOT / cfg["admin_polygon"])
    land_set = set(cells)
    det = assign_cells(det, grid)
    pair = list(zip(det.cell_i, det.cell_j))
    in_land = np.array([p in land_set for p in pair])
    det_land = det[in_land]
    n_outside_land = int((~in_land).sum())

    keys = set(bl["constellation"])
    kept, excl_counts, lost = constellation_split(
        det_land, keys, observed_set)

    years = sorted({d[:4] for d in observed})
    folds, pooled_p, pooled_y = {}, [], []
    for Y in years:
        train_days = [d for d in observed if d[:4] != Y]
        train_det = kept[~kept.date_wit.str.startswith(Y)]
        probs = climatology(train_det, train_days, cells,
                            int(bl["doy_half_window"]))
        cells_sorted = sorted(probs)
        P = np.stack([probs[c] for c in cells_sorted])
        test_days = [d for d in observed if d[:4] == Y]
        cols = [day_of_year_365(date.fromisoformat(d)) - 1
                for d in test_days]
        Pp = P[:, cols]
        y = np.zeros_like(Pp)
        fy = kept[kept.date_wit.isin(set(test_days))]
        fy_cd = set(zip(fy.date_wit, fy.cell_i, fy.cell_j))
        cell_row = {c: k for k, c in enumerate(cells_sorted)}
        for (dw, ci, cj) in fy_cd:
            if (ci, cj) in cell_row:
                y[cell_row[(ci, cj)], test_days.index(dw)] = 1.0
        n_pos = int(y.sum())
        tsub = train_det[train_det.date_wit.isin(set(train_days))]
        train_pos = len(set(zip(tsub.date_wit, tsub.cell_i, tsub.cell_j)))
        base = train_pos / (len(cells_sorted) * len(train_days))
        brier = float(np.mean((Pp - y) ** 2))
        brier_ref = float(np.mean((base - y) ** 2))
        bss = 1.0 - brier / brier_ref if brier_ref > 0 else None
        ap = average_precision(Pp.ravel(), y.ravel().astype(int))
        folds[Y] = {
            "observed_days": len(test_days),
            "n_cell_days": int(Pp.size),
            "n_positive": n_pos,
            "base_rate": round(base, 8),
            "brier": round(brier, 8),
            "brier_ref": round(brier_ref, 8),
            "brier_skill": round(bss, 8) if bss is not None else None,
            "average_precision": round(ap, 8) if ap is not None else None,
        }
        pooled_p.append(Pp.ravel())
        pooled_y.append(y.ravel())
        print(f"{Y}: {len(test_days)} observed days, {Pp.size} cell-days, "
              f"{n_pos} positive; Brier {brier:.6g} (reference "
              f"{brier_ref:.6g}, skill {bss:+.3f}), AP {ap:.4f}")

    edges = [float(v) for v in bl["reliability_bins"]]
    table = reliability(np.concatenate(pooled_p),
                        np.concatenate(pooled_y).astype(int), edges)

    return {
        "parameters": {
            "grid_m": bl["grid_m"],
            "doy_half_window": bl["doy_half_window"],
            "reliability_bins": bl["reliability_bins"],
            "constellation": bl["constellation"],
            "instrument_groups": {
                "S-NPP": groups[0], "NOAA-20": groups[1], "MODIS": groups[2]},
        },
        "store": {"first_date_wit": first, "last_date_wit": last,
                  "detections": int(len(det))},
        "grid": {"land_cells": len(cells), "cells_total": grid.nx * grid.ny,
                 "cell_deg": grid.d},
        "excluded": {
            "detections_outside_land_cells": int(n_outside_land),
            "outside_constellation_by_satellite": {k: int(v) for k, v in
                                                   sorted(excl_counts.items())},
            "positive_cell_days_lost": int(lost),
        },
        "observed_days": {"per_year": obs_by_year, "total": len(observed),
                          "unobserved": unobserved},
        "folds": folds,
        "reliability": table,
        "caveats": CAVEATS,
    }


def write_json(doc: dict, path: Path) -> None:
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def main() -> int:
    doc = evaluate()
    write_json(doc, OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
