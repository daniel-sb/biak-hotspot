"""Recurrent-location flagging (Phase 2 item 1; calibrated on PLAN.md 11.2).

Clusters detections by radius and flags clusters that recur across a long
enough record. Flags only: no detection is ever removed, and every count that
shows a flagged detection keeps showing it. Wording stays neutral - "recurrent
location" says how often hotspots appear here, nothing about what is here,
about infrastructure, or about whether a fire is real (PLAN.md 11.2: an
unmapped facility and a farmer burning the same plot each season are both
live possibilities at the one strong site in the record).
"""
import json
from datetime import date
from pathlib import Path

import pandas as pd

RECURRENT_SITES_FILENAME = "recurrent_sites.json"

# Metres per degree of latitude. Longitude degrees are cos(lat) shorter; at
# Biak (|lat| < 1.6) that is under 0.05% - about 0.4 m on a 750 m radius and
# far inside FIRMS geolocation jitter - so a single constant keeps this free
# of geodesy dependencies.
M_PER_DEG = 111_320.0

FLAG_COLUMNS = ("recurrent_site_id", "recurrent_site_days", "recurrent_site")


def compute(df: pd.DataFrame, radius_m: float, min_days: int,
            min_span_days: int,
            min_history_days: int) -> tuple[pd.DataFrame, list[dict],
                                            str | None, int]:
    """Flag recurrent clusters. Returns (flagged df, sites, reason, span).

    Clustering: leader/centroid. Rows are processed in a fixed order
    (date_wit, then latitude, longitude, row position); a row joins the
    nearest existing cluster whose centroid lies within the radius, else
    seeds a new one. Single-linkage (transitive "within radius of any
    member") was tried first and rejected on the pinned expectations: it
    chained the August 2026 airport fires to scattered 2023 detections ~2 km
    away into one flagged cluster, while centroid clustering keeps each
    episode separate and still absorbs the 375 m-spaced neighbour cells of
    the Saramom source (PLAN.md 11.2) into its site. A chain metric is the
    wrong shape for this data; a physical source is where its centre is.

    Never drops rows and never touches detection_id. `reason` is None when
    recurrence was computed, else a human-readable statement of why no flags
    were emitted (short history, empty store) - recorded in the mask file.
    """
    df = df.copy()
    if df.empty:
        span_days = 0
        reason = "store is empty; recurrence not computed"
    else:
        first, last = df["date_wit"].min(), df["date_wit"].max()
        span_days = (date.fromisoformat(last)
                     - date.fromisoformat(first)).days
        reason = None
        if span_days < min_history_days:
            reason = (f"history spans {span_days} days, below the required "
                      f"{min_history_days}; recurrence not computed - a mask "
                      "from a short record would flag real fires")

    if reason is not None:
        df["recurrent_site_id"] = pd.Series([None] * len(df), index=df.index,
                                            dtype=object)
        df["recurrent_site_days"] = pd.array([pd.NA] * len(df), dtype="Int64")
        df["recurrent_site"] = pd.Series([False] * len(df), index=df.index,
                                         dtype=bool)
        return df, [], reason, span_days

    lat = df["latitude"].to_numpy(dtype=float)
    lon = df["longitude"].to_numpy(dtype=float)
    dates = df["date_wit"].to_numpy()
    order = sorted(range(len(df)),
                   key=lambda i: (dates[i], lat[i], lon[i], i))

    eps_deg = radius_m / M_PER_DEG
    centers: list[list[float]] = []      # [lat_sum, lon_sum, n]
    members: list[list[int]] = []
    for i in order:
        best, best_d = None, None
        for ci, (sla, slo, n) in enumerate(centers):
            dlat = lat[i] - sla / n
            dlon = lon[i] - slo / n
            d = (dlat * dlat + dlon * dlon) ** 0.5
            if d <= eps_deg and (best is None or d < best_d):
                best, best_d = ci, d
        if best is None:
            centers.append([lat[i], lon[i], 1])
            members.append([i])
        else:
            centers[best][0] += lat[i]
            centers[best][1] += lon[i]
            centers[best][2] += 1
            members[best].append(i)

    has_distrik = "distrik" in df.columns
    clusters = []
    for idxs in members:
        d_list = sorted(dates[i] for i in idxs)
        days = len(set(d_list))
        span = (date.fromisoformat(d_list[-1])
                - date.fromisoformat(d_list[0])).days
        if has_distrik:
            d = df["distrik"].iloc[idxs].dropna()
            distrik = d.mode().min() if len(d) else None
        else:
            distrik = None
        clusters.append({
            "idx": idxs, "days": days, "span": span, "count": len(idxs),
            "lat": float(lat[idxs].mean()), "lon": float(lon[idxs].mean()),
            "first": d_list[0], "last": d_list[-1], "distrik": distrik,
        })

    flagged = [c for c in clusters
               if c["days"] >= min_days and c["span"] >= min_span_days]
    # Deterministic identity for site ids and file order: recurrence first,
    # then centroid. Same input -> same ids, always.
    flagged.sort(key=lambda c: (-c["days"], c["lat"], c["lon"]))
    for i, c in enumerate(flagged, 1):
        c["id"] = f"R{i:03d}"

    ids = [None] * len(df)
    day_counts: list = [pd.NA] * len(df)
    flags = [False] * len(df)
    for c in flagged:
        for i in c["idx"]:
            ids[i] = c["id"]
            day_counts[i] = c["days"]
            flags[i] = True

    df["recurrent_site_id"] = pd.Series(ids, index=df.index, dtype=object)
    df["recurrent_site_days"] = pd.Series(day_counts, index=df.index,
                                          dtype="Int64")
    df["recurrent_site"] = pd.Series(flags, index=df.index, dtype=bool)

    sites = [{"id": c["id"],
              "centroid_lat": round(c["lat"], 6),
              "centroid_lon": round(c["lon"], 6),
              "distinct_days": c["days"],
              "detections": c["count"],
              "first_date": c["first"],
              "last_date": c["last"],
              "distrik": c["distrik"]}
             for c in flagged]
    return df, sites, None, span_days


def write_sites(path: Path, sites: list[dict], params: dict,
                history_days: int, reason: str | None) -> None:
    """The reviewable mask file. Regenerated from data on every run, never
    hand-edited; no timestamp so the same input yields byte-identical files."""
    doc = {"status": "skipped" if reason is not None else "ok",
           "reason": reason,
           "history_days": history_days,
           "params": params,
           "sites": sites}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def flag(df: pd.DataFrame, cfg_rec: dict, mask_path: Path):
    """Entry point for the ingest: config-driven compute + mask file write.

    Returns (flagged df, sites, reason). Defaults live here - the only place
    recurrence thresholds are spelled out outside config.yaml.
    """
    params = {"radius_m": float(cfg_rec.get("radius_m", 750)),
              "min_days": int(cfg_rec.get("min_days", 10)),
              "min_span_days": int(cfg_rec.get("min_span_days", 90)),
              "min_history_days": int(cfg_rec.get("min_history_days", 365))}
    df, sites, reason, history_days = compute(df, **params)
    write_sites(mask_path, sites, params, history_days, reason)
    return df, sites, reason
