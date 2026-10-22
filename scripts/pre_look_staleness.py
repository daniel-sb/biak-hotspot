"""Which assessed events were measured against a stale pre-fire look, and
in which direction the staleness moves their area (Task 28).

Task 18's `nearest_look` picks, per pixel, the latest clear look before
`first_seen` inside a 60-day window. The pre side is usually much older
than the post side: the median pre lag is 12.2 days against 2.9 days
after. This script separates the two opposite consequences of that
asymmetry:

  scar_in_pre             D < P < F: the ground burned before the pre look,
                          so the "before" image is already dark and the
                          event's area is under-stated;
  earlier_burn_included   P < D < F: the pre look predates older burning,
                          so that older change is counted with this event
                          and the area is over-stated;
  no_prior_detection      no prior detection strictly before the pre look.

The directions are never added together. This script does not recompute,
correct, or rank any area. `changed_ha` is Task 18's published figure; a
stale look is a reason to re-examine an event, not a measurement of error.

P is an ESTIMATE, not a scene date: burned_areas.json stores pre_lag only
as p50 and p90 percentiles over the event's pixels. The p50 estimate is
`first_seen_utc` minus the p50 lag, converted to WIT for comparison with
the WIT detection days. Individual pixels sit on both sides of it.

    python scripts/pre_look_staleness.py

Offline: the four inputs are tracked files, and no Earth Engine call is
made. If an input is missing or unreadable, the script names it and exits
non-zero without writing.

Writes data/processed/pre_look_staleness.json.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from burned_area_gee import footprint          # noqa: E402
from events import membership as membership_map  # noqa: E402
from fieldwork_gpkg import metres              # noqa: E402

CONFIG = ROOT / "config.yaml"
BURNED = ROOT / "data/processed/burned_areas.json"
EVENTS = ROOT / "data/processed/events.json"
DETECTIONS = ROOT / "data/processed/detections.parquet"
SITES = ROOT / "data/processed/recurrent_sites.json"
OUT = ROOT / "data/processed/pre_look_staleness.json"

WIT = timezone(timedelta(hours=9))
STALE_DAYS = 14
DIRECTIONS = ("scar_in_pre", "earlier_burn_included", "no_prior_detection")

CAVEATS = [
    "The pre look date is an estimate: first_seen_utc minus the stored "
    "pre_lag p50 or p90, then converted to WIT. It is not the date of a "
    "scene; individual pixels sit on both sides of it.",
    "The direction comparison uses WIT days. The pre look instant is "
    "anchored on first_seen_utc, then shifted to WIT; acq_date is already "
    "a WIT local day and is not shifted again; the prior cutoff is the "
    "first_seen_wit day.",
    "A prior detection makes contamination possible, not established: a "
    "VIIRS pixel locates a thermal anomaly, not a perimeter.",
    "changed_ha is the published Task 18 figure. Nothing here recomputes, "
    "corrects, or ranks it, and the two directions are never added "
    "together.",
    "no_prior_detection means no prior detection strictly before the "
    "estimated pre look. A detection exactly on the pre look date is "
    "neither before nor after and falls in this group; its count and date "
    "are still reported.",
    "Recurrence distance is centroid-to-site. Whether the footprint comes "
    "within recurrence.radius_m is computed from the member circles, not "
    "the centroid. recurrent_share is read from events.json and is not "
    "reconciled with the distance.",
    "The 8 assessed entries with status no local reference have no lag "
    "fields and no direction; they are listed separately, not dropped.",
    "p50 and p90 are separate estimates. When they disagree, both "
    "directions are reported and the event is not resolved to one.",
]


# --------------------------------------------------------------------------
def load_json(path):
    if not Path(path).exists():
        raise SystemExit("%s: missing - nothing written" % path)
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (path, err))


def load_config():
    try:
        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (CONFIG, err))
    try:
        footprint_m = float(cfg["burned_area"]["footprint_m"])
        pre_days = int(cfg["burned_area"]["pre_days"])
        radius_m = float(cfg["recurrence"]["radius_m"])
    except Exception as err:
        raise SystemExit("%s: staleness parameters: %s - nothing written"
                         % (CONFIG, err))
    return footprint_m, pre_days, radius_m


def parse_utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")) \
        .astimezone(timezone.utc)


def pre_look_dates(first_seen_utc, lag_days):
    """(UTC date, WIT date) of first_seen_utc minus lag_days. The WIT date
    is the one compared with acq_date and first_seen_wit."""
    instant = parse_utc(first_seen_utc) - timedelta(days=float(lag_days))
    return instant.date(), instant.astimezone(WIT).date()


def direction(d, pre_look, first_seen):
    """The three-way label. Strictly less than on both sides: D equal to
    the pre look date is neither before nor after it."""
    if d is None or pre_look is None:
        return "no_prior_detection"
    if d < pre_look < first_seen:
        return "scar_in_pre"
    if pre_look < d < first_seen:
        return "earlier_burn_included"
    return "no_prior_detection"


def classify(d, pre_p50, pre_p90, first_seen):
    """(direction_p50, direction_p90, differ) computed independently."""
    p50 = direction(d, pre_p50, first_seen)
    p90 = direction(d, pre_p90, first_seen)
    return p50, p90, p50 != p90


def prior_rows(det, member_ids, geo, first_seen_wit):
    """Detections inside the footprint, strictly before the event's WIT
    day, excluding the event's own members. acq_date is already WIT."""
    rows = []
    for r in det.itertuples(index=False):
        if r.detection_id in member_ids:
            continue
        if r.acq_date_d >= first_seen_wit:
            continue
        if geo.covers(Point(r.longitude, r.latitude)):
            rows.append(r)
    return rows


def latest_prior(rows):
    """(date, frp, confidence, count on that date) for the most recent
    prior detection day. On a tie, the strongest FRP is reported; the
    count on the date stays visible."""
    if not rows:
        return None, None, None, 0
    d = max(r.acq_date_d for r in rows)
    same = [r for r in rows if r.acq_date_d == d]
    top = max(same, key=lambda r: (float(r.frp)
                                   if pd.notna(r.frp) else -1.0))
    frp = None if pd.isna(top.frp) else round(float(top.frp), 3)
    confidence = None if pd.isna(top.confidence) else str(top.confidence)
    return d, frp, confidence, len(same)


def site_distances(event, members, sites, footprint_m, radius_m):
    """Centroid distances to each site, and whether the member circles come
    within radius_m of one. The footprint distance is computed from the
    circles, not from the centroid."""
    centroid = (float(event["centroid_lat"]), float(event["centroid_lon"]))
    points = [(float(r.latitude), float(r.longitude))
              for r in members.itertuples(index=False)]
    distances = {}
    edges = {}
    within = []
    for site in sites:
        distances[site["id"]] = round(metres(
            centroid[0], centroid[1], site["centroid_lat"],
            site["centroid_lon"]), 1)
        nearest_member = min(metres(
            site["centroid_lat"], site["centroid_lon"], lat, lon)
            for lat, lon in points)
        edge = max(0.0, nearest_member - footprint_m)
        edges[site["id"]] = round(edge, 1)
        if edge <= radius_m:
            within.append(site["id"])
    nearest_id = min(distances, key=distances.get)
    return distances, edges, nearest_id, distances[nearest_id], within


def event_record(area, event, det, members, geo, sites, footprint_m,
                 radius_m):
    p50 = float(area["look_lag_days"]["pre_lag"]["p50"])
    p90 = float(area["look_lag_days"]["pre_lag"]["p90"])
    post = area["look_lag_days"].get("post_lag", {})
    p50_utc, p50_wit = pre_look_dates(event["first_seen_utc"], p50)
    p90_utc, p90_wit = pre_look_dates(event["first_seen_utc"], p90)
    first_wit = date.fromisoformat(str(event["first_seen_wit"])[:10])

    member_ids = set(members["detection_id"])
    prior = prior_rows(det, member_ids, geo, first_wit)
    d, frp, confidence, n_on_d = latest_prior(prior)
    d50 = None if d is None else (p50_wit - d).days
    d90 = None if d is None else (p90_wit - d).days
    dir50, dir90, differ = classify(d, p50_wit, p90_wit, first_wit)
    distances, edges, nearest_id, nearest_m, within = site_distances(
        event, members, sites, footprint_m, radius_m)

    return {
        "event_id": event["event_id"],
        "changed_ha": area.get("changed_ha"),
        "first_seen_utc": event["first_seen_utc"],
        "first_seen_wit": event["first_seen_wit"],
        "last_seen_wit": event.get("last_seen_wit"),
        "n_detections": event.get("n_detections"),
        "footprint_ha": area.get("footprint_ha"),
        "pre_lag_days": {"p50": round(p50, 3), "p90": round(p90, 3)},
        "post_lag_days": {
            "p50": (round(float(post["p50"]), 3)
                    if post.get("p50") is not None else None),
            "p90": (round(float(post["p90"]), 3)
                    if post.get("p90") is not None else None),
        },
        "pre_look_p50_date": p50_wit.isoformat(),
        "pre_look_p50_date_utc": p50_utc.isoformat(),
        "pre_look_p90_date": p90_wit.isoformat(),
        "pre_look_p90_date_utc": p90_utc.isoformat(),
        "pre_look_date_is_estimated": True,
        "prior_detection_count": len(prior),
        "latest_prior_date": None if d is None else d.isoformat(),
        "latest_prior_frp_mw": frp,
        "latest_prior_confidence": confidence,
        "n_on_latest_prior_date": n_on_d,
        "days_d_to_pre_look_p50": d50,
        "days_d_to_pre_look_p90": d90,
        "direction_p50": dir50,
        "direction_p90": dir90,
        "directions_differ": differ,
        "recurrent_share": event.get("recurrent_share"),
        "nearest_site_id": nearest_id,
        "nearest_site_distance_m": nearest_m,
        "site_distances_m": distances,
        "site_footprint_distances_m": edges,
        "recurrent_sites_within_radius": within,
        "within_recurrence_radius": bool(within),
    }


def build(footprint_m, pre_days, radius_m):
    burned = load_json(BURNED)
    events_doc = load_json(EVENTS)
    sites_doc = load_json(SITES)
    try:
        det = pd.read_parquet(DETECTIONS)
    except Exception as err:
        raise SystemExit("%s: %s - nothing written" % (DETECTIONS, err))
    det["detection_id"] = det["detection_id"].astype(str)
    try:
        det["acq_date_d"] = det["acq_date"].map(date.fromisoformat)
    except Exception as err:
        raise SystemExit("%s: acq_date: %s - nothing written"
                         % (DETECTIONS, err))
    member_of = membership_map(events_doc)
    by_id = {e["event_id"]: e for e in events_doc["events"]}
    sites = sites_doc.get("sites") or []
    if not sites:
        raise SystemExit("%s: no recurrent sites - nothing written" % SITES)

    assessed = [r for r in burned["assessed"]
                if r.get("status") == "assessed"]
    no_ref = [r for r in burned["assessed"]
              if r.get("status") != "assessed"]
    rows = []
    for area in sorted(assessed, key=lambda r: r["event_id"]):
        eid = area["event_id"]
        event = by_id.get(eid)
        if event is None:
            raise SystemExit("%s: %s missing from events.json - nothing "
                             "written" % (EVENTS, eid))
        if area.get("look_lag_days") is None:
            raise SystemExit("%s: %s has no look_lag_days - nothing written"
                             % (BURNED, eid))
        members = det[det["detection_id"].isin(
            [d for d, e in member_of.items() if e == eid])]
        if members.empty:
            raise SystemExit("%s: %s has no member detections - nothing "
                             "written" % (DETECTIONS, eid))
        geo, _ = footprint(members["latitude"].tolist(),
                           members["longitude"].tolist(), footprint_m)
        rows.append(event_record(area, event, det, members, geo, sites,
                                 footprint_m, radius_m))

    groups = {}
    for name in DIRECTIONS:
        chosen = [r for r in rows if r["direction_p50"] == name]
        groups[name] = {
            "n": len(chosen),
            "changed_ha": round(sum(
                float(r["changed_ha"] or 0.0) for r in chosen), 2),
        }

    stale = [r for r in rows if r["pre_lag_days"]["p50"] > STALE_DAYS]
    stale.sort(key=lambda r: -r["pre_lag_days"]["p50"])
    posts = [r for r in rows
             if (r["post_lag_days"]["p50"] or 0.0) > STALE_DAYS]
    post_max = max((r["post_lag_days"]["p50"] or 0.0) for r in rows)

    no_ref_rows = [{
        "event_id": r.get("event_id"),
        "status": r.get("status"),
        "changed_ha": r.get("changed_ha"),
        "first_seen_wit": r.get("first_seen_wit"),
        "n_detections": r.get("n_detections"),
    } for r in sorted(no_ref, key=lambda r: r.get("event_id") or "")]

    return {
        "parameters": {
            "footprint_m": footprint_m,
            "pre_days": pre_days,
            "recurrence_radius_m": radius_m,
            "stale_threshold_days": STALE_DAYS,
            "pre_look_anchor": "first_seen_utc minus pre_lag p50/p90",
            "pre_look_comparison": "WIT dates (UTC+9); acq_date is already "
                                   "WIT and is not shifted again",
            "prior_detection_cutoff": "acq_date < first_seen_wit day "
                                      "(strict)",
            "days_sign": "pre look date minus D; positive means D is "
                         "before the pre look, negative means after it",
        },
        "counts": {
            "assessment_entries": len(burned["assessed"]),
            "assessed": len(assessed),
            "no_local_reference": len(no_ref),
            "not_assessed": len(burned["not_assessed"]),
            "assessed_changed_ha_total": round(sum(
                float(r.get("changed_ha") or 0.0) for r in assessed), 2),
        },
        "events": rows,
        "no_local_reference": no_ref_rows,
        "not_assessed": {
            "count": len(burned["not_assessed"]),
            "by_reason": dict(Counter(
                r.get("reason") for r in burned["not_assessed"])),
        },
        "group_totals": groups,
        "stale_pre_look_check": {
            "threshold_days": STALE_DAYS,
            "event_ids": [r["event_id"] for r in stale],
            "count": len(stale),
            "changed_ha_total": round(sum(
                float(r["changed_ha"] or 0.0) for r in stale), 2),
        },
        "post_lag_check": {
            "threshold_days": STALE_DAYS,
            "event_ids": [r["event_id"] for r in posts],
            "count": len(posts),
            "p50_max_days": round(post_max, 3),
        },
        "recurrent_sites": [{
            "id": s["id"],
            "distinct_days": s.get("distinct_days"),
            "first_date": s.get("first_date"),
            "last_date": s.get("last_date"),
            "centroid_lat": s.get("centroid_lat"),
            "centroid_lon": s.get("centroid_lon"),
        } for s in sites],
        "caveats": CAVEATS,
    }


# --------------------------------------------------------------------------
def print_table(title, rows):
    print("\n%s" % title)
    print("  event      changed_ha   p50   p90   latest_D    d50   d90  "
          "rec_share  nearest            p90_dir")
    for r in sorted(rows, key=lambda r: r["event_id"]):
        near = "%s %.0f m" % (r["nearest_site_id"],
                              r["nearest_site_distance_m"])
        if r["within_recurrence_radius"]:
            near += " *"
        d = r["latest_prior_date"] or "-"
        d50 = "-" if r["days_d_to_pre_look_p50"] is None \
            else "%+d" % r["days_d_to_pre_look_p50"]
        d90 = "-" if r["days_d_to_pre_look_p90"] is None \
            else "%+d" % r["days_d_to_pre_look_p90"]
        p90 = r["direction_p90"]
        if not r["directions_differ"]:
            p90 = ""
        print("  %-9s %10.2f  %4.1f  %4.1f  %-10s %5s %5s  %9.3f  "
              "%-18s %s" %
              (r["event_id"], float(r["changed_ha"] or 0.0),
               r["pre_lag_days"]["p50"], r["pre_lag_days"]["p90"], d,
               d50, d90, float(r["recurrent_share"] or 0.0), near, p90))


def main():
    footprint_m, pre_days, radius_m = load_config()
    doc = build(footprint_m, pre_days, radius_m)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print("wrote %s" % OUT.relative_to(ROOT))
    print("pre look dates are estimates from pre_lag p50/p90, not scene "
          "dates.")

    for name, title in (
            ("scar_in_pre", "scar already in the pre image (D < P < F)"),
            ("earlier_burn_included",
             "earlier burning included (P < D < F)"),
            ("no_prior_detection", "no prior detection before the pre look")):
        print_table(title, [r for r in doc["events"]
                            if r["direction_p50"] == name])

    print("\nhectares by p50 direction, never summed together:")
    for name in DIRECTIONS:
        g = doc["group_totals"][name]
        print("  %-24s %2d events  %9.2f ha" %
              (name, g["n"], g["changed_ha"]))
    print("  (* in the nearest column: footprint within %.0f m of a "
          "recurrent site)" % doc["parameters"]["recurrence_radius_m"])

    stale = doc["stale_pre_look_check"]
    print("\npre_lag p50 > %d d: %d events, %.2f ha (%s)" %
          (stale["threshold_days"], stale["count"],
           stale["changed_ha_total"], ", ".join(stale["event_ids"])))
    post = doc["post_lag_check"]
    print("post_lag p50 > %d d: %d events (max %.1f d) - clean negative" %
          (post["threshold_days"], post["count"], post["p50_max_days"]))
    no_ref = doc["no_local_reference"]
    print("\nassessed with no local reference (%d): %s" %
          (len(no_ref), ", ".join(r["event_id"] for r in no_ref)))
    print("not assessed: %d events; reasons: %s" %
          (doc["not_assessed"]["count"],
           ", ".join("%s (%d)" % kv for kv in
                     sorted(doc["not_assessed"]["by_reason"].items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())