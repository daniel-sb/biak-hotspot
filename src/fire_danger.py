"""Fire danger indices, and whether they rank burning days (Task 21,
PLAN.md Phase 5 step 1).

Computes the Canadian Fire Weather Index system (FFMC, DMC, DC, ISI, BUI,
FWI) and the Keetch-Byram Drought Index per ERA5-Land land cell per WIT
day for the AOI, from a 2022-09-01 spin-up forward, and scores them the
way Task 17 scored the detection climatology: leave one calendar year
out, average precision only.

What these indices are and are not, binding on every field here:
  - FWI and KBDI describe how weather has dried the fuel. They say
    nothing about whether anyone burned land, or why (PLAN.md sections 8
    and 14). No field names a cause or a person.
  - They were built for Canadian conifer forest. The equatorial
    day-length adjustment is applied; nothing is calibrated for this
    island's fuels. The honest outcome may be that the indices rank
    burning days no better than the calendar does - that is a result.
  - Scoring is average precision only, no Brier score: the indices are
    not probabilities, and turning them into probabilities is fitting a
    model, which is Phase 5 step 3.

Weather: ECMWF/ERA5_LAND/HOURLY via Earth Engine, fetched only with
--fetch <project>, one calendar month per request, each response
persisted under data/raw/era5land/ BEFORE parsing (AGENTS always-2).
Catalogue facts verified 2026-09-22 against the asset's catalogue page,
stated here because the rain sums depend on them:
  - temperature_2m and dewpoint_temperature_2m: Kelvin, instantaneous;
  - u_component_of_wind_10m and v_component_of_wind_10m: m/s,
    instantaneous;
  - total_precipitation accumulates from the beginning of the forecast
    and resets at midnight, so the fetch uses total_precipitation_hourly,
    which GEE disaggregates between consecutive forecast steps: a value
    stamped t covers the hour ENDING at t. The 24 values stamped 04:00
    UTC D-1 through 03:00 UTC D cover exactly
    [03:00 UTC D-1, 03:00 UTC D].
  - WIT (UTC+9) noon is 03:00 UTC; solar noon at 136E falls within about
    10 minutes of it. Noon local time is the FWI standard observation
    time.
  - the latest hour the asset holds is read live at fetch time and
    stored in the raw files; days after it are absent, not dry (AGENTS
    never-2).

Cells: the ERA5-Land native 0.1-degree lat-lon grid - centres at
-179.95 + 0.1*k longitude and -89.95 + 0.1*k latitude, so cell edges lie
at multiples of 0.1 degrees. Kept: squares overlapping the admin_polygon
union on positive area whose centre the land-only asset covers. A few
dozen expected.

The FWI equations are transcribed from the cffdrs R source (the canonical
implementation of Van Wagner and Pickett 1985; files fine_fuel_moisture_code.r,
duff_moisture_code.r, drought_code.r, initial_spread_index.r,
buildup_index.r, fire_weather_index.r, read 2026-09-22), implemented in
numpy - no fire-weather package (AGENTS never-7). The moisture
coefficient is 147.2 as in the 1985 report. Day-length factors are
function arguments so the published Canadian test day can pass its April
values directly; the AOI run passes the equatorial constants from config
(Lawson and Armitage 2008: Le 9.0, Lf 1.39 for 10S-10N; the cffdrs
latitude adjustment uses 1.4).

Writes data/processed/fire_danger.json (sorted keys, indent 1, no
timestamp, deterministic). No FINDINGS.md entry (the Task 17 override):
the entry is written at review from the JSON.

    python src/fire_danger.py [--fetch <gcp-project-id>]

The ee import lives inside the fetch path only, so the offline part and
its tests run without Earth Engine and never touch the network.
"""
import argparse
import json
import math
import sys
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from baseline import (average_precision, day_of_year_365, doy_window,
                      instrument_groups, observed_days)
from ingest_firms import WIT

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "era5land"
OUT = ROOT / "data" / "processed" / "fire_danger.json"
DET = ROOT / "data" / "processed" / "detections.parquet"
MANIFEST = ROOT / "data" / "processed" / "run_manifest.json"
ASSET = "ECMWF/ERA5_LAND/HOURLY"
ANNUAL_RAIN_FILE = "ERA5L_kbdi_mean_annual_rain.json"

CAVEATS = [
    "FWI and KBDI describe how weather has dried the fuel. They say "
    "nothing about whether anyone burned land, or why (PLAN.md sections 8 "
    "and 14).",
    "The FWI system was built for Canadian conifer forest; the equatorial "
    "day-length adjustment is applied, but it has not been calibrated for "
    "this island's fuels.",
    "ERA5-Land is a reanalysis at 0.1 degree, about 11 km, over a few "
    "dozen land cells. It is not a station record.",
    "Average precision measures ranking only. The indices are not "
    "probabilities, and no calibration is claimed.",
]

INDEX_KEYS = ("ffmc", "dmc", "dc", "isi", "bui", "fwi", "kbdi",
              "days_since_rain")


# ---------------------------------------------------------------------------
# FWI system, transcribed from the cffdrs R implementation of Van Wagner
# and Pickett 1985 (fwi.r and its equation helpers)
# ---------------------------------------------------------------------------
def fine_fuel_moisture_code(ffmc0, temp, rh, wind, rain):
    """Fine Fuel Moisture Code, equations 1-10."""
    rh = 99.9999 if rh >= 100.0 else rh
    wmo = 147.2 * (101.0 - ffmc0) / (59.5 + ffmc0)          # Eq. 1
    if rain > 0.5:                                          # Eqs. 2, 3a/3b
        ra = rain - 0.5
        if wmo > 150.0:
            wmo = (wmo + 0.0015 * (wmo - 150.0) * (wmo - 150.0)
                   * math.sqrt(ra)
                   + 42.5 * ra * math.exp(-100.0 / (251.0 - wmo))
                   * (1.0 - math.exp(-6.93 / ra)))
        else:
            wmo = (wmo + 42.5 * ra * math.exp(-100.0 / (251.0 - wmo))
                   * (1.0 - math.exp(-6.93 / ra)))
    wmo = 250.0 if wmo > 250.0 else wmo
    ed = (0.942 * rh ** 0.679 + 11.0 * math.exp((rh - 100.0) / 10.0)
          + 0.18 * (21.1 - temp) * (1.0 - 1.0 / math.exp(rh * 0.115)))  # 4
    ew = (0.618 * rh ** 0.753 + 10.0 * math.exp((rh - 100.0) / 10.0)
          + 0.18 * (21.1 - temp) * (1.0 - 1.0 / math.exp(rh * 0.115)))  # 5
    if wmo < ed and wmo < ew:                               # drying
        z = (0.424 * (1.0 - ((100.0 - rh) / 100.0) ** 1.7)
             + 0.0694 * math.sqrt(wind)
             * (1.0 - ((100.0 - rh) / 100.0) ** 8))         # Eq. 6a
        x = z * 0.581 * math.exp(0.0365 * temp)             # Eq. 6b
        wm = ew - (ew - wmo) / (10.0 ** x)                  # Eq. 8
    elif wmo > ed:                                          # wetting
        z = (0.424 * (1.0 - (rh / 100.0) ** 1.7)
             + 0.0694 * math.sqrt(wind) * (1.0 - (rh / 100.0) ** 8))  # 7a
        x = z * 0.581 * math.exp(0.0365 * temp)             # Eq. 7b
        wm = ed + (wmo - ed) / (10.0 ** x)                  # Eq. 9
    else:
        wm = wmo
    ffmc = 59.5 * (250.0 - wm) / (147.2 + wm)               # Eq. 10
    return min(101.0, max(0.0, ffmc))


def duff_moisture_code(dmc0, temp, rh, rain, le):
    """Duff Moisture Code, equations 11-16; day length Le an argument
    (Canadian April 12.8, equatorial 9.0 from config)."""
    temp = -1.1 if temp < -1.1 else temp
    rk = 1.894 * (temp + 1.1) * (100.0 - rh) * le * 1e-4    # Eq. 16
    if rain <= 1.5:
        pr = dmc0
    else:
        ra = rain
        rw = 0.92 * ra - 1.27                               # Eq. 11
        wmi = 20.0 + 280.0 / math.exp(0.023 * dmc0)         # alteration
        if dmc0 <= 33:
            b = 100.0 / (0.5 + 0.3 * dmc0)                  # Eq. 13a
        elif dmc0 <= 65:
            b = 14.0 - 1.3 * math.log(dmc0)                 # Eq. 13b
        else:
            b = 6.2 * math.log(dmc0) - 17.2                 # Eq. 13c
        wmr = wmi + 1000.0 * rw / (48.77 + b * rw)          # Eq. 14
        pr = 43.43 * (5.6348 - math.log(wmr - 20.0))        # Eq. 15 alt.
    pr = max(0.0, pr)
    return max(0.0, pr + rk)


def drought_code(dc0, temp, rain, lf):
    """Drought Code with the day-length factor Lf an argument
    (Canadian April 0.9 for the test; equatorial 1.39 from config)."""
    temp = -2.8 if temp < -2.8 else temp
    pe = (0.36 * (temp + 2.8) + lf) / 2.0                   # Eq. 22
    pe = max(0.0, pe)
    rw = 0.83 * rain - 1.27                                 # Eq. 18
    smi = 800.0 * math.exp(-dc0 / 400.0)                    # Eq. 19
    if rain <= 2.8:
        dr = dc0
    else:
        dr = max(0.0, dc0 - 400.0
                 * math.log(1.0 + 3.937 * rw / smi))        # Eqs. 20-21
    return max(0.0, dr + pe)                                # Eqs. 22-23


def initial_spread_index(ffmc, wind):
    fm = 147.2 * (101.0 - ffmc) / (59.5 + ffmc)             # Eq. 10
    fw = math.exp(0.05039 * wind)                           # Eq. 24
    ff = 91.9 * math.exp(-0.1386 * fm) \
        * (1.0 + fm ** 5.31 / 49300000.0)                   # Eq. 25
    return 0.208 * fw * ff                                  # Eq. 26


def buildup_index(dmc, dc):
    bui1 = 0.8 * dc * dmc / (dmc + 0.4 * dc)                # Eq. 27a
    p = 0.0 if dmc == 0 else (dmc - bui1) / dmc
    cc = 0.92 + (0.0114 * dmc) ** 1.7
    bui0 = max(0.0, dmc - cc * p)                           # Eq. 27b
    return bui0 if bui1 < dmc else bui1


def fire_weather_index(isi, bui):
    if bui > 80.0:
        bb = 0.1 * isi * (1000.0 / (25.0 + 108.64 / math.exp(0.023 * bui)))
    else:
        bb = 0.1 * isi * (0.626 * bui ** 0.809 + 2.0)       # Eqs. 28-29
    return bb if bb <= 1.0 else math.exp(2.72 * ((0.434 * math.log(bb))
                                                 ** 0.647))


def fwi_system_step(ffmc0, dmc0, dc0, temp, rh, wind, rain, le, lf):
    """One day, start codes to end codes. The day-length factors are
    arguments so the published Canadian test passes its April values
    directly."""
    ffmc = fine_fuel_moisture_code(ffmc0, temp, rh, wind, rain)
    dmc = duff_moisture_code(dmc0, temp, rh, rain, le)
    dc = drought_code(dc0, temp, rain, lf)
    isi = initial_spread_index(ffmc, wind)
    bui = buildup_index(dmc, dc)
    return ffmc, dmc, dc, isi, bui, fire_weather_index(isi, bui)


# ---------------------------------------------------------------------------
# KBDI (Keetch and Byram 1968), metric form, Q in mm of deficit, 0..203.2
# ---------------------------------------------------------------------------
def kbdi_step(q, tmax_c, rain_mm, run_rain, mean_rain, interception):
    """One day. Rain reduces Q by the NET rain - the first
    `interception` mm of each run of consecutive rainy days is
    intercepted, everything after it mm for mm, floored at 0 - then
    drying adds to Q, floored at 0 and capped at 203.2. dQ itself is
    floored at 0."""
    if rain_mm > 0:
        run_rain = run_rain + rain_mm
    else:
        run_rain = 0.0
    net = max(0.0, run_rain - interception)
    prev_net = max(0.0, run_rain - rain_mm - interception) \
        if rain_mm > 0 else 0.0
    q = max(0.0, q - (net - prev_net))
    dq = ((203.2 - q) * (0.968 * math.exp(0.0875 * tmax_c + 1.5552) - 8.30)
          / (1.0 + 10.88 * math.exp(-0.001736 * mean_rain))) * 1e-3
    q = min(203.2, max(0.0, q + max(0.0, dq)))
    return q, run_rain


# ---------------------------------------------------------------------------
# cells: the ERA5-Land native grid, offline
# ---------------------------------------------------------------------------
def native_cells(admin_path):
    """Candidate native ERA5-Land cells whose square overlaps the admin
    union on positive area. Centres at -179.95 + 0.1*k longitude and
    -89.95 + 0.1*k latitude; cell edges at multiples of 0.1 degrees.
    Cells whose centre is over sea return no values from the land-only
    asset and drop out at fetch time."""
    from shapely.geometry import box as sbox, shape
    from shapely.ops import unary_union
    from shapely.prepared import prep

    doc = json.loads(Path(admin_path).read_text(encoding="utf-8"))
    u = prep(unary_union([shape(f["geometry"]) for f in doc["features"]]))
    x0, y0, x1, y1 = u.context.bounds
    lon0 = math.floor(x0 / 0.1) * 0.1
    lat0 = math.floor(y0 / 0.1) * 0.1
    cells = []
    for i in range(int(math.ceil((x1 - lon0) / 0.1)) + 1):
        for j in range(int(math.ceil((y1 - lat0) / 0.1)) + 1):
            b = sbox(lon0 + i * 0.1, lat0 + j * 0.1,
                     lon0 + (i + 1) * 0.1, lat0 + (j + 1) * 0.1)
            if u.intersects(b) and not u.touches(b):
                cells.append((round(lon0 + i * 0.1, 4),
                              round(lat0 + j * 0.1, 4)))
    return sorted(cells)


# ---------------------------------------------------------------------------
# parsing the raw months
# ---------------------------------------------------------------------------
def rh_magnus(t_c, td_c):
    """RH (%) from T and Td (C) by the Magnus form (Alduchov and
    Eskridge 1996), capped at 100."""
    if t_c is None or td_c is None or t_c != t_c or td_c != td_c:
        return None
    rh = 100.0 * math.exp(17.625 * td_c / (243.04 + td_c)) \
        / math.exp(17.625 * t_c / (243.04 + t_c))
    return min(100.0, rh)


def load_weather():
    """Parse the persisted raw months. A row is usable when both hourly
    windows were complete server-side (24 hourly stamps each: the rain
    window and the WIT day) and the noon values exist. Days after the
    latest ERA5-Land hour are absent, not dry."""
    files = sorted(RAW.glob("ERA5L_20*.json"))
    if not files:
        raise SystemExit(f"no raw ERA5-Land months under {RAW} - run with "
                         "--fetch <project>")
    rows, latest_hour = [], None
    for p in files:
        if "kbdi" in p.name:
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows.extend(doc["rows"])
        lh = doc.get("latest_hour_utc")
        if lh and (latest_hour is None or lh > latest_hour):
            latest_hour = lh
    wdf = pd.DataFrame(rows)
    # a raw row's date is the WIT day whose noon the values belong to;
    # normalize in case an older fetch stored full timestamps
    wdf["date"] = wdf["date"].astype(str).str[:10]
    wdf["valid"] = (wdf.rain_n == 24) & (wdf.tmax_n == 24) \
        & wdf.t_noon_c.notna()
    wdf["rh_noon"] = [rh_magnus(t, td) for t, td in
                      zip(wdf.t_noon_c, wdf.td_noon_c)]
    return wdf, latest_hour


# ---------------------------------------------------------------------------
# per-cell daily series: continuous bookkeeping, gaps re-spun
# ---------------------------------------------------------------------------
def cell_index_series(days, weather, start_codes, mean_rain, le, lf,
                      spin_up_days, interception):
    """One cell's daily index series. weather maps day -> the day's
    inputs, or is absent for a day with no usable input.

    A missing day leaves a hole and restarts the cell from the start
    codes at the next day with weather; the restarted values count only
    after spin_up_days of continuous running, the same length the
    initial spin-up gets. DC has a memory of months; a year removes the
    start values' influence."""
    ffmc, dmc, dc = (start_codes["ffmc"], start_codes["dmc"],
                     start_codes["dc"])
    q, run_rain, run_len = 0.0, 0.0, None
    out = {}
    for day in days:
        w = weather.get(day)
        if w is None:
            run_len = None
            continue
        if run_len is None:
            ffmc, dmc, dc = (start_codes["ffmc"], start_codes["dmc"],
                             start_codes["dc"])
            q, run_rain, run_len = 0.0, 0.0, 0
        ffmc, dmc, dc, isi, bui, fwi = fwi_system_step(
            ffmc, dmc, dc, w["t_noon_c"], w["rh_noon"], w["wind_noon_kmh"],
            w["rain_24h_mm"], le, lf)
        q, run_rain = kbdi_step(q, w["t_max_c"], w["rain_24h_mm"],
                                run_rain, mean_rain, interception)
        run_len += 1
        if run_len > spin_up_days:
            out[day] = {"ffmc": round(ffmc, 2), "dmc": round(dmc, 2),
                        "dc": round(dc, 2), "isi": round(isi, 2),
                        "bui": round(bui, 2), "fwi": round(fwi, 2),
                        "kbdi": round(q, 2)}
    return out


def days_since_rain_series(aoi_rain, rain_day_mm):
    """Whole days since the AOI-mean rain last reached rain_day_mm; None
    before the first qualifying day."""
    out, since = {}, None
    for day in sorted(aoi_rain):
        v = aoi_rain[day]
        if v is not None and v >= rain_day_mm:
            since = 0
        elif since is not None:
            since += 1
        out[day] = since
    return out


def build_series(cfg, wdf, mean_rain):
    """Per-cell index series, then the AOI daily series: the mean over
    the cells with a valid value that day, plus the cell count. The AOI
    weather columns are means over those same cells."""
    fd = cfg["fire_danger"]
    # only cells the land-only asset actually covers can carry an index;
    # the other candidate squares are sea and would be counted missing
    # forever
    valid_cells = sorted(wdf[wdf.valid].cell.unique())
    wdf = wdf[wdf.cell.isin(valid_cells)]
    cells = valid_cells
    days_all = sorted({str(d) for d in wdf.date})
    days_scored = [d for d in days_all if d >= fd["score_start"]]
    le = float(fd["dmc_day_length"])
    lf = float(fd["dc_day_length_factor"])
    spin_up = (date.fromisoformat(fd["score_start"])
               - date.fromisoformat(fd["spin_up_start"])).days
    interception = float(fd["kbdi_rain_interception_mm"])

    wx = wdf.set_index(["cell", "date"])
    cells_series = {}
    n_missing = 0
    for c in cells:
        w = {}
        sub = wdf[wdf.cell == c]
        for r in sub.itertuples():
            if r.valid:
                w[r.date] = {"t_noon_c": r.t_noon_c, "rh_noon": r.rh_noon,
                             "wind_noon_kmh": r.wind_noon_kmh,
                             "rain_24h_mm": r.rain_24h_mm,
                             "t_max_c": r.t_max_c}
        got = cell_index_series(days_all, w, fd["start_codes"],
                                mean_rain.get(c, 0.0), le, lf, spin_up,
                                interception)
        cells_series[c] = got
        n_missing += len(days_all) - len(got)

    aoi = {}
    for day in days_scored:
        valid = [c for c in cells if day in cells_series[c]]
        if not valid:
            row = {k: None for k in INDEX_KEYS}
            row |= {"n_cells": 0, "rain_24h_mm": None, "t_noon_c": None,
                    "rh_noon": None, "wind_noon_kmh": None}
            aoi[day] = row
            continue
        aoi[day] = {k: round(float(np.mean([cells_series[c][day][k]
                                            for c in valid])), 2)
                    for k in ("ffmc", "dmc", "dc", "isi", "bui", "fwi",
                              "kbdi")}
        aoi[day]["n_cells"] = len(valid)
        aoi[day]["days_since_rain"] = None     # filled after rain means
        for field in ("rain_24h_mm", "t_noon_c", "rh_noon",
                      "wind_noon_kmh"):
            vals = [wx.loc[(c, day), field] for c in valid]
            vals = [v for v in vals if v is not None and v == v]
            aoi[day][field] = round(float(np.mean(vals)), 2) if vals \
                else None
    rain_means = {d: aoi[d]["rain_24h_mm"] for d in aoi}
    dsr = days_since_rain_series(rain_means, float(cfg["fire_danger"]
                                                ["rain_day_mm"]))
    for day in aoi:
        aoi[day]["days_since_rain"] = dsr[day]
    return aoi, cells, n_missing


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def positives_and_days(det, constellation_keys):
    """WIT days with at least one land detection from the fixed
    constellation. The recurrent-site exclusion (PLAN.md 5 item 5:
    persistent heat sources are not driven by the weather) removes days
    whose only detections are flagged; both day sets come back so the
    output can say what the exclusion cost."""
    keep = det[det.satellite.isin(list(constellation_keys)) & det.on_land]
    days_all = set(keep.date_wit)
    days_no_rec = set(keep.loc[~keep.recurrent_site.fillna(False),
                               "date_wit"])
    return days_all, days_no_rec


def fold_climatology(observed, positives, held_out_year, half_window):
    """The AOI-day climatology fitted on every OTHER observed year: the
    share of observed training days within the day-of-year window whose
    y was 1. Year Y's days never reach it."""
    train = [d for d in observed if d[:4] != held_out_year]
    pos = {d: d in positives for d in train}
    probs = {}
    for d in observed:
        if d[:4] != held_out_year:
            continue
        w = doy_window(day_of_year_365(date.fromisoformat(d)), half_window)
        in_w = [pos[x] for x in train
                if day_of_year_365(date.fromisoformat(x)) in w]
        probs[d] = (sum(in_w) / len(in_w)) if in_w else 0.0
    return probs


def score_fold(year, observed, positives, aoi, clim, base_rate):
    """AP per index, the climatology's AP and the base rate on one
    held-out year, with the pre-registered readings. Average precision
    measures ranking only; no calibration is claimed."""
    days = [d for d in observed if d[:4] == year and d in aoi
            and aoi[d]["n_cells"] > 0]
    if not days:
        return None
    out = {"n_observed": len(days),
           "n_positive": sum(1 for d in days if d in positives),
           "ap": {}, "readings": {}}
    for idx in INDEX_KEYS:
        pairs = [(aoi[d][idx], d) for d in days if aoi[d][idx] is not None]
        labels = [1 if d in positives else 0 for _, d in pairs]
        if not pairs or not any(labels):
            out["ap"][idx] = None
        else:
            out["ap"][idx] = round(
                average_precision([p[0] for p in pairs], labels), 4)
    clim_pairs = [(clim[d], d) for d in days if clim[d] is not None]
    clim_labels = [1 if d in positives else 0 for _, d in clim_pairs]
    out["ap"]["climatology"] = round(
        average_precision([p[0] for p in clim_pairs], clim_labels), 4) \
        if clim_pairs else None
    out["base_rate_ap"] = round(base_rate, 4)
    for idx in INDEX_KEYS:
        ap_i = out["ap"][idx]
        if ap_i is None or out["ap"]["climatology"] is None:
            out["readings"][idx] = None
            continue
        out["readings"][idx] = {
            "ap": ap_i,
            "vs_climatology": "above_climatology"
            if ap_i > out["ap"]["climatology"] else "not_above_climatology",
            "ap_climatology": out["ap"]["climatology"],
            "vs_base_rate": "above_base_rate" if ap_i > base_rate
            else "not_above_base_rate",
            "ap_base_rate": out["base_rate_ap"],
        }
    return out


# ---------------------------------------------------------------------------
# context tables
# ---------------------------------------------------------------------------
def monthly_table(aoi, positives):
    out = []
    months = sorted({d[:7] for d in aoi})
    for m in months:
        days = [d for d in aoi if d[:7] == m]
        row = {"month": m,
               "n_days": len(days),
               "n_positive": sum(1 for d in days if d in positives)}
        for idx in ("fwi", "dc", "kbdi"):
            vals = [aoi[d][idx] for d in days if aoi[d][idx] is not None]
            row[f"{idx}_median"] = round(float(np.median(vals)), 2) \
                if vals else None
            row[f"{idx}_p90"] = round(float(np.percentile(vals, 90)), 2) \
                if vals else None
        out.append(row)
    return out


def august_table(aoi, positives, det, constellation_keys):
    days = [d for d in sorted(aoi) if "2026-08-15" <= d <= "2026-08-31"]
    n_det = det[det.satellite.isin(list(constellation_keys))
                & det.on_land].groupby("date_wit").size().to_dict()
    rows = []
    for d in days:
        r = aoi[d]
        rows.append({
            "date": d, "y": 1 if d in positives else 0,
            "n_detections": int(n_det.get(d, 0)),
            **{k: r.get(k) for k in
               ("ffmc", "dmc", "dc", "isi", "bui", "fwi", "kbdi",
                "days_since_rain", "rain_24h_mm")},
        })
    return rows


# ---------------------------------------------------------------------------
def evaluate(cfg) -> dict:
    """Everything offline: parse the raw weather, run the indices, score
    the folds, assemble the document."""
    fd = cfg["fire_danger"]
    bl = cfg["baseline"]
    det = pd.read_parquet(DET)
    runs = json.loads(MANIFEST.read_text(encoding="utf-8"))["runs"]
    groups = instrument_groups(bl["constellation"])
    # the dense calendar span, as Task 17's rule requires: an unobserved
    # day is not a zero, and every day in the store's span is checked
    span_days = []
    cur = date.fromisoformat(str(det.date_wit.min()))
    end = date.fromisoformat(str(det.date_wit.max()))
    while cur <= end:
        span_days.append(cur.isoformat())
        cur += timedelta(days=1)
    observed, unobserved = observed_days(span_days, runs, groups)

    wdf, latest_hour = load_weather()
    mean_rain = {}
    if (RAW / ANNUAL_RAIN_FILE).exists():
        annual_doc = json.loads((RAW / ANNUAL_RAIN_FILE)
                                .read_text(encoding="utf-8"))
        mean_rain = annual_doc.get("mean_annual_mm", {})

    aoi, cells, n_missing = build_series(cfg, wdf, mean_rain)
    days_all_rec, positives = positives_and_days(
        det, set(bl["constellation"]))
    n_removed = len(days_all_rec - positives)

    years = sorted({d[:4] for d in observed if d in aoi
                    and aoi[d]["n_cells"] > 0})
    folds = {}
    for y in years:
        days_y = [d for d in observed if d[:4] == y]
        n_pos_y = sum(1 for d in days_y if d in positives)
        clim = fold_climatology(observed, positives, y,
                                int(bl["doy_half_window"]))
        base = n_pos_y / len(days_y) if days_y else 0.0
        folds[y] = score_fold(y, observed, positives, aoi, clim, base)
        folds[y]["n_observed"] = len([d for d in observed
                                      if d[:4] == y])
        folds[y]["n_positive"] = n_pos_y
        folds[y]["base_rate_ap"] = round(base, 4)
        folds[y]["n_positive_pre_exclusion"] = sum(
            1 for d in days_y if d in days_all_rec)
        print(f"{y}: observed {folds[y]['n_observed']}, positives "
              f"{folds[y]['n_positive']} | " + "  ".join(
                  f"{k} {folds[y]['ap'][k]}" for k in
                  ("ffmc", "dc", "fwi", "kbdi", "days_since_rain",
                   "climatology")))

    reading_counts = {}
    for idx in INDEX_KEYS:
        c = {"above_climatology": 0, "not_above_climatology": 0,
             "above_base_rate": 0, "not_above_base_rate": 0, "none": 0}
        for y in folds:
            r = folds[y]["readings"].get(idx) if folds[y] else None
            if r is None:
                c["none"] += 1
                continue
            c[r["vs_climatology"]] += 1
            c[r["vs_base_rate"]] += 1
        reading_counts[idx] = c

    doc = {
        "parameters": {
            "spin_up_start": fd["spin_up_start"],
            "score_start": fd["score_start"],
            "start_codes": fd["start_codes"],
            "dmc_day_length": fd["dmc_day_length"],
            "dc_day_length_factor": fd["dc_day_length_factor"],
            "kbdi_rain_interception_mm": fd["kbdi_rain_interception_mm"],
            "kbdi_mean_rain_period": fd["kbdi_mean_rain_period"],
            "rain_day_mm": fd["rain_day_mm"],
            "constellation": bl["constellation"],
        },
        "weather": {
            "cells": cells,
            "n_cells": len(cells),
            "span": [str(min(wdf.date)), str(max(wdf.date))],
            "raw_files": sorted(p.name for p in RAW.glob("ERA5L_*.json")),
            "latest_hour_utc": latest_hour,
            "missing_cell_days": n_missing,
        },
        "positive_days": {
            "pre_exclusion_total": len(days_all_rec),
            "removed_by_recurrent_exclusion": n_removed,
            "total": len(positives),
        },
        "daily": [{"date": d, "y": 1 if d in positives else 0, **aoi[d]}
                  for d in sorted(aoi) if d >= fd["score_start"]],
        "folds": folds,
        "reading_counts": reading_counts,
        "monthly": monthly_table(aoi, positives),
        "august_2026": august_table(aoi, positives, det,
                                    set(bl["constellation"])),
        "caveats": CAVEATS,
    }
    return doc


def write_json(doc: dict, path: Path) -> None:
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# fetch (--fetch <project>): Earth Engine lives only here
# ---------------------------------------------------------------------------
def month_days(month: str):
    """WIT days in one calendar month, as UTC datetimes of 03:00
    (WIT noon)."""
    y, m = int(month[:4]), int(month[5:7])
    n = monthrange(y, m)[1]
    return [datetime_of(y, m, d) for d in range(1, n + 1)]


def datetime_of(y, m, d):
    from datetime import datetime as dt, timezone as tz
    return datetime(y, m, d, 3, 0, tzinfo=tz.utc)   # 03:00 UTC = WIT noon


def rain_window_utc(noon_utc):
    """The hourly stamps covering [03:00 UTC D-1, 03:00 UTC D]. With the
    hour-ENDING stamping convention a value stamped t covers the hour
    ending at t, so the window's 24 stamps run 04:00 UTC D-1 through
    03:00 UTC D."""
    return noon_utc - timedelta(hours=23), noon_utc + timedelta(hours=1)


def day_image(coll, noon_utc):
    """One WIT day's values as a multi-band image, server-side.
    noon_utc = the day's 03:00 UTC instant (WIT noon)."""
    import ee
    rain_start, rain_end = rain_window_utc(noon_utc)
    rain = (coll.filterDate(rain_start, rain_end)
            .select("total_precipitation_hourly"))
    rain_img = rain.sum().multiply(1000.0).rename("rain_24h_mm")
    rain_n = rain.count().rename("rain_n")
    day_start = noon_utc - timedelta(hours=12)      # 15:00 D-1
    tday = coll.filterDate(day_start, day_start + timedelta(hours=24)) \
        .select("temperature_2m")
    tmax = tday.max().subtract(273.15).rename("t_max_c")
    tmax_n = tday.count().rename("tmax_n")
    noon_coll = coll.filterDate(noon_utc, noon_utc + timedelta(hours=1))
    # ERA5-Land has days with missing hours (verified: 2026-09-16 holds
    # only hours 0,1,2,4,9,14,17,21). An absent hour yields a fully
    # masked image - no value is invented (AGENTS never-2) and the row
    # drops out client-side on the t_noon_c check.
    noon = ee.Image(ee.Algorithms.If(
        noon_coll.size().gt(0),
        noon_coll.first().select(
            ["temperature_2m", "dewpoint_temperature_2m",
             "u_component_of_wind_10m", "v_component_of_wind_10m"]),
        ee.Image.constant([0.0, 0.0, 0.0, 0.0]).rename(
            ["temperature_2m", "dewpoint_temperature_2m",
             "u_component_of_wind_10m", "v_component_of_wind_10m"])
        .updateMask(0)))
    t_noon = noon.select("temperature_2m").subtract(273.15) \
        .rename("t_noon_c")
    td_noon = noon.select("dewpoint_temperature_2m").subtract(273.15) \
        .rename("td_noon_c")
    wind = (noon.select("u_component_of_wind_10m").pow(2)
            .add(noon.select("v_component_of_wind_10m").pow(2))
            .sqrt().multiply(3.6).rename("wind_noon_kmh"))
    return rain_img.addBands([tmax, tmax_n, rain_n, t_noon, td_noon, wind])


def fetch_weather(project) -> None:
    """Fetch per calendar month from the spin-up start to the latest
    hour, persisting each response before any parsing. Also the
    1991-2020 mean annual rain per cell for KBDI's R."""
    import ee
    ee.Initialize(project=project)
    coll = ee.ImageCollection(ASSET)
    latest = ee.Date(coll.aggregate_max("system:time_start")) \
        .format("YYYY-MM-dd'T'HH:mm'Z'").getInfo()
    print(f"ERA5-Land latest hour: {latest}")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    candidates = native_cells(ROOT / cfg["admin_polygon"])
    cells_fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Rectangle(
            [c[0], c[1], c[0] + 0.1, c[1] + 0.1]), {"cell": f"{c[0]},{c[1]}"})
        for c in candidates])

    start = date.fromisoformat(cfg["fire_danger"]["spin_up_start"])
    latest_dt = datetime.strptime(latest, "%Y-%m-%dT%H:%MZ") \
        .replace(tzinfo=timezone.utc)
    end = latest_dt.date()
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    RAW.mkdir(parents=True, exist_ok=True)
    for month in months:
        out = RAW / f"ERA5L_{month}.json"
        if out.exists():
            print(f"  {out.name} already present, keeping it")
            continue
        # days whose WIT noon (03:00 UTC) is past the asset's latest hour
        # are absent upstream, not dry (AGENTS never-2) - never fetched
        days = [d for d in month_days(month) if d <= latest_dt]
        if not days:
            continue
        # 31 daily reductions at once exceeds EE's concurrent-aggregation
        # limit: fetch in 7-day batches with a pause between them
        rows = []
        for cs in range(0, len(days), 7):
            chunk = days[cs:cs + 7]
            fcs = []
            for d in chunk:
                img = day_image(coll, d)
                fc = img.reduceRegions(cells_fc, ee.Reducer.mean(), 11132)
                fcs.append(fc.map(
                    lambda f, dd=d: f.set("date", dd.strftime("%Y-%m-%d"))))
            got = ee.FeatureCollection(fcs).flatten().getInfo()
            rows.extend(f["properties"] for f in got["features"])
            time.sleep(3.0)
        if not rows:
            raise SystemExit(f"ERA5-Land returned no values for {month} - "
                             "a failed request is not a dry month; "
                             "nothing written")
        keep = [r for r in rows
                if r.get("t_noon_c") is not None
                and r.get("t_noon_c") == r.get("t_noon_c")]
        if not keep:
            raise SystemExit(f"ERA5-Land returned only empty cells for "
                             f"{month} - nothing written for {month}")
        (RAW / f"ERA5L_{month}.json").write_text(
            json.dumps({"month": month, "latest_hour_utc": latest,
                        "rows": rows}, indent=1) + "\n",
            encoding="utf-8")
        print(f"  ERA5L_{month}.json: {len(rows)} rows "
              f"({len(keep)} valid)")

    # KBDI's R: the mean annual total per cell over the normal period
    ra = cfg["fire_danger"]["kbdi_mean_rain_period"]
    annual = {}
    for y in range(int(ra[0]), int(ra[1]) + 1):
        s = coll.filterDate(f"{y}-01-01", f"{y + 1}-01-01") \
            .select("total_precipitation_hourly").sum().multiply(1000.0)
        rr = s.reduceRegions(cells_fc, ee.Reducer.mean(), 11132)
        for f in rr.getInfo()["features"]:
            key = f["properties"]["cell"]
            v = f["properties"].get("mean")
            if v is not None and v == v:
                annual.setdefault(key, []).append(v)
    mean_annual = {c: round(float(np.mean(v)), 1)
                   for c, v in sorted(annual.items())}
    (RAW / ANNUAL_RAIN_FILE).write_text(
        json.dumps({"period": [int(ra[0]), int(ra[1])],
                    "mean_annual_mm": mean_annual}, indent=1) + "\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", metavar="PROJECT",
                    help="fetch missing ERA5-Land months from Earth "
                         "Engine (network only here, never from the "
                         "cron)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.fetch:
        fetch_weather(args.fetch)
        return 0
    doc = evaluate(cfg)
    write_json(doc, OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")

    print("\nper-fold average precision (leave one calendar year out):")
    head = ["ffmc", "dmc", "dc", "isi", "bui", "fwi", "kbdi",
            "days_since_rain", "climatology", "base_rate_ap"]
    print("  year  obs  pos  " + "  ".join(f"{k[:8]:>8}" for k in
                                           ("ffmc", "dmc", "dc", "isi",
                                            "bui", "fwi", "kbdi",
                                            "dsr_rain", "clim", "base")))
    for y, f in doc["folds"].items():
        print(f"  {y}  {f['n_observed']:4d} {f['n_positive']:4d}  "
              + "  ".join(f"{f['ap'].get(k)!s:>8}" for k in
                          ("ffmc", "dmc", "dc", "isi", "bui", "fwi",
                           "kbdi", "days_since_rain", "climatology"))
              + f"  {f['base_rate_ap']!s:>6}")
    print("\nAugust 2026 (the episode the project exists to explain):")
    print("  date        y  det   FFMC   DMC     DC   ISI   BUI   FWI  "
          "KBDI  dsr_rain  rain")
    for r in doc["august_2026"]:
        print(f"  {r['date']}  {r['y']} {r['n_detections']:4d}  "
              + "  ".join(f"{(r[k] if r.get(k) is not None else '-')!s:>5}"
                          for k in ("ffmc", "dmc", "dc", "isi", "bui",
                                    "fwi", "kbdi", "days_since_rain"))
              + f"  {r['rain_24h_mm']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
