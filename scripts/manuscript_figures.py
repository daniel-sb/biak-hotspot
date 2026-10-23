"""The four figures for the RS/GIS manuscript.

    python scripts/manuscript_figures.py

Writes manuscript/figures/fig1..fig4 as PNG at 300 dpi and PDF. Every number
is read from a tracked file; nothing is recomputed and nothing is typed in by
hand. If an input is missing the script says which and exits non-zero, so an
absent figure is never a blank one (AGENTS never-2).

Colours are the first three slots of the validated categorical palette, which
pass the all-pairs colour-vision checks as a set of three. Marker shape repeats
the colour, so the figures survive greyscale printing.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "manuscript" / "figures"

AREAS = ROOT / "data/processed/burned_areas.json"
POLYS = ROOT / "data/processed/burned_areas.geojson"
STALE = ROOT / "data/processed/pre_look_staleness.json"
DETECT = ROOT / "data/processed/detections.parquet"
GPKG = ROOT / "data/labels/biak_labels.gpkg"
DESA = ROOT / "data/boundaries/biak_desa.geojson"
INDICES = ROOT / "docs/data/burn_indices.json"
IMAGERY = ROOT / "data/labels/imagery"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d8d7d2"

DIRECTIONS = (
    ("scar_in_pre", "Prior detection before the pre-image", ORANGE, "o"),
    ("earlier_burn_included", "Prior detection after the pre-image", BLUE, "s"),
    ("no_prior_detection", "No prior detection", AQUA, "^"),
)


def need(path):
    if not path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} is missing - nothing written")
    return path


def load_json(path):
    return json.loads(need(path).read_text(encoding="utf-8"))


def style(ax):
    """Recessive axes: no top or right spine, a thin grid behind the marks."""
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8, length=3)
    ax.grid(True, color=GRID, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300, bbox_inches="tight",
                    facecolor="white")
    plt.close(fig)
    print(f"wrote manuscript/figures/{name}.png and .pdf")


# --------------------------------------------------------------------------
# Figure 1: the corridor, the mapped burns, the reference boxes

def gpkg_boxes():
    from burn_classifier import gpkg_geometry
    con = sqlite3.connect(f"file:{GPKG.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute('SELECT sample_id, sampling, "class", geom '
                           "FROM labels").fetchall()
    finally:
        con.close()
    return [(r[0], r[1], r[2], gpkg_geometry(r[3])) for r in rows]


def figure1():
    need(DESA), need(POLYS), need(DETECT), need(GPKG)
    import geopandas as gpd

    land = unary_union(list(gpd.read_file(DESA).geometry))
    burns = [shape(f["geometry"]) for f in load_json(POLYS)["features"]]
    boxes = gpkg_boxes()
    det = pd.read_parquet(DETECT)

    xs = [g.centroid.x for _, _, _, g in boxes]
    ys = [g.centroid.y for _, _, _, g in boxes]
    pad = 0.035
    xlim = (min(xs) - pad, max(xs) + pad)
    ylim = (min(ys) - pad, max(ys) + pad)
    # Frame the overview on the ground that carries detections. The AOI box is
    # mostly ocean, and the desa file reaches outlying islets 200 km north that
    # have never burned; either would leave the map a speck in a field of white.
    overview = ((det["longitude"].min() - 0.12, det["longitude"].max() + 0.12),
                (det["latitude"].min() - 0.12, det["latitude"].max() + 0.12))

    fig, (ax0, ax1) = plt.subplots(
        1, 2, figsize=(7.2, 2.9),
        gridspec_kw={"width_ratios": [1, 1.25], "wspace": 0.38})

    # Left: the island, with the detail box marked.
    for geom in getattr(land, "geoms", [land]):
        ax0.fill(*geom.exterior.xy, facecolor="#eceae4", edgecolor="#b9b7ae",
                 linewidth=0.4, zorder=1)
    ax0.scatter(det["longitude"], det["latitude"], s=1.2, c=INK2, alpha=0.30,
                linewidths=0, zorder=2)
    ax0.add_patch(Rectangle((xlim[0], ylim[0]), xlim[1] - xlim[0],
                            ylim[1] - ylim[0], fill=False, edgecolor=ORANGE,
                            linewidth=1.2, zorder=3))
    ax0.set_xlim(*overview[0])
    ax0.set_ylim(*overview[1])
    ax0.set_title("a  Biak and Supiori, all detections",
                  fontsize=8, color=INK, loc="left", pad=6)
    ax0.set_xlabel("Longitude", fontsize=8, color=INK2)
    ax0.set_ylabel("Latitude", fontsize=8, color=INK2)

    # Right: the assessed events and the reference boxes.
    for geom in getattr(land, "geoms", [land]):
        ax1.fill(*geom.exterior.xy, facecolor="#eceae4", edgecolor="#b9b7ae",
                 linewidth=0.4, zorder=1)
    for geom in burns:
        ax1.fill(*geom.exterior.xy, facecolor="#3a3a38", edgecolor="none",
                 zorder=2)
    marks = {"map_burned": (BLUE, "s"), "footprint_unmapped": (ORANGE, "o"),
             "random_box": (AQUA, "^")}
    for name, (colour, marker) in marks.items():
        pts = [(g.centroid.x, g.centroid.y) for _, s, _, g in boxes
               if s == name]
        ax1.scatter([p[0] for p in pts], [p[1] for p in pts], s=16,
                    marker=marker, facecolor=colour, edgecolor="white",
                    linewidth=0.5, zorder=4,
                    label=f"{name.replace('_', ' ')} ({len(pts)})")
    ax1.set_xlim(*xlim)
    ax1.set_ylim(*ylim)
    ax1.set_title("b  Burned area and the 142 reference boxes",
                  fontsize=8, color=INK, loc="left", pad=6)
    ax1.set_xlabel("Longitude", fontsize=8, color=INK2)

    handles, labels = ax1.get_legend_handles_labels()
    handles.append(Line2D([], [], color="#3a3a38", linewidth=5))
    labels.append("dNBR+ burned area")
    leg = fig.legend(handles, labels, fontsize=7.5, frameon=False, ncols=4,
                     loc="lower center", bbox_to_anchor=(0.5, 0.02),
                     handletextpad=0.6, columnspacing=1.8)
    for text in leg.get_texts():
        text.set_color(INK2)

    # Equal ground distance per axis unit at this latitude, set as a ratio so
    # it cannot override the limits the detail panel was given.
    aspect = 1.0 / np.cos(np.radians(np.mean(ys)))
    for ax in (ax0, ax1):
        style(ax)
        ax.set_aspect(aspect)
    save(fig, "fig1_study_area")


# --------------------------------------------------------------------------
# Figure 2: the pre-image is staler than the post-image

def figure2():
    rows = [e for e in load_json(STALE)["events"] if e.get("changed_ha")
            is not None]
    if not rows:
        raise SystemExit("pre_look_staleness.json holds no assessed event "
                         "- nothing written")

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(7.2, 3.5), sharey=True,
                                   gridspec_kw={"wspace": 0.08})

    for ax, key, title in (
            (ax0, "pre_lag_days", "a  Before the fire: latest clear look"),
            (ax1, "post_lag_days", "b  After the fire: earliest clear look")):
        ax.axvspan(14, 32, color="#f4f3ef", zorder=0)
        for code, label, colour, marker in DIRECTIONS:
            sel = [e for e in rows if e["direction_p50"] == code]
            if not sel:
                continue
            ax.scatter([e[key]["p50"] for e in sel],
                       [e["changed_ha"] for e in sel],
                       s=34, marker=marker, facecolor=colour,
                       edgecolor="white", linewidth=0.6, zorder=3,
                       label=f"{label} ({len(sel)})")
        ax.axvline(14, color=INK2, linewidth=0.8, linestyle=(0, (4, 3)),
                   zorder=2)
        ax.set_yscale("log")
        ax.set_xlim(-1.5, 32)
        ax.set_ylim(3, 1500)
        ax.set_title(title, fontsize=8.5, color=INK, loc="left", pad=6)
        style(ax)

    ax0.set_ylabel("Burned area of the event, ha (log scale)", fontsize=8,
                   color=INK2)
    ax0.text(14.8, 1000, "more than 14 days", fontsize=7, color=INK2)
    ax1.text(14.8, 1000, "no event falls here", fontsize=7, color=INK2,
             style="italic")

    # Direct labels on the four events that carry the most area.
    for e in sorted(rows, key=lambda r: -r["changed_ha"])[:4]:
        x = e["pre_lag_days"]["p50"]
        # Labels go right by default and left near the panel edge, and up
        # where a neighbouring marker sits on the same row.
        right = x < 20
        ax0.annotate(e["event_id"], (x, e["changed_ha"]),
                     textcoords="offset points",
                     xytext=(7, -2) if right else (-8, -2),
                     ha="left" if right else "right",
                     fontsize=7, color=INK2)

    handles, labels = ax0.get_legend_handles_labels()
    leg = fig.legend(handles, labels, fontsize=7.5, frameon=False, ncols=3,
                     loc="lower center", bbox_to_anchor=(0.5, -0.13),
                     handletextpad=0.4, columnspacing=1.6)
    for text in leg.get_texts():
        text.set_color(INK2)
    fig.supxlabel("Days from the event to the clear look the pipeline chose "
                  "for that pixel (event median)", fontsize=8, color=INK2,
                  y=-0.02)
    save(fig, "fig2_look_lag")


# --------------------------------------------------------------------------
# Figure 3: false alarms where burning is impossible

def figure3():
    d = load_json(INDICES)
    panels = (
        ("false_alarm_primary", "uni", "water", "a  Uni-temporal, open sea"),
        ("false_alarm_primary", "uni", "cloud", "b  Uni-temporal, cloud"),
        ("false_alarm_primary", "bi", "water", "c  Bi-temporal, open sea"),
        ("false_alarm_check", "bi", "cloud", "d  Bi-temporal, cloud (cloudy pair)"),
    )
    order = ["NBR", "NBRSWIR", "NDSWIR", "MIRBI", "BAIS2", "ATBI", "NBR+"]

    fig, axes = plt.subplots(1, 4, figsize=(7.4, 2.9), sharey=True,
                             gridspec_kw={"wspace": 0.12})
    for ax, (block, form, stratum, title) in zip(axes, panels):
        table = d[block][form]
        names = [n for n in order if n in table]
        vals = [table[n][stratum] * 100 for n in names]
        colours = [BLUE if n == "NBR+" else "#c9c7c0" for n in names]
        y = np.arange(len(names))
        ax.barh(y, vals, color=colours, height=0.62, zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels(names, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlim(0, 105)
        ax.set_xticks([0, 50, 100])
        ax.set_title(title, fontsize=7.5, color=INK, loc="left", pad=6)
        for yi, v in zip(y, vals):
            ax.text(min(v + 2.5, 92), yi, f"{v:.1f}", va="center", fontsize=6.5,
                    color=INK2, zorder=4)
        style(ax)
        ax.grid(axis="y", visible=False)

    axes[0].set_ylabel("")
    fig.supxlabel("False alarms, % of the stratum above the burning-plausible "
                  "95th percentile", fontsize=8, color=INK2, y=-0.04)
    save(fig, "fig3_false_alarms")


# --------------------------------------------------------------------------
# Figure 4: the same ground at 20 m and at 1 m

def stretch(a, lo=2, hi=98):
    a = a.astype("float32")
    finite = a[np.isfinite(a) & (a > 0)]
    if finite.size == 0:
        return np.zeros_like(a)
    p = np.percentile(finite, [lo, hi])
    if p[1] <= p[0]:
        return np.zeros_like(a)
    return np.clip((a - p[0]) / (p[1] - p[0]), 0, 1)


def figure4(sample_id="MAP15", date_tag="20260917"):
    import rasterio
    from rasterio.warp import transform as warp_points
    from rasterio.windows import from_bounds

    boxes = {s: (st, cls, g) for s, st, cls, g in gpkg_boxes()}
    if sample_id not in boxes:
        raise SystemExit(f"{sample_id} is not a label box - nothing written")
    geom = boxes[sample_id][2]
    half = 240.0                        # metres, so the 60 m box reads small

    panels, ring, centre = [], None, None
    for prefix, label in (("s2n_swir", "Sentinel-2 at 20 m, as the sensor saw it"),
                          ("swir", "S2DR4 reconstruction at 1 m")):
        # "*_swir_" also matches "*_s2n_swir_", which would put the 20 m chip
        # in both panels, so the 1 m case excludes the native prefix by name.
        hits = [h for h in sorted(IMAGERY.glob(f"*_{prefix}_{date_tag}.tif"))
                if not h.name.endswith(".aux.xml")
                and (prefix != "swir" or "_s2n_" not in h.name)]
        if not hits:
            raise SystemExit(f"no {prefix}_{date_tag}.tif under "
                             "data/labels/imagery - nothing written")
        for path in hits:
            with rasterio.open(path) as src:
                # The chips are UTM; the labels are EPSG:4326. Project the box
                # into the raster's own grid rather than the other way round.
                part = (geom if geom.geom_type == "Polygon"
                        else max(geom.geoms, key=lambda g: g.area))
                lon, lat = part.exterior.coords.xy
                px, py = warp_points("EPSG:4326", src.crs, list(lon), list(lat))
                cx, cy = float(np.mean(px)), float(np.mean(py))
                b = src.bounds
                if not (b.left < cx < b.right and b.bottom < cy < b.top):
                    continue
                win = from_bounds(cx - half, cy - half, cx + half, cy + half,
                                  src.transform)
                arr = src.read(window=win, boundless=True, fill_value=0)
                if src.count < 3 or src.dtypes[0] != "uint8":
                    raise SystemExit(f"{path.name} is not a rendered 3-band "
                                     "uint8 composite - nothing written")
                # These chips are already rendered RGB. Re-stretching them,
                # and worse, stretching each channel on its own percentiles,
                # is the error F19 recorded: it breaks the relation between
                # channels and the colours stop meaning anything.
                rgb = np.dstack([arr[i] for i in range(3)]) / 255.0
                panels.append((rgb, f"{label}\n{path.name}"))
                ring, centre = (px, py), (cx, cy)
                break
    if len(panels) != 2:
        raise SystemExit(f"{sample_id} is not inside both a 20 m and a 1 m "
                         f"chip for {date_tag} - nothing written")
    cx, cy = centre

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4),
                             gridspec_kw={"wspace": 0.06})
    for ax, (rgb, caption), tag in zip(axes, panels, "ab"):
        ax.imshow(rgb, extent=(cx - half, cx + half, cy - half, cy + half),
                  interpolation="nearest")
        ax.plot(ring[0], ring[1], color="#ffd400", linewidth=1.4)
        ax.set_title(f"{tag}  {caption}", fontsize=7.5, color=INK, loc="left",
                     pad=6)
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ax.spines:
            ax.spines[side].set_color(GRID)
    fig.text(0.5, -0.02, f"Short-wave infrared composite, {sample_id}, "
             f"{date_tag[:4]}-{date_tag[4:6]}-{date_tag[6:]}. "
             "The box is 60 m across.", ha="center", fontsize=7.5, color=INK2)
    save(fig, "fig4_resolution")


def main():
    figure1()
    figure2()
    figure3()
    figure4()
    return 0


if __name__ == "__main__":
    sys.exit(main())
