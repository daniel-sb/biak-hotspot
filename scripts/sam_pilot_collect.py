"""Collect the SAM pilot runs into one tracked file.

    python scripts/sam_pilot_collect.py

Reads the Colab result folders under data/raw/ (gitignored, and large) and writes
data/processed/sam_pilot.json, which is small, tracked, and enough to rebuild the
figure and the finding without the imagery.

Every score is compared against one bar: the IoU of claiming that the whole VIIRS
footprint burned. A prompt that ties it carries no information from the model, and
one below it is worse than saying nothing. The footprint areas come from the same
375 m circles Task 18 uses, measured on the 1 m grid.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import events as ev  # noqa: E402
import burned_area_gee as ba  # noqa: E402

RAW = ROOT / "data/raw"
TILES = RAW / "s2dr4_biak_2026-08-28/output/ID/T53MPU"
TILE = {"E0301": "T53MPU-4e09bbfee", "E0313": "T53MPU-0c59f172e", "E0368": "T53MPU-c501689c0"}
DESA = {"E0301": "Anjareuw", "E0313": "Yendidori", "E0368": "Insumarires"}
RUNS = {"words": "sam3_word_counts.json", "points": "sam3_point_scores.json",
        "boxes": "sam3_box_scores.json", "langsam": "sam3_lang_scores.json"}
SIZE = 2048               # the crop the Colab runs used, in metres at 1 m
TOL = 0.01                # IoU margin below which a result ties the trivial claim
OUT = ROOT / "data/processed/sam_pilot.json"
UTM = "EPSG:32753"
to_utm = Transformer.from_crs("EPSG:4326", UTM, always_xy=True).transform


def latest(name: str) -> Path | None:
    """The newest copy of a result file across the downloaded result folders."""
    hits = sorted(RAW.glob(f"sam3_results*/{name}"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def reference() -> dict:
    """Footprint and dNBR+ areas per event, measured on the 1 m crop the runs used."""
    doc = json.loads((ROOT / "data/processed/events.json").read_text(encoding="utf-8"))
    mem = ev.membership(doc)
    store = pd.read_parquet(ROOT / "data/processed/detections.parquet")
    polys = json.loads((ROOT / "data/processed/burned_areas.geojson")
                       .read_text(encoding="utf-8"))["features"]
    out = {}
    for eid, tile in TILE.items():
        ids = [d for d, e in mem.items() if e == eid]
        pts = store[store.detection_id.isin(ids)]
        xs, ys = zip(*[to_utm(lon, lat) for lon, lat in
                       zip(pts.longitude, pts.latitude)])
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        with rasterio.open(TILES / tile / f"S2L3Ax10_{tile}-20260828_MS.tif") as r:
            row, col = r.index(cx, cy)
            transform = r.window_transform(Window(col - SIZE // 2, row - SIZE // 2,
                                                  SIZE, SIZE))

        def paint(geom):
            return rasterize([(mapping(geom), 1)], out_shape=(SIZE, SIZE),
                             transform=transform, fill=0, dtype="uint8").astype(bool)

        fp = paint(shp_transform(to_utm, ba.footprint(pts.latitude.tolist(),
                                                      pts.longitude.tolist(), 375.0)[0]))
        ref = np.zeros((SIZE, SIZE), bool)
        for f in polys:
            if f["properties"]["event_id"] == eid:
                ref |= paint(shp_transform(to_utm, shape(f["geometry"])))
        ha = 1e-4
        fp_ha, ref_ha = fp.sum() * ha, ref.sum() * ha
        out[eid] = {"desa": DESA[eid], "n_detections": int(len(pts)),
                    "footprint_ha_in_crop": round(fp_ha, 1),
                    "dnbr_ha_in_crop": round(ref_ha, 1),
                    "trivial_iou": round(ref_ha / fp_ha, 3)}
    return out


def main() -> int:
    runs, missing = {}, []
    for key, name in RUNS.items():
        path = latest(name)
        if path is None:
            missing.append(name)
            continue
        runs[key] = {"source": str(path.relative_to(ROOT)).replace("\\", "/"),
                     "result": json.loads(path.read_text(encoding="utf-8"))}
    if missing:
        raise SystemExit("missing result files: " + ", ".join(missing))

    ref = reference()
    best = {}
    for eid, r in ref.items():
        for key in ("points", "boxes", "langsam"):
            scored = [(k, v.get("iou")) for k, v in runs[key]["result"].items()
                      if k.startswith(eid) and isinstance(v, dict) and v.get("iou") is not None]
            if not scored:
                continue
            k, iou = max(scored, key=lambda kv: kv[1])
            # TOLERANCE: rasterising polygons on a 1 m grid moves IoU by a thousandth
            # or two, so a margin that small is noise, not a win.
            margin = iou - r["trivial_iou"]
            verdict = ("above_trivial" if margin > TOL else
                       "below_trivial" if margin < -TOL else "ties_trivial")
            best[f"{eid}|{key}"] = {"best_run": k, "iou": round(iou, 3),
                                    "trivial_iou": r["trivial_iou"],
                                    "margin": round(margin, 3), "verdict": verdict}

    doc = {
        "what": ("SAM 2.1, SAM 3 and LangSAM asked to delineate burn scars, scored "
                 "against the Task 18 dNBR+ polygons inside each event's VIIRS footprint."),
        "imagery": {"source": "Gamma Earth S2DR4, Sentinel-2 super-resolved to 1 m",
                    "date": "2026-08-28", "crop_m": SIZE,
                    "note": ("1 m detail is model output, not observation; it is used for "
                             "delineation only, and no area figure rests on it")},
        "events": ref,
        "best_per_prompt_type": best,
        "runs": runs,
        "caveats": [
            ("The trivial claim that the whole footprint burned scores IoU = dNBR+ area / "
             "footprint area. A prompt that matches it exactly carries no information."),
            (f"A result within {TOL} IoU of that claim is recorded as a tie: rasterising the "
             "polygons on a 1 m grid moves the number by about that much."),
            ("Point and box prompts need SAM 3's Meta backend, which needs triton; there is "
             "no Windows build, so those runs were made on Colab."),
            ("Agreement or disagreement here is with dNBR+, not with the ground. Neither is "
             "a field measurement."),
        ],
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")

    print(f"{'event':6s} {'detections':>10s} {'footprint':>10s} {'dNBR+':>8s} {'trivial':>8s}")
    for eid, r in ref.items():
        print(f"{eid:6s} {r['n_detections']:10d} {r['footprint_ha_in_crop']:9.1f}h "
              f"{r['dnbr_ha_in_crop']:7.1f}h {r['trivial_iou']:8.3f}")
    print()
    for k, v in sorted(best.items()):
        print(f"{k:18s} best {v['iou']:.3f} vs trivial {v['trivial_iou']:.3f} "
              f"({v['margin']:+.3f}) -> {v['verdict']:14s} ({v['best_run']})")
    print("\nwritten", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
