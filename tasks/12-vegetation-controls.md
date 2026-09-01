# Task 12 — Aerosol and view geometry as controls on the July NDMI residual

PLAN.md §2.4 and §14. Read §14 first, then read `src/vegetation_gee.py` and
`docs/data/vegetation.json`, which task 11 produced. This task extends that work by one
question. It does not redo it.

## Do not overwrite anything task 11 produced

`docs/data/vegetation.json` is published data behind a live panel. This task writes a
**new** file, `docs/data/vegetation_controls.json`, and leaves the old one untouched. If
your change would rewrite, re-sort, re-round or regenerate `vegetation.json`, you have
misread the task. The same goes for the panel: task 11's panel is not edited here.

## The situation you are walking into

Task 11 published NDVI and NDMI for the AOI, each beside the share of land pixels passing
its product's cloud test. The correlation between index and quality share came out
r = 0.965 for July NDVI (n = 26) and r = 0.802 for July NDMI. July 2026 — the driest July
in the 46-year CHIRPS record, and the only month in the MOD16A2 record with a negative
water balance — holds the highest July NDVI of the 26 years.

Regressing each July index on its own good-pixel share and looking at what is left over:

```
NDVI July   2026 residual  -0.0024   z -0.16   rank 11 of 26
NDMI July   2026 residual  +0.0206   z +1.90   rank 26 of 26
```

So the NDVI record dissolves once observation quality is accounted for: an ordinary July
that was simply seen better. The NDMI excess does not dissolve. After the same control,
July 2026 is still the moistest July of the 26.

That residual is the question. Physically it runs the wrong way — a canopy losing water
should raise SWIR reflectance (`sur_refl_b06`) and *lower* NDMI. Three explanations are
open, and two of them are testable with bands the pipeline already downloads past:

1. **Smoke aerosol.** August 2026 is the hotspot outlier of the record. The good-pixel
   test in task 11 reads `StateQA` bits 0–1, which encode cloud state only. Aerosol
   loading is a different field in the same bitmask and has never been looked at. Heavy
   smoke defeats the atmospheric correction, and the SWIR band is where that shows.
2. **Sun–sensor geometry.** A dry-season rise in MODIS greenness over tropical forest is a
   known and contested result; the leading explanation for the Amazonian case is view and
   illumination geometry rather than canopy change. MOD13A1 carries the per-composite view
   angle. It has never been read here either.
3. **The canopy really did not dry out.** Deep-rooted tropical forest can hold canopy water
   through a one-month rainfall deficit. If this is what is left after (1) and (2) are
   controlled, then the water balance describes the surface and not the canopy, and that is
   a finding about what P−ET can and cannot stand in for.

This task tests (1) and (2) so that (3) is what remains, or is not.

## What to build

### `src/vegetation_controls_gee.py`

Run by hand with Earth Engine credentials, like `src/vegetation_gee.py`:

    python src/vegetation_controls_gee.py <google-cloud-project-id>

Import the helpers from `src/vegetation_gee.py` rather than copying them — the AOI read,
`land_mask`, the month list, the one-`getInfo`-per-series pattern. Same mask, same scale,
same reducer as task 11, or the new series is not comparable with the old one and the whole
exercise is void. Verify every band name against the Earth Engine catalog before you use
it; the names below are from memory and may be wrong.

Per month, over the same masked land pixels:

- `aerosol_high_share` — from MOD09A1 `StateQA`, the aerosol quantity field (bits 6–7,
  where 3 = high). The share of land pixels at that level. State in a comment which bits
  you read and what the values mean, as task 11 did for bits 0–1.
- `aerosol_climatology_share` — the same field at value 0, which means the correction fell
  back to a climatological aerosol estimate because it could not retrieve one. That is a
  different kind of bad, and worth separating.
- `view_zenith_deg` — the mean of the MOD13A1 view zenith band over the same pixels, in
  degrees (the band is stored in hundredths; apply the scale).
- `solar_zenith_deg` — same, from the solar zenith band. Illumination is half of the
  geometry argument and costs one more band.

Write `docs/data/vegetation_controls.json` with a `monthly` array keyed by the same
`month` strings as `vegetation.json`, plus a `coverage` block and a `sources` block in the
same shape task 11 used.

### The residual analysis, in the same script

After writing the file, read `docs/data/vegetation.json` back and, for July only, report:

- the residual of NDMI after regressing on `ndmi_good_share` alone (this reproduces the
  numbers above, and is your check that you have the same series);
- the residual after adding each new control **one at a time**;
- the residual with all controls together.

Report for each model: the coefficient on each term, `n`, the residual standard deviation,
and where July 2026 sits in the residual ranking. Plain `statistics` and arithmetic — no
new dependency (AGENTS never-7). A small least-squares solve for three or four predictors
is twenty lines; do not add a stats package for it.

**Report the leverage of July 2026 in every model, and say it plainly.** In the
single-control fit, its good-pixel share of 0.832 is the maximum of the July range
(0.299–0.833). The point whose residual the whole question rests on sits at the edge of the
predictor range, where a linear fit is least constrained. If it is also at the edge of the
new predictors, the model is being asked about a corner of the data it barely covers, and
that must be stated in the output — not discovered later by a reviewer. With n = 26, four
predictors is already generous. Do not add a fifth to improve a fit.

## Constraints

- **No data file without data.** If Earth Engine is unreachable or the credentials are
  missing, the script exits with the error and writes nothing. Do not write a placeholder,
  a synthetic series, a zero-filled file, or a generator of stand-in values. A previous
  hand-off shipped 300 months of invented MODIS numbers to a public page because the
  service could not be reached; an absent file is the correct output of a failed fetch.
- **No page change.** Task 11's panel stays as it is. If the controls change the reading,
  that is a conversation with the owner, not an edit. Note in your final message what the
  panel would have to say if the result holds.
- **Never edit `PLAN.md`** (AGENTS never-6). §14 records the exploratory correlations
  +0.883 and +0.591, which task 11's committed run superseded with 0.965 and 0.802; that
  revision is already pending with the owner. Add nothing to it yourself.
- **Do not touch `docs/data/vegetation.json`,** `src/vegetation_gee.py`'s outputs, or the
  drought files.
- Whole-word ban on "clear" and "safe" anywhere in `docs/index.html` — not relevant if you
  change no page, and a reason not to.

## Acceptance criteria

- `python src/vegetation_controls_gee.py <project>` writes `docs/data/vegetation_controls.json`
  and prints every model with its coefficients, `n`, residual standard deviation, July 2026
  rank, and July 2026 leverage.
- `git status` after the run shows `docs/data/vegetation.json` unmodified.
- A pytest asserts the controls file is month-aligned with `vegetation.json` (same month
  strings over the overlap, none invented), that every share is in [0, 1], and that the
  zenith angles are in a physically possible range. Skip cleanly if the file is absent, the
  way `test_vegetation_json_internal_consistency` does.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes unchanged.
- One commit whose message states what the residual did under each control.

## Out of scope

- Cirrus and cloud-shadow bits. They are in the same bitmask and they are a third question.
- Sentinel-2 anything.
- A BRDF correction. Reading the geometry is not correcting for it, and a corrected index
  is a research product, not a monitoring one.
- Any statement about fire risk, or any causal claim connecting the residual to the
  hotspots.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — the exact bits and band names you read,
the scale you reduced at, how you handled months with no usable composite, and the
leverage caveat in whatever form the numbers ended up taking.

State plainly which of the three explanations the result supports, including the case where
the answer is that n = 26 cannot separate them.
