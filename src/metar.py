"""Corroborate burning events against airport smoke reports (Task 19,
PLAN.md Phase 2 item 4).

Field validation on Biak is blocked; the one independent ground
observation available at scale is Frans Kaisiepo (ICAO WABB), which
reports every 30 minutes and carries FU (smoke) and HZ (haze) in its
present-weather group. For every event in data/processed/events.json
(Task 16) this script reports what the airport saw in
[first_seen_utc, last_seen_utc + lag_hours] and assigns exactly one
pre-registered class:

  unobserved             coverage below metar.min_coverage: the station
                         was not reporting enough to say anything - a
                         data gap, not a negative (AGENTS never-2)
  beyond_range           farther than metar.max_km; Numfor lies 126-148 km
                         from the airport and one station cannot speak
                         for it
  corroborated           at least one FU report whose surface wind comes
                         from the event's direction
  smoke_other_direction  FU reports, none from the event (including calm
                         and variable winds)
  no_smoke_at_station    none of the above: the most common class, and
                         its name states only what was observed at one
                         point

The classes are asymmetric by design: an FU report is strong positive
evidence (83 consecutive days before August 2026 had none - PLAN.md
10.2), while the absence of FU is close to no evidence (PLAN.md 12: on
2026-08-27 the airport reported clear for ten hours while a resident
6.5 km away was in heavy smoke). Nothing here can refute an event or say
it was not burning, and no label suggests otherwise.

The wind test is one sector rule on the reported surface wind, not plume
modelling: drct is where the wind blows FROM, calm (drct 0, sknt 0) and
variable (drct M) leave the direction undefined, and the report counts as
wind from the event when its direction sits within
metar.sector_half_width_deg of the bearing from the station to the event.

Source: the Iowa State Environmental Mesonet archive (PLAN.md 10.1),
fetched only with --fetch, one calendar year per request, each response
persisted under data/raw/metar/ BEFORE parsing (AGENTS always-2). A year
that returns an HTML page or no data rows exits non-zero naming the year
and writes nothing: a failed request is not a quiet year. Without --fetch
the script parses the raw files offline and never touches the network.

Parsing traps, each applied explicitly because each fails silently:
`M` means a missing observation in vsby, "no present-weather group" in
wxcodes, and a variable wind in drct; calm (drct 0, sknt 0) shares the
undefined-direction treatment; vsby is statute miles and 6.21 is the
"10 km or more" ceiling, censored, never averaged; FU and HZ match as
whole space-separated tokens; valid is UTC and a WIT day is derived from
it (AGENTS always-1).

Writes data/processed/metar_corroboration.json (sorted keys, indent 1,
no timestamp, deterministic from the raw files). events.json and
detections.parquet are read, never written. No FINDINGS.md entry (the
Task 17 override applies): the entry is written at review from the JSON.

    python src/metar.py [--fetch]
"""
import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from recurrence import M_PER_DEG

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "metar"
OUT = ROOT / "data" / "processed" / "metar_corroboration.json"
DET = ROOT / "data" / "processed" / "detections.parquet"
EVENTS = ROOT / "data" / "processed" / "events.json"
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
CEILING_SM = 6.21          # "10 km or more": censored, never a measurement

CAVEATS = [
    "A smoke (FU) report at WABB is strong evidence that smoke reached the "
    "airport. Its absence is close to no evidence: the station is one "
    "point, and smoke can pool a few kilometres away under a night "
    "inversion without reaching it (PLAN.md section 12).",
    "Events that overlap in time share the same reports; "
    "n_concurrent_events says how many. A corroboration shared with many "
    "events corroborates the episode, not the event.",
    "Visibility is in statute miles; 6.21 is the '10 km or more' ceiling, "
    "not a measurement.",
    "Smoke at the airport says nothing about why land was burned or who "
    "burned it (PLAN.md section 8).",
]


# ---------------------------------------------------------------------------
# fetch (only with --fetch)
# ---------------------------------------------------------------------------
def year_chunks(archive_start: str, today: date):
    """One calendar year per request; the service is slow (PLAN.md 10.1)."""
    start = date.fromisoformat(archive_start)
    out, y = [], start.year
    while y <= today.year:
        out.append((max(start, date(y, 1, 1)), min(today, date(y, 12, 31))))
        y += 1
    return out


def year_url(cfg, s: date, e: date) -> str:
    return (f"{IEM}?station={cfg['station']}"
            "&data=vsby&data=wxcodes&data=drct&data=sknt&data=metar"
            "&tz=Etc%2FUTC&format=onlycomma&report_type=3&report_type=4"
            f"&year1={s.year}&month1={s.month}&day1={s.day}"
            f"&year2={e.year}&month2={e.month}&day2={e.day}")


def validate_year_csv(text: str, year: int) -> int:
    """A response is usable only if it is the CSV and holds at least one
    data row. An HTML error page and a header-only CSV both mimic a quiet
    station; neither may be persisted. Returns the data-row count."""
    stripped = text.strip()
    if "<html" in stripped[:200].lower():
        raise SystemExit(f"IEM returned an HTML page for {year}, not CSV - "
                         f"nothing written for {year}")
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if not lines or not lines[0].lower().startswith("station"):
        raise SystemExit(f"IEM returned no CSV header for {year} - nothing "
                         f"written for {year}")
    rows = [ln for ln in lines[1:] if ln.strip()]
    if not rows:
        raise SystemExit(f"IEM archive returned no data rows for {year} - "
                         f"a failed request is not a quiet year; nothing "
                         f"written for {year}")
    return len(rows)


def fetch_years(cfg) -> list:
    """Fetch each archive year once, persisting the raw response BEFORE
    any parsing. Existing files are kept: the archive is immutable, so a
    re-run costs no network for years already on disk."""
    import requests
    RAW.mkdir(parents=True, exist_ok=True)
    files = []
    for s, e in year_chunks(cfg["archive_start"], date.today()):
        out = RAW / f"WABB_{s.isoformat()}_{e.isoformat()}.csv"
        if out.exists():
            print(f"  {out.name} already present, keeping it")
            files.append(out.name)
            continue
        try:
            resp = requests.get(year_url(cfg, s, e), timeout=600)
        except requests.RequestException as exc:
            raise SystemExit(f"fetch failed for {s.year}: {exc} - nothing "
                             f"written for {s.year}")
        n = validate_year_csv(resp.text, s.year)
        out.write_text(resp.text, encoding="utf-8")
        print(f"  {out.name}: {n} rows")
        files.append(out.name)
    return files


# ---------------------------------------------------------------------------
# parsing - every trap applied explicitly, because each fails silently
# ---------------------------------------------------------------------------
def parse_observations(raw_files) -> pd.DataFrame:
    """Parse the persisted CSVs into one observation frame:
    vsby_sm (statute miles, NaN where the observation is missing),
    at_ceiling, fu, hz (whole space-separated tokens of wxcodes, where
    `M` means no present-weather group at all), drct_deg/sknt with the
    direction undefined for variable (`M`) and calm (sknt 0), valid_utc,
    valid_wit, date_wit (WIT = UTC+9, AGENTS always-1). The raw metar
    string is kept only so a test can check the unit conversion."""
    frames = [pd.read_csv(p) for p in raw_files]
    df = pd.concat(frames, ignore_index=True)
    df["valid_utc"] = pd.to_datetime(df["valid"], utc=True, format="mixed")
    df["valid_wit"] = df["valid_utc"] + pd.Timedelta(hours=9)
    df["date_wit"] = df["valid_wit"].dt.date.astype(str)

    df["vsby_sm"] = pd.to_numeric(df["vsby"], errors="coerce")
    df["at_ceiling"] = (df["vsby_sm"] - CEILING_SM).abs() < 1e-6

    tokens = df["wxcodes"].fillna("M").astype(str).str.split()
    df["fu"] = tokens.apply(lambda t: "FU" in t)
    df["hz"] = tokens.apply(lambda t: "HZ" in t)

    df["drct_deg"] = pd.to_numeric(df["drct"], errors="coerce")
    df["sknt"] = pd.to_numeric(df["sknt"], errors="coerce")
    known = df["drct_deg"].notna() & (df["sknt"] > 0)
    df["wind_known"] = known
    df["dir_deg"] = np.where(known, df["drct_deg"], np.nan)
    return df.sort_values("valid_utc").reset_index(drop=True)


def angdiff(a, b) -> float:
    """Smallest absolute angular difference in degrees; north-crossing
    aware: 355 against 5 is 10, not 350."""
    d = abs(float(a) - float(b)) % 360.0
    return min(d, 360.0 - d)


def wind_from_event(drct, sknt, bearing, half_width_deg) -> bool:
    """True when the reported surface wind comes from the event: a known
    direction (not calm, not variable) within the sector around the
    bearing from the station to the event. drct is where the wind blows
    FROM - the most common way to run this test backwards."""
    if drct is None or pd.isna(drct):
        return False
    if sknt is None or pd.isna(sknt) or sknt <= 0:
        return False
    return angdiff(drct, bearing) <= half_width_deg


# ---------------------------------------------------------------------------
# geometry - the same local plane events.py uses (events.py:41): one cos
# of the mean latitude for the whole set, M_PER_DEG metres per degree
# ---------------------------------------------------------------------------
def plane_cos(lats) -> float:
    return math.cos(math.radians(float(np.mean(lats))))


def event_geometry(ev, station_lat, station_lon, k):
    """Distance in km and compass bearing FROM the station TO the event:
    atan2(east, north), 0 = north, 90 = east, clockwise."""
    dx = (float(ev["centroid_lon"]) - station_lon) * M_PER_DEG * k
    dy = (float(ev["centroid_lat"]) - station_lat) * M_PER_DEG
    dist_km = math.hypot(dx, dy) / 1000.0
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    return round(dist_km, 2), round(bearing, 1)


# ---------------------------------------------------------------------------
# the join, per event
# ---------------------------------------------------------------------------
def join_events(obs, events_doc, metar_cfg, k):
    """Per event: the station's reports inside
    [first_seen_utc, last_seen_utc + metar.lag_hours] - smoke outlasts
    the burning that makes it (burning peaked 21-22 August 2026, airport
    smoke 23-24, PLAN.md 10.4)."""
    lag = timedelta(hours=float(metar_cfg["lag_hours"]))
    half = float(metar_cfg["sector_half_width_deg"])
    slat, slon = float(metar_cfg["lat"]), float(metar_cfg["lon"])
    win = [(pd.Timestamp(ev["first_seen_utc"]),
            pd.Timestamp(ev["last_seen_utc"]) + lag)
           for ev in events_doc["events"]]

    records = []
    for idx, ev in enumerate(events_doc["events"]):
        s, e = win[idx]
        w = obs[(obs.valid_utc >= s) & (obs.valid_utc <= e)]
        n_obs = int(len(w))
        expected = int((e - s).total_seconds() / 1800) + 1
        coverage = round(n_obs / expected, 3) if expected else 0.0
        dist, bearing = event_geometry(ev, slat, slon, k)
        n_fu = int(w.fu.sum())
        n_hz = int(w.hz.sum())
        n_fu_from = int(sum(
            wind_from_event(d, knt, bearing, half)
            for d, knt in zip(w.loc[w.fu, "dir_deg"],
                              w.loc[w.fu, "sknt"])))
        v = w["vsby_sm"].dropna()
        vsby_min = round(float(v.min()), 2) if len(v) else None
        share_ceiling = (round(float(w.at_ceiling.sum()) / len(v), 4)
                         if len(v) else None)
        # how many OTHER events' windows contain at least one of this
        # event's FU reports: one plume at the airport sits in every
        # overlapping window at once, and cannot tell the events apart
        n_conc = 0
        if n_fu:
            fu_ts = w.loc[w.fu, "valid_utc"].to_numpy()
            n_conc = sum(1 for j, (s2, e2) in enumerate(win)
                         if j != idx and bool(
                             ((fu_ts >= s2) & (fu_ts <= e2)).any()))
        records.append({
            "event_id": ev["event_id"], "desa": ev.get("desa"),
            "distrik": ev.get("distrik"),
            "first_seen_utc": ev["first_seen_utc"],
            "last_seen_utc": ev["last_seen_utc"],
            "distance_km": dist, "bearing_deg": bearing,
            "n_obs": n_obs, "coverage": coverage,
            "n_fu": n_fu, "n_hz": n_hz,
            "n_fu_from_event": n_fu_from,
            "vsby_sm_min": vsby_min, "share_at_ceiling": share_ceiling,
            "n_concurrent_events": n_conc,
        })
    return records


def classify(rec, min_coverage, max_km) -> str:
    """Exactly one class, in the pre-registered order. A smoke report can
    corroborate an event; nothing here can refute it, 'unconfirm' it or
    say it was not burning - the asymmetry is by design (PLAN.md 2.6 and
    section 12)."""
    if rec["coverage"] < min_coverage:
        return "unobserved"
    if rec["distance_km"] > max_km:
        return "beyond_range"
    if rec["n_fu_from_event"] >= 1:
        return "corroborated"
    if rec["n_fu"] >= 1:
        return "smoke_other_direction"
    return "no_smoke_at_station"


def class_counts(records, min_coverage, max_km_values):
    """Class counts beside each max_km judgement, so the reader sees how
    much the range choice moves them."""
    out = {}
    for km in max_km_values:
        counts = {}
        for rec in records:
            c = classify(rec, min_coverage, km)
            counts[c] = counts.get(c, 0) + 1
        out[f"max_km_{km:g}"] = counts
    return out


# ---------------------------------------------------------------------------
# station baseline
# ---------------------------------------------------------------------------
def station_baseline(obs):
    """What makes 'smoke at WABB is rare' a number: per year and per
    month the observation count and the days carrying FU and HZ, plus FU
    reports by WIT hour - section 12 suggests smoke reaches the station
    mostly under a night inversion, and the hour table shows it."""
    by_year, by_month = [], []
    for key, level in (("year", obs.date_wit.str[:4]),
                       ("month", obs.date_wit.str[:7])):
        table = []
        for val, sub in obs.groupby(level):
            table.append({
                "period": val, "n_obs": int(len(sub)),
                "days_with_fu": int(sub.loc[sub.fu, "date_wit"].nunique()),
                "days_with_hz": int(sub.loc[sub.hz, "date_wit"].nunique()),
            })
        (by_year if key == "year" else by_month).append(table)
    fu_hours = obs.loc[obs.fu, "valid_wit"].dt.hour.value_counts()
    hours = {h: int(fu_hours.get(h, 0)) for h in range(24)}
    return by_year, by_month, hours


# ---------------------------------------------------------------------------
def evaluate(obs, cfg) -> dict:
    m = cfg["metar"]
    events_doc = json.loads(EVENTS.read_text(encoding="utf-8"))
    det_span = pd.read_parquet(DET, columns=["date_wit"]).date_wit
    store_days = []
    cur = date.fromisoformat(det_span.min())
    end = date.fromisoformat(det_span.max())
    while cur <= end:
        store_days.append(cur.isoformat())
        cur += timedelta(days=1)

    k = plane_cos([ev["centroid_lat"] for ev in events_doc["events"]])
    records = join_events(obs, events_doc, m, k)
    for rec in records:
        rec["class"] = classify(rec, float(m["min_coverage"]),
                                float(m["max_km"]))

    metar_dates = set(obs.date_wit)
    gaps = [d for d in store_days if d not in metar_dates]

    archive = {
        "raw_files": sorted(p.name for p in RAW.glob("WABB_*.csv")),
        "first_valid_utc": str(obs.valid_utc.min()),
        "last_valid_utc": str(obs.valid_utc.max()),
        "n_observations": int(len(obs)),
        "days_in_store_span_with_no_metar": gaps,
    }
    by_year, by_month, fu_hours = station_baseline(obs)
    doc = {
        "parameters": m,
        "archive": archive,
        "baseline": {"by_year": by_year, "by_month": by_month,
                     "fu_by_wit_hour": fu_hours},
        "events": sorted(records, key=lambda r: r["event_id"]),
        "class_counts": class_counts(records, float(m["min_coverage"]),
                                     [25.0, float(m["max_km"]), 100.0]),
        "caveats": CAVEATS,
    }
    counts = doc["class_counts"]
    print("class counts:")
    for key in sorted(counts):
        line = ", ".join(f"{c} {n}" for c, n in sorted(counts[key].items()))
        print(f"  {key}: {line}")
    print("station baseline, FU days per year:")
    for row in by_year[0]:
        print(f"  {row['period']}: {row['n_obs']} obs, "
              f"{row['days_with_fu']} FU days, "
              f"{row['days_with_hz']} HZ days")
    return doc


def write_json(doc: dict, path: Path) -> None:
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true",
                    help="fetch missing archive years from IEM (the "
                         "network is touched only here, never from the "
                         "cron)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.fetch:
        fetch_years(cfg["metar"])
    raws = sorted(RAW.glob("WABB_*.csv"))
    if not raws:
        raise SystemExit("no raw METAR archive under data/raw/metar - "
                         "run: python src/metar.py --fetch")
    obs = parse_observations(raws)
    doc = evaluate(obs, cfg)
    write_json(doc, OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
