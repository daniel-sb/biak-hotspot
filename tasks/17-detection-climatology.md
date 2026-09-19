# Task 17 — Detection climatology: the baseline any model must beat (PLAN.md Phase 5, step 2)

PLAN.md Phase 5 step 2: *"Probability of a detection per grid cell per day-of-year, from
the full history. Any statistical model must beat this to justify its existence."*

This task builds that baseline and scores it **out of sample**. The scoring is the point.
A climatology fitted on every year and then scored on those same years looks excellent, and
every model later compared against it would inherit the flattery. PLAN.md Phase 5 is
explicit that splits are temporal, by season, never random. The baseline gets the same
treatment the model will.

It does not build a model, and it does not build PLAN.md Phase 5 step 1 (FWI/KBDI).

## What is being predicted

For each **land grid cell** and each **observed WIT day**: did at least one detection fall
in that cell on that day? It is binary. Counts are not predicted.

- **Day:** `date_wit` (AGENTS always-1). Not `acq_date`, which is a UTC date.
- **Cell:** a regular grid of `grid_m` metres, anchored at the south-west corner of
  `aoi_bbox_wsen` in `config.yaml`. The cell size in degrees is `grid_m / M_PER_DEG` on both
  axes, using `recurrence.M_PER_DEG`. The longitude scale differs from the latitude scale by
  under 0.05% at these latitudes; say so in a comment and do not correct for it.
- **Land cell:** a cell whose square intersects the union of the `admin_polygon` features.
  Use `shapely` and a prepared geometry. Count the detections that fall in no land cell and
  report the count. They are excluded from the baseline, not from the store.

## The same eyes every year — read this before anything else

The satellites watching Biak changed during the record. **NOAA-21 contributes nothing
before 16 February 2024.** Its NRT source is `unavailable` in `run_manifest.json` for
2023-08-27 to 2024-01-16, its first stored detection is 16 February 2024, and the store
holds 0 NOAA-21 detections in 2023 against 239 in 2026. A
climatology that counts NOAA-21 would read an extra satellite as extra burning, and the
later years would look more fire-prone for a reason that has nothing to do with the ground.

So the baseline is built on **a fixed constellation that covers the whole record**:

```yaml
baseline:
  constellation:          # satellite value in the store -> manifest sources
    N:     [VIIRS_SNPP_NRT, VIIRS_SNPP_SP]
    N20:   [VIIRS_NOAA20_NRT, VIIRS_NOAA20_SP]
    Terra: [MODIS_NRT, MODIS_SP]
    Aqua:  [MODIS_NRT, MODIS_SP]
```

A detection counts only if its `satellite` is a key of `constellation`. Report how many
detections were set aside for being outside it, by satellite, and **how many positive
cell-days exist only because of them**. That second number says what the exclusion cost.

## Observed days: an unobserved day is not a zero

AGENTS never-2 applies directly. A day with no detection in a cell is a **zero only if the
satellites were looking.** A day nobody fetched is missing, and it must leave the
denominator rather than enter it as "no burning".

**Do not write your own coverage logic.** `report_daily._is_observed_closed(day, runs,
sources)` is the project's one definition of a covered day (Task 08c). A day counts as
**observed** when that function returns True for **every** instrument group:
- S-NPP, called with S-NPP's two source names;
- NOAA-20, called with NOAA-20's two source names;
- MODIS, called with the two MODIS source names.

If one instrument's fetch failed, the day is not the day the other years saw.

Report the observed days per calendar year, and list every day in the store's span that is
not observed. For reference, when this task was written that rule gave 122 observed days
in 2023 (from 1 September), 366 in 2024, 365 in 2025, 259 in 2026 to 16 September, and no
unobserved day. If your count differs, say why before going further.

Cloud is not handled, and it cannot be from this data. A cloudy observed day stays a zero.
State this as a caveat.

## The climatology

For cell *c* and day-of-year *d*:

```
p(c, d) = (observed days in the window with a detection in c)
          / (observed days in the window)
```

- **The window** is every observed day, in every training year, whose day-of-year lies
  within `doy_half_window` of *d*. Three years give three samples of any single calendar
  day, which is not a probability, so the window pools neighbouring days. Set
  `doy_half_window: 15` in config, with a comment saying why.
- **Day-of-year** runs on a 365-day circle. 29 February takes 28 February's day number. The
  window wraps, so 31 December is 1 day from 1 January.
- **No spatial smoothing, and no prior or pseudo-count.** Many cells will be exactly 0.
  That is the honest empirical climatology, and the metrics below handle zeros. A smoothed
  baseline is a model, not a baseline.

Expose it as a function, `climatology(...)`, that takes the training detections and the
training observed days and returns the probabilities. Phase 5 step 3 will import it.
**Do not write the probability array to disk.** It is regenerated from the store in
seconds, and a stored copy is one that goes stale.

## Scoring: leave one calendar year out

The record runs from 2023-09-01 to today. Burning here peaks inside one calendar year, so
calendar years are the seasons. For each calendar year *Y* with observed days:

1. Fit the climatology on every **other** year's detections and observed days.
2. Predict *p* for every (land cell, observed day of *Y*).
3. Score those predictions against what happened in *Y*.

**Year *Y*'s detections must never reach its own training data.** A test checks this.

For each fold, report:
- `n_cell_days` and `n_positive`;
- the **Brier score**: the mean of (p − y)²;
- the **reference Brier**: the Brier score of a constant equal to the training base rate
  (training positives / training cell-days);
- the **Brier skill score**: 1 − Brier / reference Brier;
- the **average precision**, the area under the precision-recall curve, defined as
  sklearn's `average_precision_score`: AP = Σₖ (Rₖ − Rₖ₋₁) · Pₖ over **unique** score
  thresholds in descending order.

**Ties matter here.** Most predictions will be exactly 0, and ranking tied scores
arbitrarily changes AP. Tied scores are one threshold. Implement it with the standard
library and numpy; no scikit-learn (AGENTS never-7). A test checks it against a
hand-computed case with ties.

Also report a **reliability table** pooled across folds. Put the predictions into bins with
edges `[0, 1e-4, 1e-3, 1e-2, 0.05, 0.1, 0.2, 1]`; the rates are small, so the bins are
too. Per bin, give the count, the mean predicted *p*, and the observed frequency. PLAN.md
Phase 5 asks for a reliability curve, and this is its data.

**The 2023 and 2026 folds are partial years.** 2023 starts 1 September. For 2026 the store
ends at its last observed day. Report each fold's observed-day count so no one averages
them as though they were equal.

**2026 is the fold that will look worst, and that is expected.** PLAN.md 11.1 records
August 2026 as far outside the 2023-2025 record. A climatology from quieter years
under-predicts an extreme year by construction. Put that sentence in the output's
caveats. Do not tune anything to improve the 2026 fold.

## Configuration

```yaml
baseline:
  grid_m: 1000
  doy_half_window: 15
  reliability_bins: [0, 0.0001, 0.001, 0.01, 0.05, 0.1, 0.2, 1]
  constellation: ...        # as above
```

Every value gets a comment giving its reason. AGENTS always-5: nothing hard-coded in the
module.

## Output

`src/baseline.py`, runnable as `python src/baseline.py`. It writes
`data/processed/baseline_eval.json`, with sorted keys, indent 1 and no timestamp. Add that
file to the `data/processed/` allowlist in `.gitignore`. The file holds:

- parameters, and the store's first and last `date_wit`;
- land cell count; detections outside land cells; detections outside the constellation, by
  satellite, with the positive cell-days lost to that exclusion;
- observed days per calendar year, and the list of unobserved days;
- per-fold metrics as specified above;
- the pooled reliability table;
- a `caveats` list, verbatim:
  - "A day is observed when every constellation instrument was successfully fetched for
    it. Cloud is not detected: a cloudy observed day counts as a day without detection."
  - "The constellation excludes NOAA-21, which contributes nothing before 16 February 2024,
    so that the baseline sees each year through the same satellites."
  - "Three years of history is the minimum PLAN.md Phase 5 names. Probabilities are pooled
    over a 31-day window and remain small-sample estimates."
  - "A climatology fitted on 2023-2025 under-predicts August 2026 by construction; that
    fold measures how unusual 2026 was as much as how good the baseline is."
  - "This is a climatology of satellite detections. It is not a forecast of fire, not a
    fire danger rating, and it says nothing about why land is burned or who burns it
    (PLAN.md section 8)."

Print one line per fold to stdout.

## Do not write the finding

**Do not add an entry to `FINDINGS.md` for this task.** This overrides AGENTS always-6, on
purpose. F7's figures were misquoted in its prose and needed F8. These numbers become the
bar every later model is held to, so the entry is written at review, from
`baseline_eval.json`. Put the per-fold table in your final message.

## Constraints

- **Offline only.** The inputs are the tracked `detections.parquet`, `run_manifest.json`
  and the desa polygons. Nothing is fetched. If an input is missing or unreadable, exit
  non-zero naming it and write nothing. **No placeholder, no synthetic detections or
  manifest, no generator of stand-in values**, even to make a test pass.
- Reuse `report_daily._is_observed_closed` and `recurrence.M_PER_DEG`. Do not copy them.
- AGENTS never-3: `confidence` is not read at all here. AGENTS never-5: `detections.parquet`
  is read, never written.
- **Wording**, everywhere, including your final message: "detection climatology",
  "probability of a detection". Never "fire risk", "fire danger", "fire forecast" or
  "prediction of fires". PLAN.md section 8.

## Check

`tests/test_baseline.py`, offline, with synthetic frames and a synthetic manifest built
inside the test, in the style of `tests/test_recurrence.py`.

1. A point maps to the expected cell. Given a small land polygon, only the cells it
   intersects are land cells.
2. 29 February takes 28 February's day number; the window wraps across 31 December and
   1 January.
3. Known counts give the known probability. Example: a cell with a detection on one of two
   observed years' same day, `doy_half_window` 0, gives 0.5.
4. A day missing from the manifest leaves the denominator; it does not enter it as a zero.
5. A day where only MODIS was fetched and VIIRS failed is not observed.
6. An N21 detection is excluded and counted, and a cell-day positive only through N21 is
   counted as lost.
7. Brier and average precision match hand-computed values, including a case with tied
   scores.
8. Leakage: in each fold, the held-out year's detections change nothing in its own training
   climatology. Perturbing them leaves that fold's training probabilities identical.
9. The same inputs give byte-identical `baseline_eval.json`.

## Out of scope

- Any model: logistic, gradient boosting or anything else (Phase 5 step 3).
- FWI, KBDI, ERA5-Land (Phase 5 step 1).
- Cloud masking, and any correction for it.
- A map or dashboard panel, the daily cron, and `docs/`.
- Using events (`events.json`) instead of detections. PLAN.md defines the baseline on
  detections. If you think events are the better unit, say so in your final message and
  leave it.
