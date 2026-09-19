"""Burning events: space-time DBSCAN over the detection store (Task 16).

A detection is one pixel hot at one overpass. An event is the same patch of
ground burning across one or several overpasses - the unit Phase 4 and every
per-fire table need. This module groups the store into events, keeps each
event's ID stable as the store grows, and writes a per-event record.

    python src/events.py            # build data/processed/events.{json,csv}
    python src/events.py --tune     # print the parameter grid and the
                                    # known-event checks; writes nothing

Reads the store and the tracked road file only. Never fetches anything, and
never writes to detections.parquet: the daily ingest rewrites that store, and
a column it does not know about is a column waiting to be dropped.

Wording (PLAN.md section 8): `first_seen` is the first overpass that caught
heat, not the moment anything was lit, and nothing here says why something
burned or who burned it.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import yaml
from shapely.geometry import MultiPoint

import fieldwork_gpkg as fw
from recurrence import M_PER_DEG

ROOT = Path(__file__).resolve().parents[1]
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


# --------------------------------------------------------------------------
# Clustering

def _plane(df):
    """Local metre plane. One cos() for the whole store: across the AOI's
    2.4 degrees of latitude it varies by 0.015%, far inside FIRMS jitter."""
    k = math.cos(math.radians(float(df["latitude"].mean())))
    x = (df["longitude"].to_numpy(dtype=float) * M_PER_DEG * k)
    y = df["latitude"].to_numpy(dtype=float) * M_PER_DEG
    return x, y


def _seconds(df):
    return ((df["datetime_utc"] - EPOCH) // pd.Timedelta(seconds=1)) \
        .to_numpy(dtype="int64")


def dbscan(df, eps_m, eps_hours, min_samples):
    """Label per row, -1 for noise. Neighbours must be close in both space
    and time.

    Rows are compared only inside the eps_hours window after them in time
    order, so the cost grows with the burning rate rather than with the
    square of a store that grows every day. Seeds are taken in time order
    (ties by detection_id), which fixes the one order-dependence DBSCAN has:
    a border point reachable from two events joins the earlier one.
    """
    n = len(df)
    x, y = _plane(df)
    t = _seconds(df)
    ids = df["detection_id"].astype(str).to_numpy()
    order = sorted(range(n), key=lambda i: (t[i], ids[i]))
    eps_s, eps2 = eps_hours * 3600, eps_m * eps_m

    nbrs = [[] for _ in range(n)]
    for a, i in enumerate(order):
        for j in order[a + 1:]:
            if t[j] - t[i] > eps_s:
                break
            if (x[i] - x[j]) ** 2 + (y[i] - y[j]) ** 2 <= eps2:
                nbrs[i].append(j)
                nbrs[j].append(i)

    core = [len(nb) + 1 >= min_samples for nb in nbrs]
    labels, k = [-1] * n, 0
    for i in order:
        if not core[i] or labels[i] != -1:
            continue
        labels[i], stack = k, [i]
        while stack:
            for q in nbrs[stack.pop()]:
                if labels[q] == -1:
                    labels[q] = k
                    if core[q]:
                        stack.append(q)
        k += 1
    return labels


def groups(df, params):
    """Member row positions per event, noise included as events of one,
    in first-seen order."""
    labels = dbscan(df, params["eps_m"], params["eps_hours"],
                    params["min_samples"])
    t = _seconds(df)
    ids = df["detection_id"].astype(str).to_numpy()
    by = {}
    for i, lab in enumerate(labels):
        # AGENTS never-5: noise is not discarded. A single pixel on a single
        # overpass is the commonest thing a small plot burn produces here.
        by.setdefault(lab if lab != -1 else ("noise", i), []).append(i)
    out = list(by.values())
    out.sort(key=lambda m: (min(t[i] for i in m), min(ids[i] for i in m)))
    return out


# --------------------------------------------------------------------------
# Identity

def membership(doc):
    """detection_id -> event_id from a built or loaded document.

    Stored as a list of {"detection_id", "event_id"} records rather than a
    mapping keyed by detection_id: a 40-hex key is what the pre-commit hook
    reads as a leaked credential, and the record shape is the one exception
    it grants, because it is how detection IDs are already published.
    """
    return {r["detection_id"]: r["event_id"]
            for r in (doc or {}).get("membership", [])}


def assign_ids(members, prior, params):
    """Event IDs that survive re-runs. Returns (ids, registry info).

    A new event inherits the ID of the prior event it shares the most
    detections with; growth therefore keeps an ID. When two prior events
    merge, the one with more detections keeps its ID and the other is
    retired as merged into it. A prior event split in two keeps its ID on
    the larger share. Numbers are never reused, even across a rebuild, so an
    old reference can never be mistaken for a new event.
    """
    same = bool(prior) and prior.get("params") == params
    version = int(prior.get("registry_version", 0)) if prior else 0
    next_number = int(prior.get("next_number", 1)) if prior else 1
    retired = dict(prior.get("retired", {})) if prior else {}
    notes = []
    if prior and not same:
        notes.append("parameters changed; all IDs reassigned - do not compare "
                     "IDs with earlier registry versions")
    version = version if same else version + 1

    ids = [None] * len(members)
    if same:
        old = membership(prior)
        sizes = {}
        for pid in old.values():
            sizes[pid] = sizes.get(pid, 0) + 1
        pairs = []
        for gi, m in enumerate(members):
            overlap = {}
            for det in m:
                pid = old.get(det)
                if pid:
                    overlap[pid] = overlap.get(pid, 0) + 1
            pairs += [(-n, -sizes[pid], pid, gi) for pid, n in overlap.items()]
        taken = set()
        for _, _, pid, gi in sorted(pairs):
            if ids[gi] is None and pid not in taken:
                ids[gi] = pid
                taken.add(pid)
        where = {det: gi for gi, m in enumerate(members) for det in m}
        for pid in sorted(set(sizes) - taken):
            holder = {}
            for det, p in old.items():
                gi = where.get(det)
                if p == pid and gi is not None and ids[gi]:
                    holder[ids[gi]] = holder.get(ids[gi], 0) + 1
            into = min(holder, key=lambda h: (-holder[h], h)) if holder \
                else None
            retired[pid] = {"merged_into": into}

    used = {int(p[1:]) for p in ids if p}
    used |= {int(p[1:]) for p in retired}
    for gi in range(len(members)):
        if ids[gi] is None:
            while next_number in used:
                next_number += 1
            ids[gi] = "E%04d" % next_number
            used.add(next_number)
            next_number += 1
    return ids, {"registry_version": max(version, 1),
                 "next_number": next_number, "retired": retired,
                 "notes": notes}


# --------------------------------------------------------------------------
# Records

def _iso(ts):
    return ts.isoformat().replace("+00:00", "Z")


def _mode(values):
    s = pd.Series([v for v in values if isinstance(v, str) and v])
    if s.empty:
        return None
    counts = s.value_counts()
    top = counts[counts == counts.max()].index
    return sorted(top)[0]


def record(df, rows, eid, segs, x, y):
    m = df.iloc[rows]
    t0, t1 = m["datetime_utc"].min(), m["datetime_utc"].max()
    first = m[m["datetime_utc"] == t0]
    frp = m["frp"]
    road_m, road_cls = fw.nearest_road(float(first["latitude"].mean()),
                                       float(first["longitude"].mean()), segs)
    hull = MultiPoint([(x[i], y[i]) for i in rows]).convex_hull
    area = hull.area / 1e4 if hull.geom_type == "Polygon" else None
    return {
        "event_id": eid,
        "singleton": len(rows) == 1,
        "n_detections": len(rows),
        "satellites": sorted(m["satellite"].astype(str).unique()),
        "n_overpasses": int(m["datetime_utc"].nunique()),
        "first_seen_utc": _iso(t0),
        "last_seen_utc": _iso(t1),
        "first_seen_wit": t0.tz_convert("Asia/Jayapura").isoformat(),
        "last_seen_wit": t1.tz_convert("Asia/Jayapura").isoformat(),
        "duration_hours": round((t1 - t0).total_seconds() / 3600.0, 2),
        # AGENTS never-4: FRP is kept; a missing value is counted, never
        # read as zero.
        "frp_sum": round(float(frp.sum(skipna=True)), 2),
        "frp_max": (round(float(frp.max(skipna=True)), 2)
                    if frp.notna().any() else None),
        "n_frp_missing": int(frp.isna().sum()),
        "centroid_lat": round(float(m["latitude"].mean()), 6),
        "centroid_lon": round(float(m["longitude"].mean()), 6),
        "first_lat": round(float(first["latitude"].mean()), 6),
        "first_lon": round(float(first["longitude"].mean()), 6),
        # A lower bound: the hull of pixel centres ignores the footprint of
        # each pixel, 375 m for VIIRS and 1 km for MODIS.
        "hull_area_ha": round(area, 2) if area else None,
        "road_m": None if road_m is None else round(road_m, 1),
        "road_class": road_cls,
        "desa": _mode(m["desa"]),
        "distrik": _mode(m["distrik"]),
        "recurrent_share": round(float(m["recurrent_site"].astype(bool)
                                       .mean()), 4),
        "on_land_share": round(float(m["on_land"].astype(bool).mean()), 4),
    }


def build(df, params, prior=None, segs=()):
    df = df.reset_index(drop=True)
    members_rows = groups(df, params)
    ids_col = df["detection_id"].astype(str).to_numpy()
    members = [{ids_col[i] for i in rows} for rows in members_rows]
    ids, reg = assign_ids(members, prior, params)
    x, y = _plane(df)
    events = [record(df, rows, eid, segs, x, y)
              for rows, eid in zip(members_rows, ids)]
    member_rows = sorted(({"detection_id": det, "event_id": eid}
                          for m, eid in zip(members, ids) for det in m),
                         key=lambda r: r["detection_id"])
    doc = {"params": params, **reg,
           "store_rows": len(df),
           "store_last_date_wit": str(df["date_wit"].max()) if len(df)
           else None,
           "events": sorted(events, key=lambda e: e["event_id"]),
           "membership": member_rows}
    return doc


def write(doc, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "events.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    rows = [{**e, "satellites": "+".join(e["satellites"])}
            for e in doc["events"]]
    pd.DataFrame(rows).to_csv(out_dir / "events.csv", index=False,
                              lineterminator="\n")


# --------------------------------------------------------------------------
# Tuning

def _extent_km(m):
    x, y = _plane(m)
    return round(max(x.max() - x.min(), y.max() - y.min()) / 1000.0, 1)


def _select(df, k):
    sel = pd.Series(True, index=df.index)
    if "from" in k:
        sel &= df["date_wit"].astype(str) >= k["from"]
    if "to" in k:
        sel &= df["date_wit"].astype(str) <= k["to"]
    if "lat" in k:
        d = [fw.metres(k["lat"], k["lon"], a, b)
             for a, b in zip(df["latitude"], df["longitude"])]
        sel &= pd.Series(d, index=df.index) <= k["radius_m"]
    return sel


def tune(df, grid_m, grid_h, min_samples, known):
    df = df.reset_index(drop=True)
    print("%6s %4s | %7s %6s | %8s %8s %9s" % (
        "eps_m", "eps_h", "events", "single", "largest", "dur_h", "extent_km"))
    for em in grid_m:
        for eh in grid_h:
            p = {"eps_m": em, "eps_hours": eh, "min_samples": min_samples}
            g = groups(df, p)
            big = max(g, key=len)
            bm = df.iloc[big]
            dur = (bm["datetime_utc"].max()
                   - bm["datetime_utc"].min()).total_seconds() / 3600
            print("%6d %4d | %7d %6d | %8d %8.1f %9.1f" % (
                em, eh, len(g), sum(len(m) == 1 for m in g), len(big), dur,
                _extent_km(bm)))
            for k in known:
                sel = set(df.index[_select(df, k)])
                hit = [m for m in g if sel & set(m)]
                if not hit:
                    print("        %-10s no detections selected" % k["name"])
                    continue
                top = max(hit, key=len)
                tm = df.iloc[top]
                days = tm["date_wit"].astype(str)
                print("        %-10s %4d det in %3d events; largest %4d det, "
                      "%s..%s, %5.1f km" % (
                          k["name"], len(sel), len(hit), len(top),
                          days.min(), days.max(), _extent_km(tm)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tune", action="store_true",
                    help="print the parameter grid and known-event checks")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ev = cfg["events"]
    params = {"eps_m": ev["eps_m"], "eps_hours": ev["eps_hours"],
              "min_samples": ev["min_samples"]}
    df = pd.read_parquet(ROOT / cfg["output_paths"]["processed"])

    if args.tune:
        tune(df, ev["tune_eps_m"], ev["tune_eps_hours"], ev["min_samples"],
             ev["known_events"])
        return 0

    out_dir = (ROOT / cfg["output_paths"]["processed"]).parent
    prior_path = out_dir / "events.json"
    prior = (json.loads(prior_path.read_text(encoding="utf-8"))
             if prior_path.exists() else None)
    segs = fw.load_roads(ROOT / cfg["road_lines"])
    doc = build(df, params, prior, segs)
    write(doc, out_dir)
    single = sum(e["singleton"] for e in doc["events"])
    print("events: %d (%d singletons) from %d detections; registry v%d"
          % (len(doc["events"]), single, doc["store_rows"],
             doc["registry_version"]))
    for note in doc["notes"]:
        print("note:", note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
