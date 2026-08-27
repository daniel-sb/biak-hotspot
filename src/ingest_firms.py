"""FIRMS active-fire ingest for the Biak AOI (Task 01, PLAN.md 2.1 / Phase 1).

Pulls near-real-time detections for all configured sources, persists raw
responses under data/raw/ before parsing, then deduplicates on a stable
detection_id and merges into data/processed/detections.parquet.

Chunks whose window touches today or yesterday (UTC) are always re-downloaded;
wholly-past chunks reuse cached raw files unless --refetch. FIRMS refreshes
NRT several times a day, so recent cache is never trusted.

Usage:
    python src/ingest_firms.py [--lookback N] [--end YYYY-MM-DD] [--refetch]

FIRMS_MAP_KEY must be set in the environment.
"""
import argparse
import hashlib
import io
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]

FIRMS_URL = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
             "{key}/{source}/{w},{s},{e},{n}/{days}/{start}")
DAY_RANGE_MAX = 5  # FIRMS rejects >5: "Invalid day range. Expects [1..5]."
WIT = timezone(timedelta(hours=9))  # Papua is UTC+9

log = logging.getLogger("ingest_firms")


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


def prepare(text: str, bbox: list[float]) -> pd.DataFrame:
    """Raw FIRMS CSV text -> tidy DataFrame, clipped to the bbox.

    Keeps acq_date/acq_time and confidence as returned (confidence must never
    be coerced: VIIRS l/n/h and MODIS 0-100 share the column); latitude and
    longitude become float. Adds detection_id, datetime_utc (tz-aware),
    datetime_wit (+09:00) and date_wit.
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
    # HOOK for step 2 (not built yet): administrative polygon clipping goes here
    # once a boundary file exists (see admin_polygon in config.yaml,
    # PLAN.md 2.7 / Phase 1). This function is deliberately the single place
    # where spatial filtering happens.
    w, s, e, n = bbox
    inside = lat.between(s, n) & lon.between(w, e)
    return df[inside]


def merge_tables(*frames: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate on detection_id only.

    keep="first" with existing tables passed before new ones means re-running
    never overwrites stored rows or changes their IDs. Detections are distinct
    per satellite because satellite/instrument are part of the ID hash.
    """
    combined = pd.concat(frames, ignore_index=True)
    return (combined.drop_duplicates(subset="detection_id", keep="first")
            .sort_values("detection_id").reset_index(drop=True))


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", type=int,
                    help="window size in days (default: config lookback_days)")
    ap.add_argument("--end",
                    help="window end date YYYY-MM-DD (default: today)")
    ap.add_argument("--refetch", action="store_true",
                    help="re-download every raw file, including wholly-past "
                         "chunks (default: recent chunks always refetch, "
                         "older chunks reuse cached raw responses)")
    args = ap.parse_args(argv)

    key = os.environ.get("FIRMS_MAP_KEY")
    if not key:
        sys.exit("FIRMS_MAP_KEY environment variable is not set. Get a free "
                 "map key at https://firms.modaps.eosdis.nasa.gov/api/map_key/"
                 " and export it in .env.")

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    bbox = [float(v) for v in cfg["aoi_bbox_wsen"]]
    raw_dir = ROOT / cfg["output_paths"]["raw_dir"]
    processed = ROOT / cfg["output_paths"]["processed"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed.parent.mkdir(parents=True, exist_ok=True)

    # Local date would run ahead of UTC on a UTC+9 machine and request a
    # window that ends in the future; FIRMS answers with a short result, no error.
    today_utc = datetime.now(timezone.utc).date()
    end = date.fromisoformat(args.end) if args.end else today_utc
    lookback = args.lookback if args.lookback is not None else int(cfg["lookback_days"])
    jobs = [(src, *chunk) for src in cfg["sources"]
            for chunk in chunk_starts(end, lookback)]

    frames, fetched, num_cached, failures = [], 0, 0, 0
    for i, (source, start, days) in enumerate(jobs):
        if i:
            time.sleep(1)
        raw_path = cache_path(raw_dir, source, start, days)
        force = args.refetch or should_refetch(start, days, today_utc)
        if raw_path.exists() and not force:
            text = raw_path.read_text()
            num_cached += 1
            note = "cached"
        else:
            text = fetch_chunk(key, source, bbox, start, days)
            if text is None:
                failures += 1
                continue
            raw_path.write_text(text)
            fetched += 1
            note = f"fetched {len(text.splitlines()) - 1} rows"
        frames.append(prepare(text, bbox))
        log.info("%s %s (%dd) -> %s", source, start, days, note)

    log.info("summary: %d fetched, %d served from cache, %d failed of %d chunks",
             fetched, num_cached, failures, len(jobs))

    if not frames:
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
