"""Daily hotspot brief and GeoJSON export (Task 02/02b, PLAN.md Phase 1).

Reads data/processed/detections.parquet - never fetches anything - and writes
the published outputs under docs/: a rolling-window GeoJSON point layer, a
machine-readable summary JSON, and one Markdown brief per covered WIT day.

The brief covers exactly one WIT local day (the most recent one in the store
by default). Three per-source states are kept strictly apart, because they are
different facts (AGENTS rule 2): a detection count; "observed, no detections"
(the run manifest shows the AOI was successfully queried for that day); and
"not observed" (the query failed or there is no record). The third is never
presented as a zero. A district count of 0 is a different thing again.

Usage:
    python src/report_daily.py [--day YYYY-MM-DD] [--allow-stale]
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml

from ingest_firms import (MANIFEST_FILENAME, WIT,  # UTC+9 reused
                          load_boundaries)

# Every user-facing string lives here so the Bahasa Indonesia translation
# required by PLAN.md section 6 is a swap of this dict, not a rewrite.
T = {
    "title": "Biak hotspot daily brief",
    "generated_line": "Generated {utc} UTC ({wit} WIT). "
                      "Covers WIT day {day} only.",
    "totals": "**{detections} thermal anomaly detections**: "
              "{on_land} on land, "
              "{offshore} offshore/water (kept and flagged, never dropped).",
    "sources_heading": "Satellite sources",
    "source_row": "| {name} | {count} |",
    # Per-source states (never two states may share a rendering):
    "state_empty": "observed, no detections",
    "state_failed": "not observed (fetch failed)",
    "state_norecord": "not observed (no record)",
    "coverage_incomplete":
        "Coverage for this day was incomplete ({list}). Zeros below were "
        "not confirmed observations of absence; cloud or a failed query may "
        "be hiding fires.",
    "manifest_missing":
        "No fetch-provenance record was found next to the store "
        "(" + MANIFEST_FILENAME + "): it cannot be shown that every source "
        "actually observed the AOI on this day.",
    "zero_means": "A district count of 0 means the area was observable and "
                  "no thermal anomalies were detected inside it.",
    # Used instead of zero_means whenever coverage was incomplete. The two must
    # never both appear: saying a zero is a confirmed observation directly under
    # a warning that it is not would undermine the brief's credibility.
    "zero_means_partial":
        "A district count of 0 below means no thermal anomaly was recorded "
        "there. Because coverage for this day was incomplete, it is not "
        "evidence that nothing burned.",
    "recurrent_heading": "Recurrent locations",
    "recurrent_line": "Site {site_id} ({distrik}): {today_detections} "
                      "today, at a location flagged as recurrent - hotspots "
                      "have appeared there on {days} distinct days of the "
                      "recorded history.",
    "recurrent_note": "\"Recurrent location\" describes only how often "
                      "hotspots have appeared at one place. It does not say "
                      "what is there, and it does not diminish any individual "
                      "detection: these rows are included in every count "
                      "above, never excluded.",
    "evening_heading": "The previous evening (Himawari-9)",
    "evening_scope": "This section describes the night BEFORE the day above: "
                     "15:00 {prev} WIT to 01:00 {day} WIT. A brief written "
                     "during a WIT day cannot yet contain that day's own "
                     "evening, so this is always the night just ended.",
    "evening_slots": "Slots retrieved: {retrieved} of {expected} expected "
                     "({cadence}-minute cadence, 06:00-16:00 UTC).",
    "evening_missing": "{missing} expected slot(s) missing upstream - a "
                       "missing slot is a gap in the record, not a zero.",
    "evening_unavailable": "Evening product unavailable for this night (no "
                           "Himawari file was produced). This is a gap in the "
                           "record, not an observation, and not a zero.",
    "evening_none_after_dark": "No evening thermal anomaly above threshold "
                               "after dark.",
    "evening_not_evidence": "That is not evidence that nothing burned: AHI at "
                            "2 km resolves only larger or hotter fires than "
                            "VIIRS at 375 m (about 28 times the pixel area), "
                            "and a smouldering fire without flame may never "
                            "cross a thermal threshold.",
    "evening_night_flags": "Pixels flagged after dark: {n}.",
    "evening_flag_row": "- {wit} WIT, {lat}, {lon}: B07 anomaly +{anom} K",
    "evening_floor": "A Himawari flag is not a FIRMS detection: AHI at 2 km "
                     "resolves only larger or hotter fires than VIIRS at "
                     "375 m (about 28 times the pixel area).",
    "evening_daylight_summary": ("Daylight flags before sunset (unreliable - "
                                 "reflected sunlight): {n} {pixel}, {t0}-{t1} "
                                 "WIT, peak anomaly +{peak} K. Listed in the "
                                 "evening file."),
    "evening_largest": ("Largest after-dark anomaly: +{anom:.1f} K at {wit} "
                        "WIT ({lat}, {lon}). Below the {thr:g} K flag "
                        "threshold and not a detection."),
    "evening_reader": "Reader check (marked ocean sample - not AOI): B14 "
                      "median {med} K.",
    "districts_heading": "Detections by district",
    "district_header": "| distrik | kabupaten | detections | total FRP (MW) "
                       "| max FRP (MW) |",
    "caveat": "A hotspot is a thermal anomaly, not a confirmed fire. Satellite "
              "hotspots cannot identify who started a fire, and should never "
              "be read as an accusation against any person or village. Small-"
              "scale burning is a long-standing practice in Papua; this report "
              "describes what instruments observed, nothing more.",
    "window_line": "The point layer (hotspots_latest.geojson) covers the "
                   "{days}-day WIT window ending {day}.",
}

# How each source status renders as the table cell text.
STATE_CELL = {"empty": T["state_empty"], "failed": T["state_failed"],
              "norecord": T["state_norecord"]}

# Satellite field values returned by each configured FIRMS source.
# Add an entry here whenever a new source is added to config.yaml.
SOURCE_SATS = {
    "VIIRS_SNPP_NRT": {"N"},
    "VIIRS_NOAA20_NRT": {"N20"},
    "VIIRS_NOAA21_NRT": {"N21"},
    "MODIS_NRT": {"Terra", "Aqua"},
}


def load_config(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def resolve(root: Path, value: str) -> Path:
    """Config-relative path; absolute values pass through unchanged."""
    p = Path(value)
    return p if p.is_absolute() else root / p


def district_table(boundaries) -> list[dict]:
    """All distrik from the boundary file, alphabetically, each mapped to its
    single kabupaten. The brief lists every one even on a zero-detection day."""
    _, _, names = boundaries
    mapping: dict[str, set] = {}
    for _desa, distrik, kabupaten in names:
        if distrik is None:
            continue
        mapping.setdefault(distrik, set()).add(kabupaten)
    rows = []
    for distrik in sorted(mapping):
        kabs = mapping[distrik]
        if len(kabs) != 1:
            raise ValueError(f"distrik {distrik!r} spans {kabs} in boundary "
                             "file; expected exactly one kabupaten")
        rows.append({"distrik": distrik, "kabupaten": next(iter(kabs)),
                     "detections": 0, "total_frp": None, "max_frp": None})
    return rows


def _covers(entry: dict, wit_day: str) -> bool:
    """Did this manifest chunk's query cover WIT day `wit_day`?

    A chunk queries UTC dates [chunk_start, chunk_start+days-1]. A WIT day
    draws acquisitions from its own UTC date and the preceding evening, so
    coverage means the chunk interval intersects [wit_day-1, wit_day].
    """
    d = date.fromisoformat(wit_day)
    lo, hi = d - timedelta(days=1), d
    s = date.fromisoformat(entry["chunk_start"])
    e = s + timedelta(days=int(entry["days"]) - 1)
    return max(s, lo) <= min(e, hi)


def _source_status(src: str, sats: set | None, day_df: pd.DataFrame,
                   runs: list[dict], wit_day: str) -> dict:
    """One of three facts per source: detections found; observed, none there;
    or not observed (query failed / no record). Never merges the last two."""
    if sats is None:
        raise ValueError(f"no satellite mapping for configured source "
                         f"{src!r}; add it to SOURCE_SATS")
    counts = (day_df.groupby("satellite").size().to_dict()
              if len(day_df) else {})
    n = int(sum(c for sat, c in counts.items() if sat in sats))
    if n:
        return {"source": src, "detections": n, "status": "observed"}
    covering = [e for e in runs
                if e.get("source") == src and _covers(e, wit_day)]
    if not covering:
        status = "norecord"
    elif any(e.get("outcome") == "failed" for e in covering):
        status = "failed"
    else:
        status = "empty"
    return {"source": src, "detections": 0, "status": status}


def summarize(day_df: pd.DataFrame, districts: list[dict], sources: list[str],
              runs: list[dict], wit_day: str) -> dict:
    """Counts for one WIT day. Never drops anything: offshore detections are
    counted and reported as their own group."""
    total = len(day_df)
    on_land = int(day_df["on_land"].sum()) if total else 0
    by_district = {}
    if total:
        grp = day_df[day_df["on_land"]].groupby("distrik")["frp"]
        agg = grp.agg(["count", "sum", "max"])
        by_district = {k: (int(r["count"]), round(float(r["sum"]), 1),
                           round(float(r["max"]), 1))
                       for k, r in agg.iterrows()}
    for row in districts:
        if row["distrik"] in by_district:
            c, s, m = by_district[row["distrik"]]
            row.update(detections=c, total_frp=s, max_frp=m)

    source_rows = [_source_status(src, SOURCE_SATS.get(src), day_df,
                                  runs, wit_day) for src in sources]
    return {"detections": total, "on_land": on_land,
            "offshore": total - on_land,
            "sources": source_rows, "districts": districts}


def _geojson_props(rec: dict) -> dict:
    out = {}
    for key, val in rec.items():
        if isinstance(val, pd.Timestamp):
            if not pd.isna(val):
                out[key] = val.isoformat()
        elif val is None or (isinstance(val, float) and pd.isna(val)) \
                or val is pd.NaT:
            continue
        else:
            try:
                val = val.item()  # numpy scalar -> python scalar
            except AttributeError:
                pass
            out[key] = val
    return out


def write_geojson(window_df: pd.DataFrame, path: Path, generated_utc: str,
                  covered_day: str):
    feats = []
    for rec in window_df.sort_values("detection_id").to_dict("records"):
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [float(rec.pop("longitude")),
                                         float(rec.pop("latitude"))]},
            "properties": _geojson_props(rec),
        })
    doc = {"type": "FeatureCollection",
           "generated_utc": generated_utc,
           "covered_wit_date": covered_day,
           "features": feats}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False),
                    encoding="utf-8")


def write_summary(doc: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True,
                               ensure_ascii=False) + "\n", encoding="utf-8")


def recurrent_today(day_df: pd.DataFrame) -> list[dict]:
    """Flagged detections on the covered day, one entry per site.

    Presentational only - the flags live in the store, computed by
    src/recurrence.py. A store written before that feature has no
    recurrent_site column and yields an empty list.
    """
    if "recurrent_site" not in day_df.columns or not len(day_df):
        return []
    flagged = day_df[day_df["recurrent_site"].fillna(False).astype(bool)]
    out = []
    for site_id, grp in flagged.groupby("recurrent_site_id", sort=True):
        d = grp["distrik"].dropna() if "distrik" in grp else []
        out.append({
            "site_id": str(site_id),
            "distrik": str(d.mode().min()) if len(d) else None,
            "detections_today": int(len(grp)),
            "days_total": int(grp["recurrent_site_days"].iloc[0]),
        })
    return out


def evening_section(cfg: dict, root: Path, brief_day: str) -> tuple[dict,
                                                                    list[str]]:
    """The Himawari-9 evening product for the night BEFORE the brief's WIT
    day (15:00 brief_day-1 -> 01:00 brief_day WIT).

    Resolution of "which night" (Task 06): a brief written for a WIT day
    cannot contain that day's own evening, which ends at 01:00 WIT the next
    morning. The section therefore always describes the night that has just
    ended, states so in its scope line, and is titled "previous evening" so
    a reader can never mistake it for the coming night. The producer
    (src/himawari.py, run after 16:00 UTC) writes the file the same evening;
    if it is missing, the section says so rather than rendering a zero.

    Returns (info for the summary JSON, brief lines).
    """
    info = {"state": "unavailable", "evening_date": None,
            "slots_expected": 0, "slots_retrieved": 0, "slots_missing": 0,
            "flags": [], "daylight_flags": 0, "night_flags": 0,
            "daylight_summary": None, "largest_after_dark": None,
            "ocean_bt14_median_k": None}
    window = cfg["himawari_window_utc"]
    cadence = int(cfg["himawari_cadence_minutes"])
    prev = (date.fromisoformat(brief_day) - timedelta(days=1)).isoformat()
    info["evening_date"] = prev
    day_d = date.fromisoformat(prev)
    start_dt = datetime.combine(day_d,
                                datetime.strptime(window[0], "%H:%M").time(),
                                tzinfo=timezone.utc)
    end_dt = datetime.combine(day_d,
                              datetime.strptime(window[1], "%H:%M").time(),
                              tzinfo=timezone.utc)
    info["slots_expected"] = int(
        (end_dt - start_dt).total_seconds() // 60 // cadence) + 1
    info["window_utc"] = f"{window[0]}-{window[1]}"

    lines = [T["evening_scope"].format(prev=prev, day=brief_day)]
    path = (resolve(root, cfg["output_paths"]["processed"]).parent /
            f"himawari_evening_{prev}.parquet")
    if not path.exists():
        lines.append(T["evening_unavailable"])
        lines.append(T["evening_not_evidence"])
        return info, lines

    df = pd.read_parquet(path)
    info["state"] = "ok"
    retrieved = int(df["acq_time_utc"].nunique()) if len(df) else 0
    info["slots_retrieved"] = retrieved
    info["slots_missing"] = max(0, info["slots_expected"] - retrieved)

    ocean = df[df["ocean_sample"]] if "ocean_sample" in df.columns \
        else df.iloc[0:0]
    if len(ocean):
        info["ocean_bt14_median_k"] = round(float(ocean["bt14"].median()), 1)

    land = df[~df["ocean_sample"]] if "ocean_sample" in df.columns \
        else df
    night_rows = land[land["is_night"].astype(bool)]
    daylight_rows = land[~land["is_night"].astype(bool)]

    # After-dark flagged rows are the product: listed in full.
    night_flagged = night_rows[night_rows["flagged"]] \
        if "flagged" in night_rows.columns else night_rows.iloc[0:0]
    for _, r in night_flagged.sort_values("acq_time_wit").iterrows():
        anom = pd.to_numeric(r["bt07_anomaly"], errors="coerce")
        info["flags"].append({
            "acq_time_wit": str(r["acq_time_wit"]),
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "anomaly_k": round(float(anom), 1) if pd.notna(anom) else None,
        })
    info["night_flags"] = len(info["flags"])

    # Daylight flags are summarised, never enumerated: they are labelled
    # unreliable and must not crowd out the after-dark result.
    info["daylight_flags"] = int(daylight_rows["flagged"].sum()) \
        if "flagged" in daylight_rows.columns and len(daylight_rows) else 0
    info["daylight_summary"] = None
    if info["daylight_flags"]:
        times = daylight_rows["acq_time_wit"].astype(str)
        anom = pd.to_numeric(daylight_rows["bt07_anomaly"], errors="coerce")
        peak = anom.max()
        info["daylight_summary"] = {
            "t0": str(times.min())[11:16], "t1": str(times.max())[11:16],
            "peak_k": (round(float(peak), 1)
                       if pd.notna(peak) else None),
        }

    # When nothing was flagged after dark, report the largest after-dark
    # anomaly over land (flagged or not) so the reader can weigh it - always
    # with the "not a detection" clause (Task 06b / PLAN.md 13.5).
    info["largest_after_dark"] = None
    if info["night_flags"] == 0 and len(night_rows):
        anom = pd.to_numeric(night_rows["bt07_anomaly"], errors="coerce")
        if anom.notna().any():
            r = anom.idxmax()
            info["largest_after_dark"] = {
                "anomaly_k": round(float(anom.loc[r]), 1),
                "wit": str(night_rows.loc[r, "acq_time_wit"])[11:16],
                "lat": round(float(night_rows.loc[r, "lat"]), 4),
                "lon": round(float(night_rows.loc[r, "lon"]), 4),
            }

    lines.append(T["evening_slots"].format(
        retrieved=retrieved, expected=info["slots_expected"],
        cadence=cadence))
    if info["slots_missing"]:
        lines.append(T["evening_missing"].format(
            missing=info["slots_missing"]))
    if info["night_flags"]:
        lines.append(T["evening_night_flags"].format(
            n=info["night_flags"]))
        for f in info["flags"]:
            lines.append(T["evening_flag_row"].format(
                wit=f["acq_time_wit"][11:16], lat=f["lat"], lon=f["lon"],
                anom=f.get("anomaly_k", 0.0)))
    else:
        lines.append(T["evening_none_after_dark"])
        if info["daylight_summary"]:
            d = info["daylight_summary"]
            peak = d["peak_k"] if d["peak_k"] is not None else 0.0
            n = info["daylight_flags"]
            pixel = "pixel" if n == 1 else "pixels"
            lines.append(T["evening_daylight_summary"].format(
                n=n, pixel=pixel, t0=d["t0"], t1=d["t1"], peak=peak))
        if info["largest_after_dark"]:
            la = info["largest_after_dark"]
            lines.append(T["evening_largest"].format(
                anom=la["anomaly_k"], wit=la["wit"], lat=la["lat"],
                lon=la["lon"], thr=float(cfg["himawari_min_anomaly_k"])))
        lines.append(T["evening_not_evidence"])
    if info["night_flags"]:
        lines.append(T["evening_floor"])
    if info["ocean_bt14_median_k"] is not None:
        lines.append(T["evening_reader"].format(
            med=info["ocean_bt14_median_k"]))
    return info, lines


def render_brief(summary: dict, covered_day: str, gen_utc: datetime,
                 window_days: int, manifest_found: bool) -> str:
    def stamp(dt, tz):
        return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# {T['title']} — {covered_day} (WIT)",
        "",
        "_" + T["generated_line"].format(
            utc=stamp(gen_utc, timezone.utc),
            wit=stamp(gen_utc, WIT), day=covered_day) + "_",
        "_" + T["window_line"].format(days=window_days, day=covered_day) + "_",
        "",
        T["totals"].format(**summary),
        "",
        f"## {T['sources_heading']}",
        "",
        "| source | detections |",
        "|---|---|",
    ]
    for row in summary["sources"]:
        count = row["detections"] if row["status"] == "observed" \
            else STATE_CELL[row["status"]]
        lines.append(T["source_row"].format(name=row["source"], count=count))

    unobserved = [r["source"] for r in summary["sources"]
                  if r["status"] in ("failed", "norecord")]
    lines += [""]
    if unobserved:
        lines.append("> " + T["coverage_incomplete"].format(
            list=", ".join(unobserved)))
    if not manifest_found:
        lines.append(f"> {T['manifest_missing']}")
    complete = not unobserved and manifest_found
    lines += ["", T["zero_means"] if complete else T["zero_means_partial"], "",
              f"## {T['districts_heading']}",
              "", T["district_header"],
              "|---|---|---|---|---|"]
    for row in summary["districts"]:
        total_frp = "-" if row["total_frp"] is None else f"{row['total_frp']:.1f}"
        max_frp = "-" if row["max_frp"] is None else f"{row['max_frp']:.1f}"
        lines.append('| {distrik} | {kabupaten} | {det} | {tfrp} | {mfrp} |'
                     .format(distrik=row["distrik"], kabupaten=row["kabupaten"],
                             det=row["detections"], tfrp=total_frp,
                             mfrp=max_frp))
    if summary.get("recurrent_today"):
        lines += ["", f"## {T['recurrent_heading']}", ""]
        for r in summary["recurrent_today"]:
            n = r["detections_today"]
            tod = f"{n} detection" if n == 1 else f"{n} detections"
            lines.append("- " + T["recurrent_line"].format(
                site_id=r["site_id"], distrik=r["distrik"] or "-",
                today_detections=tod, days=r["days_total"]))
        lines += ["", f"> {T['recurrent_note']}"]
    if summary.get("evening_lines"):
        lines += ["", f"## {T['evening_heading']}", ""]
        lines += summary["evening_lines"]
    lines += ["", f"> {T['caveat']}", ""]
    return "\n".join(lines)


def build(cfg: dict, root: Path, now_utc: datetime | None = None,
          day: str | None = None) -> tuple[dict, list[Path]]:
    """Produce all three published outputs for `day` (default: most recent
    WIT day in the store). Deterministic apart from the generation timestamp."""
    now_utc = now_utc or datetime.now(timezone.utc)
    gen = now_utc.replace(microsecond=0)

    store = resolve(root, cfg["output_paths"]["processed"])
    if not store.exists():
        raise FileNotFoundError(f"detections store not found: {store}")
    df = pd.read_parquet(store)
    if df.empty or "date_wit" not in df:
        raise ValueError(f"detections store is empty or unparseable: {store}")
    if "on_land" not in df.columns:
        raise ValueError(f"store lacks administrative assignment (run "
                         f"src/ingest_firms.py to refresh): {store}")

    covered_day = day or df["date_wit"].max()
    day_df = df[df["date_wit"] == covered_day]

    # Fetch provenance (Task 02b). A corrupt manifest must never look like a
    # complete one - fail loudly instead of assuming observation.
    manifest_path = store.parent / MANIFEST_FILENAME
    if manifest_path.exists():
        try:
            runs = json.loads(
                manifest_path.read_text(encoding="utf-8"))["runs"]
        except (json.JSONDecodeError, KeyError) as exc:
            sys.exit(f"unreadable run manifest {manifest_path}: {exc}")
        manifest_found = True
    else:
        runs, manifest_found = [], False

    boundaries = load_boundaries(resolve(root, cfg["admin_polygon"]))
    summary = summarize(day_df, district_table(boundaries),
                        cfg["sources"], runs, covered_day)
    summary.update({"covered_wit_date": covered_day,
                    "generated_utc": gen.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "geojson_window_days": int(cfg["geojson_window_days"]),
                    "manifest_found": manifest_found})
    summary["recurrent_today"] = recurrent_today(day_df)
    evening_info, evening_lines = evening_section(cfg, root, covered_day)
    summary["evening"] = evening_info
    summary["evening_lines"] = evening_lines

    geo_path = resolve(root, cfg["output_paths"]["geojson"])
    sum_path = resolve(root, cfg["output_paths"]["summary_json"])
    brief_dir = resolve(root, cfg["output_paths"]["brief_dir"])

    window_start = (datetime.fromisoformat(covered_day)
                    - timedelta(days=int(cfg["geojson_window_days"]) - 1)
                    ).date().isoformat()
    window = df[(df["date_wit"] >= window_start)
                & (df["date_wit"] <= covered_day)]
    write_geojson(window, geo_path, summary["generated_utc"], covered_day)
    published = {
        "covered_wit_date": covered_day,
        "generated_utc": summary["generated_utc"],
        "geojson_window_days": summary["geojson_window_days"],
        "manifest_found": summary["manifest_found"],
        "totals": {k: summary[k] for k in
                   ("detections", "on_land", "offshore")},
        "sources": summary["sources"],
        "districts": summary["districts"],
        "recurrent_today": summary["recurrent_today"],
        "evening": summary["evening"],
    }
    write_summary(published, sum_path)
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / f"{covered_day}.md"
    brief_path.write_text(render_brief(summary, covered_day, gen,
                                       summary["geojson_window_days"],
                                       manifest_found),
                          encoding="utf-8")
    return summary, [brief_path, geo_path, sum_path]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Write the daily hotspot brief.")
    ap.add_argument("--day", help="WIT day to cover, YYYY-MM-DD "
                                  "(default: latest day in the store)")
    ap.add_argument("--now", help="override generation time, "
                                  "YYYY-MM-DD HH:MM:SS treated as UTC "
                                  "(testing/backfill use)")
    ap.add_argument("--allow-stale", action="store_true",
                    help="publish even when the store's latest WIT day is "
                         "not today (planned regeneration)")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "config.yaml")

    now_utc = datetime.now(timezone.utc)
    if args.now:
        now_utc = datetime.strptime(args.now, "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc)

    store = resolve(root, cfg["output_paths"]["processed"])
    if not store.exists():
        sys.exit(f"detections store not found: {store}\n"
                 "Run src/ingest_firms.py first.")
    latest = pd.read_parquet(store)["date_wit"].max()
    if args.day:
        covered = args.day
    else:
        covered = latest
        today_wit = now_utc.astimezone(WIT).date().isoformat()
        if covered != today_wit and not args.allow_stale:
            sys.exit(f"store covers up to WIT day {covered} but today is "
                     f"{today_wit}. Refusing to republish old data as "
                     "current. Re-run src/ingest_firms.py, or pass "
                     "--allow-stale if regenerating deliberately.")

    summary, paths = build(cfg, root, now_utc=now_utc, day=covered)
    for p in paths:
        print(p.relative_to(root))
    print(f"covered {summary['covered_wit_date']}: "
          f"{summary['detections']} detections, "
          f"{summary['offshore']} offshore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
