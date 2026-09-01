# Task 13 — Does the July 2026 NDMI excess appear on Aqua as well?

PLAN.md §2.4 and §14. Read `tasks/12-vegetation-controls.md` and its result first, then
`src/vegetation_controls_gee.py`. This task asks one question of a second sensor. It does
not revisit the first.

## Do not overwrite anything tasks 11 and 12 produced

`docs/data/vegetation.json` and `docs/data/vegetation_controls.json` are committed data,
one of them behind a live panel. This task writes a **new** file,
`docs/data/vegetation_aqua.json`, and leaves both alone. `git status` after the run must
show them unmodified. No panel is edited.

## The situation you are walking into

Task 11 found that MODIS NDVI and NDMI over the AOI track composite quality rather than
the surface: July NDVI correlates with its own good-pixel share at r = 0.965 (n = 26).
July 2026 — the driest July in the 46-year CHIRPS record — holds the highest July NDVI of
the record, and controlling for quality dissolves that NDVI excess entirely.

The NDMI excess did not dissolve. Task 12 added aerosol loading and observation geometry
as controls and predicted July 2026 out of sample:

```
                          in sample        out of sample (fitted on the other 25 Julys)
base (quality only)       z +1.90          -
+ aerosol (either)        z +1.84 / +1.60  -
+ view zenith             z +1.76          +2.80 sd
+ solar zenith            z +0.56          +1.76 sd
all four controls         z +0.51          +1.64 sd
```

Aerosol is out: July 2026 has the lowest climatology-fallback share of all 307 months, so
the driest July also had the best-retrieved atmosphere in the record. The smoke arrived in
August.

Solar zenith looks like it explains the year, and does not. July 2026 sits at 100% of the
July solar-zenith range with leverage h = 0.683, and removing it halves the coefficient it
is then judged against (+0.00084 to +0.00045 per degree). Out of sample the excess comes
back at +1.64 sd under all four controls.

The reason solar zenith is at the edge of its range is not weather. July solar zenith over
the AOI sat between 29.6° and 32.8° from 2001 to 2022, then went 36.4°, 41.0°, 47.7°,
54.6° — a monotone, accelerating rise. That is Terra's overpass time drifting earlier
since orbit maintenance ended, not anything about Biak.

So the open question has exactly the shape this task tests: **the one surviving control is
a Terra-specific instrument artifact, and it is confounded with time.** Aqua carries the
same instrument on a different orbit whose drift runs the other way. If July 2026 is
anomalously moist on Aqua too, a Terra-specific drift cannot be the explanation.

## Write down what each outcome means before you run it

Put this in the script's printed output and in your final message, decided in advance:

- **Aqua shows a comparable July 2026 excess** (out-of-sample, against Aqua's own controls,
  same direction and roughly the same magnitude in sd): Terra orbit drift is out. What
  remains is that the canopy did not dry, and the water balance describes the surface
  rather than the tree crowns. This is the informative outcome.
- **Aqua shows no excess:** this does **not** establish that Terra drift caused it, and you
  must not write that it does. Aqua crosses in the early afternoon and Terra in the
  morning; canopy water content, illumination and cloud field all differ by time of day,
  so a disagreement has at least two explanations and this design cannot separate them. The
  honest report is that the sensors disagree and why that is not decisive.
- **Aqua's own July series is too short or too gappy to fit:** say so and stop. MYD09A1
  begins mid-2002, so there are around two fewer Julys than Terra has, and n was already
  the binding constraint.

The asymmetry is the point: agreement is strong evidence, disagreement is weak evidence.
Deciding this after seeing the numbers is how a result gets talked into existence.

## What to build

### `src/vegetation_aqua_gee.py`

Run by hand with Earth Engine credentials:

    python src/vegetation_aqua_gee.py <google-cloud-project-id>

Import the helpers from `src/vegetation_gee.py` and `src/vegetation_controls_gee.py`
rather than copying them — the AOI read, `land_mask`, the month list, the
one-`getInfo`-per-series pattern, `ols`, `july_rows`, and the report with its leave-one-out
step. Same mask, same scale, same reducer, or the two sensors are not comparable and the
comparison is void. Verify every band and collection name against the Earth Engine catalog
before use; the names below are from memory and may be wrong.

Per month, over the same masked land pixels, from the Aqua products:

- `ndmi` — `MODIS/061/MYD09A1`, `(sur_refl_b02 - sur_refl_b06) / (sur_refl_b02 + sur_refl_b06)`.
- `ndmi_good_share` — `MYD09A1` `StateQA` bits 0–1 == 0, the same test task 11 used on
  MOD09A1. Confirm the bit layout is identical between the two products rather than
  assuming it.
- `aerosol_high_share` and `aerosol_climatology_share` — `StateQA` bits 6–7, values 3 and 0,
  as in task 12.
- `view_zenith_deg` and `solar_zenith_deg` — from `MODIS/061/MYD13A1`, scale 0.01.
- `ndvi` and `ndvi_good_share` — from `MYD13A1` (`SummaryQA <= 1`), so the NDVI half of the
  task 11 result gets the same second opinion for free.

Write `docs/data/vegetation_aqua.json` in the same shape as the two existing files —
`monthly`, `coverage`, `sources` — with its own month list, which starts where MYD09A1
starts and not where `vegetation.json` starts.

### The analysis

Run the task 12 July report on the Aqua series, **fitted entirely within Aqua**: Aqua NDMI
on Aqua's good-pixel share and Aqua's own aerosol and geometry controls, with the same
leave-2026-out prediction. Print Terra's figures beside Aqua's for reading, and print
Aqua's July solar-zenith series so the direction of its drift is visible next to Terra's.

Do not pool the two sensors into one regression, do not compare absolute NDMI between them,
and do not difference them. Instrument calibration, spectral response and degradation
differ; only each sensor's departure within its own record is comparable, and even that is
a comparison of two numbers, not a test.

## Constraints

- **No data file without data.** If Earth Engine is unreachable or credentials are missing,
  the exception propagates and nothing is written. No placeholder, no synthetic series, no
  zero-filled file, no generator of stand-in values. A previous hand-off shipped 300 months
  of invented MODIS numbers to a public page because the service could not be reached.
- **No page change.** The panel says nothing about Aqua until there is something settled to
  say. Note in your final message what it would have to say if the result holds.
- **Never edit `PLAN.md`** (AGENTS never-6), and do not edit `tasks/11-*.md` or
  `tasks/12-*.md`.
- **Do not touch** `docs/data/vegetation.json`, `docs/data/vegetation_controls.json`, or the
  drought files.
- Plain arithmetic for the fit; no statistics package (AGENTS never-7). The solver exists.

## Acceptance criteria

- `python src/vegetation_aqua_gee.py <project>` writes `docs/data/vegetation_aqua.json` and
  prints: the Aqua month range and coverage dates, the Aqua July solar-zenith series beside
  Terra's, every model with coefficients, `n`, residual sd, July 2026 in-sample residual and
  rank, leverage, and the leave-2026-out prediction with its error in sd.
- The pre-registered reading of each outcome is printed before the numbers.
- `git status` after the run shows `vegetation.json` and `vegetation_controls.json`
  unmodified.
- A pytest asserts the Aqua file's internal consistency (shares in [0, 1], zenith angles
  physically possible, months dense and sorted, month range consistent with MYD09A1's
  start), skipping cleanly when the file is absent, as the task 11 and 12 tests do.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes unchanged.
- One commit whose message states whether the sensors agree, and what that does and does
  not settle.

## Out of scope

- Any BRDF or orbit-drift correction. Reading the geometry is not correcting for it.
- Sentinel-2, VIIRS vegetation products, or any third sensor.
- Cirrus and cloud-shadow bits.
- Pooling, differencing or harmonising the two sensors.
- Any statement connecting the residual to fire risk or to the hotspots.

## What this task does not settle, and should be said out loud when you finish

Terra's drift affects every Terra product this repository uses, not only the vegetation
indices. `MODIS/061/MOD16A2` is the evapotranspiration behind the water balance in PLAN §14
and behind the claim that July 2026 is the only month in the record that lost water. If
overpass time has moved by nearly two hours over four years, an ET series that ends in a
record high deserves the same question this task asks of NDMI. That is not this task —
name it in your final message so the owner can decide whether it becomes the next one.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — collection and band names as verified
today, the bit layout check, the scale you reduced at, Aqua's month range and how many
Julys it actually yielded, and which of the three pre-registered outcomes the numbers
landed on.
