# Task 23 — Enough labels to say something: more boxes, and a second interpreter

F22 settles what the reference sample can and cannot do. With 20 judged boxes in the mapped
stratum and 10 in the unmapped one, the burned-area estimate for three events is 614 ha with
a 95% interval of 435 to 953 ha. The map's own 819 ha sits inside it. The estimator is not
the problem: a zero-count stratum of ten has an upper bound of 28% whatever the ground does,
and that one number widens the interval by 226 ha.

Published good practice asks for 50 to 100 sample units per stratum (Olofsson et al. 2014,
Remote Sensing of Environment 148, 42-57). This task gets there, and adds the one check the
reference has never had: a second person judging the same boxes.

It does not change any published figure, and it does not touch `docs/`, the brief or the cron.

## What to build

### 1. More boxes, in the stratum that binds

`scripts/label_add_map_stratum.py` already draws from the dNBR+ polygons. Extend the same
pattern to the unmapped stratum, and raise both toward 50 judged boxes each:

| stratum | judged now | target | frame |
|---|---|---|---|
| A, mapped by dNBR+ | 20 | 50 | random points inside the dNBR+ polygons of the three events |
| B, inside a footprint, unmapped | 10 | 50 | random points inside the footprints, on ground the polygons do not claim |

- Same 60 m box, same 150 m minimum separation, same fixed seeds, recorded in the script.
- New boxes must not overlap any box already drawn, and must not reuse a `sample_id`.
- Mark them `sampling = map_burned` and `sampling = footprint_unmapped`. **Do not reuse
  `random_box`**: those 42 came from a different frame, 7 in and 7 out of each footprint,
  and mixing the two would make the inclusion probabilities unknowable.
- `scripts/label_accuracy.py` reads stratum B from `random_box` boxes today. It will need to
  read both that and the new stratum, and say in its output how many boxes came from each.

Report the areas the strata cover after the draw, because the estimator weights by area and
those weights are what the figures rest on.

### 2. A second interpreter

Every agreement figure in F20, F21 and F22 comes from one person reading one set of images.
That is the largest unmeasured uncertainty in the project, larger than the estimator choice.

- Build `scripts/label_second_pass.py`: it copies the label boxes into a **new GeoPackage**
  with `class`, `confidence` and `notes` emptied, and the first pass invisible. Same imagery,
  same manual.
- The second interpreter judges the same boxes without seeing the first pass.
- Then report **Cohen's kappa** and the raw agreement between the two passes, per stratum,
  and list every box they disagree on with both answers. Put the comparison in
  `data/processed/label_agreement.json`.
- Where they disagree, neither answer wins automatically. The disagreement rate is the
  result; a reconciled label is a separate decision for the owner, taken box by box and
  recorded with a reason.

Keep the second pass in its own file: `data/labels/biak_labels_pass2.gpkg`. Do not write
into the first pass under any circumstance.

### 3. Rerun what rests on the labels

Once the boxes are judged, re-run and report the deltas, nothing more:

- `scripts/label_accuracy.py` — the two-stratum estimate and its interval;
- `src/burn_classifier.py` — the fold table; more positives in stratum B is exactly what its
  weakest number needed.

**Do not retune the classifier** because the sample grew. Same features, same defaults, same
leave-one-event-out folds.

## Configuration

```yaml
labels:
  box_m: 60
  min_separation_m: 150
  target_per_stratum: 50
  seeds: {map_burned_2: ..., footprint_unmapped: ...}
```

Every value gets a comment giving its reason. AGENTS always-5.

## Check

Extend `tests/test_label_tools.py`, or create it:

1. A new draw never places a box overlapping an existing one, and never repeats a
   `sample_id`.
2. The second-pass GeoPackage carries the same geometries and empty judgements, and the
   first-pass file is byte-identical afterwards.
3. Cohen's kappa on a hand-worked table, including the case where both passes agree
   everywhere, which must give 1.0 rather than a division by zero.
4. The accuracy script reads stratum B from both `random_box` and `footprint_unmapped`
   boxes, and reports the count from each.
5. A stratum with zero burned boxes still produces an upper bound, as F22 relies on.

## Constraints

- **The map stays hidden while judging.** No dNBR+ layer in either project file. Sampling by
  the map is standard; judging by it is not.
- No new dependency. scikit-learn is already approved; kappa is four lines of arithmetic, so
  do not add a statistics package for it.
- The existing 67 boxes and their judgements are not to be modified, reordered or re-seeded.

## Do not write the finding

As with Tasks 17, 19, 20, 21 and 22. Put the new interval, the kappa and the disagreement
list in your final message; the entry is written at review.

## Out of scope

- More events. Three events have 1 m imagery; adding a fourth means another S2DR4 run and
  belongs to its own task.
- Reconciling disagreements into a single label set.
- Any change to F11's published 2,415 ha.
