# Task 14 — Does the water balance in F1 survive Terra's orbit drift?

Read `FINDINGS.md` F1 and F4 first, then `tasks/13-aqua-cross-check.md` and
`src/vegetation_aqua_gee.py`. This task asks the question F1 leaves open against itself.

## Why this one matters more than tasks 12 and 13

F1 is **published**. The drought panel on the live dashboard states that July 2026 is the
only month in the MOD16A2 record for this AOI with a negative water balance, and that
evapotranspiration rose to its highest value in the record while the rain failed. That is
the strongest single claim the product makes about the 2026 season.

`MOD16A2` is a Terra product. F4 established that Terra's overpass has drifted since 2022 —
July solar zenith over the AOI went from about 31° to 54.6° in four years — and that any
multi-year trend from a Terra product after 2022 is confounded with it. A record high at the
end of a drifting record is exactly the shape an artifact takes.

Tasks 12 and 13 asked this of NDMI, which was never published. This asks it of a number a
reader can see today.

## Do not overwrite anything

Write a **new** file, `docs/data/drought_et_check.json`. `docs/data/drought.json`,
`docs/data/vegetation.json`, `docs/data/vegetation_controls.json` and
`docs/data/vegetation_aqua.json` are all committed data and are out of bounds. `git status`
after the run must show every one of them unmodified.

## Establish the record length before you plan the analysis

`src/drought_gee.py` sets `SERIES_START = "2021-01-01"` with the comment that MOD16A2 v061
begins there. **Verify that against the catalog today rather than trusting it.** The answer
decides which analysis is possible, and getting it wrong wastes the whole task:

- **If the record really begins in 2021**, there are about six Julys. Six is not enough to
  fit the models tasks 12 and 13 used, and no amount of care makes it enough. Say so, do not
  fit them, and fall back to the cross-sensor comparison and a plain description of the
  series. A refusal to fit is a valid and useful result here.
- **If the record begins in 2001**, you have roughly 26 Julys and the task 12 and 13
  machinery applies directly: import `ols`, `july_rows` and the report with its
  leave-one-out step rather than writing new ones. In that case also note in your final
  message that `drought_gee.py` has been starting its series 20 years late, which is a
  separate defect worth its own task.

Print which case you are in before any other output.

## What to build

### `src/drought_et_check_gee.py`

Run by hand with Earth Engine credentials:

    python src/drought_et_check_gee.py <google-cloud-project-id>

Import the helpers from the existing scripts — the AOI read, `land_mask`, the month list,
the one-`getInfo`-per-series pattern, and the solver. Same mask, same 500 m scale, same
reducer as `drought_gee.py`, or the new series cannot be compared with the published one.
Verify every collection and band name against the catalog before use; the names below are
from memory and may be wrong.

Compute, per month over the same masked land pixels:

- `et_terra_mm` — `MODIS/061/MOD16A2` `ET`, 8-day totals in 0.1 mm summed over the month,
  exactly as `drought_gee.py` does it. This must reproduce `drought.json` month for month.
  If it does not, stop and report the discrepancy; everything after depends on it.
- `et_aqua_mm` — `MODIS/061/MYD16A2`, the Aqua counterpart, same treatment. Check whether it
  carries 2026 data at all before building anything on it. **Do not substitute a gap-filled
  product.** F1 records that `MOD16A2GF` held no 2026 data; the same trap exists on the Aqua
  side.
- `et_qc_good_share_terra` and `et_qc_good_share_aqua` — the share of land pixels passing
  each product's own quality band. State in a comment which bits or values you read and what
  they mean. Every other panel in this project publishes an index beside the share of pixels
  that actually saw the ground; this one should be no different.
- `solar_zenith_deg` and `view_zenith_deg` — copy the Terra geometry series already computed
  in `docs/data/vegetation_controls.json` rather than re-fetching, and the Aqua series from
  `docs/data/vegetation_aqua.json`. Say in the file's `sources` block that they were taken
  from there.

### The comparison that answers the question

Three outputs, in this order:

1. **Do the two sensors agree about July 2026?** Report each sensor's July 2026 ET, its rank
   among that sensor's Julys, and its departure from that sensor's own July mean. Compare
   departures within each record, never absolute values between the two — the instruments,
   their calibration and their overpass hours differ.
2. **Does the headline claim survive?** Recompute the monthly water balance using Aqua ET
   against the same CHIRPS precipitation, and report whether July 2026 is still the only
   month in the record with P − ET below zero, and by how much. This is the number the
   dashboard is publishing.
3. **If and only if the record is long enough**, run the task 12 report on ET: regress on the
   quality share, add the geometry controls one at a time and together, and predict July 2026
   out of sample with the coefficient shift and leverage printed, exactly as tasks 12 and 13
   do. Otherwise print why you are not fitting.

## Write down what each outcome means before you run it

Print this before the numbers, and repeat it in your final message:

- **Both sensors show July 2026 as an extreme ET month, and the negative balance holds under
  Aqua:** F1 survives. The claim is about the atmosphere and the land, not about Terra.
- **Aqua shows no such extreme, or the balance is not negative under Aqua:** F1's headline is
  in question. Do not edit the panel — but put this at the **top** of your final message as a
  correction awaiting the owner's decision, because a live page is asserting it.
- **Aqua has no usable 2026 data:** the cross-check cannot be run. Report the geometry
  control result if the record allows one, and state plainly that the question is open. Do
  not present an unrun test as a passed one.

One caution that applies to every branch. `MOD16A2` is not a reflectance index: it is a
Penman-Monteith model driven by reanalysis meteorology together with MODIS inputs. The
meteorological forcing does not move with the overpass; the MODIS inputs do. So the
contamination path is narrower here than it was for NDMI, and a Terra–Aqua difference has a
model-input explanation as well as a geometric one. Say which parts of the product could
carry drift and which could not, rather than treating ET as if it were a band.

## Constraints

- **No data file without data.** If Earth Engine is unreachable or the credentials are
  missing, the exception propagates and nothing is written. No placeholder, no synthetic
  series, no zero-filled file, no generator of stand-in values.
- **No page change.** Report what the drought panel would have to say under each outcome.
- **Never edit `PLAN.md`** (AGENTS never-6).
- **Append the result to `FINDINGS.md` as F6** (AGENTS always-6): a dated entry naming this
  script and its commit, never rewriting F1. If the result contradicts F1, F6 says so and
  names what it supersedes; F1 stays as written.
- Plain arithmetic for any fit; no statistics package (AGENTS never-7).

## Acceptance criteria

- `python src/drought_et_check_gee.py <project>` writes `docs/data/drought_et_check.json`,
  prints the record-length case it found, the pre-registered readings, the per-sensor July
  comparison, the recomputed water balance under Aqua ET, and either the out-of-sample models
  or the reason there are none.
- The Terra ET series in the new file matches `drought.json` month for month over the
  overlap; a test asserts this.
- A test asserts the new file's internal consistency — months dense and sorted, shares in
  [0, 1], no month invented beyond each product's coverage — and skips cleanly when the file
  is absent, as the task 11 to 13 tests do.
- `git status` shows the four existing data files unmodified.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes unchanged.
- One commit for the code and data, one for the `FINDINGS.md` entry, matching how F1 to F5
  are recorded.

## Out of scope

- Any correction for drift. Measuring it is not correcting it.
- Changing `SERIES_START` in `drought_gee.py` or regenerating `drought.json`, even if you
  find the start date is wrong. Report it; it is its own task.
- Gap-filled ET products, alternative ET datasets, SPI, KBDI, FWI.
- Any statement connecting evapotranspiration to fire risk or to the hotspots.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — the verified collection start dates, the
quality bits you read, the scale you reduced at, how many Julys each sensor actually yielded,
and which pre-registered outcome the numbers landed on.

If F1's published claim is in question, that goes in the first line of your message, not the
last.
