"""Compare two S2DR4 multispectral rasters pixel by pixel over their overlap.

    python scripts/s2dr4_compare.py REFERENCE.tif CANDIDATE.tif [--json OUT]

Written to answer one question: does the credited REST API route reproduce the
imagery the 142 label boxes were judged on, which came from the free-tier wheel
run in notebooks/s2dr4_biak_colab.ipynb? If it does, the labels and every figure
resting on them are route-independent. If it does not, that is a caveat the
write-up has to carry, and this script says how large it is.

It assumes nothing about the band order. F19 found S2DR4 writes its ten bands as
B2 B3 B4 B8 B5 B6 B7 B11 B12 B8A - the 10 m bands first, then the 20 m ones -
and labels none of them, which is how F18 came to publish a near-infrared
composite it called SWIR. So each candidate band is correlated against every
reference band and the best match is reported. A permutation shows up as an
off-diagonal match rather than as a quiet change in the colours.

Nothing here reads a network or a credential. Give it two files that already
exist, or it exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

ROOT = Path(__file__).resolve().parents[1]
# Enough pixels for a stable correlation, few enough to stay quick on a
# 4100 x 4100 x 10 band tile. The stride is derived from the overlap, so the
# sample is spread over the whole of it rather than taken from one corner.
SAMPLE_TARGET = 400_000


def overlap(a: rasterio.DatasetReader, b: rasterio.DatasetReader):
    """The two rasters' common bounds, in the reference's CRS."""
    from rasterio.warp import transform_bounds
    bb = transform_bounds(b.crs, a.crs, *b.bounds)
    box = (max(a.bounds.left, bb[0]), max(a.bounds.bottom, bb[1]),
           min(a.bounds.right, bb[2]), min(a.bounds.top, bb[3]))
    if box[0] >= box[2] or box[1] >= box[3]:
        raise SystemExit("the two rasters do not overlap - nothing to compare")
    return box


def read_window(src: rasterio.DatasetReader, box, like=None):
    """The overlap as an array. `like` puts a differently gridded candidate onto
    the reference's own pixels, with nearest neighbour: resampling by averaging
    would invent values and flatter the agreement."""
    win = rasterio.windows.from_bounds(*box, transform=src.transform)
    if like is None:
        return src.read(window=win), src.window_transform(win)
    ref_arr, ref_tf = like
    out = np.zeros((src.count,) + ref_arr.shape[1:], dtype="float64")
    reproject(source=rasterio.band(src, list(range(1, src.count + 1))),
              destination=out, src_transform=src.transform, src_crs=src.crs,
              dst_transform=ref_tf, dst_crs=src.crs if src.crs else None,
              resampling=Resampling.nearest)
    return out, ref_tf


def subsample(arr: np.ndarray) -> np.ndarray:
    """Every nth pixel on a regular grid, flattened per band."""
    n_px = arr.shape[1] * arr.shape[2]
    stride = max(1, int(np.sqrt(n_px / SAMPLE_TARGET)))
    return arr[:, ::stride, ::stride].reshape(arr.shape[0], -1).astype("float64")


# How far the best match has to beat a band's own position before the band order
# is called different. S2DR4's four vegetation and near-infrared bands correlate
# with each other at about r=0.93 on this ground, so on two images of different
# dates the best match wanders between them by a hundredth or two. Without this
# margin the script reported a permutation for 23 against 28 August, where the
# only real difference was five days of burning.
ORDER_MARGIN = 0.02


def best_matches(ref: np.ndarray, cand: np.ndarray) -> list[dict]:
    """For each candidate band, the reference band it correlates with best, and
    how far that beats the band's own position.

    A permutation is only claimed when the margin is decisive, and the test is
    only meaningful when both rasters cover the same scene on the same date.
    """
    def z(x):
        sd = x.std(axis=1, keepdims=True)
        return (x - x.mean(axis=1, keepdims=True)) / np.where(sd == 0, 1, sd)

    corr = z(cand) @ z(ref).T / ref.shape[1]
    out = []
    for i in range(cand.shape[0]):
        best = int(np.argmax(corr[i]))
        self_r = float(corr[i, i]) if i < ref.shape[0] else float("nan")
        margin = float(corr[i, best]) - self_r
        out.append({"candidate_band": i + 1,
                    "best_reference_band": best + 1,
                    "r": round(float(corr[i, best]), 4),
                    "same_band_r": round(self_r, 4),
                    "margin_over_same_band": round(margin, 4),
                    "decisive": bool(best != i and margin > ORDER_MARGIN)})
    return out


def per_band(ref: np.ndarray, cand: np.ndarray) -> list[dict]:
    rows = []
    for i in range(min(ref.shape[0], cand.shape[0])):
        d = cand[i] - ref[i]
        lo, hi = np.percentile(ref[i], [2, 98])
        span = max(hi - lo, 1e-9)
        rows.append({
            "band": i + 1,
            "reference_median": round(float(np.median(ref[i])), 1),
            "candidate_median": round(float(np.median(cand[i])), 1),
            "median_difference": round(float(np.median(d)), 1),
            "rmse": round(float(np.sqrt((d ** 2).mean())), 1),
            "rmse_pct_of_p2_p98_span": round(float(100 * np.sqrt((d ** 2).mean()) / span), 2),
            "identical_pixels_pct": round(float(100 * (d == 0).mean()), 2),
        })
    return rows


def geometry(src: rasterio.DatasetReader) -> dict:
    return {"crs": str(src.crs), "pixel_m": round(abs(src.transform.a), 4),
            "size_px": [src.width, src.height], "bands": src.count,
            "dtype": src.dtypes[0],
            "bounds": [round(float(v), 2) for v in src.bounds],
            "area_km2": round(src.width * abs(src.transform.a) / 1000
                              * src.height * abs(src.transform.e) / 1000, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reference", type=Path, help="the wheel's MS GeoTIFF")
    ap.add_argument("candidate", type=Path, help="the API's MS GeoTIFF")
    ap.add_argument("--json", type=Path, default=None, help="write the report here too")
    args = ap.parse_args()
    for path in (args.reference, args.candidate):
        if not path.exists():
            raise SystemExit(f"missing {path}")

    with rasterio.open(args.reference) as a, rasterio.open(args.candidate) as b:
        report = {"reference": {"path": str(args.reference), **geometry(a)},
                  "candidate": {"path": str(args.candidate), **geometry(b)}}
        box = overlap(a, b)
        report["overlap_km2"] = round((box[2] - box[0]) * (box[3] - box[1]) / 1e6, 3)
        ref_arr, ref_tf = read_window(a, box)
        aligned = (a.crs == b.crs and abs(a.transform.a - b.transform.a) < 1e-6)
        report["same_grid"] = bool(aligned)
        cand_arr, _ = read_window(b, box) if aligned else read_window(b, box, (ref_arr, ref_tf))

    if ref_arr.shape[1:] != cand_arr.shape[1:]:
        n = (min(ref_arr.shape[1], cand_arr.shape[1]),
             min(ref_arr.shape[2], cand_arr.shape[2]))
        ref_arr, cand_arr = ref_arr[:, :n[0], :n[1]], cand_arr[:, :n[0], :n[1]]

    ref_s, cand_s = subsample(ref_arr), subsample(cand_arr)
    report["pixels_compared"] = int(ref_s.shape[1])
    report["band_order"] = best_matches(ref_s, cand_s)
    report["bands"] = per_band(ref_s, cand_s)
    permuted = [m for m in report["band_order"] if m["decisive"]]
    wobble = [m for m in report["band_order"]
              if not m["decisive"] and m["candidate_band"] != m["best_reference_band"]]
    report["band_order_matches"] = not permuted

    print(f"overlap {report['overlap_km2']} km2, {report['pixels_compared']} pixels sampled, "
          f"{'same grid' if report['same_grid'] else 'candidate resampled onto the reference grid'}")
    print(f"reference {report['reference']['bands']} bands {report['reference']['dtype']} "
          f"{report['reference']['pixel_m']} m {report['reference']['crs']}")
    print(f"candidate {report['candidate']['bands']} bands {report['candidate']['dtype']} "
          f"{report['candidate']['pixel_m']} m {report['candidate']['crs']}")
    print("\nband  ref median  cand median   median d     rmse   rmse %span  identical %")
    for r in report["bands"]:
        print(f"{r['band']:4d}  {r['reference_median']:10.1f}  {r['candidate_median']:11.1f}"
              f"  {r['median_difference']:9.1f}  {r['rmse']:7.1f}  {r['rmse_pct_of_p2_p98_span']:10.2f}"
              f"  {r['identical_pixels_pct']:11.2f}")

    if permuted:
        print("\nTHE BAND ORDER DIFFERS between the two files:")
        for m in permuted:
            print(f"  candidate band {m['candidate_band']} matches reference band "
                  f"{m['best_reference_band']} at r={m['r']}, against r={m['same_band_r']} "
                  f"for its own position")
        print("  A composite built on one file's order is wrong on the other. See F19.")
    else:
        print("\nband order: no decisive permutation, each band matching its own position")
    if wobble:
        print("  (undecided, inside the %.2f margin: %s. Expected when the two files are "
              "of different dates, since the vegetation and near-infrared bands correlate "
              "with each other)"
              % (ORDER_MARGIN, ", ".join(f"band {m['candidate_band']}~{m['best_reference_band']}"
                                         for m in wobble)))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
        print("written", args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
