# Task 27 — A fuel map for the corridor, from products already in use

`PLAN.md` §2.3 states a local correction and then asks for it to be checked: Biak is raised
coral limestone, not peatland, so the expected fuel is savanna and grassland, secondary
shrub, and shifting-cultivation plots — fast surface fire, not smouldering ground fire. The
instruction there is "Verify the fuel assumption against WorldCover before building on it".
That verification has never been done. F6 supports the assumption indirectly (651 of 653
detections daytime, fires that do not survive the night), but nothing in this repository
says what the ground actually carries.

This task builds the smallest map that answers it, from three assets the repository already
reads, and crosses it against what burned.

**It is a reclassification, not a classification.** No training points, no supervised model,
no new imagery. Task 18b already ruled the supervised route out of scope, for the reason
that still holds: there is no labelled fuel-type set for Biak and none can be made from the
142 burn labels, which judge burned against unburned and say nothing about cover.

## The scheme

Six classes, cut by fire behaviour rather than by botany, because the point of a fuel map
here is how fast something burns and for how long:

| code | name | what it means for fire |
|---|---|---|
| 1 | `grass_savanna` | fast-moving surface fire, residence time in minutes |
| 2 | `shrub_regrowth` | surface fire with low shrub, the secondary-growth fuel |
| 3 | `cultivation_mosaic` | the clearing fuel; burned on purpose, repeatedly |
| 4 | `forest_closed` | closed canopy, low flammability, rarely carries fire |
| 5 | `mangrove` | saline coastal fringe, effectively non-fuel |
| 6 | `nonfuel` | built, bare rock and karst outcrop, open water |

**FGBFM 40 (Scott & Burgan 2005) is deliberately not used.** It is calibrated on US fuels
and has no Papuan analogue; importing it would be the same error as importing the peat
frame. Say so in the output's `notes`, so the choice is visible to a reader who expects the
standard scheme.

## Inputs

All three are already read elsewhere in this repository. **Add no dependency and no new
asset** beyond these (AGENTS never-7):

- **`ESA/WorldCover/v200/2021`**, band `Map`, 10 m — the base. Same asset as the water mask
  in `src/drought_gee.py:49` and six other modules.
- **`GOOGLE/DYNAMICWORLD/V1`**, band `label`, 10 m — a second, independent reading
  contemporary with the fire season. Take the **per-pixel mode** over the window in config.
  The window must **end before the August 2026 burning**, because Dynamic World reads burned
  ground as `bare` and a post-fire map would classify the fuel as its own absence.
- **`projects/JRC/TMF/v1_2024/AnnualChanges`**, band `Dec2024`, Landsat 30 m — splits
  WorldCover's single `trees` class into closed forest and regrowth. This is Task 18b's
  finding applied: on F11's changed area Esri called 70.6% trees where TMF found 15.2%
  undisturbed forest against 23.0% regrowth and 18.0% degraded. A fuel map that cannot tell
  closed forest from regrowth on cleared land would repeat that error.

Read the asset ids, the Dynamic World window, the TMF year and the output scale from
`config.yaml` under a new `fuel:` block. Do not hard-code any of them (AGENTS always-5).
The TMF year is capped the way `burned_area.tmf_latest_year` already caps it; reuse that
value rather than adding a second one.

## The reclass table

From WorldCover, exhaustively — every class in the product must appear, including the ones
that cannot occur on Biak, so that a surprise shows up as a non-zero area instead of
vanishing:

| WorldCover | → fuel |
|---|---|
| 10 tree cover | split by TMF, see below |
| 20 shrubland | 2 `shrub_regrowth` |
| 30 grassland | 1 `grass_savanna` |
| 40 cropland | 3 `cultivation_mosaic` |
| 50 built-up | 6 `nonfuel` |
| 60 bare / sparse vegetation | 6 `nonfuel` |
| 70 snow and ice | 6 `nonfuel` |
| 80 permanent water | 6 `nonfuel` |
| 90 herbaceous wetland | 6 `nonfuel` |
| 95 mangroves | 5 `mangrove` |
| 100 moss and lichen | 6 `nonfuel` |

Where WorldCover is 10, TMF decides: 1 undisturbed → 4 `forest_closed`; 2 degraded →
4 `forest_closed`; 3 deforested → 2 `shrub_regrowth`; 4 regrowth → 2 `shrub_regrowth`;
5 water or 6 other, or TMF unmapped → stay 4 `forest_closed` and count that fallback.

Three of those rows are judgement calls and each must be reported as a separate area, not
buried in its class total, so the owner can re-cut them without re-running anything:

- `forest_closed_from_degraded_ha` — TMF class 2. Degraded forest has more surface fuel and
  a more open canopy than undisturbed; calling it closed forest is the conservative choice
  and may be wrong.
- `forest_closed_from_tmf_fallback_ha` — tree cover TMF did not resolve.
- `nonfuel_from_wetland_ha` — WorldCover 90. Herbaceous wetland burns when it dries out;
  this map says it does not.

Build the same six classes **independently from Dynamic World** (water→6, trees→split by
TMF the same way, grass→1, flooded_vegetation→6, crops→3, shrub_and_scrub→2, built→6,
bare→6, snow_and_ice→6) and report the **6×6 confusion matrix between the two maps** in
hectares. The disagreement is part of the result. Task 18b's rule applies unchanged:
picking one product silently would hide it.

## What to compute

Area in hectares per fuel class, over corridor **land** (`WorldCover != 80`, the mask every
other module uses), for:

1. **Corridor land overall** — the denominator.
2. **The detection points** — the fuel class under each of the 1,166 rows of
   `data/processed/detections.parquet`, as a count per class, not an area. That store runs
   from 2023-08-31 to 2026-09-23, so most of it predates the Dynamic World window and some
   of it predates the WorldCover 2021 snapshot. **Report the count twice**: all 1,166 rows,
   and the 2026 rows alone. One map cannot be contemporary with three fire seasons, and
   splitting the count is the cheapest way to make that visible instead of averaging it
   away.
3. **The mapped burned area** — `data/processed/burned_areas.geojson` (1,050 features when
   this task was written), area per class.

Print each as a share with the corridor share beside it, so enrichment is readable at a
glance. Carry `frp` through if detection attributes are summarised (AGENTS never-4), and
keep `confidence` as text if it is carried at all — VIIRS returns `l`/`n`/`h` and MODIS
returns 0–100 in the same column (AGENTS never-3).

Write `data/processed/fuel_map.json`, a **new** file. Nothing under `docs/` is read or
written, and no existing file in `data/processed/` is modified.

## What this task is not allowed to conclude

- **Not that the map is accurate.** There is no fuel ground truth for Biak. Every figure is
  a reading of three global products, two of them 2021 and December 2024 vintage. No
  accuracy, no confusion against truth, no validation claim. The two-product confusion
  matrix measures agreement between maps and nothing more.
- **Not that a fuel class caused burning.** The detections are where satellites saw heat,
  not a random sample of land, so a class over-represented among them is an association. No
  chi-square, no p-value, no significance claim, no "preferentially burns".
- **Not a fire-behaviour prediction.** Rate of spread, flame length and residence time need
  fuel load and moisture this map does not carry. The class names describe expected
  behaviour; they are not inputs to a spread model.

### The 23 notes are not validation

Twenty-three of the 142 label boxes carry free-text notes, and a few happen to name cover:
`it is a shrub/grassland it is unburned i...`, `it is heavy forest vegetation, the close...`,
`build up area`, `beach lines`. Print the fuel class at each noted box's centroid beside the
note text, as a spot-check for the owner's eye. **Do not compute any agreement figure,
percentage or score from them.** They are one interpreter's incidental remarks on 16% of the
boxes, written for a different question, and a number built on them would read as validation
when it is not.

## The check

One `test_*.py` under `tests/`, offline, no network (AGENTS always-3 and always-4). The
reclass is arithmetic over band images, so call the real functions with a stand-in `ee`
module the way `tests/test_atbi.py:74` does — do not re-implement the table in the test:

- Every WorldCover class 10 to 100 maps to a fuel code in 1 to 6, with none left unmapped.
- WorldCover 10 with TMF 1 gives `forest_closed`; WorldCover 10 with TMF 4 gives
  `shrub_regrowth`. This is the split the task exists for.
- WorldCover 10 with TMF 5 or an unmapped TMF pixel gives `forest_closed` and increments the
  fallback count.
- The Dynamic World window read from config ends before the first August 2026 detection
  date. An off-by-one here maps burned ground as fuel and is invisible in the output.

## Constraints

- **Never write a value you did not compute.** If Earth Engine will not authenticate, if an
  asset id is wrong, or if `detections.parquet` or `burned_areas.geojson` cannot be read,
  print which one and why and exit non-zero. Write no file, no placeholder, no zero
  presented as an area, and no synthetic class, share or hectare figure. An empty answer and
  a failed read are different facts and must stay distinguishable in the output and in the
  exit code (AGENTS never-2). **This rule binds whatever agent runs this task.** This
  repository has already published synthetic MODIS data once, produced by a handed-off task
  that was blocked and filled the gap instead of reporting it, and the figure reached the
  public page.
- **Never delete rows.** All six classes appear in every table, including those with zero
  area (AGENTS never-5).
- **Never edit `PLAN.md`** (AGENTS never-6). §2.3's fuel expectation is what this task
  tests; if the result contradicts it, say so in the final message and leave the spec alone.
- Timestamps in UTC with a WIT (UTC+9) column derived, if any timestamp is written
  (AGENTS always-1).
- No page change and no commit to `docs/`.

## Split at the credential boundary

**Part A — offline, no credential.** `src/fuel_map_gee.py` with the reclass functions, the
config block, the stand-in-`ee` test, and `python -m pytest tests/test_fuel_map.py` passing.
Nothing is fetched. This part can be written and checked with no Earth Engine account.

**Part B — the authenticated run.** `python src/fuel_map_gee.py deeplearning-370412`, which
writes `data/processed/fuel_map.json`. If Part A's agent has no working Earth Engine
credential, it **stops at the end of Part A and says so**. It does not invent the JSON, and
it does not write a partial file to show progress.

## Acceptance criteria

- `python -m pytest tests/` passes. Run it with the `geolibre` conda environment's
  interpreter, `C:/Users/User/.conda/envs/geolibre/python.exe`; `.venv` lacks geopandas and
  its test count differs, which is not a result.
- Part B, when run, writes `data/processed/fuel_map.json` with all six classes in every
  table, the 6×6 two-product confusion matrix, the three judgement-call areas named above,
  and the TMF year actually used.
- `git status` shows nothing under `docs/` touched and `data/labels/biak_labels.gpkg`
  unmodified — the owner is re-reviewing labels while this runs, so any write to that file
  destroys work in progress.
- `python scripts/render_check.py` passes unchanged. It currently skips because playwright
  is not installed in either environment; that skip is pre-existing and is not to be fixed
  here.
- One commit for Part A, one for Part B.

## Out of scope

- Supervised classification of Sentinel-2 for a true 2026 fuel map. Same reason Task 18b
  gave: no labelled training set, no validation set.
- Fuel load, fuel moisture, rate of spread, flame length, any fire-behaviour model.
- KLHK Penutupan Lahan and Global Mangrove Watch. Both are in `PLAN.md` §2.3; both need a
  download and a new file in `data/boundaries/`, and WorldCover class 95 covers the mangrove
  fringe well enough for six classes.
- Landsat LST, the September 2026 episode polygon, Task 25 Part B, and anything that spends
  Gamma Earth credits.
- Re-running `scripts/label_accuracy.py`, or moving any figure in F20 to F24.

## Do not write the finding

As with Tasks 17 and 19 to 26. Put the tables in the final message; the `FINDINGS.md` entry
is written at review.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open. In particular: the Dynamic World window you
chose and why it ends where it does, how you handled a Dynamic World pixel with no scene in
the window, whether TMF was upsampled or the output downsampled to 30 m, and what the script
does when `burned_areas.geojson` holds an event with no overlapping corridor land.

State the per-class figures plainly and resist summarising them into one headline number. If
the corridor turns out to be mostly `forest_closed` rather than grass and shrub, that
contradicts `PLAN.md` §2.3 and is the most useful thing this task could find — report it as
such rather than reaching for a reclass that rescues the assumption.
