# Task 26 — Which label boxes have a hotspot detection later than the image they were judged on

The owner noticed that on the 17 September 2026 chip some boxes read as burned far more
obviously than they did on 28 August. Regrowth cannot explain that: in humid tropical Papua
grass and fern regreen within weeks, which makes a scar **less** distinct, not more. Three
mechanisms run in the observed direction, and this task measures the first one.

**Burning continued inside the chips for a week after the 28 August image was taken.** A
check on 2026-10-20 found 26 detections inside the three 4.1 km chip footprints dated after
26 August — 11 in E0301, 14 in E0313, 1 in E0368 — on 27 August, 28 August, and 1, 2 and 3
September. The record runs to 2026-09-23, which is **later than the last chip**, so even the
17 September image cannot show everything that burned.

The other two mechanisms are out of scope here and named so nobody mistakes this task for
settling them. Delayed severity development: ash is bright, rain removes it over weeks and
exposes dark char, and scorched canopy keeps browning, which is why MTBS and BAER separate
initial from extended assessment. And the reconstruction growing more confident: the wheel
inspects the Sentinel-2 images of the 180 days before the target date
(`scripts/s2dr4_dates.py`, from the SDK release notes read 2026-10-15), so by 17 September a
month of post-burn scenes sits in that window where on 28 August only two or three days did.
Tile cloud was 41.9% on 28 August and 37.5% on 17 September, so both of those chips are
substantially reconstruction rather than observation, and only 23 August at 0.4% is close to
what the sensor saw.

Separating ground change from model confidence needs a human looking at the native 20 m
series beside the 1 m one. **That is not this task.** This task produces the shortlist of
boxes worth looking at, by arithmetic alone.

## What this task is not allowed to conclude

A detection near a box is **not** evidence that the box burned. A VIIRS pixel is 375 m and
locates a thermal anomaly, not a burn perimeter — the same rule Task 15 was built on, and
the reason the hotspot record is never used as truth anywhere in this repository.

So the output carries distances and dates and nothing else. **Do not emit a boolean such as
`burned_later`, `relabel`, or `suspect`.** Do not rank the boxes by likelihood of having
burned. Do not suggest a class for any box. The judgement is the owner's and it is already
made; this is a lookup table that tells them where to look first.

## What to build

### `scripts/label_late_detections.py`

Runs on the laptop with no credential, no network and no Earth Engine:

```
python scripts/label_late_detections.py
```

Inputs, both already in the repository:

- `data/labels/biak_labels.gpkg`, layer `labels` — 142 boxes, EPSG:4326, columns `fid`,
  `geom`, `sample_id`, `event_id`, `sampling`, `class`, `confidence`, `notes`, `drawn_on`.
- `data/processed/detections.parquet` — 1,166 rows, `acq_date`, `latitude`, `longitude`,
  `confidence`, `frp` and the rest.

Read `box_m` and the GeoPackage path from `config.yaml` (AGENTS always-5). Do not hard-code
60, and do not hard-code any date: derive the chip dates from the filenames in
`data/labels/imagery/`, the way `scripts/label_qgis_project.py` already does with
`*_swir_2026*.tif`. The six dates are currently 20260813, 20260823, 20260825, 20260828,
20260902 and 20260917, and the script must still be right when a seventh is added.

**Reuse what exists; add no dependency** (AGENTS never-7):

- `gpkg_geometry` in `src/burn_classifier.py:116` reads a GeoPackage blob to a shapely
  geometry with `sqlite3` alone. No geopandas is needed for one table.
- `metres` in `src/fieldwork_gpkg.py:68` is the local flat-earth distance, whose own
  docstring notes that over 375 m at 1 S the error is microns. That is the right tool at
  these distances; do not reach for a projection.

**Open the GeoPackage read-only.** Use `sqlite3.connect("file:...?mode=ro", uri=True)`. The
142 judgements were finished on 2026-10-20 and committed in `41188d7`, and this script must
be incapable of touching them. It issues `SELECT` and nothing else — no `UPDATE`, no
`INSERT`, no `VACUUM`, no new layer, no new column.

### What to compute, per box

For each of the 142 boxes, against every detection in the store:

1. The distance in metres from the box to the nearest detection **later than each chip
   date**, one figure per chip date, plus that detection's `acq_date`. Distance to a box
   means distance to the box polygon, so a detection inside it is 0.
2. A distance band for each: `inside`, `<=375`, `<=750`, `<=1500`, `>1500`. 375 m is the
   VIIRS pixel; 1500 m is `ADJ_M` from `src/burn_indices_gee.py`, kept the same so the two
   analyses speak one language.
3. The list of chip dates that **precede** the nearest later detection within 375 m. That is
   the mechanical statement this task exists to make: those chips were taken before ground
   near that box last registered a thermal anomaly, so they cannot show its final state.

Write `data/processed/label_late_detections.json`, a **new** file. Nothing under `docs/` is
read or written, and no existing file in `data/processed/` is modified.

Print a table of only the boxes with a detection within 375 m later than at least one chip
date, with `sample_id`, `sampling`, the class the owner gave, the distance, the detection
date, and which chips it postdates. Then print the counts per stratum, because
`random_box`, `map_burned` and `footprint_unmapped` have different inclusion probabilities
and are never pooled.

One box is worth naming in the output if it appears: `E0301-IN03`, whose `notes` read
`1709 anjereuw very obviously burned`. It is the only one of the 23 notes that names a date,
and it names 17 September, so it is the clearest single case of the effect the owner
described. Twenty-three of the 142 boxes carry notes at all, so the notes are not a general
route to which date a box was judged on; say that plainly rather than implying the field
answers the question.

### The check

One `test_*.py` under `tests/`, offline, no network (AGENTS always-3 and always-4):

- A box containing a detection reports distance 0 and band `inside`.
- A detection on exactly a chip date is **not** counted as later than that chip. The
  comparison is strictly greater than, and an off-by-one here silently moves boxes between
  bands.
- The chip dates come from the imagery directory rather than a literal, so adding a seventh
  file changes the output.
- Skip cleanly when `data/labels/biak_labels.gpkg` is absent, the way the Task 11 to 15
  checks do.

## Constraints

- **Never write a value you did not compute.** If `data/processed/detections.parquet` or the
  GeoPackage is missing or unreadable, print which one and why and exit non-zero. Write no
  file, no placeholder, no empty table presented as a result, and no synthetic detection,
  box, date or distance. An empty answer and a failed read are different facts and must stay
  distinguishable in the output and in the exit code (AGENTS never-2). **This rule binds
  whatever agent runs this task.** This repository has already published synthetic MODIS
  data once, produced by a handed-off task that was blocked and filled the gap instead of
  reporting it, and the figure reached the public page.
- **The GeoPackage is read-only.** See above. If any code path could write to it, the task
  is wrong.
- **Never cast the FIRMS `confidence` column to a number** (AGENTS never-3): VIIRS returns
  `l`/`n`/`h` and MODIS returns 0–100 in the same column. This task does not need
  `confidence` at all; if it is carried through, carry it as text.
- **Never drop the `frp` column** if detection attributes are copied into the output
  (AGENTS never-4).
- **Never delete rows.** All 142 boxes appear in the JSON, including those with no late
  detection anywhere near them (AGENTS never-5).
- Timestamps in UTC with a WIT (UTC+9) column derived, if any timestamp is written
  (AGENTS always-1). The detection store's `acq_date` is already a WIT local day; do not
  shift it again.
- **Never edit `PLAN.md`** (AGENTS never-6).
- No new dependency. `sqlite3`, `pandas`, `shapely` and the two helpers named above are
  enough.
- No page change, no commit to `docs/`, and no re-run of `scripts/label_accuracy.py`.

## Do not write the finding

As with Tasks 17 and 19 to 25. Put the table and the per-stratum counts in the final
message; the `FINDINGS.md` entry is written at review.

## Acceptance criteria

- `python scripts/label_late_detections.py` writes `data/processed/label_late_detections.json`
  with all 142 boxes and prints the shortlist plus per-stratum counts.
- `git status` shows `data/labels/biak_labels.gpkg` unmodified, and nothing under `docs/`
  touched. This is the criterion that matters most: if the GeoPackage shows as `M`, the task
  failed regardless of its output.
- `python -m pytest tests/` passes. Run it with the `geolibre` conda environment's
  interpreter, `C:/Users/User/.conda/envs/geolibre/python.exe`; `.venv` lacks geopandas and
  its test count differs, which is not a result.
- `python scripts/render_check.py` passes unchanged. It currently skips because playwright is
  not installed in either environment; that skip is pre-existing and is not something to fix
  here.
- One commit for the script, its test and the JSON.

## Out of scope

- Judging, re-judging, moving, resizing or reclassifying any box. The 142 are finished.
- Recomputing `data/processed/label_accuracy.json` or moving any figure in F20 to F23.
- The native-20 m-against-1 m visual comparison. It needs an interpreter's eye, and this
  task only produces the shortlist for it.
- Deciding whether the 17 September sharpening is ground change or model confidence. Two of
  the three mechanisms are untouched by this arithmetic.
- Task 25 Part B, and any ATBI or dNBR+ figure.
- New imagery, new S2DR4 dates, or anything that spends Gamma Earth credits.
- The September 2026 episode's own burned area, which still has no polygon and needs its own
  task.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — in particular how distance to a box was
defined, what the band edges are, how the chip dates were derived, and what the script does
when a box has no later detection anywhere in the record.

State the counts plainly, per stratum, and resist summarising them into a single number. If
no box has a late detection within 375 m, that is a clean negative result and it removes the
first of the three mechanisms from consideration — report it as such rather than widening
the radius until something appears.
