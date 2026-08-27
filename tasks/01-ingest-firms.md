# Task 01 — FIRMS ingest

Build `src/ingest_firms.py` and `config.yaml`. Nothing else.

Read `AGENTS.md` first. Reference: `PLAN.md` sections 2.1 and 3 (Phase 1) and 10.4. Ignore
every other section — they describe later phases you are not building.

## What it does

Fetch active-fire detections for the Biak AOI from the NASA FIRMS API, store them, and be
safe to re-run.

## Inputs

- `FIRMS_MAP_KEY` from the environment. Fail with a clear message if unset.
- `config.yaml`, which you also create, holding: AOI bbox, source list, output paths,
  and default lookback in days.

## API details

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{W,S,E,N}/{DAY_RANGE}/{START_DATE}
```

- AOI bbox: `134.6,-1.45,136.7,-0.55` (west, south, east, north).
- Sources: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`.
- **`DAY_RANGE` maximum is 5.** A larger value returns HTTP 400 with body
  `Invalid day range. Expects [1..5].` Chunk longer lookbacks into requests of five days.
- Sleep 1 second between requests.
- A failed or non-CSV response must be logged loudly and must not be written as an empty day.

## Required behaviour

**Stable detection ID.** Compute as a SHA-1 hex digest of the joined string
`satellite|instrument|acq_date|acq_time|lat|lon`, with latitude and longitude formatted to
exactly 5 decimal places. The same detection fetched twice must produce the same ID. Store it
as a column named `detection_id`.

**Deduplicate on `detection_id` only.** Overlapping five-day chunks will refetch the same
detections; those are duplicates and must collapse to one row.

**Do not deduplicate across satellites.** S-NPP and NOAA-20 observing the same fire are two
independent observations and both must be kept. This is the mistake to avoid here.

**Time columns.** Keep `acq_date` and `acq_time` as returned. Add `datetime_utc` (parsed,
timezone-aware) and `datetime_wit` (UTC+9), plus `date_wit` for daily grouping.

**Clip to the bbox only.** The administrative polygon does not exist in this repository yet.
Leave a clearly marked hook for it and note the omission in your final message. Do not
download or invent a boundary file.

**Storage.** Write raw responses to `data/raw/{SOURCE}_{START_DATE}.csv` before parsing, then
write the combined deduplicated table to `data/processed/detections.parquet`. Re-running must
merge into the existing table without duplicating rows or changing existing IDs.

## The check

Write `tests/test_ingest_firms.py`. It must not touch the network. Using the committed
fixtures in `data/raw/`, assert at least:

1. Parsing the same fixture twice and merging produces the same row count as parsing it once.
2. `detection_id` is stable across two independent parses of the same input.
3. A detection at 2026-08-25 21:00 UTC lands on WIT date 2026-08-26, not 2026-08-25.
4. The `confidence` column still contains both `n` and a numeric-looking MODIS value after
   parsing — proving it was not coerced to a number.
5. `frp` survives parsing as a float.

## Out of scope — do not build

Maps, plots, reports, GeoJSON export, the dashboard, quality-control filters, event
clustering, Earth Engine, METAR, anything in PLAN.md phases 2 through 6.

## Expected result as a sanity check

A pull covering 2026-08-13 to 2026-08-27 should return roughly 650 detections, peaking around
280 on WIT day 2026-08-22. If your numbers are wildly different, something is wrong — say so
rather than adjusting the code until they match.
