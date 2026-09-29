"""Figure for the SAM pilot: what each prompt type actually returned, next to
the trivial "the whole footprint burned" claim.

Four panels per event:
  1. the S2DR4 1 m SWIR composite (B12/B8A/B4) - what a reader sees;
  2. the Task 18 dNBR+ polygons - the delineation being tested against;
  3. the SAM point-prompt mask - measured to cover 100% of the footprint, so it
     is drawn as the footprint itself where the mask raster was not kept;
  4. a bar chart: box-prompt IoU and point-prompt IoU against the IoU of
     claiming the entire footprint burned.

The bar chart is the argument. A point-prompt IoU that equals the trivial claim
carries no information from the model; a box-prompt IoU below it is worse than
saying nothing at all.

    python scripts/sam_pilot_figure.py <out.png>

Reads data/processed/sam_pilot.json (written by scripts/sam_pilot_collect.py) and
the S2DR4 tiles under data/raw/, which are gitignored: the figure can only be
rebuilt on a machine that holds the 1 m imagery.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from rasterio.features import rasterize
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(r"C:\Users\User\Documents\Biak_hotspot")
sys.path.insert(0, str(ROOT / "src"))
import events as ev, burned_area_gee as ba

TILES = ROOT / "data/raw/s2dr4_biak_2026-08-28/output/ID/T53MPU"
PILOT = ROOT / "data/processed/sam_pilot.json"
TILE = {"E0301": "T53MPU-4e09bbfee", "E0313": "T53MPU-0c59f172e", "E0368": "T53MPU-c501689c0"}
DESA = {"E0301": "Anjareuw", "E0313": "Yendidori", "E0368": "Insumarires"}
SIZE = 2048                      # metres, at 1 m per pixel
to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32753", always_xy=True).transform


def stretch(band):
    lo, hi = np.percentile(band, [2, 98])
    return np.clip((band - lo) / max(hi - lo, 1e-6), 0, 1)


def event_data(eid, mem, store, polys):
    ids = [d for d, e in mem.items() if e == eid]
    pts = store[store.detection_id.isin(ids)][["latitude", "longitude"]]
    xs, ys = zip(*[to_utm(lon, lat) for lat, lon in pts.values])
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    tile = TILE[eid]
    with rasterio.open(TILES / tile / f"S2L3Ax10_{tile}-20260828_MS.tif") as r:
        row, col = r.index(cx, cy)
        win = Window(col - SIZE // 2, row - SIZE // 2, SIZE, SIZE)
        swir = r.read(indexes=[10, 8, 3], window=win).astype("float32")   # B12, B8A, B4
        transform = r.window_transform(win)
    rgb = np.dstack([stretch(b) for b in swir])

    def burn(geom):
        return rasterize([(mapping(geom), 1)], out_shape=(SIZE, SIZE), transform=transform,
                         fill=0, dtype="uint8").astype(bool)

    fp = burn(shp_transform(to_utm, ba.footprint(pts.latitude.tolist(),
                                                 pts.longitude.tolist(), 375.0)[0]))
    ref = np.zeros((SIZE, SIZE), bool)
    for f in polys:
        if f["properties"]["event_id"] == eid:
            ref |= burn(shp_transform(to_utm, shape(f["geometry"])))
    return rgb, fp, ref, len(pts)


def tint(rgb, mask, colour, alpha=0.55):
    out = rgb.copy()
    out[mask] = (1 - alpha) * out[mask] + alpha * np.array(colour)
    return out


def main(out_png):
    doc = json.loads((ROOT / "data/processed/events.json").read_text())
    mem = ev.membership(doc)
    store = pd.read_parquet(ROOT / "data/processed/detections.parquet")
    polys = json.loads((ROOT / "data/processed/burned_areas.geojson").read_text())["features"]
    pilot = json.loads(PILOT.read_text(encoding="utf-8"))
    points = pilot["runs"]["points"]["result"]
    boxes = pilot["runs"]["boxes"]["result"]

    fig, axes = plt.subplots(len(TILE), 4, figsize=(21, 5.4 * len(TILE)))
    for row, eid in enumerate(TILE):
        rgb, fp, ref, n_det = event_data(eid, mem, store, polys)
        ha = 1e-4                                    # one 1 m pixel in hectares
        fp_ha, ref_ha = fp.sum() * ha, ref.sum() * ha
        trivial = ref_ha / fp_ha                     # IoU of "the whole footprint burned"

        pt = points.get(f"{eid}|swir|points", {})
        best_box_key, best_box = max(
            ((k, v) for k, v in boxes.items() if k.startswith(eid) and "error" not in v),
            key=lambda kv: kv[1].get("iou") or 0, default=(None, {}))

        ax = axes[row]
        ax[0].imshow(rgb)
        ax[0].set_title(f"{eid} — {DESA[eid]}\nS2DR4 1 m, SWIR (B12/B8A/B4), 28 Aug 2026")

        ax[1].imshow(tint(rgb, ref, (0.15, 0.25, 1.0)))
        ax[1].set_title(f"dNBR+ change, Task 18\n{ref_ha:.0f} ha inside a {fp_ha:.0f} ha footprint")

        ax[2].imshow(tint(rgb, fp, (1.0, 0.15, 0.15)))
        ax[2].set_title("SAM 3, point prompts at the detections\n"
                        f"mask = {pt.get('sam_ha_in_footprint', float('nan')):.0f} ha "
                        f"of the {fp_ha:.0f} ha footprint — all of it")

        bars = ax[3]
        names = ["whole footprint\n(claims everything)", "SAM point\nprompts", "SAM box\nprompts"]
        vals = [trivial, pt.get("iou") or 0, best_box.get("iou") or 0]
        colours = ["#9aa0a6", "#d93025", "#1a73e8"]
        bars.bar(names, vals, color=colours)
        bars.axhline(trivial, color="#9aa0a6", ls="--", lw=1)
        for i, v in enumerate(vals):
            bars.text(i, v + 0.015, f"{v:.3f}", ha="center", fontsize=11)
        bars.set_ylim(0, max(0.85, max(vals) + 0.12))
        bars.set_ylabel("IoU against dNBR+")
        note = ("point prompts match the trivial claim exactly"
                if abs((pt.get("iou") or 0) - trivial) < 0.005 else "point prompts differ")
        bars.set_title(f"{n_det} detections · {note}\n"
                       f"best box: {best_box_key.split('|', 1)[1] if best_box_key else 'none'}")
        for a in ax[:3]:
            a.axis("off")

    fig.legend(handles=[Patch(color="#2640ff", label="dNBR+ change (Task 18)"),
                        Patch(color="#ff2626", label="SAM point-prompt mask = whole footprint")],
               loc="lower center", ncol=2, frameon=False, fontsize=12)
    fig.suptitle("SAM 3 on 1 m imagery cannot delineate burn scars: every prompt type fails, "
                 "each in its own way", fontsize=15, y=0.995)
    fig.tight_layout(rect=(0, 0.02, 1, 0.985))
    fig.savefig(out_png, dpi=110)
    print("written", out_png)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sam_pilot_figure.png")
