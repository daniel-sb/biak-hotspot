"""Render a Biak poster plate with forge3d: terrain, a draped surface, hotspots.

    python scripts/render_biak_poster.py [--fetch] [--lulc SOURCE] [--view V]

    --lulc  esri2025 | dw2026 | truecolor      what gets draped on the relief
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


def load_dem():
    return np.load(CACHE / "biak_dem30.npy")["DEM"].astype("float32")


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
        land = load_dem() > 0.5
        return rgb, land, None, None

    if source == "esri2025":
        lc = np.load(CACHE / "biak_lulc30_2025.npy")["lc"].astype("uint8")
        palette, water, nodata = ESRI, 1, 0
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


def burn_in(rgb, land, px, py, layers):
    m = np.zeros(rgb.shape[:2], "float32")
    np.add.at(m, (py, px), 1.0)
    for sigma, col, amp in layers:
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


def render(view, height, rgb, land, size):
    import forge3d as f3d           # noqa: PLC0415

    Wpx, Hpx = size
    hh = ndimage.gaussian_filter(height, 1.1).astype("float32")
    spacing = GRID_M
    if view == "oblique":
        # Oblique rays over the full 30 m grid at this exaggeration drive the
        # tracer's ReSTIR reuse into "no valid reservoirs" and the render
        # fails outright. Halving the grid clears it and costs nothing
        # visible: the plate is 2400 px across 80 km, coarser than 60 m.
        hh, rgb = hh[::2, ::2].copy(), rgb[::2, ::2].copy()
        land = land[::2, ::2]
        spacing = GRID_M * 2
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

SEA = np.array([138, 136, 130])
BG = np.array([52, 52, 52])


def key_out(plate):
    """Mask of everything outside the coastline: open sea, and the page.

    Flooded from the frame border rather than thresholded, so water enclosed
    by land survives. The sea plane stops at the DEM's own edge and that edge
    draws a hairline across the page; five pixels of dilation swallow it
    without reaching the coast, hundreds of pixels away.
    """
    a = plate.astype(np.int16)
    flat = ((np.abs(a - SEA).max(axis=2) <= 5)
            | (np.abs(a - BG).max(axis=2) <= 5))
    lab, _ = ndimage.label(flat)
    edge = set(np.unique(np.concatenate(
        [lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    return ndimage.binary_dilation(np.isin(lab, list(edge)),
                                   np.ones((5, 5), bool))


def sampled_colours(plate, outside, lc):
    """Median rendered colour per class, keyed by class code.

    The path tracer applies a tone curve - it compresses bright albedo hard
    and lifts dark albedo - so a legend quoting the colours handed *in* would
    misdescribe the map. The sea plane's own rectangle inside the plate gives
    the grid-to-pixel mapping needed to read the colours back out.
    """
    a = plate.astype(np.int16)
    ys, xs = np.where(np.abs(a - SEA).max(axis=2) <= 5)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
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


def _spaced(d, xy, text, font, fill, extra):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + extra


def compose_plan(plate, lc, palette, credits, title2, out):
    outside = key_out(plate)
    # Read the class colours off the plate while the sea is still on it: the
    # calibration rectangle IS the sea plane, and painting it over first
    # leaves only enclosed water to find, which is a different rectangle and
    # a silently wrong mapping.
    got = sampled_colours(plate, outside, lc) if lc is not None else {}
    plate = plate.copy()
    plate[outside] = CREAM
    nland = int((~outside).sum()) if lc is None else int(
        sum((lc == c).sum() for c in palette if c in got))

    CW, CH = 3240, 2200
    card = Image.new("RGB", (CW, CH), CREAM)
    card.paste(Image.fromarray(plate), (110, 100))
    d = ImageDraw.Draw(card)
    d.rectangle([46, 46, CW - 47, CH - 47], outline=(206, 199, 184), width=3)

    tx, ty = 2600, 660
    _spaced(d, (tx, ty), "BIAK", _font("ARIALN.TTF", 128), INK, 15)
    _spaced(d, (tx, ty + 162), title2, _font("ARIALN.TTF", 44), INK, 3)
    fc = _font("arial.ttf", 24)
    for i, line in enumerate(credits):
        d.text((tx + 3, ty + 232 + i * 34), line, font=fc, fill=MUTE)

    fl, fn = _font("arial.ttf", 28), _font("arial.ttf", 21)
    y = ty + 500
    row, dropped = 0, []
    entries = [("HOT", "Titik panas", (196, 116, 58), None)]
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
        d.ellipse([tx + 4, y + row * 58, tx + 36, y + row * 58 + 32], fill=col)
        text = label if share is None else "%s   %.1f%%" % (label, share)
        d.text((tx + 60, y + row * 58 + 1), text, font=fl, fill=INK)
        row += 1
    if dropped:
        d.text((tx + 4, y + row * 58 + 18),
               "Di bawah 0,1% daratan, tidak dilegendakan:", font=fn, fill=MUTE)
        for j in range(0, len(dropped), 2):
            d.text((tx + 4, y + row * 58 + 44 + (j // 2) * 26),
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

TITLES = {"esri2025": ("TUTUPAN LAHAN 2025",
                       ["Esri / Impact Observatory / Microsoft",
                        "Sentinel-2 10 m land cover, tahunan 2025"]),
          "dw2026": ("TUTUPAN LAHAN 2026",
                     ["Google / World Resources Institute",
                      "Dynamic World, Sentinel-2 10 m"]),
          "truecolor": ("WARNA ASLI 2026",
                        ["Sentinel-2 SR, komposit median Mei-September 2026",
                         "Masking awan Cloud Score+ cs_cdf >= 0,6"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lulc", default="esri2025",
                    choices=["esri2025", "dw2026", "truecolor"])
    ap.add_argument("--view", default="plan", choices=["plan", "oblique"])
    ap.add_argument("--fetch", action="store_true",
                    help="pull any missing input from Earth Engine first")
    ap.add_argument("--size", default=None, metavar="WxH",
                    help="output plate size; the defaults are the pairs "
                         "observed to converge, see TILE/SIZE")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.fetch:
        print("fetching:")
        fetch(args.lulc)
    missing = [p for p in (CACHE / "biak_dem30.npy",) if not p.exists()]
    if missing:
        raise SystemExit("missing cache: %s\nrun once with --fetch"
                         % ", ".join(str(p) for p in missing))

    size = SIZE[args.view]
    if args.size:
        size = tuple(int(v) for v in args.size.lower().split("x"))

    height = load_dem()
    rgb, land, lc, palette = surface(args.lulc, height.shape)
    px, py, n_hot, span = hotspots(height.shape)
    layers = ([(3.5, (0.663, 0.216, 0.106), 2.4),
               (1.3, (0.902, 0.412, 0.078), 2.0)] if args.view == "plan" else
              [(4.0, (0.95, 0.20, 0.02), 3.0), (1.6, (1.0, 0.55, 0.06), 3.0),
               (0.7, (1.0, 0.95, 0.72), 2.2)])
    rgb = burn_in(rgb, land, px, py, layers)
    print("hotspots in frame: %d (%s .. %s)" % (n_hot, span[0], span[1]))

    plate = render(args.view, height, rgb, land, size)
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
        dims, _ = compose_plan(plate, lc, palette, credits, title2, out)
    else:
        dims, _ = compose_oblique(plate, credits,
                                  "%d titik panas, %s sampai %s"
                                  % (n_hot, span[0], span[1]), out)
    print("wrote %s  %dx%d" % (out, dims[0], dims[1]))


if __name__ == "__main__":
    main()
