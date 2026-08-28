"""Recurrent-location flagging (Phase 2 item 1; calibrated on PLAN.md 11.2/11.4).

Clusters detections by radius and flags clusters that recur across a long
enough record. Flags only: no detection is ever removed, and every count that
shows a flagged detection keeps showing it. Wording stays neutral - "recurrent
location" says how often hotspots appear here, nothing about what is here,
about infrastructure, or about whether a fire is real (PLAN.md 11.2: an
unmapped facility and a farmer burning the same plot each season are both
live possibilities at the one strong site in the record).

Site identity (Task 04b): an ID names a place, not a rank. Freshly computed
clusters are matched against the previous registry - a centroid within the
radius inherits that site's ID - so briefs published last month still point at
the same place. Only genuinely new sites take the next unused number, and
numbers are never reused. Rebuilding the registry from scratch reassigns IDs,
which is why the file carries a `registry_version` that increments on every
such rebuild: IDs from files with different versions are not comparable.
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


def _clusterize(df: pd.DataFrame, radius_m: float) -> list[dict]:
    """Leader/centroid clustering. Rows are processed in a fixed order
    (date_wit, then latitude, longitude, row position); a row joins the
    nearest existing cluster whose centroid lies within the radius, else
    seeds a new one. Single-linkage (transitive "within radius of any
    member") was tried first and rejected on the pinned expectations: it
    chained the August 2026 airport fires to scattered 2023 detections ~2 km
    away into one flagged cluster, while centroid clustering keeps each
    episode separate and still absorbs the 375 m-spaced neighbour cells of
    the Saramom source (PLAN.md 11.2) into its site. A chain metric is the
    wrong shape for this data; a physical source is where its centre is.
    """
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
    return clusters


def compute(df: pd.DataFrame, radius_m: float, min_days: int,
            min_span_days: int, min_history_days: int,
            registry: dict | None = None,
            prior_version_hint: int = 0) -> tuple[pd.DataFrame, list[dict],
                                                  str | None, int, dict]:
    """Flag recurrent clusters. Returns (flagged df, sites, reason, span,
    reg_info).

    Never drops rows and never touches detection_id. `reason` is None when
    recurrence was computed, else a human-readable statement of why no flags
    were emitted (short history, empty store) - recorded in the mask file.

    When `registry` (a previously written mask file's dict) is given, clusters
    inherit the IDs of prior sites whose centroid lies within the radius, so
    an ID keeps naming the same place as counts change. New sites take the
    next unused number; numbers are never reused. `reg_info` carries the new
    registry_version, next_number and any split/rebuild notes for the file.
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

    prior_version = max(int(registry.get("registry_version", 0))
                        if registry else 0, int(prior_version_hint))
    # Legacy registries (pre-04b) carry no next_number; derive it from the
    # highest ID they ever recorded, so a dropped site's number is never
    # handed to a new site.
    prior_ids = [s.get("id") for s in registry.get("sites", [])] \
        if registry else []
    legacy_next = max([int(pid[1:]) for pid in prior_ids
                       if str(pid)[1:].isdigit()], default=0) + 1
    next_number = max(int(registry.get("next_number", 1)) if registry else 1,
                      legacy_next)
    reg_info = {"version": prior_version,
                "next_number": next_number,
                "notes": []}

    if reason is not None:
        df["recurrent_site_id"] = pd.Series([None] * len(df), index=df.index,
                                            dtype=object)
        df["recurrent_site_days"] = pd.array([pd.NA] * len(df), dtype="Int64")
        df["recurrent_site"] = pd.Series([False] * len(df), index=df.index,
                                         dtype=bool)
        return df, [], reason, span_days, reg_info

    clusters = [c for c in _clusterize(df, radius_m)
                if c["days"] >= min_days and c["span"] >= min_span_days]

    # Registry matching (Task 04b). Clusters are matched largest-detection-
    # count first: if a site splits in two, the larger fragment keeps the ID.

    assigned_ids: list[str | None] = [None] * len(clusters)
    splits: list[tuple[int, int]] = []       # (prior site index, fragment idx)
    if registry and registry.get("sites"):
        eps_deg = radius_m / M_PER_DEG
        claim: dict[int, int] = {}           # prior site index -> cluster idx
        order = sorted(range(len(clusters)),
                       key=lambda i: (-clusters[i]["count"],
                                      clusters[i]["lat"], clusters[i]["lon"]))
        for ci in order:
            c = clusters[ci]
            best, best_d = None, None
            for si, s in enumerate(registry["sites"]):
                if si in claim:
                    continue
                dlat = c["lat"] - s["centroid_lat"]
                dlon = c["lon"] - s["centroid_lon"]
                d = (dlat * dlat + dlon * dlon) ** 0.5
                if d <= eps_deg and (best is None or d < best_d):
                    best, best_d = si, d
            if best is not None:
                claim[best] = ci
                assigned_ids[ci] = registry["sites"][best]["id"]

        # A split: an unassigned cluster still lies within the radius of a
        # prior site that another cluster kept. The larger fragment kept the
        # ID (processing order); the fragment gets a new ID, and the file
        # says so (Task 04b).
        for ci, pid in enumerate(assigned_ids):
            if pid is not None:
                continue
            c = clusters[ci]
            best_d, best = min(
                (((c["lat"] - s["centroid_lat"]) ** 2
                  + (c["lon"] - s["centroid_lon"]) ** 2) ** 0.5, si)
                for si, s in enumerate(registry["sites"]))
            if best_d <= eps_deg and best in claim:
                splits.append((best, ci))

    if clusters and not any(assigned_ids):
        # Fresh assignment with nothing inherited: every ID changes meaning.
        reg_info["version"] = prior_version + 1
        if registry:
            reg_info["notes"].append("no prior site matched; all IDs "
                                     "renumbered - do not compare IDs with "
                                     "earlier file versions")
    else:
        reg_info["version"] = prior_version
    # Never publish v0: a prior file written before registry versions existed
    # upgrades to v1 on first contact, without counting as a renumber.
    reg_info["version"] = max(reg_info["version"], 1)

    # New IDs in deterministic order (recurrence, then centroid), never
    # reusing a number.
    used_numbers = {int(pid[1:]) for pid in assigned_ids if pid}
    for ci, c in enumerate(clusters):
        if assigned_ids[ci] is None:
            while next_number in used_numbers:
                next_number += 1
            assigned_ids[ci] = f"R{next_number:03d}"
            used_numbers.add(next_number)
            next_number += 1
    reg_info["next_number"] = next_number

    for prior_si, frag_ci in splits:
        kept = registry["sites"][prior_si]["id"]
        reg_info["notes"].append(
            f"site split: {kept} kept by its largest fragment "
            f"({clusters[claim[prior_si]]['count']} detections); the "
            f"{clusters[frag_ci]['count']}-detection fragment received new "
            f"ID {assigned_ids[frag_ci]}")

    ids = [None] * len(df)
    day_counts: list = [pd.NA] * len(df)
    flags = [False] * len(df)
    for c, pid in zip(clusters, assigned_ids):
        for i in c["idx"]:
            ids[i] = pid
            day_counts[i] = c["days"]
            flags[i] = True

    df["recurrent_site_id"] = pd.Series(ids, index=df.index, dtype=object)
    df["recurrent_site_days"] = pd.Series(day_counts, index=df.index,
                                          dtype="Int64")
    df["recurrent_site"] = pd.Series(flags, index=df.index, dtype=bool)

    sites = [{"id": pid,
              "centroid_lat": round(c["lat"], 6),
              "centroid_lon": round(c["lon"], 6),
              "distinct_days": c["days"],
              "detections": c["count"],
              "first_date": c["first"],
              "last_date": c["last"],
              "distrik": c["distrik"]}
             for c, pid in sorted(zip(clusters, assigned_ids),
                                  key=lambda t: t[1])]
    return df, sites, None, span_days, reg_info


def write_sites(path: Path, doc: dict) -> None:
    """Write one mask copy. No timestamp: the same store and the same prior
    registry yield byte-identical files (Task 04b, kept from Task 04)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")


def load_prior(mask_path: Path, publish_path: Path | None = None) -> dict | None:
    """Most recent prior registry: the working copy first, then the published
    one. The published copy surviving deletion of the working copy is what
    keeps IDs stable across someone clearing data/processed/."""
    for p in (mask_path, publish_path):
        if p is not None and Path(p).exists():
            try:
                return json.loads(Path(p).read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raise
    return None


def flag(df: pd.DataFrame, cfg_rec: dict, mask_path: Path,
         publish_path: Path | None = None,
         prior_version_hint: int = 0):
    """Entry point for the ingest: config-driven compute, registry matching,
    and writing of the mask file plus its published copy.

    `prior_version_hint` is the highest registry_version known from durable
    state outside the mask files (the ingest reads it from the run manifest),
    so a rebuild after both mask copies were deleted still increments.

    Returns (flagged df, sites, reason, registry_version). Defaults live here
    - the only place recurrence thresholds are spelled out outside
    config.yaml.
    """
    params = {"radius_m": float(cfg_rec.get("radius_m", 750)),
              "min_days": int(cfg_rec.get("min_days", 10)),
              "min_span_days": int(cfg_rec.get("min_span_days", 90)),
              "min_history_days": int(cfg_rec.get("min_history_days", 365))}
    registry = load_prior(mask_path, publish_path)
    df, sites, reason, span_days, reg_info = compute(
        df, registry=registry, prior_version_hint=prior_version_hint,
        **params)
    doc = {"status": "skipped" if reason is not None else "ok",
           "reason": reason,
           "history_days": span_days,
           "params": params,
           "registry_version": reg_info["version"],
           "next_number": reg_info["next_number"],
           "notes": reg_info["notes"],
           "sites": sites}
    write_sites(mask_path, doc)
    if publish_path is not None:
        write_sites(publish_path, doc)
    return df, sites, reason, reg_info["version"]
