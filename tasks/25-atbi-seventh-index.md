# Task 25 — ATBI as a seventh index, and the first index comparison with a reference

F7 compared six burned-area indices and could only judge them by where they are certainly
wrong, because no reference data existed on 2026-09-03. It chose NBR+ on that basis and
Phase 4 was built on it. F20 then measured the product that followed and found it
over-claims: 819 ha mapped against 614 ha corrected, roughly a quarter too much, with the
commission concentrated at polygon edges. F22 and F23 revised the interval and the method
but not the direction of the error.

**Two things have changed since F7.** There are now 114 judged label boxes in
`data/labels/biak_labels.gpkg`, so an index can be scored against something other than its
own false alarms. And a 2025 index exists that was designed against exactly the error F20
measured: the Automated Temporal Burn Index.

> Bilal, M. (2025). *The automated temporal burn index (ATBI) for accurate and scalable
> burned area mapping.* International Journal of Applied Earth Observation and
> Geoinformation, 144, 104866. https://doi.org/10.1016/j.jag.2025.104866

The index multiplies NBR by the SWIR/NIR ratio, so a pixel scores high only when both
spectral conditions of burning hold at once — NIR down and SWIR up. Cloud shadow (both
down) and phenological change (NIR up, SWIR down) fail one of them and are suppressed. The
author reports precision 0.919 against dNBR's 0.729 and F1 0.946 against 0.836 on the 2024
Park Fire. **That is the index author's own figure on one chaparral fire in California, and
it is not evidence about humid tropical Papua.** It is a reason to test the index here. It
is not a result to quote.

This task adds the index and measures it. It does not replace NBR+ anywhere, and it
publishes no map and no area.

## Where the formula comes from, and what may not be copied

The formula was reached through a third-party Google Earth Engine implementation,
`https://github.com/Defani/Kebakaran-Hutan--ATBI---GEE`, read on 2026-10-20.

**That repository carries no LICENSE file, so none of its code may be copied into this
one.** Mathematical formulas are not copyrightable; the 76 lines of JavaScript around them
are. Write the expression from the algebra below, in the idiom of
`src/burn_indices_gee.py`, and take nothing else from it.

There are five further reasons not to follow that implementation even if it were licensed,
and each is a trap this task must avoid:

| what it does | why it fails here |
|---|---|
| `.filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)).mosaic()` | a scene-level filter, then `mosaic()` takes the last image per pixel. `SCL` is never consulted, so no pixel is ever cloud-masked. Over Biak that is fatal, and F7's cloud stratum exists because of it |
| `mosaic()` over a three-month pre window and a one-month post window | no scene pair, so no provenance. Task 15 requires both scene identifiers recorded |
| `B8` for NIR, exported at `scale: 10` | mixes a 10 m band with a 20 m `B12` and resamples the result to 10 m. Everything here is 20 m |
| thresholds 0.20 / 0.27 / 0.66 | inherited from a dNBR convention calibrated in California. Its own README admits this under *Keterbatasan*. This task chooses no threshold at all |
| `SWIR/NIR` with no guard | see **The division** below |

The paper itself is **not** in `References/`. Obtain it before trusting any claim attributed
to it above. If it cannot be obtained, say so in the final message and state plainly that
the formula was taken from the algebra in this task and the third-party README, not from the
source publication.

## The formula, and the sign that will be got wrong

The published index uses the USGS convention, `NBR_usgs = (NIR - SWIR) / (NIR + SWIR)`,
where *low* means burned:

```
ATBI_pub = NBR_usgs * (SWIR / NIR)
dATBI_pub = ATBI_pub(pre) - ATBI_pub(post)            the paper's equation (2)
```

`src/burn_indices_gee.py` follows Alcaras equation (1), `NBR = (B12 - B8A) / (B12 + B8A)`,
where *high* means burned, and its bi-temporal form is **post minus pre**. Both conventions
are inverted relative to the published index, and the two inversions cancel exactly. Define

```
ATBI = NBR * (B12 / B8A)          with THIS file's NBR, so high means burned
dATBI = ATBI(post) - ATBI(pre)    this file's existing bi-temporal form
```

and the result is identical in sign and magnitude to the published `dATBI_pub`, while
staying mutually comparable with the other six indices. Proof, since this is the one place
the task can silently produce a correct-looking sign error:

```
ATBI      = -ATBI_pub
dATBI     = ATBI(post) - ATBI(pre)
          = -ATBI_pub(post) + ATBI_pub(pre)
          = ATBI_pub(pre) - ATBI_pub(post)
          = dATBI_pub                                     as published
```

Check it against the worked example in the third-party README, which uses the published
convention throughout:

```
pre   NIR 0.5, SWIR 0.2    ATBI_pub = +0.17    this file's ATBI = -0.1714
post  NIR 0.1, SWIR 0.3    ATBI_pub = -1.50    this file's ATBI = +1.5
                           dATBI_pub = 1.67    this file's dATBI = +1.671
```

**Bands: `B8A`, not `B8`.** The paper uses Landsat B5 and B7; the Sentinel-2 equivalents at
a single resolution are `B8A` (865 nm, 20 m) and `B12`. Both are already in `BANDS`.

**Scaling does not matter for this index and must still be applied.** ATBI is a product of
two ratios, so it is invariant to the `/10000`. Compute it from `scaled()` anyway, like
every other index in the file, so one code path cannot drift from another.

## The division

`B12 / B8A` divides by near-infrared reflectance, which is exactly what a burned pixel has
least of. Two failure modes follow, and neither can be left to chance:

- **`B8A` at or below zero.** Sentinel-2 L2A surface reflectance is legitimately negative
  over dark water and deep shadow. The ratio then flips sign and the product becomes
  meaningless rather than merely large.
- **`B8A` very small and positive.** The ratio explodes and ATBI is unbounded above.

Do not silently floor the denominator. Mask pixels where `B8A <= 0`, **count them per
stratum, and report the counts**, so a reader knows what share of each stratum ATBI could
not be computed on. If any stratum loses more than a few percent of its pixels this way,
that is itself the finding for that stratum and must be stated instead of a distribution
quoted as if it covered the whole stratum.

The existing `pair_stats` reports percentiles, which are rank statistics and survive an
unbounded index. `min` and `max` will be extreme; that is expected, not a defect. Do not
clamp them.

## What to build

### Part A — the seventh index in `src/burn_indices_gee.py`

One entry in `indices_of()` and one name in `INDICES`. Nothing else in that file changes.

**Both existing callers select by name** — `src/burn_classifier.py:490-492` takes
`["NBR+"]`, `["NBR"]` and `["NBRSWIR"]`, and `src/burned_area_gee.py:205` takes `["NBR+"]`
— so a seventh key reaches neither. Verify that before editing and say so; if it were
otherwise, this change would silently alter F21's feature set and F11's published product.

Re-run the script and regenerate `docs/data/burn_indices.json`:

```
python src/burn_indices_gee.py <google-cloud-project-id>
```

**The six existing indices must come out numerically identical to the committed file.**
F7 and F8 quote that file at commit `272edb5` and FINDINGS is append-only, so the six
columns of F7's false-alarm table have to stay reproducible. Diff the regenerated file
against `git show HEAD:docs/data/burn_indices.json` and confirm that the only additions are
the ATBI blocks and the new `B8A <= 0` counts. **If any of the six moves, stop and report
it rather than committing** — something drifted in the scene selection or in Earth Engine's
own reprocessing, and that is a larger finding than this task.

Report ATBI as a seventh row of F7's table, in the same four columns:

| index | uni, open sea | uni, cloud | bi, open sea (primary) | bi, cloud (check pair) |
|---|---|---|---|---|
| NBR+ | 0.0% | 1.0% | 1.5% | 5.1% |
| ATBI | | | | |

NBR+'s 5.1% over cloud is the bar. An index that beats it over cloud and sea, on this AOI,
is worth the second half of this task; one that flags the sea the way NBRSWIR, MIRBI and
BAIS2 do is disqualified here whatever it scored in California, and the task stops at Part
A with that stated.

### Part B — scored against the 114 judged boxes

This is the part F7 could not run. Reuse what exists: `src/burn_classifier.py` already
samples 20 m features inside the label boxes and already drops `unsure`. Sample `dATBI` and
`dNBR+` at the same pixels, from the same scene pair, and report for each:

- the distribution over `burned` boxes and over `unburned` boxes, separately, never pooled;
- the separability `M = |mu_b - mu_ub| / (sigma_b + sigma_ub)`, the index the paper itself
  reports, so the number is comparable with its 1.38 against dNBR's 1.29;
- the share of `unburned` pixels above the `burned` 5th percentile, which is the commission
  that F20 measured, expressed at pixel level rather than in hectares.

**Strata are never pooled.** `random_box`, `map_burned` and `footprint_unmapped` are
different populations with different inclusion probabilities, and `map_burned` was drawn
from inside the dNBR+ polygons, so it is biased in dNBR+'s favour by construction. Report
per `sampling` value and say that.

If the 28 remaining boxes of `B23`-`B50` have been judged by the time this runs, use them;
if not, run on the 114 and say which.

**No threshold, and no area.** Publishing the distributions lets any threshold be evaluated
later, which is F7's rule and it still holds. An index that separates the classes better
than dNBR+ is a candidate for a future Phase 4 revision and an argument in the manuscript.
It is not a new burned-area figure, and the 904 ha estimate in
`data/processed/label_accuracy.json` is not recomputed, reinterpreted or touched.

## Constraints

- **Copy no code from the unlicensed repository.** Formula only, written fresh.
- **No new dependency** (AGENTS never-7). `earthengine-api`, `numpy` and `pandas` cover it.
- **Keep cloud pixels.** Cloud is a stratum being measured; a global cloud mask deletes the
  experiment. F7's constraint, unchanged.
- **Mask, do not floor, the `B8A <= 0` pixels, and report the counts.** A quietly floored
  denominator produces a clean-looking distribution over pixels the index cannot describe.
- **Never edit `PLAN.md`** (AGENTS never-6). Phase 4's choice of NBR+ stands; this task
  informs a future revision of it and does not make one.
- **Never write "fire", "kebakaran", or any attribution of cause or responsibility** into
  the output. PLAN section 8 applies in full, as it did for Task 15.
- Do not re-judge, move or re-draw a label box.
- No page change. `docs/index.html` is not edited and no published figure moves.

## Do not write the finding

As with Tasks 17 and 19 to 24. Put the seventh row, the separability numbers and the masked
pixel counts in the final message; the `FINDINGS.md` entry is written at review.

## Acceptance criteria

- `python src/burn_indices_gee.py <project>` writes `docs/data/burn_indices.json` with
  seven indices in both temporal forms, and the six pre-existing ones are numerically
  unchanged from `git show HEAD:docs/data/burn_indices.json`.
- A test asserts the sign convention against the worked example above: pre `B8A` 0.5 /
  `B12` 0.2 and post `B8A` 0.1 / `B12` 0.3 give `ATBI` of -0.1714 and +1.5, and a
  bi-temporal `dATBI` of +1.671, matching the published `dATBI` of 1.67 to two decimals.
  Do this by calling the real `indices_of()` with a stand-in `ee` module in `sys.modules`
  whose `Image` and band objects implement `add`, `subtract`, `multiply`, `divide`, `sqrt`
  and `rename` over plain floats — not by re-writing the expression in the test, which
  would assert only that two copies of a formula agree. The same stand-in covers BAIS2's
  disputed `+ 1` grouping for free; assert that too while it is there.
- A test asserts that `indices_of()` returns all seven keys and that `INDICES` lists them,
  so the two cannot drift apart.
- `tests/test_burn_indices.py` passes unchanged: it iterates whatever the file contains, so
  ATBI's distributions are covered by its existing ordering and non-emptiness checks.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes unchanged.
- `git status` shows no modification under `docs/` other than `docs/data/burn_indices.json`.
- One commit for the index and the regenerated data, one for Part B's output.

## Out of scope

- **`dATBIt` and `dATBItm`**, the multi-temporal detection-count and mean-composite forms
  (equations 4 and 5 of the source). They need a post-event time series this AOI does not
  have without the cloud problem Task 15 was built around. A separate task if Part A and B
  are favourable.
- Adding ATBI to `src/burn_classifier.py`'s `FEATURES`. That would change F21's model and
  needs its own task and its own leave-one-event-out run.
- Severity classes, burn perimeters, thresholds, or any area in hectares.
- Re-running `src/burned_area_gee.py` or changing the F11 product.
- Recomputing `data/processed/label_accuracy.json` or any figure in F20 to F23.
- The September 2026 episode, which still has no polygon and no area.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — in particular how the `B8A <= 0` mask was
defined and how many pixels it removed from each stratum, whether the source paper was
obtained or the formula rests on the algebra here, and which label boxes Part B ran on.

State plainly which of these the numbers support, **including the case where this AOI cannot
separate ATBI from NBR+**, which with one event and one scene pair is a legitimate outcome
and more useful than a ranking the data does not carry:

- **ATBI is better here** — fewer false alarms over cloud than NBR+'s 5.1%, higher
  separability at the label boxes, and the commission share lower. Then Phase 4 has a
  revision worth proposing and the manuscript has a comparison worth making.
- **ATBI is equivalent here** — the two are inside each other's spread. Then the paper gains
  a sentence saying a 2025 index designed against commission did not beat NBR+ on this
  island, which is a finding, and NBR+ stays.
- **ATBI is worse here** — it flags sea, cloud, or sediment-laden water, which its own
  author lists as a known failure. Then say so and stop.
