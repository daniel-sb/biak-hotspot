"""Himawari-9 evening coverage (Task 05; PLAN.md section 12).

Between 15:00 and 00:31 WIT no polar-orbiting satellite passes over Biak.
Himawari-9 scans the full disk every 10 minutes and is the only open-access
sensor covering those hours. This module pulls AHI L1b band-segments from the
public AWS bucket `noaa-himawari9` (plain HTTPS, no credentials), reads the
HSD binary with a minimal in-house reader, converts counts to brightness
temperature with the coefficients stored in each file, flags thermal
anomalies, and writes `data/processed/himawari_evening_{WIT-date}.csv`.

Wording discipline (binding, PLAN.md 12 and the task file): AHI at 2 km sees
only larger or hotter fires - a 28-fold pixel-area gap against VIIRS 375 m.
Never present a Himawari flag as equivalent to a FIRMS detection; never read
an unflagged slot as "nothing was burning". This is the first observation of
any kind during the evening hours: partial coverage replacing none.

Usage:
    python src/himawari.py [--date YYYY-MM-DD] [--firms-check]
"""
import argparse
import bz2
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

from ingest_firms import WIT, land_hits, load_boundaries

ROOT = Path(__file__).resolve().parents[1]
BUCKET = "https://noaa-himawari9.s3.amazonaws.com"
HSD_PREFIX = "AHI-L1b-FLDK"
BANDS = ("B07", "B14")            # 3.9 um fire band + 11.2 um clean window

log = logging.getLogger("himawari")


# --------------------------------------------------------------------------
# HSD reading. Minimal reader for what this task needs: navigation, calendar,
# calibration, counts. Little-endian; blocks are [I1 number][I2 length] + body.
# Coefficients (gain, offset, Planck constants, c-triplet) all come from the
# file - they are updated over the instrument's life, never hardcoded.
# --------------------------------------------------------------------------
def _u2(buf, o):
    return int.from_bytes(buf[o:o + 2], "little")


def _u4(buf, o):
    return int.from_bytes(buf[o:o + 4], "little")


def _f4(buf, o):
    return struct_f4(buf, o)


def _f8(buf, o):
    return struct_f8(buf, o)


def struct_f4(buf, o):
    import struct as _s
    return _s.unpack_from("<f", buf, o)[0]


def struct_f8(buf, o):
    import struct as _s
    return _s.unpack_from("<d", buf, o)[0]


MJD_EPOCH = datetime(1858, 11, 17, tzinfo=timezone.utc)


def read_hsd(path: Path) -> dict:
    """One HSD band-segment file -> header fields + count array.

    Returns dict with: time (UTC), sub_lon, cfac, lfac, coff, loff, rs, re,
    rp, band, wl_um, valid_bits, count_error, count_outside, gain, offset,
    c0, c1, c2, seg_first_line, seg_seq, counts (nlines x ncols uint16).
    """
    raw = bz2.decompress(Path(path).read_bytes())
    total_header = _u4(raw, 70)
    hsd = {
        "time": MJD_EPOCH + timedelta(days=_f8(raw, 46)),
        "sub_lon": _f8(raw, 335),
        "cfac": _u4(raw, 343),
        "lfac": _u4(raw, 347),
        "coff": _f4(raw, 351),
        "loff": _f4(raw, 355),
        "rs": _f8(raw, 359),
        "re": _f8(raw, 367),
        "rp": _f8(raw, 375),
        "band": _u2(raw, 601),
        "wl_um": _f8(raw, 603),
        "valid_bits": _u2(raw, 611),
        "count_error": _u2(raw, 613),
        "count_outside": _u2(raw, 615),
        "gain": _f8(raw, 617),
        "offset": _f8(raw, 625),
        "c0": _f8(raw, 633),
        "c1": _f8(raw, 641),
        "c2": _f8(raw, 649),
        "c": _f8(raw, 681),
        "h": _f8(raw, 689),
        "k": _f8(raw, 697),
        "seg_seq": raw[1008],
        "seg_first_line": _u2(raw, 1009),
    }
    n_lines = _u2(raw, 289)
    n_cols = _u2(raw, 287)
    hsd["counts"] = np.frombuffer(raw, dtype="<u2",
                                  count=n_lines * n_cols,
                                  offset=total_header).reshape(n_lines, n_cols)
    return hsd


def counts_to_bt(hsd: dict) -> np.ndarray:
    """Counts -> radiance (file gain/offset) -> BT (file Planck + c-triplet).

    HSD v2 infrared counts are inverted (space at max count), hence the
    negative stored count-radiance slope. Invalid counts (error 65535 /
    outside scan 65534) become NaN. BT in Kelvin.
    """
    counts = hsd["counts"].astype(np.float64)
    invalid = (counts == hsd["count_error"]) | (counts == hsd["count_outside"])
    rad = hsd["gain"] * counts + hsd["offset"]
    wl_m = hsd["wl_um"] * 1e-6
    # HSD radiance unit is mW/(m2 sr cm-1); the Planck denominator needs
    # W/(m2 sr m): rad * 1e6 (mW->W, um**-1 -> m**-1 combined).
    b = (2.0 * hsd["h"] * hsd["c"] ** 2) / (rad * 1e6 * wl_m ** 5) + 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        a = hsd["h"] * hsd["c"] / (hsd["k"] * wl_m)
        te = a / np.log(b)
        bt = hsd["c0"] + hsd["c1"] * te + hsd["c2"] * te * te
    bt[invalid] = np.nan
    return bt


def lonlat_grid(hsd: dict, lines, cols):
    """Full-disk 1-based HSD line/col -> lon/lat via the normalised
    geostationary projection inverse (LRIT/HRIT 4.4): ray from the satellite
    through the pixel, intersected with the WGS84 ellipsoid. Parameters come
    from the navigation block. Lines increase southward from the subpoint,
    columns eastward."""
    sl = np.deg2rad(hsd["sub_lon"])
    rs, re, rp = hsd["rs"], hsd["re"], hsd["rp"]
    sin_sl, cos_sl = np.sin(sl), np.cos(sl)
    col = np.asarray(cols, dtype=float)
    lin = np.asarray(lines, dtype=float)
    thx = np.deg2rad((col - hsd["coff"]) * 65536.0 / hsd["cfac"])
    thy = np.deg2rad((lin - hsd["loff"]) * 65536.0 / hsd["lfac"])
    if thx.ndim == 1 and thy.ndim == 1:
        # caller passed 1-D (lines, cols) ranges: build the (lines, cols) grid
        thy, thx = np.meshgrid(thy, thx, indexing="ij")
    # Ray: east tilt = sin(thx)*east, south tilt = sin(thy)*south,
    # nadir component = cos(thx)*cos(thy).
    vx = -np.sin(thx) * sin_sl - np.cos(thx) * np.cos(thy) * cos_sl
    vy = np.sin(thx) * cos_sl - np.cos(thx) * np.cos(thy) * sin_sl
    vz = -np.sin(thy)
    S = rs * np.array([cos_sl, sin_sl, 0.0])
    a = (vx * vx + vy * vy) / (re * re) + (vz * vz) / (rp * rp)
    b = 2.0 * (S[0] * vx + S[1] * vy) / (re * re)
    c = rs * rs / (re * re) - 1.0
    with np.errstate(invalid="ignore"):
        t = (-b - np.sqrt(b * b - 4 * a * c)) / (2 * a)
    px = S[0] + t * vx
    py = S[1] + t * vy
    pz = t * vz
    lon = np.degrees(np.arctan2(py, px))
    lat = np.degrees(np.arctan2(pz * re * re, np.hypot(px, py) * rp * rp))
    return lon, lat


def locate_aoi(hsd: dict, bbox, pad: int = 8) -> tuple[set, int, int, int, int]:
    """Which HSD segment(s) does the AOI bbox cover, and the AOI line/col
    window in full-disk coordinates. Computed from the navigation block -
    never hardcoded; callers assert against the expected value."""
    w, s, e, n = bbox
    seg_first = hsd["seg_first_line"]
    seg_lines = hsd["counts"].shape[0]
    cand_lines = np.arange(max(1, seg_first - pad - 600),
                           min(5500, seg_first + seg_lines + 600), 4.0)
    cand_cols = np.arange(1, 5501, 4.0)
    L, C = np.meshgrid(cand_lines, cand_cols, indexing="ij")
    lon, lat = lonlat_grid(hsd, L, C)
    inside = np.isfinite(lon) & (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)
    if not inside.any():
        return set(), 0, 0, 0, 0
    lines_in = L.ravel()[inside.ravel()]
    cols_in = C.ravel()[inside.ravel()]
    line0, line1 = int(lines_in.min()) - pad, int(lines_in.max()) + pad
    col0, col1 = int(cols_in.min()) - pad, int(cols_in.max()) + pad
    segments = {((ln - 1) // 550) + 1 for ln in (line0, line1)}
    return segments, line0, line1, col0, col1


def segment_window(hsd: dict, line0: int, line1: int, col0: int, col1: int):
    """Clip the full-disk AOI window to one segment's rows.
    Returns (row0_in_segment, row1_excl, col0_1based, col1_excl, first_line)."""
    seg_first = hsd["seg_first_line"]
    seg_last = seg_first + hsd["counts"].shape[0] - 1
    lo, hi = max(line0, seg_first), min(line1, seg_last)
    return lo - seg_first, hi - seg_first + 1, col0 - 1, col1, lo


def is_night(wit_minutes: int, sunset_wit_minutes: int) -> bool:
    """True outside daylight: at or after sunset (18:15 WIT) or before
    ~05:00 WIT (pre-dawn; covers the past-midnight part of the window).
    Daytime rows are recorded but labelled unreliable (reflected sunlight
    contaminates B07)."""
    return wit_minutes >= sunset_wit_minutes or wit_minutes <= 5 * 60


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------
def slot_key(slot_utc: datetime, band: str, segment: int) -> str:
    return (f"{HSD_PREFIX}/{slot_utc:%Y/%m/%d/%H%M}/"
            f"HS_H09_{slot_utc:%Y%m%d}_{slot_utc:%H%M}_{band}_FLDK_R20_"
            f"S{segment:02d}10.DAT.bz2")


def fetch_slot_file(slot_utc: datetime, band: str, segment: int,
                    raw_dir: Path) -> Path | None:
    """Download one band-segment into raw_dir (persist before parsing).
    Returns the local path, or None if the slot does not exist upstream
    (latency 10-16 min; slots at the window edge can legitimately be absent)."""
    key = slot_key(slot_utc, band, segment)
    dest = raw_dir / key.split("/")[-1]
    if dest.exists():
        return dest
    r = requests.get(BUCKET + "/" + key, timeout=300)
    if r.status_code != 200 or len(r.content) < 10000:
        log.warning("missing/unusable upstream: %s (HTTP %s, %s bytes)",
                    key, r.status_code, len(r.content))
        return None
    dest.write_bytes(r.content)
    return dest


# --------------------------------------------------------------------------
# Anomaly flagging - deliberately simple (no Giglio, no cloud mask)
# --------------------------------------------------------------------------
def flag_anomalies(bt07: np.ndarray, bt14: np.ndarray, min_anomaly_k: float,
                   min_diff_k: float, bg_window: int = 15):
    """bt07_background = nanmedian of a bg_window x bg_window neighbourhood
    excluding the pixel itself; anomaly = pixel - background; flagged =
    (anomaly > min_anomaly_k) AND (bt07 - bt14 > min_diff_k). Thresholds are
    provisional - say so wherever they surface."""
    from numpy.lib.stride_tricks import sliding_window_view
    wr = bg_window // 2
    h, w = bt07.shape
    if h < bg_window or w < bg_window:
        raise ValueError(f"grid {bt07.shape} smaller than window {bg_window}")
    win = sliding_window_view(bt07, (bg_window, bg_window))
    keep = np.ones((bg_window, bg_window), dtype=bool)
    keep[wr, wr] = False                     # exclude the pixel itself
    flat = win.reshape(win.shape[0], win.shape[1], -1)
    with np.errstate(invalid="ignore"):
        background = np.nanmedian(
            np.where(keep.ravel()[None, None, :], flat, np.nan), axis=-1)
    background_full = np.full(bt07.shape, np.nan)
    background_full[wr:wr + h - bg_window + 1, wr:wr + w - bg_window + 1] = \
        background
    anomaly = bt07 - background_full
    diff = bt07 - bt14
    flagged = (anomaly > min_anomaly_k) & (diff > min_diff_k)
    flagged[~np.isfinite(anomaly) | ~np.isfinite(diff)] = False
    return background_full, anomaly, diff, flagged


# --------------------------------------------------------------------------
# Daily run
# --------------------------------------------------------------------------
def _slot_list(day_utc: date, window_utc, cadence_min: int):
    start = datetime.combine(day_utc,
                             datetime.strptime(window_utc[0], "%H:%M").time(),
                             tzinfo=timezone.utc)
    end = datetime.combine(day_utc,
                           datetime.strptime(window_utc[1], "%H:%M").time(),
                           tzinfo=timezone.utc)
    out, t = [], start
    while t <= end:
        out.append(t)
        t += timedelta(minutes=cadence_min)
    return out


def wit_date(day_utc: date) -> date:
    """The covered evening is the WIT date whose 15:00 starts the window."""
    return (datetime.combine(day_utc, datetime.min.time(),
                             tzinfo=timezone.utc) + timedelta(hours=9)).date()


def _slot_rows(sub07, sub14, lon_g, lat_g, land_grid, ocean_pixels,
               utc, wit, night, min_anomaly_k, min_diff_k, bg_window):
    """One slot's grids -> output rows: every land pixel plus the fixed
    ocean-sample pixels (marked ocean_sample, never counted as AOI)."""
    bg, anom, diff, flagged = flag_anomalies(sub07, sub14, min_anomaly_k,
                                             min_diff_k, bg_window)
    rows = []
    for i, j in ocean_pixels:
        rows.append({
            "acq_time_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "acq_time_wit": wit.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
            "lat": round(float(lat_g[i, j]), 5),
            "lon": round(float(lon_g[i, j]), 5),
            "bt07": round(float(sub07[i, j]), 3),
            "bt14": round(float(sub14[i, j]), 3),
            "bt07_minus_bt14": round(float(diff[i, j]), 3),
            "bt07_background": (round(float(bg[i, j]), 3)
                                if np.isfinite(bg[i, j]) else None),
            "bt07_anomaly": (round(float(anom[i, j]), 3)
                             if np.isfinite(anom[i, j]) else None),
            "is_night": night,
            "flagged": bool(flagged[i, j]),
            "ocean_sample": True,
        })
    for i in range(sub07.shape[0]):
        for j in range(sub07.shape[1]):
            if not land_grid[i, j]:
                continue
            if not np.isfinite(sub07[i, j]):
                continue
            rows.append({
                "acq_time_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "acq_time_wit": wit.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
                "lat": round(float(lat_g[i, j]), 5),
                "lon": round(float(lon_g[i, j]), 5),
                "bt07": round(float(sub07[i, j]), 3),
                "bt14": round(float(sub14[i, j]), 3),
                "bt07_minus_bt14": round(float(diff[i, j]), 3),
                "bt07_background": (round(float(bg[i, j]), 3)
                                    if np.isfinite(bg[i, j]) else None),
                "bt07_anomaly": (round(float(anom[i, j]), 3)
                                 if np.isfinite(anom[i, j]) else None),
                "is_night": night,
                "flagged": bool(flagged[i, j]),
                "ocean_sample": False,
            })
    return rows


def build_date(day_utc: date, cfg: dict, root: Path) -> dict:
    """Fetch, read, flag and store one evening window. Returns a summary."""
    raw_dir = root / "data" / "raw" / "himawari"
    raw_dir.mkdir(parents=True, exist_ok=True)
    bbox = [float(v) for v in cfg["aoi_bbox_wsen"]]
    cadence = int(cfg["himawari_cadence_minutes"])
    window = cfg["himawari_window_utc"]
    sunset = int(cfg["himawari_sunset_wit"].replace(":", ""))
    hh, mm = divmod(sunset, 100)
    sunset_min = hh * 60 + mm
    min_anomaly = float(cfg["himawari_min_anomaly_k"])
    min_diff = float(cfg["himawari_min_bt_diff_k"])
    bg_window = int(cfg["himawari_background_window_px"])
    expected_segments = {int(s) for s in cfg["himawari_expected_segments"]}
    sample_cap = int(cfg.get("himawari_ocean_sample_pixels", 300))

    boundaries = None
    if cfg.get("admin_polygon"):
        admin_path = root / cfg["admin_polygon"]
        if not admin_path.exists():
            sys.exit(f"admin_polygon from config.yaml not found: {admin_path}")
        boundaries = load_boundaries(admin_path)

    slots = _slot_list(day_utc, window, cadence)
    nav = None
    segments: set = set()
    line0 = line1 = col0 = col1 = 0
    land_grids: dict = {}
    ocean_by_seg: dict = {}
    rows = []
    for slot in slots:
        if nav is None:
            probe = None
            for seg in sorted(expected_segments):
                probe = fetch_slot_file(slot, "B07", seg, raw_dir)
                if probe is not None:
                    break
            if probe is None:
                log.warning("%s: nothing upstream; slot skipped", slot)
                continue
            nav = read_hsd(probe)
            segments, line0, line1, col0, col1 = locate_aoi(nav, bbox)
            if segments != expected_segments:
                sys.exit(f"SEGMENT ASSERTION FAILED: AOI resolves to "
                         f"{sorted(segments)}, expected "
                         f"{sorted(expected_segments)} - product layout "
                         "changed? Investigate before trusting any output.")
            log.info("AOI: segments %s, lines %d-%d, cols %d-%d",
                     sorted(segments), line0, line1, col0, col1)
        slot_rows = []
        for segment in sorted(segments):
            paths = {}
            for band in BANDS:
                p = fetch_slot_file(slot, band, segment, raw_dir)
                if p is None:
                    log.warning("%s %s seg%d missing upstream", slot, band,
                                segment)
                paths[band] = p
            if paths["B07"] is None or paths["B14"] is None:
                continue
            hsd7 = read_hsd(paths["B07"])
            bt07 = counts_to_bt(hsd7)
            bt14 = counts_to_bt(read_hsd(paths["B14"]))
            r0, r1, c0, c1, _ = segment_window(hsd7, line0, line1,
                                               col0, col1)
            sub07 = bt07[r0:r1, c0:c1]
            sub14 = bt14[r0:r1, c0:c1]
            lon_g, lat_g = lonlat_grid(hsd7,
                                       np.arange(r0, r1) + hsd7["seg_first_line"],
                                       np.arange(c0, c1))
            utc = slot
            wit = utc.astimezone(WIT)
            night = is_night(wit.hour * 60 + wit.minute, sunset_min)
            # The land test runs once per segment: the AOI window is
            # identical for every slot, so the land/ocean pixel split and
            # the fixed ocean sample are computed exactly once per segment.
            if segment not in land_grids:
                if boundaries is None:
                    land_grid = np.ones(sub07.shape, dtype=bool)
                    ocean_pixels = []
                else:
                    land_grid = np.array(
                        [hit is not None for hit in land_hits(
                            lon_g.ravel(), lat_g.ravel(), boundaries)]
                    ).reshape(sub07.shape)
                    ocean = [(i, j) for i in range(sub07.shape[0])
                             for j in range(sub07.shape[1])
                             if not land_grid[i, j]]
                    stride = max(1, len(ocean) // sample_cap)
                    ocean_pixels = ocean[::stride][:sample_cap]
                land_grids[segment] = land_grid
                ocean_by_seg[segment] = ocean_pixels
                log.info("seg%d: %d land px, %d ocean px, ocean sample %d px",
                         segment, int(land_grid.sum()), len(ocean),
                         len(ocean_pixels))
            land_grid = land_grids[segment]
            ocean_pixels = ocean_by_seg[segment]
            rows.extend(_slot_rows(sub07, sub14, lon_g, lat_g, land_grid,
                                   ocean_pixels, utc, wit, night,
                                   min_anomaly, min_diff, bg_window))

    processed = root / cfg["output_paths"]["processed"]
    processed.parent.mkdir(parents=True, exist_ok=True)
    out = processed.parent / f"himawari_evening_{wit_date(day_utc)}.parquet"
    frame = pd.DataFrame(rows)
    frame.to_parquet(out, index=False)
    size_mb = out.stat().st_size / 1e6
    flagged_n = int(frame["flagged"].sum()) if len(frame) else 0
    if size_mb >= 2.0:
        log.warning("evening file is %.2f MB (>= 2 MB) - the pixel count is "
                    "still wrong, not a compression problem", size_mb)
    log.info("himawari evening %s: %d slots, %d rows (%.2f MB), %d flagged "
             "-> %s", wit_date(day_utc), len(slots), len(frame), size_mb,
             flagged_n, out.relative_to(root))
    return {"parquet": out, "rows": len(frame), "flagged": flagged_n,
            "size_mb": round(size_mb, 3)}


# --------------------------------------------------------------------------
# FIRMS cross-check (the most important check in the task)
# --------------------------------------------------------------------------
def firms_crosscheck(cfg: dict, root: Path, store_path: Path) -> dict:
    """Brightest stored detection, nearest Himawari slot, actual pixel vs
    background BT. The numbers are reported; if no anomaly shows up, say so -
    do not tune thresholds until one appears."""
    store = pd.read_parquet(store_path)
    store = store[store["frp"] > 0].sort_values("frp", ascending=False)
    if store.empty:
        raise ValueError("store has no detections to cross-check")
    top = store.iloc[0]
    acq = datetime.strptime(str(top["acq_date"]) + str(top["acq_time"]).zfill(4),
                            "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
    slot = acq.replace(minute=round(acq.minute / 10.0) * 10 % 60,
                       second=0, microsecond=0)
    raw_dir = root / "data" / "raw" / "himawari"
    bbox = [float(v) for v in cfg["aoi_bbox_wsen"]]
    probe = fetch_slot_file(slot, "B07", 5, raw_dir) or \
        fetch_slot_file(slot, "B07", 6, raw_dir)
    if probe is None:
        raise FileNotFoundError(f"upstream slot missing: {slot}")
    hsd = read_hsd(probe)
    segments, line0, line1, col0, col1 = locate_aoi(hsd, bbox)
    best = None
    for segment in sorted(segments):
        p7 = fetch_slot_file(slot, "B07", segment, raw_dir)
        p14 = fetch_slot_file(slot, "B14", segment, raw_dir)
        if p7 is None or p14 is None:
            continue
        h7 = read_hsd(p7)
        sub07 = counts_to_bt(h7)
        sub14 = counts_to_bt(read_hsd(p14))
        r0, r1, c0, c1, _ = segment_window(h7, line0, line1, col0, col1)
        sub07 = sub07[r0:r1, c0:c1]
        sub14 = sub14[r0:r1, c0:c1]
        lon_g, lat_g = lonlat_grid(h7,
                                   np.arange(r0, r1) + h7["seg_first_line"],
                                   np.arange(c0, c1))
        dist = (lon_g - float(top["longitude"])) ** 2 + \
            (lat_g - float(top["latitude"])) ** 2
        r, c = np.unravel_index(np.nanargmin(dist), dist.shape)
        bg, anom, diff, flagged = flag_anomalies(sub07, sub14, 10.0, 10.0, 15)
        cand = {"segment": segment, "dist": float(dist[r, c]),
                "row": int(r), "col": int(c),
                "lat": round(float(lat_g[r, c]), 4),
                "lon": round(float(lon_g[r, c]), 4),
                "bt07": float(sub07[r, c]), "bt14": float(sub14[r, c]),
                "bg": float(bg[r, c]), "diff": float(diff[r, c]),
                "flagged": bool(flagged[r, c])}
        if best is None or cand["dist"] < best["dist"]:
            best = cand
    result = {
        "detection": {"lat": best["lat"], "lon": best["lon"],
                      "frp_mw": round(float(top["frp"]), 2),
                      "acq_utc": f"{top['acq_date']} {top['acq_time']}"},
        "slot_utc": slot.strftime("%Y-%m-%dT%H:%MZ"),
        "segment": best["segment"],
        "pixel_bt07_k": round(best["bt07"], 2),
        "background_bt07_k": round(best["bg"], 2),
        "difference_k": round(best["bt07"] - best["bg"], 2),
        "bt07_minus_bt14_k": round(best["diff"], 2),
        "pixel_bt14_k": round(best["bt14"], 2),
        "flagged_by_thresholds": best["flagged"],
    }
    log.info("FIRMS cross-check: %s", result)
    return result


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Himawari-9 evening coverage.")
    ap.add_argument("--date", help="UTC date of the evening window "
                                   "(default: yesterday UTC)")
    ap.add_argument("--firms-check", action="store_true",
                    help="also run the FIRMS cross-check (needs network)")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    day = date.fromisoformat(args.date) if args.date \
        else (datetime.now(timezone.utc) - timedelta(days=1)).date()
    if args.firms_check:
        store = root / cfg["output_paths"]["processed"]
        firms_crosscheck(cfg, root, store)
    build_date(day, cfg, root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
