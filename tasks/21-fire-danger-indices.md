# Task 21 — Fire danger indices, and whether they rank burning days (PLAN.md Phase 5, step 1)

PLAN.md Phase 5 step 1: *"Publish daily FWI and KBDI for the AOI ... defensible,
explainable, internationally standard, and requires no training data. For most of this
project's actual utility, this is sufficient."*

This task does the first half: it **computes** the Canadian Fire Weather Index system and
the Keetch-Byram Drought Index for the AOI from 2023-09-01 to the latest weather available,
and **scores** them against the detection record the same way Task 17 scored the
climatology. Publishing them (dashboard panel, brief, cron) is a later task, and it happens
only if this one shows the numbers mean something here.

It does not build a model (Phase 5 step 3), and it does not change the dashboard, the
brief, the cron or anything under `docs/`.

## Read first

- **Drought is context, never cause** (PLAN.md section 14). A high index says fuel and
  weather made burning easier. It never says burning happened, will happen, or why. No
  field, caveat or sentence may say "fire risk caused", "predicted fire", or name a person.
- **These indices were built for Canadian conifer forest.** Biak is a tropical limestone
  island with a burning regime driven by land use. The honest outcome may be that FWI ranks
  burning days no better than the calendar does. That is a result; report it plainly.
- F12 (`FINDINGS.md`) is the bar: the detection climatology from Task 17, which ranks well
  and calibrates badly. `src/baseline.py` holds the functions this task reuses.

## Weather: ERA5-Land from Earth Engine

`ECMWF/ERA5_LAND/HOURLY`, run by hand like the other `*_gee.py` scripts, in the `geolibre`
conda environment, never from the cron.

**Before writing the fetch, list the asset's band names and read its catalogue page, and
state in a comment what you found for each of these.** Do not assume them:

- the 2 m temperature and 2 m dewpoint bands (Kelvin);
- the 10 m `u` and `v` wind bands (m/s);
- the **hourly** precipitation band (metres), not the band accumulated since 00 UTC, and
  **whether an hourly value stamped `t` covers the hour ending at `t` or starting at `t`**.
  The rain sums below depend on it;
- the latest hour the asset holds on the day you run it. Days after it are absent, not
  dry (AGENTS never-2).

**Cells.** ERA5-Land is land-only at 0.1°. Use the native grid: the cells whose square
overlaps the union of the `admin_polygon` features (shapely, offline), keeping only those
where the asset returns values. State how you established where the native cell edges lie.
Record the cell list and count in the output. Biak, Supiori and Numfor are small; expect a
few dozen cells and say how many.

**Per cell, per WIT day D**, computed server-side so the response stays small:

| value | definition |
|---|---|
| `t_noon_c`, `rh_noon`, `wind_noon_kmh` | at 12:00 WIT = 03:00 UTC on D |
| `rain_24h_mm` | the 24 hourly precipitation values covering 03:00 UTC D−1 to 03:00 UTC D, summed |
| `t_max_c` | the maximum hourly 2 m temperature over the WIT day D (15:00 UTC D−1 to 14:00 UTC D) |

- Relative humidity from temperature and dewpoint (°C) by the Magnus form (Alduchov and
  Eskridge 1996): `RH = 100 · exp(17.625·Td/(243.04+Td)) / exp(17.625·T/(243.04+T))`,
  capped at 100.
- Wind speed `sqrt(u² + v²)` in m/s × 3.6 gives km/h. It is 10 m wind, which is what FWI
  expects.
- Noon local time is the FWI standard observation time. Say in a comment that WIT (UTC+9)
  noon is 03:00 UTC, and that solar noon at 136°E falls within about 10 minutes of it.

**Persist before computing** (AGENTS always-2): one JSON per calendar month under
`data/raw/era5land/`, exactly as returned, `ERA5L_<YYYY-MM>.json`. They are small; track
them (add them to the allowlist in `.gitignore` the way `data/raw/metar/` is). A run
without `--fetch` reads them and fetches nothing.

**If Earth Engine cannot be reached, refuses a request, or returns no values for a month the
span covers: exit non-zero, name the month, and write nothing for it. No placeholder file,
no synthetic weather, no generator of stand-in values**, not to make a test pass, not to fill
a gap, not labelled as synthetic either. A cell-day with a missing input gets no index for
that day and every later day of the same cell until the spin-up rule below restarts it.
Report how many cell-days that affected.

## The indices

Implement both in the standard library and numpy, **no `cffdrs` or other fire-weather
package** (AGENTS never-7).

**FWI system** (Van Wagner 1987; equations as in Van Wagner and Pickett 1985): FFMC, DMC,
DC, ISI, BUI, FWI, each day from the previous day's FFMC, DMC and DC.

- **Latitude adjustment.** The standard day-length factors are for Canada. Between 10°S and
  10°N, use the constant equatorial values: DMC effective day length `Le = 9.0` and DC
  day-length factor `Lf = 1.39` every month (Lawson and Armitage 2008; the same rule as the
  `cffdrs` package's latitude adjustment). Put both in config with that citation. Biak sits
  near 1°S.
- **Start-up and spin-up.** Start every cell on 2022-09-01 at FFMC 85, DMC 6, DC 15, run
  continuously (the tropics have no overwintering), and **discard everything before
  2023-09-01**. DC has a memory of months; a year of spin-up removes the start values'
  influence. State the spin-up in config. A cell restarted after a missing day spins up
  again from its restart day for the same length before its values count.

**KBDI** (Keetch and Byram 1968), in its metric form, Q in mm from 0 to 203.2:

```
dQ = (203.2 − Q) · (0.968 · exp(0.0875 · Tmax + 1.5552) − 8.30)
     / (1 + 10.88 · exp(−0.001736 · R)) · 1e-3
```

with `Tmax` the day's maximum temperature (°C), `R` the cell's mean annual precipitation
(mm), and `dQ` floored at 0. Rain reduces Q only by the **net** rain: the first 5.08 mm
(0.2 inch) of each run of consecutive rainy days is intercepted, and everything after it
reduces Q mm for mm, floored at 0. `R` is the 1991-2020 ERA5-Land mean annual total per
cell, computed by the same fetch and stored in the raw files; the period goes in config.
Start KBDI at 0 on 2022-09-01, inside the same spin-up.

**AOI value per day:** the mean over the land cells with a valid value that day, plus the
count of cells behind it.

Also compute **`days_since_rain`**: whole days since the AOI-mean `rain_24h_mm` last reached
`rain_day_mm` (1.0). It is the naive comparator: if FWI cannot beat a count of dry days, it
adds nothing a reader could not work out alone.

## Scoring: does the index rank burning days?

The unit is the **AOI-day**. Weather varies little across 70 km, so a daily index speaks
to *when*, and the climatology already speaks to *where*. For each observed WIT day
(`baseline.observed_days`, the same three-instrument rule as Task 17):

- `y = 1` when at least one detection on that WIT day is on land, from the fixed
  constellation in config `baseline.constellation`, **and not flagged `recurrent_site`**. PLAN.md
  section 5 item 5: persistent heat sources are not driven by the weather. Report how many
  positive days that exclusion removes.
- Positive days when this task was written: 24 in 2023 (from 1 September), 39 in 2024, 37 in
  2025, 65 in 2026, before the `recurrent_site` exclusion.

**Leave one calendar year out**, as Task 17. For each year Y with observed days, score these
against y on Y's observed days that have an AOI index value:

- each of FFMC, DMC, DC, ISI, BUI, FWI, KBDI and `days_since_rain`, as raw scores. These need
  no training;
- the **AOI-day climatology**, fitted on the other years: the share of observed training
  days within `baseline.doy_half_window` of the day-of-year with `y = 1`. Reuse
  `baseline.day_of_year_365` and `baseline.doy_window`; it is the same rule as
  `baseline.climatology` with the whole AOI as one cell;
- the **base rate**, Y's positive share: the average precision a random ranking scores.

Report **average precision** only, with `baseline.average_precision` (ties are one
threshold). **No Brier score for the indices.** They are not probabilities, and turning them
into probabilities is fitting a model, which is Phase 5 step 3. Say so in the output.

**Pre-registered reading, per index, per fold:** `above_climatology` when its AP exceeds
the climatology's, otherwise `not_above_climatology`. Also `above_base_rate` the same way.
Report the counts across folds. Do not combine indices, choose thresholds, or tune anything
after seeing the results. If you think the reading is wrong, say so and leave it.

**2026 will dominate, and it must not be pooled away.** August 2026 lies far outside the
2023-2025 record (PLAN.md 11.1). Report every fold separately with its observed-day and
positive-day counts, and do not average APs across folds.

## Context tables

- Per calendar month: the AOI-mean of FWI, DC and KBDI (median and 90th percentile) and the
  positive-day count. This is the seasonal picture a reader will ask for first.
- For WIT days 2026-08-15 to 2026-08-31: every index, the day's positive flag and the
  detection count. This is the episode the project exists to explain.

## Configuration

```yaml
fire_danger:
  spin_up_start: "2022-09-01"
  score_start: "2023-09-01"
  start_codes: {ffmc: 85, dmc: 6, dc: 15}
  dmc_day_length: 9.0            # Lawson and Armitage 2008, 10S-10N
  dc_day_length_factor: 1.39     # same
  kbdi_rain_interception_mm: 5.08
  kbdi_mean_rain_period: [1991, 2020]
  rain_day_mm: 1.0
```

Every value gets a comment giving its reason. AGENTS always-5: nothing hard-coded in the
module.

## Output

`src/fire_danger.py`, runnable as `python src/fire_danger.py [--fetch <gcp-project>]`. The
`ee` import lives inside the fetch path only, so the offline part and its tests run in
`.venv` without Earth Engine. It writes `data/processed/fire_danger.json`, sorted keys,
indent 1, no timestamp, added to the `data/processed/` allowlist. It holds:

- the parameters, the cells used, the weather span and the raw files read, the latest ERA5-
  Land hour available at fetch time, and the missing cell-day count;
- the daily AOI series from `score_start`: date, each index, `days_since_rain`,
  `rain_24h_mm`, `t_noon_c`, `rh_noon`, `wind_noon_kmh`, the cell count, and `y`;
- the per-fold scores and readings, and the context tables;
- a `caveats` list, verbatim:
  - "FWI and KBDI describe how weather has dried the fuel. They say nothing about whether
    anyone burned land, or why (PLAN.md sections 8 and 14)."
  - "The FWI system was built for Canadian conifer forest; the equatorial day-length
    adjustment is applied, but it has not been calibrated for this island's fuels."
  - "ERA5-Land is a reanalysis at 0.1 degree, about 11 km, over a few dozen land cells. It is
    not a station record."
  - "Average precision measures ranking only. The indices are not probabilities, and no
    calibration is claimed."

Print the per-fold AP table and the August 2026 table to stdout.

## Do not write the finding

**Do not add an entry to `FINDINGS.md`,** as in Tasks 17, 19 and 20. It is written at
review. Put the fold table, the readings and the cell count in your final message.

## Check

`tests/test_fire_danger.py`, offline, synthetic inputs built inside the test. The raw
ERA5-Land files may be read for one real-month check once committed, but nothing fetches.

1. **The published FWI test day.** From FFMC 85, DMC 6, DC 15, with T 17 °C, RH 42%, wind
   25 km/h, rain 0, and the **Canadian April** day-length factors (`Le = 12.8`, `Lf = 0.9`)
   passed as arguments: FFMC 87.69, DMC 8.55, DC 19.01, ISI 10.85, BUI 8.49, FWI 10.10, each
   to within 0.01. This checks the equations, which is why the factors are arguments and not
   read from config inside the functions.
2. Rain thresholds: FFMC ignores 0.5 mm, DMC ignores 1.5 mm, DC ignores 2.8 mm; just above
   each, the code falls.
3. KBDI: a hot dry day raises Q; Q never exceeds 203.2 or drops below 0; a rain run of 3, 2
   and 4 mm on consecutive days, with Tmax low enough that drying is 0, reduces Q by 3.92
   mm in total (9 − 5.08), not 9.
4. `days_since_rain` resets on a day at `rain_day_mm` and counts up otherwise.
5. The rain window: an hourly value stamped inside the 03:00-to-03:00 UTC window counts for D;
   one just outside it counts for D + 1 or D − 1, under the stamping convention you found.
6. A missing input day gives no index for that cell until its re-spin-up is complete.
7. `y` excludes a day whose only detection is a `recurrent_site`.
8. The leave-one-year-out climatology never sees year Y's days.
9. The same raw files give byte-identical `fire_danger.json`.

## Out of scope

- The dashboard, the brief, the cron, `docs/`. Publishing is the next task, if this one
  earns it.
- The Copernicus CEMS fire danger product (CDS key; forecast rather than reanalysis). It is
  the obvious source for daily publishing and belongs to that later task.
- Any model, any combination of indices, any threshold, Phase 5 step 3.
- Per-island or per-cell scoring. The AOI-day is the unit here.
