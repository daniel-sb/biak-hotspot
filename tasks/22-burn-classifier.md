# Task 22 — A learned burn classifier, and the first accuracy figure this project has had

F11 published 2,415 ha of burn-like change with **no accuracy at all**, because there was no
reference data: the field survey was stopped by security conditions, and three plots with
fourteen roadside photographs are not a validation set. F18 then showed that no prompted
segmentation model can outline a burn scar either.

The hand-drawn labels change that. Digitised on S2DR4 1 m imagery, they are an independent
reference for what a person, looking at imagery ten times finer than the product, judges to
have burned. This task uses them twice: to **measure** the Task 18 threshold rule, and to
**train** a classifier that has to beat it.

It does not touch the dashboard, the brief, the cron, or `docs/`.

## Read first

- **The labels are not ground truth.** They are one interpreter's reading of super-resolved
  imagery. S2DR4's 1 m detail is model output, not observation (F18). Every number this task
  produces is agreement with that interpretation, and must be worded that way: "agreement
  with hand-drawn labels", never "accuracy against ground truth".
- **The features must not come from the 1 m imagery.** They come from native Sentinel-2 at
  20 m, the same composites Task 18 uses. Otherwise the classifier would be learning from
  the same super-resolved pixels the labels were drawn on, and the comparison with the
  threshold rule would be unfair to the threshold.
- PLAN.md section 8 applies: no output may name a cause or a person. The words are "changed
  like a burn", "burn-like change", "estimated".

## Inputs

- `data/labels/biak_labels.gpkg`, layer `labels`: polygons with `sample_id`, `event_id`,
  `class` (`burned` / `unburned` / `unsure`), `confidence`, `notes`. Built by
  `scripts/label_prepare.py`; the sample points are stratified inside and outside the VIIRS
  footprints, 7 and 7 per event, with a fixed seed.
- **Drop every `unsure` polygon** and report how many were dropped, by event and by stratum.
  Do not guess them either way (AGENTS never-5 in spirit: the record stays auditable).
- `data/processed/events.json`, `data/processed/detections.parquet`,
  `data/processed/burned_areas.json` (for each event's threshold and look windows).

## Features, from Earth Engine at 20 m

Reuse `burned_area_gee.nearest_look` and `burn_indices_gee.scaled` / `indices_of`. Same pre
and post windows, same Cloud Score+ masking, same 20 m scale as Task 18, so that a pixel's
features and its Task 18 verdict describe the same observation.

Per 20 m pixel, inside the labelled polygons only:

- the pre and post reflectance of B2, B3, B4, B8A, B11, B12;
- their differences, post minus pre;
- `dnbr_plus` (the index F11 thresholds), `dnbr`, `dndvi`, `dnbr_swir` (B12 − B8A over the
  sum, differenced);
- the pre and post look lag in days, which F11 reports per event and which varies enough to
  matter.

**Persist the extracted table before modelling** (AGENTS always-2), as
`data/raw/labels_features/features_<date>.csv`, and track it: it is small, it is what every
number below rests on, and re-extracting it needs Earth Engine. A run without `--fetch`
reads it and never touches the network.

**If Earth Engine cannot be reached or refuses a request: exit non-zero, name the event, and
write nothing.** No placeholder rows, no synthetic reflectance, no stand-in values, not to
make a test pass and not labelled as synthetic either.

## The unit, and the leak that would flatter everything

A 20 m pixel is the unit of prediction. But **neighbouring pixels inside one polygon are
nearly the same observation**, so a random pixel split would put a polygon's own pixels on
both sides and produce an impressive, meaningless score. Two rules, both tested:

1. **Leave one event out.** Three folds: train on two events, test on the third. A polygon's
   pixels never straddle a fold, and neither does an event's weather or look date.
2. **Report per polygon as well as per pixel.** A polygon's prediction is the majority class
   over its pixels. With 42 polygons minus the `unsure` ones, the per-polygon table is the
   honest sample size; the per-pixel table is the detailed one. Give both, and say in the
   output that they answer different questions.

## What must be beaten

**The Task 18 rule, measured on the same labelled pixels**: a pixel counts as burn-like when
its `dnbr_plus` exceeds its event's `threshold` from `burned_areas.json`. That is the
product F11 published, and it needs no training, so it is the bar. Report for it exactly
what you report for the classifier.

Also report the trivial rule, "every pixel inside a VIIRS footprint burned", which F18 used
as its bar.

## The classifier

`sklearn.ensemble.HistGradientBoostingClassifier` as the model, and
`RandomForestClassifier` beside it because it costs nothing to add and reviewers ask for it.
Default hyper-parameters, `random_state` from config. **Do not tune** on the test fold; if
you want a tuned version, say so in your final message and leave it out.

scikit-learn is approved for this task (the owner agreed on 2026-09-29; AGENTS never-7). No
other new dependency: no XGBoost, no LightGBM, no imbalanced-learn.

## Metrics

Per fold, and pooled across folds, for each of: the two classifiers, the Task 18 threshold,
and the trivial rule.

- the confusion matrix counts, per pixel and per polygon;
- precision, recall and F1 for the burned class;
- **balanced accuracy**, because the two strata are not equally sized;
- average precision for the classifiers' probabilities, using
  `baseline.average_precision` (already in the project, ties counted as one threshold), so
  the number is comparable with F12 and F17.

**No single headline number.** Report per fold with its counts, and never average the three
folds into one figure without showing the counts beside it.

## Output

`src/burn_classifier.py`, runnable as `python src/burn_classifier.py [--fetch <gcp-project>]`.
The `ee` import lives inside the fetch path so the modelling and its tests run in `.venv`
without Earth Engine. Writes `data/processed/burn_classifier.json`, sorted keys, indent 1,
no timestamp, added to the `data/processed/` allowlist:

- the parameters, the label counts by class, event and stratum, and the dropped `unsure`
  count;
- the per-fold and pooled metrics for all four rules;
- the feature importances of both classifiers (permutation importance on the held-out fold,
  not the impurity kind, which favours high-cardinality features);
- a `caveats` list, verbatim:
  - "The labels are one interpreter's reading of S2DR4 1 m imagery, which is model output,
    not observation. These figures are agreement with that interpretation, not accuracy
    against ground truth."
  - "Features come from native Sentinel-2 at 20 m, not from the 1 m imagery the labels were
    drawn on."
  - "Folds leave one event out, so no polygon's pixels appear in both training and testing.
    Per-pixel figures describe pixels; the per-polygon table carries the real sample size."
  - "A learned classifier that beats the threshold rule here has beaten it on three events
    of one island in one season, and nothing more (PLAN.md section 8)."

Print the per-fold table and the comparison against the Task 18 threshold to stdout.

## Do not write the finding

**Do not add an entry to `FINDINGS.md`**, as in Tasks 17, 19, 20 and 21. It is written at
review. Put the fold table, the polygon counts and the comparison in your final message.

## Check

`tests/test_burn_classifier.py`, offline, synthetic frames built inside the test. It may read
the committed feature CSV once that exists, but must not fetch.

1. `unsure` polygons are dropped, and the dropped count is reported.
2. Leave-one-event-out: no `sample_id` appears in both the training and test split of a
   fold, and a fold's test set holds exactly one event.
3. The per-polygon vote: a polygon with 7 burned and 3 unburned pixels reads as burned; a
   4-4 tie goes to unburned and the tie is counted.
4. The Task 18 rule reads each event's own threshold, not a shared one.
5. Balanced accuracy on a hand-checked confusion matrix.
6. A feature table with a missing pre look for one pixel keeps that pixel out of the
   modelling and counts it, rather than filling it with a zero.
7. The same feature CSV gives byte-identical `burn_classifier.json` (fix every seed).

## Out of scope

- Applying the classifier to the whole island and republishing burned-area figures. Three
  events of labels do not justify that, and the request would be reasonable only after the
  labelled sample covers more of the record.
- Any change to Task 18's published areas. If the classifier disagrees with the threshold
  rule, that is a finding, not a correction to apply automatically.
- Deep learning, transfer learning, and anything with a GPU. The owner's laptop lost power
  three times under GPU load (F18), and this task does not need one.
- Retraining on the 1 m imagery, or using S2DR4 as a feature source.
