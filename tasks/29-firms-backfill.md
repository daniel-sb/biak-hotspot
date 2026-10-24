# Task 29 — Is the 2026 season unprecedented, or only unprecedented since 2023?

The detection store runs **2023-09-01 to 2026-09-23**, 1,166 rows. Inside that window 2026 is
obviously anomalous:

| year | MODIS | VIIRS | all |
|---|---|---|---|
| 2023 | 3 | 97 | 100 |
| 2024 | 3 | 87 | 90 |
| 2025 | 1 | 70 | 71 |
| 2026 | **15** | **890** | **905** |

The worst single day is 2026-08-22 with 283 detections, against a prior record of 16 on
2023-11-16.

None of that supports the sentence the project wants to write. Three years cannot say
"unprecedented", only "unprecedented since September 2023". The claim worth making is about
the two decades a resident has lived through, and FIRMS holds the data to test it: MODIS back
to November 2000, VIIRS back to 2012.

This task extends the store and answers the question. It changes no published burned-area
figure (`adr/0003`).

## The tool already exists

`src/ingest_firms.py` has a backfill mode: `--from`/`--to`, a live data-availability table that
picks the reprocessed archive (`_SP`) wherever it covers a day and near-real-time (`_NRT`)
otherwise, and chunk tiling that is stable and cached forever, so an interrupted run resumes
instead of refetching. Do not write a second ingest. Run this one.

`config.yaml` sets `backfill_years: 3`, and the comment above it argues against raising the
value because "pulling all of it wastes an hour to answer a question three years answers".
That premise is now false: the question changed. Raise the value, and rewrite the comment to
say what the longer history is for. Prefer explicit `--from`/`--to` for the run itself so the
span is in the shell history rather than inferred from a config default.

## The trap this task exists to avoid

**A detection count spliced across sensors measures the sensor, not the fire.**

VIIRS pixels are 375 m, MODIS pixels are 1 km, roughly 7 times the area. A series that is
MODIS before 2012 and VIIRS after it steps up in 2012 because the pixels shrank. Any reviewer
will say so, and they will be right.

The same trap sits inside MODIS. **Terra's record starts 2000-11, Aqua's starts 2002-07.** A
combined MODIS series doubles its own sampling in mid-2002 for the same reason.

So the long-run comparison is defined as follows, and nothing else counts as the answer:

- **Primary series: MODIS, both platforms, complete calendar years 2003 through 2026.** Twenty
  four years at constant sampling. This is the series the claim rests on.
- **Secondary series: Terra only, 2001 through 2026.** Two extra years, at half the sampling
  of the primary, reported separately and never joined to it.
- **VIIRS, 2013 through 2026**, as its own series. Better instrument, shorter record. It
  cannot speak about 2003.

Split on the `instrument` column, which is already in the store, and on `satellite` for the
Terra-only series. Partial first years (2000, 2002, 2012) are excluded from every series
rather than scaled.

## Small counts, so publish intervals

MODIS sees roughly one to three detections a year here. Fifteen in 2026 against a baseline
near two is a large ratio on small numbers, and a ratio on small numbers needs an interval
before it is a finding. Report each year's count with an exact Poisson interval, and state
2026's rank and its exceedance probability against the 2003 to 2025 distribution.

If the counts turn out too small to separate 2026 from the baseline, **say that**. A negative
result here is a real result: it would mean MODIS cannot answer the question at this AOI size
and only the VIIRS era can be characterised. Do not reach for a combined series to rescue the
claim.

## What the published data must look like afterwards

`src/report_daily.py` writes `docs/data/daily_counts.json` as a flat `[date, count]` list
spanning `date_wit.min()` to `date_wit.max()` of the whole store, sensor-blind. The moment the
store reaches 2003, that file becomes exactly the spliced series this task forbids, and
`history.html` draws it.

Two changes, both required:

1. **Bound `daily_counts.json` to the VIIRS era.** Its start comes from `config.yaml`, not a
   literal. The daily timeline on `history.html` keeps meaning what it means today, and
   `tests/test_dashboard.py::test_daily_counts_dense_sorted_matches_store` keeps passing with
   its span assertion adjusted to that bound rather than to the store's minimum.
2. **Write the long record as a new file**, annual rather than daily, carrying the three
   series above separately with their intervals. A new file under `docs/data/`; nothing
   existing is modified. The page that draws it is step 3 of the dashboard rebuild and is not
   part of this task.

## Rules that are not negotiable here

From `AGENTS.md`, the ones this task can plausibly break:

- **A failed fetch is never zero rows.** An empty FIRMS response and a failed request are
  different facts and must stay distinguishable in stored output and in the exit code. A
  backfill of 24 years will hit transient failures; every one of them must surface.
- **Never invent a value.** No synthetic rows, no placeholder counts, no "representative"
  numbers, not even to demonstrate the output shape. If `FIRMS_MAP_KEY` is absent from the
  environment, exit non-zero and write nothing. This happened before on this project: a
  handed-off task without credentials put fabricated MODIS data on the public page.
- **Never cast `confidence` to a number.** MODIS returns 0 to 100 and VIIRS returns `l`/`n`/`h`
  in the same column, and this task is the first time both eras exist in bulk. Casting
  silently discards most rows.
- **Never drop `frp`.** Never delete rows in quality control; add a boolean flag column.
- Timestamps in UTC with a derived WIT (UTC+9) column, daily aggregation on WIT local days.
- Persist raw responses under `data/raw/` before parsing.
- Read spans and bounds from `config.yaml`.
- Leave one runnable check: an `assert`-based `demo()` under `if __name__ == "__main__"`, or
  one `test_*.py`. Tests must not hit the network; use the committed fixtures in `data/raw/`.
- `FINDINGS.md` is append-only. Add one dated entry naming the script and the commit behind
  it. Never rewrite an earlier entry.
- Do not edit `PLAN.md`. If it needs changing, say so in your final message.

## Do not touch

Another agent is working in this tree on the dashboard. Stay out of:

```
site/            docs/index.html   docs/conditions.html
docs/history.html    docs/assets/      src/build_site.py
```

This task needs `src/ingest_firms.py`, `src/report_daily.py`, `config.yaml`, `data/`,
`docs/data/` and `tests/`, and none of those overlap. Work on a branch if you can.

Do not regenerate any burned-area product. `data/processed/burned_areas.*` and
`docs/data/burn_indices.json` are quoted in the manuscript with confidence intervals, and no
scheduled or incidental run may move them (`adr/0003`).

## Expect it to be slow

FIRMS caps a request at five days, which the script chunks automatically. Twenty-four years is
on the order of an hour of wall clock. Past chunks cache permanently, so an interrupted run
resumes; do not restart it with `--refetch`.

## Done when

- The store spans 2001 or earlier through the present, and the row count and span are stated.
- The three series exist, separately, with per-year counts and exact Poisson intervals.
- 2026's rank and exceedance probability against 2003 to 2025 are stated, **or** the task
  reports plainly that MODIS counts at this AOI are too small to separate them.
- `daily_counts.json` is bounded to the VIIRS era and its test passes.
- The long record is a new file under `docs/data/`, and no existing published file changed
  except `daily_counts.json`'s bound.
- One `FINDINGS.md` entry, appended.
- Every unspecified decision named in the final message: the exact `--from` date, the
  config key names you chose, the new file's name and schema, the interval method, and how
  partial years were excluded.
