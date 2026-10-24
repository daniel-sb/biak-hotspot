"""Compose one cartographic plate per labelled burn footprint.

    "$CONDA/envs/geolibre/python.exe" scripts/burn_atlas.py
    "$CONDA/envs/geolibre/python.exe" scripts/burn_atlas.py --check

Outputs, overwritten on every run:

    docs/gallery/<event>.webp     one plate per event
    docs/gallery/<event>.geolibre.json
    docs/data/gallery.json        the index the gallery page reads

WHY THESE ARE RENDERED HERE AND NOT IN LAYOUT COMPOSER

The brief asked for the plates to be laid out with Layout Composer
(github.com/Defani/Layout-Composer). That tool is a plugin for the GeoLibre
desktop app: a ribbon editor driven by hand, with no command line and no
headless mode, so no script can call it. What a script can do is produce the
same anatomy - one map frame, a locator inset, a date series, a scale bar, a
north arrow, a legend and a title block - from the data itself, so the plate
is reproducible and every number on it traces to a file in this repository.

So that the hand-finished route stays open, each plate is written alongside a
GeoLibre project (<event>.geolibre.json) holding the same layers at the same
extent. Open one in GeoLibre, enable Layout Composer, and the frame is already
set up for a print layout.

Projected in UTM zone 53S, the CRS the scenes are stored in, so the scale bar
is a true distance rather than a count of degrees.
"""

from __future__ import annotations

import argparse
import csv
import json
import textwrap
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.patches import Rectangle
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

ROOT = Path(__file__).resolve().parents[1]
IMAGERY = ROOT / "data" / "labels" / "imagery"
DOCS = ROOT / "docs"
GALLERY = DOCS / "gallery"
PROCESSED = ROOT / "data" / "processed"

UTM = "EPSG:32753"
WGS = "EPSG:4326"
TO_UTM = Transformer.from_crs(WGS, UTM, always_xy=True).transform
TO_WGS = Transformer.from_crs(UTM, WGS, always_xy=True).transform

# Biak island proper, the frame the locator inset draws.
ISLAND = (135.70, -1.34, 136.42, -0.69)

EVENTS = {
    "E0301": "Anjareuw",
    "E0313": "Yendidori",
    "E0368": "Insumarires",
}

INK = "#17201f"
SOFT = "#5c6460"
RULE = "#d5cfc3"
PAPER = "#f7f5f0"
KARST = "#ede9e1"
CANOPY = "#2f5d53"
SCAR = "#a3341f"
EMBER = "#c96a2e"
SEA = "#7fa9b8"

DPI = 150
FIGSIZE = (14.0, 11.6)         # 2100 x 1740 px


# ------------------------------------------------------------------ data ----

def load_geojson(path, event):
    feats = json.loads(Path(path).read_text(encoding="utf-8"))["features"]
    out = []
    for f in feats:
        if event is not None and f["properties"].get("event_id") != event:
            continue
        out.append((shp_transform(TO_UTM, shape(f["geometry"])),
                    f["properties"]))
    return out


def event_rows():
    with open(PROCESSED / "events.csv", encoding="utf-8") as fh:
        return {r["event_id"]: r for r in csv.DictReader(fh)}


def assessed_areas():
    data = json.loads((PROCESSED / "burned_areas.json").read_text("utf-8"))
    return {a["event_id"]: a for a in data["assessed"]}


def scenes_for(event, kind):
    """Every dated scene of one event and band combination, oldest first."""
    found = []
    for tif in sorted(IMAGERY.glob(f"{event}_{kind}_*.tif")):
        date = tif.stem.rsplit("_", 1)[1]
        if len(date) == 8 and date.isdigit():
            found.append((f"{date[:4]}-{date[4:6]}-{date[6:]}", tif))
    return found


def read_rgb(tif):
    with rasterio.open(tif) as src:
        rgb = src.read([1, 2, 3]).transpose(1, 2, 0)
        b = src.bounds
    return rgb, (b.left, b.right, b.bottom, b.top)


def series_limits(frames, lo=2, hi=98):
    """One pair of per-band limits for a whole date series.

    Sentinel-2 true colour over humid tropical forest occupies the bottom of
    the byte range, so an unstretched series renders as near-black squares
    and shows nothing. Stretching each date against its own histogram is
    worse than not stretching at all: a burn darkens the frame, a per-date
    stretch brightens it straight back, and the series stops showing the one
    thing it exists to show. The limits are therefore computed once over
    every date pooled, and applied unchanged to each.
    """
    pool = np.concatenate([f.reshape(-1, f.shape[2])[::97] for f in frames])
    valid = pool.max(axis=1) > 0
    if not valid.any():
        return np.zeros(3), np.ones(3)
    a, b = np.percentile(pool[valid].astype(np.float32), [lo, hi], axis=0)
    b = np.where(b <= a, a + 1.0, b)
    return a, b


def apply_limits(rgb, a, b):
    out = np.clip((rgb.astype(np.float32) - a) / (b - a), 0, 1)
    out[rgb.max(axis=2) == 0] = 1.0
    return out


def detections_in(extent, start_wit, end_wit):
    """FIRMS detections inside the frame during the event's own window.

    The store has no event column, so membership here is "inside this frame
    while this event was being detected" - which is what the plate claims and
    nothing more.
    """
    df = pd.read_parquet(PROCESSED / "detections.parquet")
    lon, lat = np.asarray(df["longitude"]), np.asarray(df["latitude"])
    x, y = TO_UTM(lon, lat)
    left, right, bottom, top = extent
    inside = (x >= left) & (x <= right) & (y >= bottom) & (y <= top)
    when = pd.to_datetime(df["datetime_utc"], utc=True, errors="coerce")
    window = (when >= pd.Timestamp(start_wit)) & (when <= pd.Timestamp(end_wit))
    keep = inside & np.asarray(window.fillna(False))
    return x[keep], y[keep], np.asarray(df["frp"])[keep]


# ----------------------------------------------------------------- furniture --

def scale_bar(ax, extent, length_m=1000):
    """A true ground distance: the axes are metres in UTM zone 53S."""
    left, right, bottom, top = extent
    span = right - left
    pad = span * 0.05
    x0 = left + pad
    y0 = bottom + (top - bottom) * 0.045
    h = span * 0.006
    for i in range(4):
        ax.add_patch(Rectangle((x0 + i * length_m / 4, y0), length_m / 4, h,
                               facecolor=(INK if i % 2 == 0 else PAPER),
                               edgecolor=INK, lw=0.7, zorder=6))
    for frac, text in ((0, "0"), (0.5, f"{length_m // 2} m"),
                       (1, f"{length_m // 1000} km")):
        ax.text(x0 + length_m * frac, y0 + h * 1.6, text, ha="center",
                va="bottom", fontsize=7.5, color=INK, zorder=6,
                bbox=dict(fc=PAPER, ec="none", alpha=0.75, pad=1.0))


def north_arrow(ax, extent):
    left, right, bottom, top = extent
    x = right - (right - left) * 0.055
    y = bottom + (top - bottom) * 0.045
    h = (top - bottom) * 0.075
    ax.annotate("", xy=(x, y + h), xytext=(x, y),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4),
                zorder=6)
    ax.text(x, y + h * 1.08, "N", ha="center", va="bottom", fontsize=9,
            color=INK, zorder=6,
            bbox=dict(fc=PAPER, ec="none", alpha=0.75, pad=1.0))
    ax.text(x, y - h * 0.18, "grid", ha="center", va="top", fontsize=6,
            color=SOFT, zorder=6)


def graticule(ax, extent):
    """Latitude and longitude ticks on a projected frame, so a reader can
    place the plate without a second map."""
    left, right, bottom, top = extent
    xs = np.linspace(left, right, 5)[1:-1]
    ys = np.linspace(bottom, top, 5)[1:-1]
    lon_ticks, _ = TO_WGS(xs, np.full_like(xs, bottom))
    _, lat_ticks = TO_WGS(np.full_like(ys, left), ys)
    ax.set_xticks(xs)
    ax.set_yticks(ys)
    ax.set_xticklabels([f"{v:.3f}°E" for v in lon_ticks], fontsize=6.5)
    ax.set_yticklabels([f"{abs(v):.3f}°S" for v in lat_ticks], fontsize=6.5,
                       rotation=90, va="center")
    ax.tick_params(length=2.5, width=0.6, colors=SOFT, pad=1.5)
    for s in ax.spines.values():
        s.set_color(INK)
        s.set_linewidth(0.9)


def draw_polys(ax, polys, **kw):
    for geom, _props in polys:
        parts = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
        for part in parts:
            ax.add_patch(MplPolygon(np.asarray(part.exterior.coords), **kw))


# -------------------------------------------------------------- the plate ----

def plate(event, desa, row, area, out_path):
    """One page: map frame, side panel, date series, title block, credits.

    The side panel carries the locator and the legend, and the date series
    runs full width under the map, so the square scene is not stranded in a
    wide axes with half the page empty either side of it.
    """
    swir = scenes_for(event, "swir")
    tci = scenes_for(event, "tci")
    if not swir:
        raise SystemExit(f"{event}: no SWIR scenes under {IMAGERY}")
    main_date, main_tif = swir[-1]
    rgb, extent = read_rgb(main_tif)

    burned = load_geojson(DOCS / "data" / "burned_areas.geojson", event)
    labels = load_geojson(DOCS / "data" / "labels.geojson", event)
    desa_rings = load_geojson(DOCS / "data" / "biak_desa.geojson", None)
    dx, dy, dfrp = detections_in(extent, row["first_seen_utc"],
                                 row["last_seen_utc"])

    changed = area["changed_ha"] if area else None
    foot = area["footprint_ha"] if area else None

    fig = plt.figure(figsize=FIGSIZE, dpi=DPI, facecolor=KARST)
    grid = fig.add_gridspec(
        4, 2, width_ratios=[1.0, 0.40],
        height_ratios=[0.135, 1.0, 0.26, 0.055],
        left=0.035, right=0.975, top=0.972, bottom=0.025,
        wspace=0.05, hspace=0.17)

    # --- title block -------------------------------------------------------
    head = fig.add_subplot(grid[0, :])
    head.axis("off")
    head.set_xlim(0, 1)
    head.set_ylim(0, 1)
    head.plot([0, 1], [1, 1], color=CANOPY, lw=2.4, clip_on=False)
    head.text(0, 0.74, f"{desa} \u2014 {event}", fontsize=22, color=INK,
              va="center", ha="left", fontweight="bold")
    head.text(0, 0.32,
              f"Mapped burn extent from Sentinel-2, {main_date}. "
              f"Detected {row['first_seen_wit'][:16].replace('T', ' ')} to "
              f"{row['last_seen_wit'][:16].replace('T', ' ')} WIT: "
              f"{row['n_detections']} detections over {row['n_overpasses']} "
              f"overpasses, peak FRP {float(row['frp_max']):.0f} MW.",
              fontsize=10, color=SOFT, va="center", ha="left")

    # --- main frame --------------------------------------------------------
    ax = fig.add_subplot(grid[1, 0])
    ax.imshow(rgb, extent=(extent[0], extent[1], extent[2], extent[3]),
              origin="upper", interpolation="bilinear")
    draw_polys(ax, desa_rings, closed=True, fill=False, ec="#ffffff", lw=0.7,
               alpha=0.38, zorder=2)
    draw_polys(ax, burned, closed=True, fc="none", ec=SCAR, lw=1.3, zorder=4)
    draw_polys(ax, labels, closed=True, fc="none", ec="#ffd166", lw=0.9,
               ls=(0, (3, 2)), zorder=5)
    if len(dx):
        ax.scatter(dx, dy, s=14 + 2.4 * np.nan_to_num(dfrp),
                   facecolors="none", edgecolors="#ffffff", linewidths=1.2,
                   zorder=5)
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect("equal")
    ax.set_anchor("W")
    graticule(ax, extent)
    scale_bar(ax, extent)
    north_arrow(ax, extent)
    ax.text(0.012, 0.985,
            "Sentinel-2 B12 / B8A / B4 \u2014 burned ground magenta to "
            "orange, living vegetation green",
            transform=ax.transAxes, fontsize=7.5, va="top", color=INK,
            bbox=dict(fc=PAPER, ec=RULE, lw=0.6, pad=2.5), zorder=6)

    # --- side panel: locator, legend, what the frame claims ----------------
    panel = grid[1, 1].subgridspec(2, 1, height_ratios=[1.0, 1.25],
                                   hspace=0.08)

    loc = fig.add_subplot(panel[0])
    loc.set_facecolor(SEA)
    draw_polys(loc, desa_rings, closed=True, fc=KARST, ec="#ffffff", lw=0.4,
               zorder=2)
    lx0, ly0 = TO_UTM(ISLAND[0], ISLAND[1])
    lx1, ly1 = TO_UTM(ISLAND[2], ISLAND[3])
    loc.add_patch(Rectangle((extent[0], extent[2]),
                            extent[1] - extent[0], extent[3] - extent[2],
                            fc="none", ec=SCAR, lw=2.0, zorder=4))
    loc.set_xlim(lx0, lx1)
    loc.set_ylim(ly0, ly1)
    loc.set_aspect("equal")
    loc.set_xticks([])
    loc.set_yticks([])
    for s in loc.spines.values():
        s.set_color(INK)
        s.set_linewidth(0.9)
    loc.set_title("Biak island, with this frame", fontsize=8.5, color=SOFT,
                  pad=4)

    key = fig.add_subplot(panel[1])
    key.axis("off")
    key.set_xlim(0, 1)
    key.set_ylim(0, 1)
    handles = [
        Line2D([], [], color=SCAR, lw=1.8,
               label="Mapped burn polygon (dNBR+)"),
        Line2D([], [], color="#b58b00", lw=1.3, ls=(0, (3, 2)),
               label="Interpretation box, 60 m"),
        Line2D([], [], marker="o", color="none", markerfacecolor="none",
               markeredgecolor=SOFT, markeredgewidth=1.3, markersize=8,
               label="Thermal anomaly, sized by FRP"),
        Line2D([], [], color=SOFT, lw=1.1,
               label="Desa / kelurahan boundary"),
    ]
    leg = key.legend(handles=handles, loc="upper left",
                     bbox_to_anchor=(-0.02, 1.0), frameon=False, fontsize=9,
                     handlelength=2.0, borderaxespad=0, labelspacing=0.75)
    for text in leg.get_texts():
        text.set_color(INK)
    claim = (f"Product maps {changed:,.1f} ha of change "
             f"inside a {foot:,.1f} ha footprint."
             if changed is not None else
             "No assessed area for this event: no usable local reference "
             "existed. Absent, not zero.")
    key.text(0, 0.56, chr(10).join(textwrap.wrap(claim, 44)),
             fontsize=9.5, color=SCAR, va="top", ha="left", linespacing=1.5)
    key.text(0, 0.56 - 0.13,
             "A mapped extent, not a validated area. It carries no interval,\n"
             "and the validated figure on the results page covers this\n"
             "footprint and two others, not the season.",
             fontsize=8.5, color=SOFT, va="top", ha="left", linespacing=1.5)
    key.text(0, 0.03,
             f"{len(labels)} interpretation boxes \u00b7 "
             f"{len(dx)} detections in frame\n"
             f"UTM zone 53S \u00b7 scene {extent[1] - extent[0]:.0f} m across",
             fontsize=8, color=SOFT, va="bottom", ha="left", linespacing=1.5)

    # --- date series, full width ------------------------------------------
    strip = grid[2, :].subgridspec(1, len(tci), wspace=0.035)
    frames = [read_rgb(tif) for _d, tif in tci]
    lo_lim, hi_lim = series_limits([f for f, _e in frames])
    for i, (date, _tif) in enumerate(tci):
        a = fig.add_subplot(strip[i])
        raw, ext = frames[i]
        a.imshow(apply_limits(raw, lo_lim, hi_lim),
                 extent=(ext[0], ext[1], ext[2], ext[3]),
                 origin="upper", interpolation="bilinear")
        draw_polys(a, burned, closed=True, fc="none", ec=SCAR, lw=0.8,
                   zorder=4)
        a.set_xlim(ext[0], ext[1])
        a.set_ylim(ext[2], ext[3])
        a.set_aspect("equal")
        a.set_xticks([])
        a.set_yticks([])
        for s in a.spines.values():
            s.set_color(RULE)
            s.set_linewidth(0.8)
        a.set_title(date, fontsize=8, color=INK, pad=2.5)
    # --- credits -----------------------------------------------------------
    foot_ax = fig.add_subplot(grid[3, :])
    foot_ax.axis("off")
    foot_ax.set_xlim(0, 1)
    foot_ax.set_ylim(0, 1)
    credits = ("Lower strip: true colour, same frame, one contrast stretch "
               "applied to all six dates. Sentinel-2 L2A (Copernicus), "
               "super-resolved to 1 m by S2DR4. Detections: NASA FIRMS. "
               "Boundaries: BIG. A thermal anomaly is not a confirmed fire "
               "and names nobody.")
    foot_ax.text(0, 0.5, chr(10).join(textwrap.wrap(credits, 132)),
                 fontsize=8, color=SOFT, ha="left", va="center",
                 linespacing=1.6)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format="webp", dpi=DPI, facecolor=KARST)
    plt.close(fig)
    return {
        "event": event, "desa": desa, "date": main_date,
        "detections": int(row["n_detections"]),
        "first_seen_wit": row["first_seen_wit"],
        "last_seen_wit": row["last_seen_wit"],
        "changed_ha": changed, "footprint_ha": foot,
        "n_label_boxes": len(labels), "n_burn_polygons": len(burned),
        "series_dates": [d for d, _ in tci],
        "file": f"gallery/{out_path.name}",
    }


# --------------------------------------------------- the GeoLibre project ----

# The default style block and raster metadata GeoLibre writes for a new
# layer. Copied from a project the geolibre MCP server created, because the
# first version of this function was written from the README and guessed the
# schema: `view` for `mapView`, `basemap` for `basemapStyleUrl`, and a `source`
# path where a vector layer wants its GeoJSON inlined. GeoLibre refused to
# open the result, which is how the guess was caught.
STYLE_DEFAULTS = {
    "minZoom": 0,
    "maxZoom": 24,
    "textColor": "#111827",
    "textHaloColor": "#ffffff",
    "textHaloWidth": 2,
    "textSize": 16,
    "extrusionEnabled": False,
    "extrusionColor": "#3b82f6",
    "extrusionOpacity": 0.8,
    "extrusionHeightProperty": "height",
    "extrusionHeightScale": 1,
    "extrusionBase": 0,
    "extrusionAdvancedStyleEnabled": False,
    "extrusionColorExpression": "",
    "extrusionHeightExpression": "",
    "vectorStyleMode": "single",
    "vectorStyleProperty": "",
    "vectorStyleClassCount": 5,
    "vectorStyleColorRamp": "viridis",
    "vectorStyleClassificationScheme": "equal-interval",
    "vectorStyleStops": [
        {
            "value": 0,
            "color": "#dbeafe"
        },
        {
            "value": 1,
            "color": "#2563eb"
        }
    ],
    "vectorStyleExpression": "",
    "pointRenderer": "single",
    "heatmapRadius": 30,
    "heatmapIntensity": 1,
    "clusterRadius": 50,
    "clusterMaxZoom": 14,
    "rasterBrightnessMin": 0,
    "rasterBrightnessMax": 1,
    "rasterSaturation": 0,
    "rasterContrast": 0,
    "rasterHueRotate": 0,
    "blendMode": "normal"
}

RASTER_METADATA = {
    "customLayerType": "raster",
    "externalDeckLayer": True,
    "externalNativeLayer": True,
    "identifiable": False,
    "panelCollapsed": True,
    "rasterOverlayMode": "interleaved",
    "rasterSource": "url",
    "rasterState": {
        "bands": [
            1,
            2,
            3
        ],
        "mode": "rgb"
    },
    "sourceIds": [],
    "sourceKind": "maplibre-gl-raster"
}


def _vector_layer(layer_id, name, features, style, visible=True):
    return {
        "id": layer_id, "name": name, "type": "geojson",
        "visible": visible, "opacity": 1,
        "style": dict(STYLE_DEFAULTS, **style),
        "metadata": {}, "source": {"type": "geojson"},
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def _features(path, event):
    """The published GeoJSON for one event, unprojected, as GeoLibre wants it."""
    feats = json.loads(Path(path).read_text(encoding="utf-8"))["features"]
    if event is None:
        return feats
    return [f for f in feats if f["properties"].get("event_id") == event]


def geolibre_project(event, desa, extent, out_path):
    """The same layers at the same extent, as a project GeoLibre can open.

    This is the hand-off to Layout Composer, which cannot be scripted: open
    this file in GeoLibre, enable the plugin, and the frame is already set.

    The raster is referenced by a path relative to the repository root, which
    is what the GeoLibre workspace is rooted at, so open the project with this
    repository as the workspace or the 1 m scene will not resolve.
    """
    west, south = TO_WGS(extent[0], extent[2])
    east, north = TO_WGS(extent[1], extent[3])
    scene = f"data/labels/imagery/{event}_swir_20260917.tif"
    layers = [
        {
            "id": f"{event}-swir", "name": "Sentinel-2 B12/B8A/B4, 1 m",
            "type": "cog", "visible": True, "opacity": 1,
            "style": dict(STYLE_DEFAULTS),
            "metadata": dict(RASTER_METADATA,
                             nativeLayerIds=[f"{event}-swir"],
                             rasterState={"bands": [1, 2, 3], "mode": "rgb"}),
            "source": {"type": "raster", "url": scene},
            "sourcePath": scene,
        },
        _vector_layer(
            f"{event}-desa", "Desa / kelurahan boundaries",
            _features(DOCS / "data" / "biak_desa.geojson", None),
            {"fillOpacity": 0, "strokeColor": "#8a8a8a", "strokeWidth": 0.7}),
        _vector_layer(
            f"{event}-burned", "Mapped burn polygons",
            _features(DOCS / "data" / "burned_areas.geojson", event),
            {"fillColor": SCAR, "fillOpacity": 0.35, "strokeColor": SCAR,
             "strokeWidth": 1.2}),
        _vector_layer(
            f"{event}-labels", "Interpretation boxes",
            _features(DOCS / "data" / "labels.geojson", event),
            {"fillOpacity": 0, "strokeColor": "#b58b00", "strokeWidth": 1.0}),
        _vector_layer(
            f"{event}-survey", "Field plots",
            _features(DOCS / "data" / "survey.geojson", None),
            {"fillColor": SCAR, "strokeColor": "#ffffff", "strokeWidth": 2,
             "circleRadius": 5}),
    ]
    project = {
        "version": "0.1.0",
        "name": f"{desa} ({event}) burn footprint",
        "mapView": {"center": [(west + east) / 2, (south + north) / 2],
                    "zoom": 13.4, "bearing": 0, "pitch": 0},
        "basemapStyleUrl": "https://tiles.openfreemap.org/styles/liberty",
        "basemapVisible": True,
        "basemapOpacity": 1,
        "layers": layers,
        "styles": {},
        "preferences": {},
        "metadata": {
            "note": "Written by scripts/burn_atlas.py beside the atlas plate "
                    "of the same name. The raster path is relative to the "
                    "repository root.",
        },
    }
    out_path.write_text(json.dumps(project, indent=1), encoding="utf-8")


# ----------------------------------------------------------------- check ----

def demo():
    index = json.loads((DOCS / "data" / "gallery.json").read_text("utf-8"))
    plates = index["plates"]
    assert len(plates) == len(EVENTS), f"{len(plates)} plates for {len(EVENTS)} events"
    for p in plates:
        img = DOCS / p["file"]
        assert img.exists(), f"{p['file']} is indexed and missing"
        assert img.stat().st_size > 50_000, f"{p['file']} is suspiciously small"
        assert p["n_burn_polygons"] > 0, f"{p['event']} plate draws no burn polygon"
        assert p["n_label_boxes"] > 0, f"{p['event']} plate draws no label box"
        assert len(p["series_dates"]) >= 2, f"{p['event']} has no date series"
        assert p["series_dates"] == sorted(p["series_dates"]), \
            f"{p['event']} date series is out of order"
        proj = DOCS / "gallery" / f"{p['event']}.geolibre.json"
        assert proj.exists(), f"{proj.name} missing"
        layers = json.loads(proj.read_text("utf-8"))["layers"]
        assert any(l["type"] == "cog" for l in layers), proj.name
        assert any(l["type"] == "geojson" and l["geojson"]["features"]
                   for l in layers), f"{proj.name} has no vector features"
    # The plates show three footprints. Saying so is the point of the page.
    assert index["covers_events"] == sorted(EVENTS), index["covers_events"]
    print(f"{len(plates)} plates, "
          f"{sum((DOCS / p['file']).stat().st_size for p in plates) / 1e6:.1f} MB")
    print("all assertions passed")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="assert the existing output, write nothing")
    args = ap.parse_args()
    if args.check:
        demo()
        return 0

    rows = event_rows()
    areas = assessed_areas()
    plates = []
    for event, desa in EVENTS.items():
        out = GALLERY / f"{event}.webp"
        info = plate(event, desa, rows[event], areas.get(event), out)
        _rgb, extent = read_rgb(scenes_for(event, "swir")[-1][1])
        geolibre_project(event, desa, extent,
                         GALLERY / f"{event}.geolibre.json")
        plates.append(info)
        print(f"{out.relative_to(ROOT)}  {out.stat().st_size / 1e6:.2f} MB")

    (DOCS / "data" / "gallery.json").write_text(json.dumps({
        "covers_events": sorted(EVENTS),
        "note": "Three of the season's events. They are the three with "
                "hand-drawn interpretation boxes and 1 m imagery, which is "
                "why the validated area figure covers these footprints and "
                "no others.",
        "plates": plates,
    }, indent=1), encoding="utf-8")
    demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
