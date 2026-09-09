"""Render a Biak poster plate with forge3d: terrain, a draped surface, hotspots.

    python scripts/render_biak_poster.py [--fetch] [--lulc SOURCE] [--view V]

    --lulc  esri2025 | dw2026 | dw2026conf | truecolor
            what gets draped on the relief. dw2026conf is the Dynamic World
            classification washed toward the page wherever the winning class
            beat the runner-up by less than MARGIN_MIN.
    --view  plan | oblique                     top-down plate, or a 3D relief

This is a one-off illustration tool, not part of any daily or cron path, and
nothing in src/ or tests/ imports it. It needs a heavier environment than the
pipeline does - forge3d, scipy, Pillow, and earthengine-api for --fetch - so
run it from the `geolibre` conda environment rather than the project default:

    "$CONDA/envs/geolibre/python.exe" scripts/render_biak_poster.py --fetch

Inputs are cached as .npy under geolibre_data/ (gitignored) so a re-render
costs no network. Pass --fetch once per source to fill that cache.

Data: Copernicus DEM GLO-30 (ESA, CC-BY-4.0). Esri Land Cover 10 m (Esri /
Impact Observatory / Microsoft, CC-BY-4.0). Dynamic World V1 (Google / World
Resources Institute, CC-BY-4.0). Sentinel-2 (Copernicus). Hotspots: NASA
FIRMS. Cite these wherever a rendered plate is published.

A hotspot is a thermal anomaly. The plates mark where detections cluster;
they do not measure burnt area, fire intensity, or who lit anything.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "geolibre_data" / "forge3d"
DETECTIONS = ROOT / "data" / "processed" / "detections.parquet"

# Biak island proper, from the extent of its ten districts plus a margin.
# Supiori and Numfor are inside the project AOI but outside this frame, so
# every count quoted on a plate is recomputed against this box.
BOX = (135.70, -1.34, 136.42, -0.69)
GRID_M = 30.0                       # the DEM scale everything is resampled to
HOTSPOT_FROM = "2026-08-01"

CREAM = (242, 237, 226)
INK = (58, 56, 52)
MUTE = (139, 134, 124)
FONTS = Path("C:/Windows/Fonts")

# forge3d refuses to return an unconverged frame, which is the right call and
# also means a render fails outright rather than degrading quietly.
#
# Two failure modes worth knowing before changing the numbers below. A tile
# much larger than these blows the 512 MB GPU budget and says so plainly. And
# some combinations of tile size and plate size come back as "ReSTIR reuse
# chain produced no valid reservoirs", which is not a size error and does not
# follow an obvious rule - 2400x1500 at tile 600 converges while 2400x1600 at
# tile 400 does not, partial tiles and all. These pairs are the ones observed
# to converge; treat a change to them as something to re-test, not assume.
TILE = {"plan": 400, "oblique": 600}
SIZE = {"plan": (2400, 2000), "oblique": (2400, 1500)}


# --------------------------------------------------------------------------
# Fetch

def _earthengine():
    import ee                       # noqa: PLC0415 - optional, only for --fetch
    ee.Initialize(project="deeplearning-370412")
    return ee


def _download(image, bands, scale, out, label):
    """Pull one image as a structured .npy through the Earth Engine REST API."""
    import requests                 # noqa: PLC0415
    ee = sys.modules["ee"]
    aoi = ee.Geometry.Rectangle(list(BOX))
    url = image.getDownloadURL({"region": aoi, "scale": scale,
                                "crs": "EPSG:4326", "format": "NPY",
                                "bands": bands})
    r = requests.get(url, timeout=900)
    # AGENTS never-2: a refused request is not an empty answer. Earth Engine
    # returns 400 when the computation times out, which happens with a long
    # date range, and writing a partial cache from that would be silent
    # corruption of every later render.
    r.raise_for_status()
    arr = np.load(io.BytesIO(r.content))
    np.save(out, arr)
    print("  %-14s %s  %.1f MB" % (label, arr.shape, len(r.content) / 1e6))
    return arr


def fetch(source):
    CACHE.mkdir(exist_ok=True)
    ee = _earthengine()
    sys.modules["ee"] = ee
    aoi = ee.Geometry.Rectangle(list(BOX))

    dem = CACHE / "biak_dem30.npy"
    if not dem.exists():
        img = ee.ImageCollection("COPERNICUS/DEM/GLO30").select("DEM") \
                .mosaic().clip(aoi)
        _download(img, ["DEM"], GRID_M, dem, "dem")

    if source == "esri2025":
        out = CACHE / "biak_lulc30_2025.npy"
        if out.exists():
            return
        c = ee.ImageCollection(
            "projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS")
        img = ee.Image(c.filterDate("2025-01-01", "2026-01-01").mosaic()) \
                .clip(aoi).rename("lc")
        _download(img, ["lc"], GRID_M, out, "esri2025")

    elif source == "dw2026":
        out = CACHE / "biak_dw2026.npy"
        if out.exists():
            return
        dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(aoi)
              .filterDate("2026-05-01", "2026-09-05"))
        # `n` travels with the classification on purpose: a modal class built
        # from one clear look is not the same measurement as one built from
        # twenty, and the plate should be able to say so.
        img = (dw.select("label").reduce(ee.Reducer.mode()).rename("lc")
               .addBands(dw.select("label").count().rename("n"))).clip(aoi)
        _download(img, ["lc", "n"], GRID_M, out, "dw2026")

    elif source == "dw2026conf":
        out = CACHE / "biak_dwconf30.npy"
        if out.exists():
            return
        raise SystemExit(
            "biak_dwconf30.npy is built from nine mean-probability bands "
            "pulled one at a time; see the note in this file's header. "
            "Earth Engine refuses the combined request.")

    elif source == "truecolor":
        out = CACHE / "biak_s2_clean.npy"
        if out.exists():
            return
        cs = ee.ImageCollection("GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED")
        s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
              .filterBounds(aoi).filterDate("2026-05-01", "2026-09-05"))
        joined = s2.linkCollection(cs, ["cs_cdf"])
        # A wider window times out server-side before it ever returns; four
        # dry-season months is what fits in one synchronous request.
        img = (joined.map(lambda i: i.updateMask(i.select("cs_cdf").gte(0.6)))
               .select(["B4", "B3", "B2"]).median().clip(aoi).toInt16())
        _download(img, ["B4", "B3", "B2"], 60, out, "s2")


# --------------------------------------------------------------------------
# Surfaces

# Water is deliberately absent from both palettes. The sea is drawn as the
# page, so a water entry would colour it twice and - worse - land in the
# denominator, turning every class share into a fraction of the frame instead
# of a fraction of the island.
ESRI = {                            # code: (colour, label)
    2:  ((0.161, 0.376, 0.239), "Pohon"),
    4:  ((0.478, 0.686, 0.573), "Vegetasi tergenang"),
    5:  ((0.878, 0.702, 0.310), "Tanaman pangan"),
    7:  ((0.482, 0.353, 0.361), "Terbangun"),
    8:  ((0.902, 0.882, 0.835), "Lahan terbuka"),
    10: ((0.784, 0.784, 0.784), "Awan"),
    11: ((0.816, 0.663, 0.396), "Semak"),
}
DW = {
    1: ((0.161, 0.376, 0.239), "Pohon"),
    2: ((0.478, 0.612, 0.302), "Rumput"),
    3: ((0.478, 0.686, 0.573), "Vegetasi tergenang"),
    4: ((0.878, 0.702, 0.310), "Tanaman pangan"),
    5: ((0.816, 0.663, 0.396), "Semak belukar"),
    6: ((0.482, 0.353, 0.361), "Terbangun"),
    7: ((0.902, 0.882, 0.835), "Lahan terbuka"),
    8: ((0.784, 0.784, 0.784), "Salju/es"),
}


# Each source carries the grid it was pulled on. Esri is native 10 m and
# survives a 20 m pull in one request; the Dynamic World probability stack is
# nine bands and only fits at 30 m, so its plate is coarser. The DEM has to
# match whichever grid the surface uses, because the albedo the renderer
# takes must be the same raster as the heightmap.
SOURCES = {
    "esri2025":   dict(dem="biak_dem20.npy", scale=20.0),
    "dw2026":     dict(dem="biak_dem30.npy", scale=30.0),
    "dw2026conf": dict(dem="biak_dem30.npy", scale=30.0),
    "truecolor":  dict(dem="biak_dem30.npy", scale=30.0),
}

# A pixel that beats the runner-up by less than this is a coin flip dressed
# as a classification. Measured on Dynamic World's mean probabilities over
# the south-coast survey corridor, more than half the pixels it labels
# "trees" win by under 0.15, with a median margin of 0.022 - against ground
# observation of shrub and bare burn scars.
MARGIN_MIN = 0.15


def load_dem(source):
    a = np.load(CACHE / SOURCES[source]["dem"])["DEM"]
    return a.astype("float32")


def surface(source, shape):
    """(albedo RGB, land mask, class raster or None, palette or None)."""
    H, W = shape
    if source == "truecolor":
        s = np.load(CACHE / "biak_s2_clean.npy")
        raw = np.dstack([s["B4"], s["B3"], s["B2"]]).astype("float32")
        # The composite is pulled at 60 m to stay inside one request, so it
        # has to be lifted onto the DEM grid: every later step - the land
        # mask, the hotspot positions, the albedo the renderer wants - is
        # indexed in DEM pixels.
        sy = (np.arange(H) * (raw.shape[0] - 1) / (H - 1)).round().astype(int)
        sx = (np.arange(W) * (raw.shape[1] - 1) / (W - 1)).round().astype(int)
        raw = raw[np.ix_(sy, sx)]
        raw = ndimage.gaussian_filter(raw, (1.6, 1.6, 0))
        # A fixed reflectance ceiling keeps the band balance the sensor
        # recorded. Stretching each channel to its own percentiles does not,
        # and turns tropical forest cyan.
        rgb = np.clip(raw / 1600.0, 0, 1) ** (1 / 1.6)
        g = rgb.mean(axis=2, keepdims=True)
        rgb = np.clip(g + (rgb - g) * 1.15, 0, 1)
        land = load_dem(source) > 0.5
        return rgb, land, None, None

    margin = None
    if source == "esri2025":
        lc = np.load(CACHE / "biak_lulc20_2025.npy")["lc"].astype("uint8")
        palette, water, nodata = ESRI, 1, 0
    elif source == "dw2026conf":
        d = np.load(CACHE / "biak_dwconf30.npy")
        lc = d["lc"].astype("uint8")
        margin = d["margin"].astype("float32") / 255.0
        palette, water, nodata = DW, 0, None
    else:
        lc = np.load(CACHE / "biak_dw2026.npy")["lc"].astype("uint8")
        palette, water, nodata = DW, 0, None

    is_land = lc != water
    if nodata is not None:
        is_land &= lc != nodata
    # Fill holes so a lagoon enclosed by the coastline keeps the colour its
    # class earned, instead of being punched out with the open sea.
    land = ndimage.binary_closing(ndimage.binary_fill_holes(is_land),
                                  np.ones((3, 3), bool))
    rgb = np.empty((H, W, 3), "float32")
    rgb[:] = np.array(CREAM, "float32") / 255.0
    for code, (col, _) in palette.items():
        rgb[lc == code] = col
    rgb[~land] = np.array(CREAM, "float32") / 255.0

    if margin is not None:
        # Where the decision was close, wash the class colour toward the page
        # in proportion to how close it was. The map still says what the
        # classifier picked; it stops implying the classifier was sure.
        doubt = np.clip(1.0 - margin / MARGIN_MIN, 0.0, 1.0) * land
        doubt = (doubt * 0.72)[..., None]
        page = np.array(CREAM, "float32") / 255.0
        rgb = rgb * (1 - doubt) + page * doubt
    return rgb, land, lc, palette


def hotspots(shape):
    """Detection pixel positions inside BOX, and how many there are."""
    H, W = shape
    det = pd.read_parquet(DETECTIONS)
    det = det[det["date_wit"].astype(str) >= HOTSPOT_FROM]
    w, s, e, n = BOX
    det = det[det["longitude"].between(w, e) & det["latitude"].between(s, n)]
    px = ((det["longitude"].to_numpy() - w) / (e - w) * (W - 1)).astype(int)
    py = ((n - det["latitude"].to_numpy()) / (n - s) * (H - 1)).astype(int)
    span = (det["date_wit"].astype(str).min(), det["date_wit"].astype(str).max())
    return px, py, len(det), span


def desa_rings(shape):
    """Desa outlines and label anchors, in grid pixels.

    Yields (rings, name, area) per feature, largest first, so the caller can
    label the ones with room for a label and drop the slivers.
    """
    import json                      # noqa: PLC0415
    H, W = shape
    w, s, e, n = BOX
    src = ROOT / "data" / "boundaries" / "biak_desa.geojson"
    out = []
    for f in json.loads(src.read_text(encoding="utf-8"))["features"]:
        geom = f["geometry"]
        parts = (geom["coordinates"] if geom["type"] == "Polygon"
                 else [r for part in geom["coordinates"] for r in part])
        rings, area, best = [], 0.0, None
        for ring in parts:
            if len(ring) < 3:
                continue
            pts = [((x - w) / (e - w) * (W - 1),
                    (n - y) / (n - s) * (H - 1)) for x, y in ring]
            rings.append(pts)
            # Shoelace on the ring already in pixels: the same number that
            # ranks features for labelling also decides which are slivers.
            a = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1]
                        for i in range(len(pts)))) / 2.0
            if a > area:
                area, best = a, pts
        if best is None:
            continue
        cx = sum(x for x, _ in best) / len(best)
        cy = sum(y for _, y in best) / len(best)
        out.append((rings, f["properties"].get("WADMKD", ""), area, (cx, cy)))
    out.sort(key=lambda r: -r[2])
    return out


def draw_admin(card, origin, rect, grid_shape, outside, u, labels=30):
    """Desa boundaries and names, drawn on the finished plate.

    Baked into the albedo instead, a label is shaded by the sun angle and
    stretched over the relief until it is unreadable; a boundary line is
    dimmed wherever the hillside faces away. Drawn here, both keep the
    contrast they were given. The grid rectangle is what makes it possible
    to place them without re-deriving the camera.
    """
    ox, oy = origin
    y0, y1, x0, x1 = rect
    H, W = grid_shape

    def to_card(pt):
        gx, gy = pt
        return (ox + x0 + gx / (W - 1) * (x1 - x0),
                oy + y0 + gy / (H - 1) * (y1 - y0))

    feats = desa_rings(grid_shape)
    # Draw into a mask first and composite it only over land. Administrative
    # lines continue across the water to the reefs and the next island, and
    # on a plate whose sea is the page those strands read as scribble.
    stroke = Image.new("L", card.size, 0)
    ds = ImageDraw.Draw(stroke)
    for rings, _, _, _ in feats:
        for ring in rings:
            if len(ring) > 1:
                ds.line([to_card(p) for p in ring], fill=255,
                        width=max(1, u(2)), joint="curve")
    m = np.array(stroke)
    ch, cw = outside.shape
    keep = np.zeros(m.shape, bool)
    keep[oy:oy + ch, ox:ox + cw] = ~outside
    m[~keep] = 0
    card.paste(Image.new("RGB", card.size, (255, 214, 41)),
               (0, 0), Image.fromarray(m))

    d = ImageDraw.Draw(card)
    font = _font("arialbd.ttf", max(11, u(21)))
    placed, drawn = [], 0
    ch, cw = outside.shape
    for _, name, _, cen in feats:
        if drawn >= labels or not name:
            continue
        x, y = to_card(cen)
        px, py = int(x - ox), int(y - oy)
        # A centroid can fall in the sea for a horseshoe-shaped desa, and a
        # label there points at nothing.
        if not (0 <= px < cw and 0 <= py < ch) or outside[py, px]:
            continue
        if any(abs(x - qx) < u(230) and abs(y - qy) < u(52)
               for qx, qy in placed):
            continue
        box = d.textbbox((x, y), name, font=font, anchor="mm")
        pad = u(7)
        if not (ox + x0 < box[0] - pad and box[2] + pad < ox + x1
                and oy + y0 < box[1] and box[3] < oy + y1):
            continue
        d.rounded_rectangle([box[0] - pad, box[1] - u(3),
                             box[2] + pad, box[3] + u(3)],
                            radius=u(9), fill=(248, 245, 236))
        d.text((x, y), name, font=font, fill=INK, anchor="mm")
        placed.append((x, y))
        drawn += 1
    return drawn


def burn_in(rgb, land, px, py, layers, scale):
    """`layers` give the glow radius in metres; a radius in pixels would
    shrink on a finer grid and quietly change the map."""
    m = np.zeros(rgb.shape[:2], "float32")
    np.add.at(m, (py, px), 1.0)
    for metres, col, amp in layers:
        sigma = metres / scale
        g = ndimage.gaussian_filter(m, sigma)
        g /= max(g.max(), 1e-6)
        a = (np.clip(g * amp, 0, 1) * land)[..., None]
        rgb = np.clip(rgb * (1 - a) + np.array(col, "float32") * a, 0, 1)
    return rgb


# --------------------------------------------------------------------------
# Render

PLAN = dict(exposure=0.85, exaggeration=3.4, sun_azimuth_deg=315,
            sun_elevation_deg=36, sun_intensity=2.0, env_intensity=0.30)
OBLIQUE = dict(exposure=1.35, exaggeration=6.5, sun_azimuth_deg=318,
               sun_elevation_deg=27, sun_intensity=3.6, env_intensity=0.35)


def render(source, view, height, rgb, land, size):
    import forge3d as f3d           # noqa: PLC0415

    Wpx, Hpx = size
    hh = ndimage.gaussian_filter(height, 1.1).astype("float32")
    spacing = SOURCES[source]["scale"]
    if view == "oblique":
        # Oblique rays over the full grid at this exaggeration drive the
        # tracer's ReSTIR reuse into "no valid reservoirs" and the render
        # fails outright. Halving the grid clears it and costs nothing
        # visible at plate scale.
        hh, rgb = hh[::2, ::2].copy(), rgb[::2, ::2].copy()
        land = land[::2, ::2]
        spacing *= 2
    H, W = hh.shape
    if view == "plan":
        # A flat sea shades to exactly one tone, and that is what lets the
        # plate and the page meet without a seam when it is keyed out.
        hh[~land] = 0.0
        D = 420000.0
        fov = 2 * np.degrees(np.arctan((H * spacing / 2) / D)) * 1.04
        cam = dict(origin=(0.0, D, 0.0), look_at=(0.0, 0.0, 0.0),
                   up=(0.0, 0.0, -1.0), fov_y=fov)
        opts = PLAN
    else:
        cam = dict(origin=(0.0, 26000.0, 70000.0),
                   look_at=(0.0, 1500.0, -6000.0), up=(0.0, 1.0, 0.0),
                   fov_y=30.0)
        opts = OBLIQUE
    cam.update(aspect=Wpx / Hpx, exposure=opts["exposure"])

    alb = np.dstack([rgb, np.ones(rgb.shape[:2], "float32")]).astype("float32")
    out = f3d.render_terrain_poster(
        hh, Wpx, Hpx, camera=cam, albedo_map=alb,
        # Every surface is built on the DEM grid, so the albedo and the
        # heightmap are the same raster: nearest keeps class edges crisp and
        # has nothing to interpolate away.
        albedo_sampling="nearest",
        spacing=(spacing, spacing), exaggeration=opts["exaggeration"],
        sun_azimuth_deg=opts["sun_azimuth_deg"],
        sun_elevation_deg=opts["sun_elevation_deg"],
        sun_intensity=opts["sun_intensity"],
        env_intensity=opts["env_intensity"],
        max_frames=2048, min_frames=64, tile=TILE[view])
    return out["rgba"][:, :, :3]


# --------------------------------------------------------------------------
# Compose

def flat_tones(plate):
    """The two constant colours in a plan plate: the page, and the sea.

    Both are flat surfaces under one light, so each renders as a single
    value - but which value depends on the grid and the lighting, so it is
    measured per plate rather than hardcoded. The renderer's background is
    whatever sits in the corner; the sea is the other colour big enough to
    be a surface rather than a class.
    """
    flat = plate.reshape(-1, 3)
    cols, counts = np.unique(flat, axis=0, return_counts=True)
    order = np.argsort(-counts)
    bg = plate[0, 0].astype(int)
    sea = None
    for i in order:
        c = cols[i].astype(int)
        if np.abs(c - bg).max() <= 5:
            continue
        if counts[i] / len(flat) < 0.05:
            break
        sea = c
        break
    return bg, sea


def key_out(plate, bg, sea):
    """Mask of everything outside the coastline: the page, and the open sea.

    Not one flood from the frame border. The renderer's background and its
    sea plane meet along an anti-aliased ring, and at some plate sizes that
    ring breaks the two apart, so a single flood keys the background and
    leaves the sea grey. Instead the background is taken border-connected,
    and the sea is taken by area: a flat plane is a large component, while
    water enclosed by the coastline is a small one and keeps its colour.

    The sea plane also stops at the DEM's own edge, and that edge draws a
    hairline across the page; a few pixels of dilation swallow it without
    reaching the coast, hundreds of pixels away.
    """
    a = plate.astype(np.int16)
    outside = np.zeros(a.shape[:2], bool)

    page = np.abs(a - bg).max(axis=2) <= 5
    lab, _ = ndimage.label(page)
    edge = set(np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    if edge:
        outside |= np.isin(lab, list(edge))

    if sea is not None:
        water = np.abs(a - sea).max(axis=2) <= 5
        lab, n = ndimage.label(water)
        if n:
            big = np.bincount(lab.ravel())
            big[0] = 0
            keep = np.where(big > 0.005 * water.size)[0]
            if len(keep):
                outside |= np.isin(lab, keep)

    return ndimage.binary_dilation(outside, np.ones((5, 5), bool))


def grid_rect(plate, sea):
    """Where the DEM grid lands on the plate, as (y0, y1, x0, x1).

    The sea is a flat plane covering exactly the grid, so its own bounding
    rectangle is the calibration: it turns a grid coordinate into a plate
    pixel without re-deriving the camera. Everything drawn after the render -
    the legend's sampled colours, the boundaries, the labels - rides on it.
    """
    a = plate.astype(np.int16)
    ys, xs = np.where(np.abs(a - sea).max(axis=2) <= 5)
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def sampled_colours(plate, outside, lc, rect):
    """Median rendered colour per class, keyed by class code.

    The path tracer applies a tone curve - it compresses bright albedo hard
    and lifts dark albedo - so a legend quoting the colours handed *in* would
    misdescribe the map.
    """
    a = plate.astype(np.int16)
    y0, y1, x0, x1 = rect
    H, W = lc.shape
    yy = ((np.arange(y0, y1 + 1) - y0) / (y1 - y0) * (H - 1)).astype(int)
    xx = ((np.arange(x0, x1 + 1) - x0) / (x1 - x0) * (W - 1)).astype(int)
    on_plate = lc[np.ix_(yy, xx)]
    sub = a[y0:y1 + 1, x0:x1 + 1]
    keep = ~outside[y0:y1 + 1, x0:x1 + 1]
    got = {}
    for code in np.unique(on_plate):
        m = (on_plate == code) & keep
        if m.sum() >= 60:
            got[int(code)] = tuple(int(v) for v in np.median(sub[m], axis=0))
    return got


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _spaced_width(d, text, font, extra):
    return sum(d.textlength(ch, font=font) + extra for ch in text) - extra


def _spaced(d, xy, text, font, fill, extra, fit=None, name=None, size=None):
    """Draw letter-spaced text, shrinking to fit `fit` pixels if given.

    Titles are set from data - a source name, a year, a qualifier - so their
    length is not known when the layout is written. Measuring and shrinking
    is what keeps a long one from running through the keyline.
    """
    if fit is not None and name is not None and size is not None:
        while size > 8 and _spaced_width(d, text, font, extra) > fit:
            size -= 2
            font = _font(name, size)
            extra = max(1, int(extra * 0.9))
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + extra


def compose_plan(plate, lc, palette, credits, title2, out,
                 admin=True, grid_shape=None):
    bg, sea = flat_tones(plate)
    outside = key_out(plate, bg, sea)
    print("  page tone %s  sea tone %s  keyed out %.1f%%"
          % (tuple(bg), None if sea is None else tuple(sea),
             100 * outside.mean()))
    # Read the class colours off the plate while the sea is still on it: the
    # calibration rectangle IS the sea plane, and painting it over first
    # leaves only enclosed water to find, which is a different rectangle and
    # a silently wrong mapping.
    rect = grid_rect(plate, sea) if sea is not None else None
    got = (sampled_colours(plate, outside, lc, rect)
           if lc is not None and rect is not None else {})
    plate = plate.copy()
    plate[outside] = CREAM
    nland = int((~outside).sum()) if lc is None else int(
        sum((lc == c).sum() for c in palette if c in got))

    # Everything below is laid out in units of the plate, so a bigger render
    # yields a bigger poster rather than a bigger picture in the same frame.
    ph, pw = plate.shape[:2]
    k = ph / 2000.0
    def u(v):
        return int(round(v * k))
    CW, CH = pw + u(950), ph + u(200)
    card = Image.new("RGB", (CW, CH), CREAM)
    card.paste(Image.fromarray(plate), (u(110), u(100)))
    if admin and rect is not None and grid_shape is not None:
        n = draw_admin(card, (u(110), u(100)), rect, grid_shape, outside, u)
        print("  desa labelled: %d" % n)
    d = ImageDraw.Draw(card)
    d.rectangle([u(46), u(46), CW - u(47), CH - u(47)],
                outline=(206, 199, 184), width=max(2, u(3)))

    tx, ty = pw + u(200), u(660)
    fit = CW - u(47) - u(24) - tx
    _spaced(d, (tx, ty), "BIAK", _font("ARIALN.TTF", u(128)), INK, u(15),
            fit=fit, name="ARIALN.TTF", size=u(128))
    _spaced(d, (tx, ty + u(162)), title2, _font("ARIALN.TTF", u(44)), INK,
            u(3), fit=fit, name="ARIALN.TTF", size=u(44))
    fc = _font("arial.ttf", u(24))
    for i, line in enumerate(credits):
        d.text((tx + u(3), ty + u(232) + i * u(34)), line, font=fc, fill=MUTE)

    fl, fn = _font("arial.ttf", u(28)), _font("arial.ttf", u(21))
    y = ty + u(500)
    row, dropped = 0, []
    entries = [("HOT", "Titik panas", (214, 92, 46), None)]
    if lc is not None:
        total = max(int(sum((lc == c).sum() for c in palette)), 1)
        for code, (_, label) in palette.items():
            share = 100.0 * int((lc == code).sum()) / total
            entries.append((code, label, got.get(code), share))
        entries.sort(key=lambda e: -(e[3] or 1e9))
    for code, label, col, share in entries:
        # A swatch for a class covering a twentieth of a percent is
        # decoration, not a legend: below 0.1% of land the sampled colour is
        # mostly its neighbours bleeding in.
        if col is None or (share is not None and share < 0.10):
            if share is not None:
                dropped.append("%s %.2f%%" % (label.lower(), share))
            continue
        yy = y + row * u(58)
        d.ellipse([tx + u(4), yy, tx + u(36), yy + u(32)], fill=col)
        text = label if share is None else "%s   %.1f%%" % (label, share)
        d.text((tx + u(60), yy + u(1)), text, font=fl, fill=INK)
        row += 1
    if dropped:
        yy = y + row * u(58)
        d.text((tx + u(4), yy + u(18)),
               "Di bawah 0,1% daratan, tidak dilegendakan:", font=fn, fill=MUTE)
        for j in range(0, len(dropped), 2):
            d.text((tx + u(4), yy + u(44) + (j // 2) * u(26)),
                   ", ".join(dropped[j:j + 2]), font=fn, fill=MUTE)
    card.save(out)
    return card.size, nland


def compose_oblique(plate, credits, title2, out):
    """Dark plate: the renderer's flat background becomes a dusk gradient."""
    a = plate.astype(np.float32)
    Hh, Ww, _ = a.shape
    bg = np.abs(a - a[5, 5]).sum(axis=2) < 8
    ramp = np.linspace(0, 1, Hh, dtype=np.float32)[:, None]
    sky = (np.array([16, 26, 46], np.float32) * (1 - ramp)
           + np.array([120, 116, 128], np.float32) * ramp)
    for y in range(Hh):
        if bg[y].any():
            a[y, bg[y]] = sky[y]

    # Size the footer from what goes in it. A fixed height silently clips
    # the last credit as soon as a source needs one line more.
    pad = 70
    foot = 196 + len(credits) * 36 + 62
    card = Image.new("RGB", (Ww + pad * 2, Hh + pad + foot), (11, 14, 20))
    card.paste(Image.fromarray(a.astype(np.uint8)), (pad, pad))
    d = ImageDraw.Draw(card)
    y = pad + Hh + 46
    d.text((pad, y), "PULAU BIAK", font=_font("arialbd.ttf", 78),
           fill=(238, 236, 230))
    d.text((pad, y + 96), title2, font=_font("arial.ttf", 34),
           fill=(196, 122, 60))
    fc = _font("arial.ttf", 25)
    for i, line in enumerate(credits):
        d.text((pad, y + 150 + i * 36), line, font=fc, fill=(150, 152, 158))
    card.save(out)
    return card.size, None


# --------------------------------------------------------------------------
# PDF

def write_pdf(png, pdf, dpi=300):
    """Wrap a PNG in a one-page PDF without re-encoding a single pixel.

    Pillow's own PDF writer puts RGB through DCTDecode - JPEG - so a plate
    saved that way is no longer the plate that was rendered. Flate is zlib,
    which the standard library already has, so the lossless path costs a
    dependency of nothing (AGENTS never-7).
    """
    import zlib                      # noqa: PLC0415

    im = Image.open(png).convert("RGB")
    w, h = im.size
    raw = zlib.compress(im.tobytes(), 9)
    pw, ph = w * 72.0 / dpi, h * 72.0 / dpi

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
         "/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>"
         % (pw, ph)).encode(),
        None,                        # contents stream, built below
        None,                        # image stream, built below
    ]
    content = ("q %.2f 0 0 %.2f 0 0 cm /Im0 Do Q" % (pw, ph)).encode()
    objs[3] = (b"<< /Length %d >>\nstream\n" % len(content) + content
               + b"\nendstream")
    objs[4] = (("<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                "/ColorSpace /DeviceRGB /BitsPerComponent 8 "
                "/Filter /FlateDecode /Length %d >>\nstream\n"
                % (w, h, len(raw))).encode() + raw + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, start))
    Path(pdf).write_bytes(bytes(out))


# --------------------------------------------------------------------------

TITLES = {"esri2025": ("TUTUPAN LAHAN 2025",
                       ["Esri / Impact Observatory / Microsoft",
                        "Sentinel-2 10 m land cover, tahunan 2025"]),
          "dw2026": ("TUTUPAN LAHAN 2026",
                     ["Google / World Resources Institute",
                      "Dynamic World, Sentinel-2 10 m"]),
          "dw2026conf": ("TUTUPAN LAHAN 2026 + KEYAKINAN",
                         ["Google / World Resources Institute",
                          "Dynamic World, peluang rata-rata Mei-Agustus 2026",
                          "Pudar = margin juara atas runner-up < %.2f"
                          % MARGIN_MIN]),
          "truecolor": ("WARNA ASLI 2026",
                        ["Sentinel-2 SR, komposit median Mei-September 2026",
                         "Masking awan Cloud Score+ cs_cdf >= 0,6"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lulc", default="esri2025",
                    choices=["esri2025", "dw2026", "dw2026conf",
                             "truecolor"])
    ap.add_argument("--view", default="plan", choices=["plan", "oblique"])
    ap.add_argument("--fetch", action="store_true",
                    help="pull any missing input from Earth Engine first")
    ap.add_argument("--size", default=None, metavar="WxH",
                    help="output plate size; the defaults are the pairs "
                         "observed to converge, see TILE/SIZE")
    ap.add_argument("--no-admin", action="store_true",
                    help="leave off the desa boundary and label overlay "
                         "(plan view only; the oblique plate has no grid "
                         "rectangle to place them by)")
    ap.add_argument("--pdf", action="store_true",
                    help="also write a lossless PDF beside the PNG")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.fetch:
        print("fetching:")
        fetch(args.lulc)
    missing = [p for p in (CACHE / SOURCES[args.lulc]["dem"],)
               if not p.exists()]
    if missing:
        raise SystemExit("missing cache: %s\nrun once with --fetch"
                         % ", ".join(str(p) for p in missing))

    size = SIZE[args.view]
    if args.size:
        size = tuple(int(v) for v in args.size.lower().split("x"))

    height = load_dem(args.lulc)
    rgb, land, lc, palette = surface(args.lulc, height.shape)
    px, py, n_hot, span = hotspots(height.shape)
    # The renderer's tone curve compresses bright albedo, so a "vivid" input
    # lands muted. These are chosen for what comes out, not what goes in.
    layers = ([(150.0, (0.94, 0.09, 0.05), 3.0),
               (62.0, (1.00, 0.42, 0.04), 2.6),
               (26.0, (1.00, 0.93, 0.38), 2.2)] if args.view == "plan" else
              [(240.0, (0.95, 0.20, 0.02), 3.0),
               (96.0, (1.0, 0.55, 0.06), 3.0),
               (42.0, (1.0, 0.95, 0.72), 2.2)])
    rgb = burn_in(rgb, land, px, py, layers, SOURCES[args.lulc]["scale"])
    print("hotspots in frame: %d (%s .. %s)" % (n_hot, span[0], span[1]))

    plate = render(args.lulc, args.view, height, rgb, land, size)
    title2, credits = TITLES[args.lulc]
    credits = credits + ["Relief Copernicus GLO-30, dilebihkan %.1fx"
                         % (PLAN if args.view == "plan"
                            else OBLIQUE)["exaggeration"]]
    if args.view == "plan":
        # The oblique plate states the count and the span in its subtitle;
        # repeating them in the credits is what overran the footer.
        credits += ["%d titik panas VIIRS + MODIS" % n_hot,
                    "%s sampai %s" % span]
    credits += ["Dirender dengan forge3d"]

    out = args.out or (CACHE / ("biak_%s_%s.png" % (args.lulc, args.view)))
    if args.view == "plan":
        dims, _ = compose_plan(plate, lc, palette, credits, title2, out,
                               admin=not args.no_admin,
                               grid_shape=height.shape)
    else:
        dims, _ = compose_oblique(plate, credits,
                                  "%d titik panas, %s sampai %s"
                                  % (n_hot, span[0], span[1]), out)
    print("wrote %s  %dx%d" % (out, dims[0], dims[1]))
    if args.pdf:
        pdf = Path(out).with_suffix(".pdf")
        write_pdf(Path(out), pdf)
        print("wrote %s  %.1f MB" % (pdf, pdf.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
