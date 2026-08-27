# Task 03 — historical backfill from the FIRMS archive

Extend `src/ingest_firms.py` so it can pull a multi-year history, not just a recent lookback.
This is the prerequisite for the Phase 2 persistent-source filter: a location that produces
hotspots on most days for months is infrastructure, and that judgement is impossible against
the fifteen days currently stored.

Read `AGENTS.md` first. Reference: PLAN.md sections 2.1 and 3 (Phase 2 item 1). Do not build
the persistent-source filter itself — that is the next task.

---

## The problem

Each FIRMS source has a limited near-real-time window and rolls over into a separate archive
("standard processing") source. Observed on 2026-08-27:

```
MODIS_NRT          2026-05-01 .. 2026-08-27      MODIS_SP          2000-11-01 .. 2026-04-30
VIIRS_SNPP_NRT     2026-04-28 .. 2026-08-27      VIIRS_SNPP_SP     2012-01-20 .. 2026-04-27
VIIRS_NOAA20_NRT   2026-06-01 .. 2026-08-27      VIIRS_NOAA20_SP   2018-04-01 .. 2026-05-31
VIIRS_NOAA21_NRT   2024-01-17 .. 2026-08-27      (no SP counterpart)
```

**These dates roll forward continuously. Do not hardcode any of them.** Read the live table:

```
https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{MAP_KEY}/all
```

It returns `data_id,min_date,max_date`. A backfill that assumes NRT reaches back years returns
empty results rather than an error — silently, which is the dangerous kind.

## What to build

A backfill mode, `--from YYYY-MM-DD --to YYYY-MM-DD`, alongside the existing `--lookback`.
Reuse the existing chunking, caching, manifest and merge machinery — do not write a parallel
ingest path.

### Source selection per date — the trap to avoid

For each chunk date range, choose exactly one source per satellite:

- If the range falls inside that satellite's SP window, use the `_SP` source.
- If it falls inside the NRT window, use the `_NRT` source.
- If a range straddles the boundary, split it so each part uses one source.
- If a satellite has no SP counterpart (NOAA-21 today), use NRT for its whole available range.
- If a date is outside both windows, skip it and record that in the manifest as `unavailable`.
  Do not treat it as an empty result.

**Never fetch the same date from both the SP and NRT source of one satellite.** The archive is
reprocessed, so coordinates and acquisition times can differ slightly between the two. Those
rows will not collapse under `detection_id` deduplication and you will double-count the same
fire. The `version` column records which processing produced a row — keep it, it is the audit
trail for this.

### Resumability

A multi-year backfill will be interrupted. It must resume without refetching. The existing
cache already gives this: `should_refetch()` treats wholly-past windows as cacheable, and past
chunks are exactly what a backfill pulls. Confirm this holds rather than assuming it, and log
progress (chunk N of M) so an interrupted run is obviously resumable.

### Rate limit

5000 transactions per 10 minutes. Three years across four satellites is roughly 880 requests at
5 days per chunk. The existing 1-second sleep keeps this comfortably inside the limit; do not
remove it, and do not add parallelism.

### Configuration

Add `backfill_years` to `config.yaml`, default 3. Three years is enough to establish
persistence. Do not extend the default further on the theory that more is better — MODIS
reaches back to 2000 and pulling all of it wastes an hour to answer a question three years
already answers.

---

## The checks

No network in any test. Inject a fake availability table.

1. Given the availability table above and a requested range of 2024-01-01 to 2026-08-27,
   source selection returns `_SP` for dates inside each SP window and `_NRT` for dates inside
   each NRT window, and never both for one satellite on one date.
2. A chunk straddling a satellite's SP/NRT boundary is split at the boundary.
3. A date outside every window for a satellite is recorded `unavailable`, not as zero rows.
4. NOAA-21, having no SP counterpart, resolves to NRT across its whole range.
5. Chunk tiling over a long range still produces chunks of at most 5 days that cover the range
   exactly, with no gaps and no overlaps.
6. The existing 24 tests still pass unchanged.

## Out of scope

The persistent-source filter, coastline and glint flags, METAR, SiPongi — all next tasks.
Anything in PLAN.md phases 3 to 6. No new dependencies.

## Before you finish

If any decision in this task was not specified and you had to choose — a file name, a default,
an edge case, an ordering — say so explicitly in your final message. Do not silently pick one.
Every defect found in tasks 01 and 02 lived in an unspecified decision, not in a misread
instruction.
