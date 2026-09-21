"""When burning is first seen from the geostationary orbit (Task 20,
PLAN.md Phase 4 item 4; PLAN.md 13).

VIIRS looks at Biak about twice a day, around 13:00 and 01:00 WIT, so an
event's first_seen (Task 16) is the first polar-orbit look that caught it,
not when the burning began. Himawari-9 scans every 10 minutes at 2 km;
this script narrows the gap for the largest events by computing the onset
bracket: the last slot at which the event's pixels were clear and quiet,
and the first slot at which they were anomalously hot.

A bracket is when heat first rose above a 2 km sensor's detection floor.
A small or smouldering fire can burn for hours below that floor
(PLAN.md 13.5), so the bracket is an upper bound on when heat was
present, never a start time. It says nothing about why land was burned or
by whom (PLAN.md section 8) - that override governs every field, key and
caveat here, which is why the words are "first Himawari flag", "onset
bracket" and "last quiet slot".

Everything reuses the Task 05/06 reader (src/himawari.py): read_hsd,
counts_to_bt, lonlat_grid, locate_aoi, segment_window, flag_anomalies,
slot_key, fetch_slot_file, is_night - and the evening product's land test
and thresholds. One fix lives in fetch_slot_file itself (404 = absent
upstream; any other failure raises - a failed request is not an empty
slot, AGENTS never-2), so the evening product inherits it.

Per slot an event is in exactly one state:
  missing    a band-segment it needs is absent upstream (404) - not a zero
  obscured   no event pixel can show heat: none has B14 >= cloud_bt14_k.
             Obscured is not quiet, and it is not a cloud mask.
  flagged    at least one clear (non-obscured) event pixel is flagged by
             the existing flag_anomalies thresholds
  quiet      at least one clear pixel and none flagged

Pre-registered readings, in this order, decided before the numbers:
  too_few_slots, not_resolved, flagged_from_window_start, bracketed,
  no_quiet_slot.

Writes data/processed/himawari_onset.json (sorted keys, indent 1, no
timestamp, deterministic). Raw band-segments land in data/raw/himawari/
(gitignored, AGENTS always-2); a raise stops the run and writes nothing -
no placeholder, no synthetic brightness temperatures, ever. No FINDINGS.md
entry (the Task 17 override): the entry is written at review from the JSON.

    python src/himawari_onset.py [--fetch]
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from himawari import (BANDS, fetch_slot_file, flag_anomalies, is_night,
                      locate_aoi, lonlat_grid, read_hsd, counts_to_bt,
                      segment_window, slot_key)
from events import membership
from ingest_firms import WIT, land_hits, load_boundaries

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "himawari"
OUT = ROOT / "data" / "processed" / "himawari_onset.json"
DET = ROOT / "data" / "processed" / "detections.parquet"
EVENTS = ROOT / "data" / "processed" / "events.json"
ABSENT = RAW_DIR / "absent_upstream.json"

STATES = ("missing", "obscured", "flagged", "quiet")
READINGS = ("too_few_slots", "not_resolved", "flagged_from_window_start",
            "bracketed", "no_quiet_slot")

CAVEATS = [
    "A first Himawari flag is when heat first rose above a 2 km sensor's "
    "detection floor. Burning can run below that floor for hours, so the "
    "onset bracket bounds when heat was present; it is never a start time.",
    "Obscured means the event's pixels were colder than the cloud "
    "threshold (B14). It is not a cloud mask: thin cloud passes it, and an "
    "obscured slot says nothing about the ground.",
    "In daylight, reflected sunlight raises the 3.9 um band. The anomaly "
    "is measured against the local background, which removes most of it; "
    "the thresholds remain provisional (PLAN.md 13.4).",
    "Timing says nothing about why land was burned or who burned it "
    "(PLAN.md section 8).",
]


# ---------------------------------------------------------------------------
# slots, windows, readings, brackets
# ---------------------------------------------------------------------------
def floor10(ts: datetime) -> datetime:
    """Round down to the 10-minute AHI slot."""
    return ts.replace(minute=ts.minute // 10 * 10, second=0, microsecond=0)


def slots_between(first_dt, last_dt, cadence):
    out, t = [], first_dt
    while t <= last_dt:
        out.append(t)
        t += timedelta(minutes=cadence)
    return out


def event_window(first_seen_utc, lookback_hours, after_minutes, cadence):
    """UTC slot window around an event's first polar-orbit look:
    [floor10(first_seen) - lookback, floor10(first_seen) + after]."""
    anchor = floor10(pd.Timestamp(first_seen_utc).tz_convert("UTC")
                     .to_pydatetime())
    first = anchor - timedelta(hours=lookback_hours)
    last = anchor + timedelta(minutes=after_minutes)
    return first, last, slots_between(first, last, cadence)


def viirs_slots(first_seen_utc, after_minutes, cadence):
    """The slots at and just after the VIIRS look: the validation."""
    anchor = floor10(pd.Timestamp(first_seen_utc).tz_convert("UTC")
                     .to_pydatetime())
    return [anchor + timedelta(minutes=m)
            for m in range(0, after_minutes + 1, cadence)]


def slots_for_wit_day(day_iso, cadence):
    """Every AHI slot of one WIT day: 00:00 WIT is 15:00 UTC the day
    before, then cadence-minute steps through 23:50 WIT. The slots are
    normalized to UTC so slot_key, filenames and the absence records
    carry true UTC instants."""
    d = date.fromisoformat(day_iso)
    start = (datetime(d.year, d.month, d.day, tzinfo=WIT)
             - timedelta(hours=9)).astimezone(timezone.utc)
    return [start + timedelta(minutes=cadence * k)
            for k in range(24 * 60 // cadence)]


def slots_for_wit_days(day_first, day_last, cadence):
    out, cur = [], date.fromisoformat(day_first)
    last = date.fromisoformat(day_last)
    while cur <= last:
        out.extend(slots_for_wit_day(cur.isoformat(), cadence))
        cur += timedelta(days=1)
    return out


def reading_of(states, seen_at_viirs, min_slot_share):
    """Exactly one pre-registered reading, in this order."""
    not_missing = sum(1 for s in states if s != "missing")
    if not states or not_missing / len(states) < min_slot_share:
        return "too_few_slots"
    if not seen_at_viirs:
        return "not_resolved"
    if states[0] == "flagged":
        return "flagged_from_window_start"
    first_flag = next((i for i, s in enumerate(states) if s == "flagged"),
                      None)
    if first_flag is not None and any(
            s == "quiet" for s in states[:first_flag]):
        return "bracketed"
    return "no_quiet_slot"


def bracket_from_states(states, slots):
    """first_flag / last_quiet indices and the gap between them. The
    bracket is open on the left when the window opens flagged; gap_states
    counts the missing/obscured slots inside it, because a wide gap full
    of cloud leaves the heat's arrival unknown within it."""
    first_flag = next((i for i, s in enumerate(states) if s == "flagged"),
                      None)
    if first_flag is None:
        return None, None, None, {}
    last_quiet = max((i for i, s in enumerate(states[:first_flag])
                      if s == "quiet"), default=None)
    gap = {}
    if last_quiet is not None:
        for s in states[last_quiet + 1:first_flag]:
            gap[s] = gap.get(s, 0) + 1
    minutes = ((slots[first_flag] - slots[last_quiet]).total_seconds()
               / 60.0) if last_quiet is not None else None
    return first_flag, last_quiet, minutes, gap


def slot_state(pixels_by_seg, seg_grids, cloud_bt14_k):
    """One slot's segment grids for one event ->
    (state, max_anomaly_k, max_bt_diff_k, min_b14_k).
    missing beats obscured beats flagged beats quiet. obscured = no event
    pixel can show heat (no finite B14 at or above the threshold); it is
    not a cloud mask and it is not quiet."""
    clears, flags, anoms, diffs, b14s = [], [], [], [], []
    for seg, px_list in pixels_by_seg.items():
        g = seg_grids.get(seg)
        if g is None:
            return "missing", None, None, None
        rc = np.asarray(px_list)
        rows, cols = rc[:, 0], rc[:, 1]
        clear = np.isfinite(g["bt14"][rows, cols]) \
            & (g["bt14"][rows, cols] >= cloud_bt14_k)
        clears.append(clear)
        flags.append(g["flagged"][rows, cols] & clear)
        anoms.append(g["anomaly"][rows, cols])
        diffs.append(g["diff"][rows, cols])
        b14s.append(g["bt14"][rows, cols])
    clear = np.concatenate(clears)
    flag = np.concatenate(flags)
    b14 = np.concatenate(b14s)
    if not clear.any():
        return "obscured", None, None, (
            round(float(np.nanmin(b14)), 2) if np.isfinite(b14).any()
            else None)
    state = "flagged" if flag.any() else "quiet"
    anom = np.concatenate(anoms)[clear]
    diff = np.concatenate(diffs)[clear]
    return (state,
            round(float(np.nanmax(anom)), 2)
            if np.isfinite(anom).any() else None,
            round(float(np.nanmax(diff)), 2)
            if np.isfinite(diff).any() else None,
            round(float(np.nanmin(b14)), 2) if np.isfinite(b14).any()
            else None)


# ---------------------------------------------------------------------------
# raw band-segments: paths, absence bookkeeping, the fetch pass
# ---------------------------------------------------------------------------
def local_path(slot, band, segment) -> Path:
    return RAW_DIR / slot_key(slot, band, segment).split("/")[-1]


def absent_set() -> set:
    if ABSENT.exists():
        return {(datetime.fromisoformat(r["slot_utc"]), r["band"],
                 r["segment"])
                for r in json.loads(ABSENT.read_text(encoding="utf-8"))}
    return set()


def mark_absent(absent: set) -> None:
    rows = sorted(
        ({"slot_utc": s.isoformat(), "band": b, "segment": g}
         for s, b, g in absent),
        key=lambda r: (r["slot_utc"], r["band"], r["segment"]))
    ABSENT.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")


def jobs_for(slots_by_seg, bands):
    """(slot, band, segment) triples, sorted."""
    jobs = set()
    for slot, segs in slots_by_seg.items():
        for band in bands:
            for seg in segs:
                jobs.add((slot, band, seg))
    return sorted(jobs, key=lambda j: (j[0], j[1], j[2]))


def plan_and_report(jobs, absent) -> None:
    """What is on disk, what must come from upstream, and what that
    weighs - measured from the band-segments already here."""
    existing = list(RAW_DIR.glob("*.DAT.bz2"))
    per_file = (float(np.mean([p.stat().st_size for p in existing]))
                if existing else 6_050_000.0)
    todo = [j for j in jobs if j not in absent
            and not local_path(*j).exists()]
    print(f"band-segments needed: {len(jobs)}  on disk: "
          f"{len(jobs) - len(todo)}  to fetch: {len(todo)}  "
          f"~{len(todo) * per_file / 1e9:.1f} GB at "
          f"{per_file / 1e6:.2f} MB/file")


def fetch_jobs(jobs, absent) -> None:
    """Download what is missing, recording 404s as absent-upstream facts.
    Any other failure raises out of fetch_slot_file and stops the run."""
    todo = [j for j in jobs if j not in absent
            and not local_path(*j).exists()]
    for k, (slot, band, seg) in enumerate(sorted(todo), 1):
        p = fetch_slot_file(slot, band, seg, RAW_DIR)
        if p is None:
            absent.add((slot, band, seg))
        if k % 50 == 0:
            print(f"  {k}/{len(todo)} fetched, {len(absent)} absent "
                  "upstream", flush=True)
    mark_absent(absent)


def first_missing(jobs, absent):
    for slot, band, seg in jobs:
        if (slot, band, seg) not in absent \
                and not local_path(slot, band, seg).exists():
            return slot, band, seg
    return None

# ---------------------------------------------------------------------------
# events -> pixels
# ---------------------------------------------------------------------------
def match_pixels(chosen, member_map, det_pos, seg_ll):
    """Member detections -> the AHI pixel whose centre is nearest across
    all AOI segment windows (no buffer: a 2 km pixel already covers
    several VIIRS pixels). seg_ll = {segment: (lon_grid, lat_grid)}.
    Returns {event_id: {segment: [(row, col), ...]}}."""
    members_of = {}
    for did, eid in member_map.items():
        members_of.setdefault(eid, []).append(did)
    out = {}
    for ev in chosen:
        px = {}
        for did in members_of.get(ev["event_id"], []):
            pos = det_pos.get(did)
            if pos is None:
                continue
            lat, lon = pos
            best = None
            for seg, (lon_g, lat_g) in seg_ll.items():
                d2 = (lon_g - lon) ** 2 + (lat_g - lat) ** 2
                r, c = np.unravel_index(np.argmin(d2), d2.shape)
                if best is None or d2[r, c] < best[0]:
                    best = (float(d2[r, c]), seg, int(r), int(c))
            if best is not None:
                px.setdefault(best[1], set()).add((best[2], best[3]))
        out[ev["event_id"]] = {seg: sorted(v) for seg, v in px.items()}
    return out


# ---------------------------------------------------------------------------
# slot processing
# ---------------------------------------------------------------------------
def read_slot_grids(slot, seg, win, absent, th):
    """Both bands of one segment for one slot, read from disk, sliced to
    the AOI window and flagged with the existing thresholds. None when
    the segment is absent upstream (recorded 404)."""
    p7, p14 = local_path(slot, "B07", seg), local_path(slot, "B14", seg)
    if (slot, "B07", seg) in absent or (slot, "B14", seg) in absent:
        return None
    if not p7.exists() or not p14.exists():
        raise SystemExit(
            f"missing raw band-segment: slot {slot:%Y-%m-%dT%H:%MZ} "
            f"segment {seg} under data/raw/himawari - run with --fetch")
    hsd7 = read_hsd(p7)
    sub07 = counts_to_bt(hsd7)
    sub14 = counts_to_bt(read_hsd(p14))
    r0, r1, c0, c1, _ = segment_window(hsd7, *win)
    sub07, sub14 = sub07[r0:r1, c0:c1], sub14[r0:r1, c0:c1]
    _, anom, diff, flagged = flag_anomalies(
        sub07, sub14, th["min_anomaly_k"], th["min_bt_diff_k"],
        int(th["background_window_px"]))
    return {"bt07": sub07, "bt14": sub14, "anomaly": anom, "diff": diff,
            "flagged": flagged}


def process_states(events_active, ev_px, segs_needed, absent, th, win):
    """Per slot: read what that slot needs once, then assign each active
    event exactly one state. events_active: {slot: [event_id, ...]},
    ev_px: {event_id: {segment: [(row, col), ...]}}."""
    out = {ev_id: [] for ids in events_active.values() for ev_id in ids}
    for slot in sorted(events_active):
        seg_grids = {seg: read_slot_grids(slot, seg, win, absent, th)
                     for seg in sorted(segs_needed[slot])}
        for ev_id in events_active[slot]:
            st, mx_a, mx_d, mn_b = slot_state(ev_px[ev_id], seg_grids,
                                              th["cloud_bt14_k"])
            out[ev_id].append({
                "slot_utc": slot.strftime("%Y-%m-%dT%H:%MZ"),
                "state": st, "max_anomaly_k": mx_a,
                "max_bt_diff_k": mx_d, "min_b14_k": mn_b,
            })
    return out


def process_diurnal(slots, segs, land_grids, absent, th, win, sunset_min):
    """AOI-wide diurnal curve over land pixels for the peak WIT days:
    the same land test and thresholds as the evening product."""
    out = []
    for slot in slots:
        wit = slot.astimezone(WIT)
        row = {"slot_utc": slot.strftime("%Y-%m-%dT%H:%MZ"),
               "wit_day": wit.date().isoformat(),
               "wit_hour": wit.hour,
               "is_night": is_night(wit.hour * 60 + wit.minute, sunset_min)}
        n_land = n_obsc = n_flag = 0
        for seg in sorted(segs):
            g = read_slot_grids(slot, seg, win, absent, th)
            if g is None:
                continue
            land = land_grids[seg]
            is_land = land & np.isfinite(g["bt07"])
            clear14 = np.isfinite(g["bt14"]) \
                & (g["bt14"] >= th["cloud_bt14_k"])
            n_land += int(is_land.sum())
            n_obsc += int((is_land & ~clear14).sum())
            n_flag += int((is_land & clear14 & g["flagged"]).sum())
        row["n_land_px"], row["n_obscured"], row["n_flagged"] = \
            n_land, n_obsc, n_flag
        out.append(row)
    return out


def diurnal_by_hour(rows):
    """Per WIT hour: flagged pixels summed, obscured share."""
    hours = {}
    for r in rows:
        h = hours.setdefault(r["wit_hour"], {"flagged_px": 0,
                                             "land_px": 0,
                                             "obscured_px": 0})
        h["flagged_px"] += r["n_flagged"]
        h["land_px"] += r["n_land_px"]
        h["obscured_px"] += r["n_obscured"]
    return {h: {"flagged_px": v["flagged_px"],
                "obscured_share": round(v["obscured_px"] / v["land_px"], 4)
                if v["land_px"] else None}
            for h, v in sorted(hours.items())}


# ---------------------------------------------------------------------------
def land_grids_for(seg_ll, admin_path):
    """The evening product's land test, computed once per segment."""
    boundaries = load_boundaries(admin_path) if admin_path else None
    grids = {}
    for seg, (lon_g, lat_g) in seg_ll.items():
        if boundaries is None:
            grids[seg] = np.ones(lon_g.shape, dtype=bool)
        else:
            grids[seg] = np.array(
                [hit is not None for hit in
                 land_hits(lon_g.ravel(), lat_g.ravel(), boundaries)]
            ).reshape(lon_g.shape)
    return grids


def summarise(per_event):
    """Reading counts and the bracketed summary. Reading names travel as
    VALUES here, never as keys: the wording override bans the fragments
    of their names from the document's keys."""
    counts = {r: 0 for r in READINGS}
    for rec in per_event:
        counts[rec["reading"]] += 1
    ff_slot_counts = {}
    for rec in per_event:
        if rec["first_flag_utc"]:
            ff_slot_counts[rec["first_flag_utc"]] = \
                ff_slot_counts.get(rec["first_flag_utc"], 0) + 1
    ff_hours, shared = {}, 0
    leads, gaps = [], []
    for rec in per_event:
        if rec["first_flag_utc"]:
            if ff_slot_counts[rec["first_flag_utc"]] > 1:
                shared += 1
            if rec["reading"] not in ("too_few_slots", "not_resolved"):
                h = rec["first_flag_wit"][11:13]
                ff_hours[h] = ff_hours.get(h, 0) + 1
        if rec["reading"] == "bracketed":
            leads.append(rec["lead_minutes"])
            gaps.append(rec["gap_minutes"])
    summary = {
        "readings": [{"reading": r, "n": counts[r]} for r in READINGS],
        "first_flag_wit_hour": {h: ff_hours[h] for h in sorted(ff_hours)},
        "events_sharing_first_flag_slot": shared,
    }
    if leads:
        summary["lead_minutes"] = {
            "median": round(float(np.median(leads)), 1),
            "min": round(float(np.min(leads)), 1),
            "max": round(float(np.max(leads)), 1)}
        summary["gap_minutes"] = {
            "median": round(float(np.median(gaps)), 1),
            "min": round(float(np.min(gaps)), 1),
            "max": round(float(np.max(gaps)), 1)}
    return summary


def build_document(on, th, chosen, below, ev_px, per_event, diurnal_rows,
                   named_case, cfg):
    return {
        "parameters": {
            "min_detections": on["min_detections"],
            "lookback_hours": on["lookback_hours"],
            "after_minutes": on["after_minutes"],
            "cadence_minutes": on["cadence_minutes"],
            "cloud_bt14_k": on["cloud_bt14_k"],
            "min_slot_share": on["min_slot_share"],
            "diurnal_days": on["diurnal_days"],
            "named_case": on["named_case"],
            "min_anomaly_k": th["min_anomaly_k"],
            "min_bt_diff_k": th["min_bt_diff_k"],
            "background_window_px": th["background_window_px"],
            "expected_segments": cfg["himawari_expected_segments"],
        },
        "events_assessed": [ev["event_id"] for ev in chosen],
        "events_below_bar": below,
        "events": per_event,
        "summary": summarise(per_event),
        "diurnal": {
            "days": on["diurnal_days"],
            "by_slot": diurnal_rows,
            "by_wit_hour": diurnal_by_hour(diurnal_rows),
        },
        "named_case": on["named_case"] | named_case,
        "caveats": CAVEATS,
    }


def diurnal_by_hour(rows):
    hours = {}
    for r in rows:
        h = hours.setdefault(r["wit_hour"], {"flagged_px": 0,
                                             "land_px": 0,
                                             "obscured_px": 0})
        h["flagged_px"] += r["n_flagged"]
        h["land_px"] += r["n_land_px"]
        h["obscured_px"] += r["n_obscured"]
    return {h: {"flagged_px": v["flagged_px"],
                "obscured_share": round(v["obscured_px"] / v["land_px"], 4)
                if v["land_px"] else None}
            for h, v in sorted(hours.items())}


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true",
                    help="download missing band-segments (network only "
                         "here, never from the cron)")
    ap.add_argument("--plan", action="store_true",
                    help="print the fetch plan (file count, size) and exit")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    on = cfg["himawari_onset"]
    th = {"min_anomaly_k": cfg["himawari_min_anomaly_k"],
          "min_bt_diff_k": cfg["himawari_min_bt_diff_k"],
          "background_window_px": cfg["himawari_background_window_px"],
          "cloud_bt14_k": on["cloud_bt14_k"]}
    sunset = cfg["himawari_sunset_wit"].replace(":", "")
    sunset_min = int(sunset[:-2]) * 60 + int(sunset[-2:])

    events_doc = json.loads(EVENTS.read_text(encoding="utf-8"))
    member_map = membership(events_doc)
    det = pd.read_parquet(DET)
    det_pos = {r.detection_id: (r.latitude, r.longitude)
               for r in det.itertuples()}
    chosen = [e for e in events_doc["events"]
              if e["n_detections"] >= on["min_detections"]]
    below = [{"event_id": e["event_id"], "n_detections": e["n_detections"]}
             for e in events_doc["events"]
             if e["n_detections"] < on["min_detections"]]
    print(f"events at or above the bar "
          f"(n_detections >= {on['min_detections']}): {len(chosen)} "
          f"({len(below)} below it)")

    ev_slots, all_slots = {}, set()
    for ev in chosen:
        _, _, slots = event_window(ev["first_seen_utc"],
                                   on["lookback_hours"],
                                   on["after_minutes"],
                                   on["cadence_minutes"])
        ev_slots[ev["event_id"]] = slots
        all_slots.update(slots)
    diurnal_slots = slots_for_wit_days(*on["diurnal_days"],
                                       on["cadence_minutes"])
    nc = on["named_case"]
    nc_slots = slots_for_wit_day(nc["wit_day"], on["cadence_minutes"])
    all_slots |= set(diurnal_slots) | set(nc_slots)
    all_slots = sorted(all_slots)

    absent = absent_set()
    # navigation comes from the earliest slot that exists; segments and
    # the AOI window come from the navigation block, never hard-coded
    probe = next((local_path(s, "B07", seg) for s in all_slots
                  for seg in (5, 6)
                  if local_path(s, "B07", seg).exists()), None)
    if probe is None:
        if not args.fetch:
            raise SystemExit(
                f"no raw band-segment on disk; first slot needed is "
                f"{all_slots[0]:%Y-%m-%dT%H:%MZ} - run with --fetch")
        for seg in (5, 6):
            probe = fetch_slot_file(all_slots[0], "B07", seg, RAW_DIR)
            if probe is not None:
                break
        if probe is None:
            raise SystemExit(f"upstream has no slot for "
                             f"{all_slots[0]:%Y-%m-%dT%H:%MZ}")
    nav = read_hsd(probe)
    segments, line0, line1, col0, col1 = locate_aoi(
        nav, [float(v) for v in cfg["aoi_bbox_wsen"]])
    if segments != {int(s) for s in cfg["himawari_expected_segments"]}:
        raise SystemExit(f"AOI resolves to segments {sorted(segments)}, "
                         f"expected "
                         f"{cfg['himawari_expected_segments']} - product "
                         "layout changed? Investigate before trusting any "
                         "output.")
    win = (line0, line1, col0, col1)

    # one B07 file per segment, read for pixel matching (the earliest slot
    # that has it); navigation is constant across slots
    seg_ll = {}
    for seg in sorted(segments):
        p = next((local_path(s, "B07", seg) for s in all_slots
                  if local_path(s, "B07", seg).exists()), None)
        if p is None:
            raise SystemExit(f"no B07 band-segment on disk for segment "
                             f"{seg} - run with --fetch")
        hsd = read_hsd(p)
        r0, r1, c0, c1, _ = segment_window(hsd, *win)
        seg_ll[seg] = lonlat_grid(
            hsd, np.arange(r0, r1) + hsd["seg_first_line"],
            np.arange(c0, c1))
    ev_px = match_pixels(chosen, member_map, det_pos, seg_ll)

    # which segments each slot needs: events active there, plus the whole
    # AOI for the diurnal and named-case days
    active = {slot: [] for slot in all_slots}
    for ev in chosen:
        for slot in ev_slots[ev["event_id"]]:
            active[slot].append(ev["event_id"])
    segs_needed = {}
    for slot in all_slots:
        segs = set()
        for ev_id in active[slot]:
            segs |= set(ev_px[ev_id])
        if slot in set(diurnal_slots) or slot in set(nc_slots):
            segs |= set(segments)
        segs_needed[slot] = segs

    jobs = jobs_for(segs_needed, BANDS)
    if args.plan:
        plan_and_report(jobs, absent)
        return 0
    if args.fetch:
        plan_and_report(jobs, absent)
        fetch_jobs(jobs, absent)
    else:
        missing = first_missing(jobs, absent)
        if missing is not None:
            slot, band, seg = missing
            raise SystemExit(
                f"missing raw band-segment: slot "
                f"{slot:%Y-%m-%dT%H:%MZ} band {band} segment {seg} under "
                f"data/raw/himawari - run with --fetch")
    states = process_states(active, ev_px, segs_needed, absent, th, win)

    admin_path = ROOT / cfg["admin_polygon"] if cfg.get("admin_polygon") \
        else None
    lgrids = land_grids_for(seg_ll, admin_path) if admin_path else {
        seg: np.ones(seg_ll[seg][0].shape, dtype=bool) for seg in seg_ll}

    per_event = []
    for ev in chosen:
        ev_id = ev["event_id"]
        rows = states[ev_id]
        slots = ev_slots[ev_id]
        sts = [r["state"] for r in rows]
        counts = {s: sts.count(s) for s in STATES}
        ff_i, lq_i, gap_min, gap_states = bracket_from_states(sts, slots)
        vs = viirs_slots(ev["first_seen_utc"], on["after_minutes"],
                         on["cadence_minutes"])
        vs_iso = {s.strftime("%Y-%m-%dT%H:%MZ") for s in vs}
        by_iso = {r["slot_utc"]: r["state"] for r in rows}
        seen = any(by_iso.get(i) == "flagged" for i in vs_iso)
        reading = reading_of(sts, seen, on["min_slot_share"])
        ff_utc = (slots[ff_i].strftime("%Y-%m-%dT%H:%MZ")
                  if ff_i is not None else None)
        ff_wit = (slots[ff_i].astimezone(WIT)
                  .strftime("%Y-%m-%dT%H:%M+09:00")
                  if ff_i is not None else None)
        lq_utc = (slots[lq_i].strftime("%Y-%m-%dT%H:%MZ")
                  if lq_i is not None else None)
        lq_wit = (slots[lq_i].astimezone(WIT)
                  .strftime("%Y-%m-%dT%H:%M+09:00")
                  if lq_i is not None else None)
        lead = None
        if ff_i is not None:
            lead = round((floor10(pd.Timestamp(ev["first_seen_utc"])
                                  .tz_convert("UTC").to_pydatetime())
                          - slots[ff_i]).total_seconds() / 60.0, 1)
        per_event.append({
            "event_id": ev_id,
            "n_detections": ev["n_detections"],
            "pixel_count": sum(len(v) for v in ev_px[ev_id].values()),
            "window_first_slot_utc":
                slots[0].strftime("%Y-%m-%dT%H:%MZ"),
            "window_last_slot_utc":
                slots[-1].strftime("%Y-%m-%dT%H:%MZ"),
            "state_counts": counts,
            "first_flag_utc": ff_utc, "first_flag_wit": ff_wit,
            "last_quiet_utc": lq_utc, "last_quiet_wit": lq_wit,
            "gap_minutes": gap_min, "gap_states": gap_states,
            "seen_at_viirs": seen, "lead_minutes": lead,
            "reading": reading,
            "slot_states": rows,
        })

    diurnal_rows = process_diurnal(diurnal_slots, segments, lgrids, absent,
                                   th, win, sunset_min)
    nc_ev = next((e for e in events_doc["events"]
                  if e["event_id"] == nc["event_id"]), None)
    named_case = {"event_id": nc["event_id"], "wit_day": nc["wit_day"]}
    if nc_ev is not None:
        px = match_pixels([nc_ev], member_map, det_pos, seg_ll)[nc["event_id"]]
        nc_states = []
        for slot in nc_slots:
            seg_grids = {seg: read_slot_grids(slot, seg, win, absent, th)
                         for seg in sorted(px)}
            st, mx_a, mx_d, mn_b = slot_state(px, seg_grids,
                                              on["cloud_bt14_k"])
            nc_states.append({
                "slot_utc": slot.strftime("%Y-%m-%dT%H:%MZ"),
                "state": st, "max_anomaly_k": mx_a,
                "max_bt_diff_k": mx_d, "min_b14_k": mn_b})
        nc_states_by_hour = {}
        for slot, s in zip(nc_slots, nc_states):
            h = slot.astimezone(WIT).hour
            nc_states_by_hour.setdefault(h, {})
            hh = nc_states_by_hour[h]
            hh[s["state"]] = hh.get(s["state"], 0) + 1
        named_case |= {"pixel_count": sum(len(v) for v in px.values()),
                       "slot_states": nc_states,
                       "by_wit_hour": nc_states_by_hour}

    doc = build_document(on, th, chosen, below, ev_px, per_event,
                         diurnal_rows, named_case, cfg)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")

    s = doc["summary"]
    print("reading counts: " + ", ".join(
        f"{row['reading']} {row['n']}" for row in s["readings"]))
    print("first-flag WIT hour: " + ", ".join(
        f"{h} {n}" for h, n in s["first_flag_wit_hour"].items()))
    print("diurnal by WIT hour (flagged px / obscured share):")
    for h, v in doc["diurnal"]["by_wit_hour"].items():
        print(f"  {h:02d}: {v['flagged_px']} / {v['obscured_share']}")
    print(f"named case {nc['event_id']} {nc['wit_day']}:")
    for r in doc["named_case"]["slot_states"]:
        print(f"  {r['slot_utc']} {r['state']:9s} "
              f"max_anom {r['max_anomaly_k']} min_b14 {r['min_b14_k']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
