# Task 23 — Enough labels to say something

F22 and F23 settle what the reference sample can and cannot do. With 20 judged boxes in the
mapped stratum and 10 in the unmapped one, the burned-area estimate for three events is
614 ha. Which interval goes round it decides the answer, and the two available answers
disagree:

| treatment | 95% interval | the map's 819 ha |
|---|---|---|
| Wilson per stratum, F22 | 435 to 953 ha | inside |
| Olofsson et al. 2014 Eqs. 9 to 11, normal approximation | 455 to 774 ha | outside |

The gap is stratum B. Zero of ten gives the normal approximation exactly zero variance for
ground that is half the study area; the Wilson upper bound of 28% gives it 226 ha. F23 keeps
the wider figure, and says the sample is too small to settle it. **This task is what settles
it**, by raising both strata to 50 judged boxes. The second-interpreter check it originally
carried is off: no second person is available, and F24 records that as a permanent
limitation rather than a gap to fill later.

It does not change any published figure, and it does not touch `docs/`, the brief or the cron.

## How many boxes is enough, from the paper

Olofsson et al. 2014 (Remote Sensing of Environment 148, 42-57, in `References/`) recommends
50 to 100 units per change stratum, and its Eq. 13 gives the arithmetic. With our stratum
weights, the mapped stratum's observed 75%, and a conjectured 10% burning in stratum B:

| target S(p) | boxes in total | per stratum | area interval, roughly |
|---|---|---|---|
| 0.05 | 54 | 27 and 27 | plus or minus 160 ha |
| 0.03 | 149 | 75 and 74 | plus or minus 96 ha |
| 0.02 | 336 | 169 and 167 | plus or minus 64 ha |

**50 judged boxes per stratum is the target**, which lands near S(p) = 0.036 and an interval
of about plus or minus 115 ha. That separates 614 from 819, or fails to, for a reason other
than sample size. Going further is a judging-time decision, not a statistical one: say in
your final message what the achieved S(p) turned out to be.

## Before you start: which Python runs this

Three interpreters on this machine, and only one runs the data work:

| interpreter | has | use it for |
|---|---|---|
| `.venv` | shapely, no geopandas | nothing here; `scripts/label_*.py` dies with `ModuleNotFoundError: No module named 'geopandas'` |
| **conda env `geolibre`** | geopandas 1.1.4, rasterio, pyproj, sklearn, ee, pytest | **everything in this task** |
| QGIS 3.44 LTR python | geopandas, osgeo, no rasterio | only `label_qgis_project.py` and `label_second_pass.py`, which import `qgis.core` |

```
GDAL_DATA=C:/Users/User/.conda/envs/geolibre/Library/share/gdal
PROJ_LIB=C:/Users/User/.conda/envs/geolibre/Library/share/proj
C:/Users/User/.conda/envs/geolibre/python.exe scripts/label_accuracy.py
```

Without those two variables pyogrio warns `Could not detect GDAL data files` and CRS work
gets unreliable. With them the whole label suite is about 7 seconds and the full
`pytest tests` about 7 minutes. Booting the QGIS interpreter per command instead costs 3.6 s
each time and cannot import rasterio at all, so do not reach for it to run a script.

**Never invent a label, a geometry or a coverage number.** If a box cannot be drawn, a file
cannot be read or a count does not come out, exit non-zero and say which one. No placeholder
rows, no synthetic judgements, not to make a test pass and not labelled as synthetic either.
A fabricated reference label is worse than a missing one: it moves the accuracy figure and
leaves no trace that it did.

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

### 2. A second interpreter - NOT HAPPENING, see F24

The owner decided on 2026-10-13 that no second person is available. Do not build toward
this and do not fill `data/processed/label_agreement.json` with a number: `compared: 0` and
a null kappa are the honest state, and a blind re-judge by the same person measures
self-consistency, not agreement between readers.

What already exists stays and is not to be removed: `scripts/label_second_pass.py`,
`data/labels/biak_labels_pass2.gpkg` with its 142 unjudged boxes, and the `--compare` path.
They work the day someone is available, for part of the boxes as well as all of them.

### 3. Rerun what rests on the labels

Once the boxes are judged, re-run and report the deltas, nothing more:

- `scripts/label_accuracy.py` — the two-stratum estimate and **both** intervals, the Wilson
  one and the `olofsson()` one already in that script. Report whether they still disagree
  about 819 ha; that disagreement closing is the result this task exists for.
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
   `tests/test_label_accuracy.py` already checks this and the Olofsson estimator against the
   published figures; extend it rather than starting a second file for the same script.

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
- Changing the assessment unit. F23 records that the 60 m box is a cluster of nine 20 m
  pixels and that the paper's variance estimators are not written for it. That is a real
  deviation, and fixing it means re-judging everything at pixel level on imagery that cannot
  support it. Leave it stated, not fixed.
- Any change to F11's published 2,415 ha.
