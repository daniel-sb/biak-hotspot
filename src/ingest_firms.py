"""FIRMS active-fire ingest for the Biak AOI (PLAN.md 2.1 / Phase 1, Task 03).

Pulls active-fire detections for all configured sources, persists raw
responses under data/raw/ before parsing, then deduplicates on a stable
detection_id and merges into data/processed/detections.parquet.

Two modes:
  * Daily lookback (default): pulls the last N days of near-real-time data.
    Chunks touching today or yesterday (UTC) are always re-downloaded;
    wholly-past chunks reuse cached raw files unless --refetch. FIRMS
    refreshes NRT several times a day, so recent cache is never trusted.
  * Historical backfill (--from/--to): multi-year history for Phase 2's
    persistent-source filter. Each satellite has a limited NRT window plus a
    reprocessed archive (_SP) window; the live data-availability table picks
    the correct source per day, a range straddling the boundary is split so
    no satellite-day is ever pulled from both, and days outside every window
    are recorded in the manifest as 'unavailable' rather than silently empty.
    Wholly-past chunks are cached forever, so an interrupted backfill resumes
    without refetching.

Usage:
    python src/ingest_firms.py [--lookback N] [--end YYYY-MM-DD] [--refetch]
    python src/ingest_firms.py --from YYYY-MM-DD --to YYYY-MM-DD [--refetch]

FIRMS_MAP_KEY must be set in the environment.
"""
import argparse
import hashlib
import io
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml
from shapely import STRtree
from shapely.geometry import Point, shape

import recurrence

ROOT = Path(__file__).resolve().parents[1]

FIRMS_URL = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
             "{key}/{source}/{w},{s},{e},{n}/{days}/{start}")
DATA_AVAILABILITY_URL = ("https://firms.modaps.eosdis.nasa.gov/api/"
                         "data_availability/csv/{key}/all")
DAY_RANGE_MAX = 5  # FIRMS rejects >5: "Invalid day range. Expects [1..5]."
WIT = timezone(timedelta(hours=9))  # Papua is UTC+9

log = logging.getLogger("ingest_firms")

# Fetch-provenance data file (Task 02b): one record per attempted chunk per
# run, appended - never overwritten - so history accumulates. Lives next to
# the detections store. The report layer reads it to distinguish "observed,
# nothing there" from "never queried / query failed" (AGENTS rule 2).
MANIFEST_FILENAME = "run_manifest.json"


def load_env_file(path: Path = ROOT / ".env") -> None:
    """Populate os.environ from a .env file, if one exists.

    README and .env.example both tell the reader to put FIRMS_MAP_KEY in
    .env, but nothing read it, so following the documented setup produced a
    file with no effect. A real environment variable always wins over the
    file: CI passes the key through Actions secrets and must not be
    overridden by a stray local .env.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_manifest(path: Path, entries: list[dict]) -> None:
    """Append chunk-outcome records to the run manifest JSON."""
    data: dict = {"runs": []}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("runs", []).extend(entries)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def chunk_starts(end: date, days: int) -> list[tuple[str, int]]:
    """Cover a `days`-long window ending at `end` with chunks of <= DAY_RANGE_MAX.

    Returns (chunk_start_iso, n_days) pairs that tile the window exactly.
    """
    out = []
    while days > 0:
        n = min(DAY_RANGE_MAX, days)
        out.append(((end - timedelta(days=days - 1)).isoformat(), n))
        days -= n
    return out


def cache_path(raw_dir: Path, source: str, start: str, days: int) -> Path:
    # The day count in the name keeps different lookback windows from
    # colliding on the same start date (e.g. a 3d and a 5d chunk both starting
    # 2026-08-13 hold different data). The flat-named {SOURCE}_{START}.csv
    # files in tests/fixtures/ are read-only test inputs from the first review
    # pull; current code never reads or writes them.
    return raw_dir / f"{source}_{start}_{days}d.csv"


def should_refetch(start: str, days: int, today: date) -> bool:
    """True if this chunk's window touches today or yesterday (UTC).

    Cached responses for recent windows go stale within hours; wholly-past
    windows are stable and may be served from cache forever.
    """
    chunk_end = date.fromisoformat(start) + timedelta(days=days - 1)
    return chunk_end >= today - timedelta(days=1)


def parse_availability(text: str) -> dict[str, tuple[date, date]]:
    """data_availability CSV -> {data_id: (min_date, max_date)}.

    Every source's coverage windows roll forward continuously; this table is
    the only authority on them and is fetched live each backfill run.
    """
    rows = text.strip().splitlines()
    if not rows or not rows[0].strip().startswith("data_id"):
        raise ValueError("unexpected data_availability header")
    table = {}
    for line in rows[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[0]:
            raise ValueError(f"unexpected availability row: {line!r}")
        try:
            table[parts[0]] = (date.fromisoformat(parts[1]),
                               date.fromisoformat(parts[2]))
        except ValueError as exc:
            raise ValueError(f"bad dates in availability row {line!r}") \
                from exc
    return table


def fetch_availability(key: str) -> dict[str, tuple[date, date]] | None:
    """Live per-source coverage windows; None on any failure (logged loudly).

    Returns None rather than a guess because a backfill that assumes NRT
    reaches back years gets silent empty results - the dangerous kind.
    """
    url = DATA_AVAILABILITY_URL.format(key=key)
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException as exc:
        log.error("AVAILABILITY FETCH FAILED: %s", exc)
        return None
    if r.status_code != 200:
        log.error("HTTP %s fetching availability: %.200s", r.status_code,
                  r.text.strip())
        return None
    try:
        return parse_availability(r.text)
    except ValueError as exc:
        log.error("UNPARSEABLE AVAILABILITY RESPONSE: %.200s (%s)",
                  r.text.strip(), exc)
        return None


def tile_forward(start: date, n_days: int) -> list[tuple[str, int]]:
    """Tile [start, start+n_days-1] with chunks of <= DAY_RANGE_MAX.

    Aligned at the range start so that extending n_days only appends chunks
    and never shifts existing ones - an interrupted backfill therefore hits
    its cache on resume instead of refetching. (The daily lookback keeps its
    own end-aligned tiling in chunk_starts(); only backfill needs stability.)
    """
    out, s = [], start
    while n_days > 0:
        k = min(DAY_RANGE_MAX, n_days)
        out.append((s.isoformat(), k))
        s += timedelta(days=k)
        n_days -= k
    return out


def plan_backfill(availability: dict[str, tuple[date, date]],
                  families: list[str], d_from: date,
                  d_to: date) -> tuple[list[tuple[str, str, int]], list[dict]]:
    """Choose exactly one FIRMS source per satellite per requested day.

    families are the configured _NRT source names. The reprocessed archive
    (_SP) window wins wherever it covers a day, otherwise NRT; a run of days
    served by one source is tiled with tile_forward(). Days outside both
    windows become contiguous gap records with outcome filled in by the
    caller - recorded as 'unavailable', never silently empty.

    Returns (jobs, gaps): jobs are (source_id, start_iso, n_days); gaps are
    {"source": <family _NRT name>, "chunk_start": iso, "days": n}.
    """
    def covers(win, d):
        return win is not None and win[0] <= d <= win[1]

    jobs: list[tuple[str, str, int]] = []
    gaps: list[dict] = []
    for fam in families:
        # Archive counterpart of an _NRT source is its _SP twin (FIRMS naming
        # convention); NOAA-21-style satellites simply have no entry.
        sp_id = fam[:-4] + "_SP" if fam.endswith("_NRT") else None
        sp_win = availability.get(sp_id) if sp_id else None
        nrt_win = availability.get(fam)

        def chosen(d):
            # SP first: if the windows ever overlap, this one consistent
            # choice keeps a satellite-day out of both sources - pulling both
            # would double-count fires that dedup cannot collapse because the
            # archive reprocessing changes coordinates/times slightly.
            if covers(sp_win, d):
                return sp_id
            if covers(nrt_win, d):
                return fam
            return None

        # One pass over the requested range per family: four satellites times
        # ~1100 days is nothing next to the HTTP requests, and far easier to
        # verify than interval algebra.
        d = d_from
        while d <= d_to:
            src = chosen(d)
            if src is None:
                gap_end = d
                while gap_end < d_to and chosen(
                        gap_end + timedelta(days=1)) is None:
                    gap_end += timedelta(days=1)
                gaps.append({"source": fam,
                             "chunk_start": d.isoformat(),
                             "days": (gap_end - d).days + 1})
                d = gap_end + timedelta(days=1)
                continue
            run_end = d
            while run_end < d_to and chosen(run_end + timedelta(days=1)) == src:
                run_end += timedelta(days=1)
            for start_iso, n in tile_forward(d, (run_end - d).days + 1):
                jobs.append((src, start_iso, n))
            d = run_end + timedelta(days=1)
    return jobs, gaps


def fetch_chunk(key: str, source: str, bbox: list[float], start: str,
                days: int) -> str | None:
    """One FIRMS request. Returns CSV text, or None on any failure.

    A failure must never look like an empty day: it returns None and is logged
    loudly, so the caller can skip writing it entirely.
    """
    w, s, e, n = bbox
    url = FIRMS_URL.format(key=key, source=source, w=w, s=s, e=e, n=n,
                           days=days, start=start)
    try:
        r = requests.get(url, timeout=60)
    except requests.RequestException as exc:
        log.error("FETCH FAILED %s %s: %s", source, start, exc)
        return None
    if r.status_code != 200:
        log.error("HTTP %s for %s %s: %.200s", r.status_code, source, start,
                  r.text.strip())
        return None
    text = r.text.strip()
    if not text.startswith("latitude"):
        # HTML error page or API error message - not parseable as detections.
        log.error("NON-CSV RESPONSE for %s %s: %.200s", source, start, text)
        return None
    return text + "\n"


def load_boundaries(path: Path):
    """Load the desa GeoJSON once per run -> (tree, geoms, names).

    names[i] = (desa, distrik, kabupaten) for geoms[i]. The STRtree indexes
    bounding boxes; query() returns candidate indices and containment is
    still verified per candidate in assign_admin().
    """
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    geoms, names = [], []
    for feat in fc["features"]:
        props = feat["properties"]
        geoms.append(shape(feat["geometry"]))
        names.append(tuple(props.get(k) or None
                           for k in ("WADMKD", "WADMKC", "WADMKK")))
    return STRtree(geoms), geoms, names


def land_hits(lons, lats, boundaries):
    """The land test: point-in-desa-polygon (contains/covers). Returns a list
    of (desa, distrik, kabupaten) tuples, None where a point falls outside
    every polygon. Shared by the ingest and the Himawari evening product so
    there is exactly one land definition (Task 06)."""
    tree, geoms, names = boundaries
    hits = []
    for lon, lat in zip(lons, lats):
        pt = Point(float(lon), float(lat))
        hit = None
        for i in tree.query(pt):
            if geoms[int(i)].covers(pt):
                hit = names[int(i)]
                break
        hits.append(hit)
    return hits


def assign_admin(df: pd.DataFrame, boundaries) -> pd.DataFrame:
    """Add desa/distrik/kabupaten/on_land from point-in-polygon.

    Never drops rows (AGENTS rule 5): a detection outside every polygon stays
    with on_land=False and null name columns - offshore pixels carry real
    information (coastal pixel vs sun glint) that Phase 2 needs.
    """
    df = df.copy()
    hits = land_hits(df["longitude"], df["latitude"], boundaries)
    # Explicit dtypes: empty clips (e.g. a header-only day) must not turn
    # on_land into object or names into float NaN.
    df["desa"] = pd.Series([h[0] if h else None for h in hits],
                           index=df.index, dtype=object)
    df["distrik"] = pd.Series([h[1] if h else None for h in hits],
                              index=df.index, dtype=object)
    df["kabupaten"] = pd.Series([h[2] if h else None for h in hits],
                                index=df.index, dtype=object)
    df["on_land"] = pd.Series([h is not None for h in hits],
                              index=df.index, dtype=bool)
    return df


def prepare(text: str, bbox: list[float], boundaries=None) -> pd.DataFrame:
    """Raw FIRMS CSV text -> tidy DataFrame, clipped to the bbox.

    Keeps acq_date/acq_time and confidence as returned (confidence must never
    be coerced: VIIRS l/n/h and MODIS 0-100 share the column); latitude and
    longitude become float. Adds detection_id, datetime_utc (tz-aware),
    datetime_wit (+09:00) and date_wit. When `boundaries` is given (from
    load_boundaries()), also adds desa/distrik/kabupaten/on_land.
    """
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    lat = pd.to_numeric(df["latitude"])
    lon = pd.to_numeric(df["longitude"])
    df["latitude"] = lat
    df["longitude"] = lon

    df.insert(0, "detection_id", [
        hashlib.sha1(
            f"{sat}|{inst}|{acq_date}|{acq_time}|{la:.5f}|{lo:.5f}".encode()
        ).hexdigest()
        for sat, inst, acq_date, acq_time, la, lo in zip(
            df["satellite"], df["instrument"], df["acq_date"], df["acq_time"],
            lat, lon)])

    utc = pd.to_datetime(df["acq_date"] + " " + df["acq_time"].str.zfill(4),
                         format="%Y-%m-%d %H%M", utc=True)
    df["datetime_utc"] = utc
    df["datetime_wit"] = utc.dt.tz_convert(WIT)
    df["date_wit"] = df["datetime_wit"].dt.strftime("%Y-%m-%d")

    # frp is the intensity measure (PLAN.md 2.1). Coerce only to NaN; rows kept.
    df["frp"] = pd.to_numeric(df["frp"], errors="coerce")

    # --- spatial filter -----------------------------------------------------
    # Step 1: clip to the AOI bbox.
    w, s, e, n = bbox
    inside = lat.between(s, n) & lon.between(w, e)
    df = df[inside]

    # Step 2: administrative assignment (desa/distrik/kabupaten) plus the
    # on_land flag. Nothing is dropped here either way; pass boundaries=None
    # when attribution is not wanted (tests of parsing alone).
    if boundaries is not None:
        df = assign_admin(df, boundaries)
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the storage contract: dtypes and required columns.

    Applied by merge_tables() to every frame that enters it - including the
    one read back from Parquet - and to the merged result. Because stored rows
    pass through here on every run, a parser fix is automatically retroactive:
    no correction to prepare() can be made permanent for existing data.

    Contract (minimum): latitude/longitude/frp float, confidence string
    (VIIRS l/n/h and MODIS 0-100 share it; never coerced to numbers),
    detection_id string, on_land boolean. acq_date/acq_time stay as returned.

    Idempotent: applying twice equals applying once.
    """
    df = df.copy()
    for col in ("latitude", "longitude", "frp"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    if "confidence" in df.columns:
        df["confidence"] = df["confidence"].astype("string")
    if "detection_id" in df.columns:
        df["detection_id"] = df["detection_id"].astype("string")
    if "on_land" in df.columns:
        df["on_land"] = df["on_land"].astype("boolean")
    else:
        # Column-set half of the contract: merge partners align cleanly, and
        # assign_admin() replaces these placeholders with real values.
        df["on_land"] = pd.array([pd.NA] * len(df), dtype="boolean")
    return df


def merge_tables(*frames: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate on detection_id only.

    keep="first" with existing tables passed before new ones means re-running
    never overwrites stored rows or changes their IDs. Detections are distinct
    per satellite because satellite/instrument are part of the ID hash.
    Every incoming frame is normalised first, and the result again, so dtype
    drift from any source (old Parquet, parser changes, empty frames) cannot
    propagate into the store.
    """
    combined = pd.concat([normalise(f) for f in frames], ignore_index=True)
    merged = (combined.drop_duplicates(subset="detection_id", keep="first")
              .sort_values("detection_id").reset_index(drop=True))
    return normalise(merged)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", type=int,
                    help="window size in days (default: config lookback_days)")
    ap.add_argument("--end",
                    help="window end date YYYY-MM-DD (default: today)")
    ap.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD",
                    help="backfill mode: first requested day")
    ap.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD",
                    help="backfill mode: last requested day (inclusive)")
    ap.add_argument("--backfill", action="store_true",
                    help="backfill the last config backfill_years ending today "
                         "(UTC); --from/--to override either end")
    ap.add_argument("--refetch", action="store_true",
                    help="re-download every raw file, including wholly-past "
                         "chunks (default: recent chunks always refetch, "
                         "older chunks reuse cached raw responses)")
    args = ap.parse_args(argv)

    load_env_file()
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        sys.exit("FIRMS_MAP_KEY environment variable is not set. Get a free "
                 "map key at https://firms.modaps.eosdis.nasa.gov/api/map_key/"
                 " and put it in .env at the repository root, or export it "
                 "in the environment.")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    bbox = [float(v) for v in cfg["aoi_bbox_wsen"]]
    raw_dir = ROOT / cfg["output_paths"]["raw_dir"]
    processed = ROOT / cfg["output_paths"]["processed"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed.parent.mkdir(parents=True, exist_ok=True)

    # Boundaries are loaded once per run, never per detection: a per-row load
    # would not survive a multi-year backfill.
    boundaries = None
    if cfg.get("admin_polygon"):
        admin_path = ROOT / cfg["admin_polygon"]
        if not admin_path.exists():
            sys.exit(f"admin_polygon from config.yaml not found: {admin_path}")
        boundaries = load_boundaries(admin_path)

    # Local date would run ahead of UTC on a UTC+9 machine and request a
    # window that ends in the future; FIRMS answers with a short result, no error.
    today_utc = datetime.now(timezone.utc).date()

    backfill = bool(args.backfill or args.date_from or args.date_to)
    if not args.backfill and bool(args.date_from) != bool(args.date_to):
        sys.exit("--from and --to must be given together, "
                 "or use --backfill to take both defaults.")
    if backfill and (args.end or args.lookback is not None):
        log.warning("--end/--lookback are ignored in backfill mode")

    gaps: list[dict] = []
    if backfill:
        availability = fetch_availability(key)
        if availability is None:
            sys.exit("Could not read the FIRMS data-availability table; "
                     "refusing to guess which archive windows exist "
                     "(a wrong guess yields silent empty results). Re-run "
                     "when the API responds.")
        # backfill_years drives the default range. It is the only consumer of
        # that config value: a knob that merely warns earns nothing.
        years_cfg = float(cfg.get("backfill_years", 3))
        d_to = date.fromisoformat(args.date_to) if args.date_to else today_utc
        d_from = (date.fromisoformat(args.date_from) if args.date_from
                  else d_to - timedelta(days=round(years_cfg * 365.25)))
        if d_from > d_to:
            sys.exit("--from must not be after --to.")
        table_max = max(mx for _, (_, mx) in availability.items())
        table_min = min(mn for _, (mn, _) in availability.items())
        if d_to > table_max or d_from < table_min:
            log.warning("requested range %s..%s extends beyond the live "
                        "availability table (%s..%s); those days are "
                        "recorded as unavailable", d_from, d_to,
                        table_min, table_max)
        years_cap = years_cfg
        if args.date_from and args.date_to and                 (d_to - d_from).days + 1 > years_cap * 366:
            log.warning("requested span exceeds the configured "
                        "backfill_years (%.0f); reconsider scope before "
                        "paying for the extra requests", years_cap)
        jobs, gaps = plan_backfill(availability, cfg["sources"], d_from, d_to)
        log.info("backfill %s..%s planned: %d chunks across %d satellites, "
                 "%d days recorded unavailable", d_from, d_to, len(jobs),
                 len(cfg["sources"]), sum(g["days"] for g in gaps))
    else:
        end = date.fromisoformat(args.end) if args.end else today_utc
        lookback = args.lookback if args.lookback is not None \
            else int(cfg["lookback_days"])
        jobs = [(src, *chunk) for src in cfg["sources"]
                for chunk in chunk_starts(end, lookback)]

    frames, fetched, num_cached, failures = [], 0, 0, 0
    records = []
    for i, (source, start, days) in enumerate(jobs):
        if i:
            time.sleep(1)
        raw_path = cache_path(raw_dir, source, start, days)
        force = args.refetch or should_refetch(start, days, today_utc)
        record = {"source": source, "chunk_start": start, "days": days,
                  "rows": None, "utc": utc_stamp()}
        if raw_path.exists() and not force:
            text = raw_path.read_text()
            num_cached += 1
            note = "cached"
            record["outcome"] = "cached"
            record["rows"] = len(text.splitlines()) - 1
        else:
            text = fetch_chunk(key, source, bbox, start, days)
            if text is None:
                failures += 1
                records.append({**record, "outcome": "failed"})
                continue
            raw_path.write_text(text)
            fetched += 1
            note = f"fetched {len(text.splitlines()) - 1} rows"
            record["outcome"] = "fetched"
            record["rows"] = len(text.splitlines()) - 1
        frames.append(prepare(text, bbox))
        records.append(record)
        # Progress marker so an interrupted multi-year run is obviously
        # resumable: the next run replays chunk N of M entirely from cache.
        log.info("[%d/%d] %s %s (%dd) -> %s", i + 1, len(jobs), source,
                 start, days, note)

    # Uncovered stretches are recorded like any other outcome: 'unavailable'
    # must never masquerade as zero rows (AGENTS rule 2).
    for g in gaps:
        records.append({**g, "outcome": "unavailable", "rows": None,
                        "utc": utc_stamp()})

    # Provenance is persisted even when the run then aborts: the failure paths
    # below are exactly when the report layer most needs it.
    append_manifest(processed.parent / MANIFEST_FILENAME, records)
    log.info("provenance: %d chunk records appended -> %s", len(records),
             MANIFEST_FILENAME)
    log.info("summary: %d fetched, %d served from cache, %d failed, "
             "%d unavailable of %d chunks",
             fetched, num_cached, failures, len(gaps), len(jobs))

    if not frames:
        if backfill and not jobs:
            sys.exit(f"No part of {args.date_from}..{args.date_to} falls "
                     "inside any configured satellite's data window - see "
                     "the manifest records marked 'unavailable'. Existing "
                     "store left untouched.")
        sys.exit("ALL FIRMS requests failed and no cached raw responses exist "
                 "- no data parsed, existing store left untouched.")
    if fetched == 0 and failures:
        sys.exit(f"EVERY intended fetch failed ({failures} of {len(jobs)} "
                 f"chunks); all parsed data came from cache. Refusing to "
                 "write possibly stale data - existing store left untouched.")
    if failures:
        log.warning("%d of %d requests failed; proceeding with partial data "
                    "but exiting non-zero", failures, len(jobs))

    pieces = []
    if processed.exists():
        pieces.append(pd.read_parquet(processed))
    pieces.extend(frames)
    merged = merge_tables(*pieces)

    if boundaries is not None:
        # Pure function of coordinates, so this is idempotent on stored rows
        # and upgrades rows written before the boundary file existed, without
        # touching detection IDs. Re-applied to every row each run: newly
        # deduped rows and legacy rows both end up consistently attributed.
        merged = assign_admin(merged, boundaries)

    # Recurrent-location flagging (Phase 2 item 1). Recomputed over the whole
    # store every run, so flags stay consistent as history grows; flagged rows
    # keep their place in every count - nothing is excluded anywhere.
    # The mask is published to docs/data/ too: it is the only way a reader can
    # check what the brief's site references mean (Task 04b).
    # registry_version survives deletion of the mask files via the manifest
    # ledger, so a rebuild can increment it (Task 04b check 3).
    hint = 0
    manifest_path = processed.parent / MANIFEST_FILENAME
    if manifest_path.exists():
        try:
            for r in json.loads(manifest_path.read_text(encoding="utf-8")) \
                    .get("runs", []):
                if r.get("outcome") == "registry_version":
                    hint = max(hint, int(r.get("rows") or 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("unreadable manifest; registry_version hint lost")
    merged, sites, rec_reason, reg_version = recurrence.flag(
        merged, cfg.get("recurrence", {}),
        processed.parent / recurrence.RECURRENT_SITES_FILENAME,
        publish_path=(ROOT / cfg["output_paths"]["summary_json"]).parent
        / recurrence.RECURRENT_SITES_FILENAME,
        prior_version_hint=hint)
    records.append({"source": "recurrent_sites", "chunk_start": "-",
                    "days": 0, "outcome": "registry_version",
                    "rows": reg_version, "utc": utc_stamp()})
    if rec_reason:
        log.warning("recurrence skipped: %s", rec_reason)
    else:
        log.info("recurrence: %d recurrent site(s) flagged (registry v%d)",
                 len(sites), reg_version)

    try:
        merged.to_parquet(processed, index=False)
    except ImportError:
        sys.exit("Writing Parquet requires pyarrow: pip install pyarrow")

    log.info("stored %d unique detections across %d sources -> %s",
             len(merged), len(cfg["sources"]),
             processed.relative_to(ROOT))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
