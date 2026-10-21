# Task 28 — Which events were measured against a stale "before" image

Task 18's burned-area product does not pick one pre-fire scene. `nearest_look`
(`src/burned_area_gee.py:175`) takes, per pixel, the **latest clear look before** `first_seen`
inside a 60-day window, masked by Cloud Score+ `cs_cdf >= 0.6`, and the **earliest clear look
after** `last_seen` inside a 30-day window. Each pixel can come from a different date, and the
`pre_lag` and `post_lag` bands record how far away that date was.

A check on 2026-10-22 over the 23 assessed events found the two sides are not alike:

| | p50 median | p50 max | events with p50 > 14 d |
|---|---|---|---|
| `post_lag` | 2.9 d | 12.4 d | 0 |
| `pre_lag` | 12.2 d | 29.1 d | 7 |

Those seven events carry 620.7 ha of the 2,414.9 ha total. E0311 sits at a `pre_lag` p50 of
27.1 days, E0371 at 29.1, E0322 at 28.1. The asymmetry has an obvious cause — the post window
searches forward into clear dry-season skies, the pre window searches backwards through the
cloudier build-up — but the consequence has never been measured.

**The consequence runs in two opposite directions, and they are different errors.** This task
separates them. It does not correct anything.

## The two directions

Write `P` for the date of the pre look, `D` for the most recent prior detection inside the
event's footprint, `F` for `first_seen`.

- **Scar already in the pre image** (`D < P < F`). The ground burned, then the pre look was
  taken, so the "before" image is already dark. dNBR+ measures the difference from
  already-burned ground, comes out small, and the event's area is **under**-stated. This is
  omission created by image selection, not by the threshold.
- **Earlier burning counted as this event** (`P < D < F`). The pre look predates burning that
  is not this event's, so the change between pre and post contains both. The event's area is
  **over**-stated, and ground that burned weeks earlier is attributed to it.
- **Neither** (no prior detection inside the footprint before `F`).

**Never add these two together.** They move the area in opposite directions and a single
"events at risk" count would hide that. Report them as separate lists with separate hectares.

## What to build

### `scripts/pre_look_staleness.py`

Offline. No credential, no network, no Earth Engine:

```
python scripts/pre_look_staleness.py
```

Inputs, all already in the repository:

- `data/processed/burned_areas.json` — `assessed`, with `look_lag_days`, `changed_ha`,
  `first_seen_wit`, `last_seen_wit`, `windows_utc`, `n_scenes`, `footprint_ha`.
- `data/processed/events.json` — `events` (488 of them, with `first_seen_utc`,
  `recurrent_share`, `centroid_lat`, `centroid_lon`) and `membership`, which says which
  detections belong to which event.
- `data/processed/detections.parquet` — 1,166 rows, 2023-08-31 to 2026-09-23.
- `data/processed/recurrent_sites.json` — three sites, `R001` to `R003`, each with
  `centroid_lat`, `centroid_lon`, `distinct_days`, `first_date`, `last_date`.

Read `burned_area.footprint_m`, `burned_area.pre_days` and `recurrence.radius_m` from
`config.yaml` (AGENTS always-5). Do not hard-code 375, 60 or 750.

**Reuse what exists; add no dependency** (AGENTS never-7). `metres` in
`src/fieldwork_gpkg.py:68` is the local flat-earth distance and is right at these scales;
`sqlite3`, `pandas`, `shapely` and `json` cover everything else.

### What to compute, per assessed event

1. **The estimated pre look date.** `first_seen_utc` minus `pre_lag` p50, and separately
   minus p90. Report both as `pre_look_p50_date` and `pre_look_p90_date`.

   **This is an approximation and must be labelled as one in the output.** `burned_areas.json`
   stores `pre_lag` only as two percentiles over the event's pixels, not per pixel and not as
   dates. The p50 date is where the median pixel's "before" image sits; individual pixels sit
   on both sides of it. Do not present it as the date of a scene. A field named
   `pre_look_date_is_estimated: true` and a line in `caveats` are the minimum.

2. **Prior detections inside the footprint.** The footprint is the union of
   `footprint_m` circles around the event's own member detections — the same construction
   `burned_area.footprint_m` describes. Inside it, count every detection in the store with an
   `acq_date` **strictly before** `first_seen`'s WIT day that is **not a member of this
   event** (use `membership`). Record the count, the most recent such date `D`, and that
   detection's `frp` (AGENTS never-4). Carry `confidence` as text or not at all — VIIRS
   returns `l`/`n`/`h` and MODIS returns 0–100 in the same column (AGENTS never-3).

3. **The direction**, from `D` against `pre_look_p50_date`: `scar_in_pre`,
   `earlier_burn_included`, or `no_prior_detection`. Compute it against the p90 date as well
   and report both, because an event can fall on different sides at the two percentiles — and
   when it does, that is the most honest thing the output can say about it.

4. **Recurrence.** `recurrent_share` is already computed per event in `events.json`; read it,
   do not recompute it. Add the distance in metres from the event centroid to each of the
   three recurrent sites, the nearest site id, and whether the footprint comes within
   `recurrence.radius_m` of one. R001 at Saramom has 74 distinct detection days between
   2023-09-01 and 2026-08-21, which is the clearest place for a pre image to have inherited an
   older scar.

Write `data/processed/pre_look_staleness.json`, a **new** file. Nothing under `docs/` is read
or written, and no existing file in `data/processed/` is modified.

Print three tables: the `scar_in_pre` events, the `earlier_burn_included` events, and the
events with no prior detection — each with `event_id`, `changed_ha`, `pre_lag` p50 and p90,
`D`, the days between `D` and the pre look, `recurrent_share`, and the nearest recurrent site
with its distance. Then print the hectares in each of the three groups, separately.

## What this task is not allowed to conclude

- **Not that any event's area is wrong.** A stale pre look is a reason to re-examine an event,
  not a measurement of error. Nothing here recomputes `changed_ha`, proposes a correction, or
  produces a second area figure. The only way to know what a fresher pre image would have given
  is to run the product again with one, and that is a different task.
- **Not that a prior detection means prior burning on that ground.** A VIIRS pixel is 375 m and
  locates a thermal anomaly, not a perimeter — the rule Task 15 was built on and the reason the
  hotspot record is never truth anywhere in this repository. A detection inside the footprint
  before `first_seen` makes contamination *possible*, not established.
- **Do not emit a boolean such as `area_wrong`, `suspect` or `needs_rerun`**, and do not rank
  the events by how wrong they might be. The direction label plus the distances and dates is
  the whole output.

## The check

One `test_*.py` under `tests/`, offline, no network (AGENTS always-3 and always-4):

- `D < P < F` classifies as `scar_in_pre`; `P < D < F` as `earlier_burn_included`. Getting
  these the wrong way round inverts the finding and is invisible in the totals.
- A detection on exactly the pre look date is **not** counted as before it; the comparison is
  strictly less than, the same rule Task 26 uses on chip dates.
- An event's own member detections are excluded from the prior count. Without this every event
  flags itself.
- The p50 and p90 classifications are computed independently, and an event that differs between
  them is reported as differing rather than resolved to one.
- Skip cleanly when `data/processed/burned_areas.json` is absent, the way the Task 11 to 15
  checks do.

## Constraints

- **Never write a value you did not compute.** If any of the four inputs is missing or
  unreadable, print which one and why and exit non-zero. Write no file, no placeholder, no
  empty table presented as a result, and no synthetic event, date, distance or hectare. An
  empty answer and a failed read are different facts and must stay distinguishable in the
  output and in the exit code (AGENTS never-2). **This rule binds whatever agent runs this
  task.** This repository has already published synthetic MODIS data once, produced by a
  handed-off task that was blocked and filled the gap instead of reporting it, and the figure
  reached the public page.
- **Never delete rows.** All 23 assessed events appear in the JSON, including those with no
  prior detection anywhere near them (AGENTS never-5). `burned_areas.json` holds 31 entries
  under `assessed`: 23 with `status: "assessed"` and a `changed_ha`, and 8 with
  `status: "no local reference"` and no lag fields — E0109, E0139, E0148, E0267, E0323, E0339,
  E0341 and E0473. List those 8 with their status rather than dropping them. The separate
  `not_assessed` list holds 457 events, every one of them "fewer than 5 detections"; it is
  summarised as a count, not enumerated.
- Timestamps in UTC with a WIT (UTC+9) column derived (AGENTS always-1). `acq_date` in the
  detection store is already a WIT local day; do not shift it again. `first_seen_utc` and
  `first_seen_wit` are both present in `events.json` — say which one each comparison uses.
- **Never edit `PLAN.md`** (AGENTS never-6).
- No new dependency, no page change, no commit to `docs/`.
- `data/labels/biak_labels.gpkg` is not read. If a later version of this script does read it,
  it opens read-only, the way `scripts/label_second_pass.py:49` does.

## Acceptance criteria

- `python scripts/pre_look_staleness.py` writes `data/processed/pre_look_staleness.json` with
  all 23 assessed events and the 8 not-assessed ones, and prints the three tables plus the
  three separate hectare totals.
- The seven events with `pre_lag` p50 above 14 days each appear with a direction label:

  | event | pre_lag p50 (d) | changed_ha |
  |---|---|---|
  | E0371 | 29.1 | 21.85 |
  | E0322 | 28.1 | 36.45 |
  | E0311 | 27.1 | 238.05 |
  | E0079 | 22.6 | 4.97 |
  | E0361 | 18.1 | 45.73 |
  | E0315 | 18.1 | 211.23 |
  | E0373 | 14.1 | 62.38 |

  620.66 ha in total. If the script's own count above 14 days is not seven, or its hectares do
  not match, that disagreement with this task file is itself worth reporting rather than
  quietly matching.
- `python -m pytest tests/` passes. Run it with the `geolibre` conda environment's interpreter,
  `C:/Users/User/.conda/envs/geolibre/python.exe`; `.venv` lacks geopandas and its test count
  differs, which is not a result. The suite was 235 passed on 2026-10-21.
- `python scripts/render_check.py` passes unchanged. It currently skips because playwright is
  not installed in either environment; that skip is pre-existing and is not to be fixed here.
- `git status` shows nothing under `docs/` touched.
- One commit for the script, its test and the JSON.

## Out of scope

- Re-running `src/burned_area_gee.py`, with a different `pre_days`, a different `cs_min`, or
  anything else. No Earth Engine call at all.
- Exporting the per-pixel `pre_lag` raster. It would replace the percentile estimate with the
  real distribution and it needs a credentialled run; if the percentile estimate turns out to
  be too coarse to separate the two directions, say so and stop, rather than reaching for GEE.
- Changing any published figure: F11's 2,415 ha, F20 to F24, or anything in `docs/`.
- `scripts/label_accuracy.py`, Task 26, Task 25 Part B, the fuel map, the September 2026
  episode polygon.
- The post side. `post_lag` p50 maxes out at 12.4 days with no event above 14, so there is
  nothing to chase there; report it as a clean negative rather than widening the test until
  something appears.

## Do not write the finding

As with Tasks 17 and 19 to 27. Put the tables in the final message; the `FINDINGS.md` entry is
written at review.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open. In particular: how the footprint union was
built, whether `first_seen_utc` or `first_seen_wit` anchors the pre look date, what the script
does when `pre_lag` p50 and p90 put an event in different directions, what it does when an
event has no prior detection at all, and how an event whose nearest recurrent site is far away
but whose `recurrent_share` is high is reported.

State the three hectare totals separately and resist combining them. If no assessed event falls
into `scar_in_pre`, that is a clean negative result and it removes image staleness as an
explanation for the omission the labels keep showing — report it as such.
