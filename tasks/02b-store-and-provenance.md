# Task 02b — store schema normalisation and fetch provenance

Task 02 was reviewed and accepted. The pinned values match exactly, the brief is correct and
well-judged, and the tests are sound. Two defects were found. Both are structural rather than
cosmetic, and both came from gaps in the previous task specification rather than from mistakes
in your implementation.

Read `AGENTS.md` first. Do not build anything from PLAN.md phases 2 to 6. Do not restructure
code that is not named below.

---

## 1. Stored coordinates are strings, and parser fixes cannot reach stored rows (high)

The stored table has `latitude` and `longitude` as `str`, not `float`:

```
fresh prepare() latitude dtype : float64
stored parquet latitude dtype  : str
merge(store, fresh) latitude   : object
```

`merge_tables()` uses `keep="first"` with the existing store passed first, which is correct for
ID stability. The consequence is that rows already in the store keep whatever `prepare()`
produced when they were first written. The float conversion added in task 01b therefore only
lands on detections seen for the first time after that change.

The immediate symptom is that arithmetic on `latitude` raises
`ArrowNotImplementedError: Function 'subtract_checked' has no kernel matching input types
(large_string, double)`. Phase 3 clustering will hit this immediately.

The structural problem is larger: **no future correction to `prepare()` can ever fix data
already stored.** Every parser bug becomes permanent for existing rows.

### What to build

Add a single `normalise(df)` function that enforces the column contract — dtypes and column
set — and apply it to **every** frame entering `merge_tables()`, including the one read back
from Parquet. Do not fix this by casting at the point of the error; fix it where all frames
converge, so the next schema change is automatically retroactive.

`normalise()` must be idempotent: applying it twice equals applying it once.

Enforce at minimum: `latitude` and `longitude` float, `frp` float, `confidence` **string**,
`on_land` boolean, `detection_id` string. Leave `acq_date` and `acq_time` as returned.

**`confidence` must stay a string.** It carries VIIRS `l`/`n`/`h` and MODIS 0-100 in one column
and must never be coerced. The existing test for this must keep passing.

### Checks

- `normalise()` applied twice equals applied once.
- A frame read back from Parquet with string coordinates comes out of `merge_tables()` with
  float coordinates and unchanged `detection_id` values.
- After a merge, `store.latitude - 0.1` evaluates without raising.
- The corpus still yields 653 detections, 651 on land, 2 off, 18 distrik.

---

## 2. The brief claims a source was observed when it cannot know that (medium)

The brief currently prints:

> "no detections recorded" means this source returned nothing for the AOI during this WIT day.

`report_daily.py` reads only the Parquet store, and nothing anywhere persists which sources
were actually fetched. If a MODIS request had failed, the brief would print exactly the same
sentence. It is a positive claim about observation that the underlying data cannot support.

This is the failed-fetch-as-zero defect at the reporting layer — AGENTS.md rule 2 and PLAN.md
section 5.1. PLAN.md section 10.4 finding 3 is the case that makes it real: FIRMS went silent
on 2026-08-26 and 08-27 while the airport was still reporting smoke, and nobody yet knows
whether the fires stopped or cloud hid them.

### What to build

**Ingest side.** `src/ingest_firms.py` already counts fetched, cached and failed chunks. Persist
that instead of discarding it. Write a run manifest as JSON — `data/processed/run_manifest.json`
is fine — recording for each `(source, chunk_start, days)`: the outcome (`fetched`, `cached`,
`failed`), the row count where known, and a UTC timestamp. Merge into any existing manifest
rather than overwriting, so history accumulates. This is a data file, not configuration.

**Report side.** Read the manifest and render three distinct states per source per day, never
two:

| State | Meaning | When |
|---|---|---|
| a count | observed, detections found | rows present |
| observed, no detections | the source was successfully queried and returned nothing | manifest shows a covering chunk `fetched` or `cached` |
| **not observed** | the source failed or was never queried for this day | manifest shows `failed`, or has no covering entry |

The third state must be visually distinct in the brief and must never be presented as a zero.
When any source is in that state, say plainly in the brief that coverage for the day was
incomplete.

If the manifest is missing entirely — as it will be for the 653 rows already stored — every
source for those days is **unknown**, not observed. Say so rather than assuming success. Do not
backfill a manifest for historical data you have no record of.

### Checks

- A source with a `failed` manifest entry renders differently from a source with a `fetched`
  entry and no rows, which renders differently again from a source with detections.
- A day with no manifest coverage renders as unknown, not as zero.
- The manifest merges across runs instead of being overwritten.
- The existing test that distinguishes a silent source from a zero-detection district still
  passes, updated for the three-state model.

---

## Acceptance

- All 19 existing tests still pass, modified only where the three-state model requires it.
- New tests cover both items above.
- The corpus still yields 653 detections, 651 on land, 2 off, 18 of 24 distrik.
- The brief still lists all 24 distrik and still carries the PLAN.md section 8 caveat.
- No new dependencies.

## Out of scope

Everything in PLAN.md phases 2 to 6: quality-control filters, the persistent-source mask, event
clustering, Earth Engine, METAR, air quality, fire danger, the dashboard, PNG maps.
