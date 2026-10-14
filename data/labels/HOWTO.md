# Judging the burn-scar labels

**75 boxes are waiting for a judgement, and they decide the project's headline number.**
Open `data/labels/biak_labels.qgz` in QGIS 3.44 LTR, not 4.2, and fill in the `class` and
`confidence` of every box that still has neither.

These labels are the reference that the Task 18 burned-area product is measured against.
Nothing else in this project can do that job: the field survey was stopped by security
conditions, and F18 showed that no prompted segmentation model can stand in.

## What the 75 boxes settle

The burned-area estimate for the three events is **614 ha**. The map being tested claims
**819 ha**. Whether those two figures agree depends on which interval you put round the 614,
and with the sample as it stands the two defensible intervals disagree:

| treatment | 95% interval | the map's 819 ha |
|---|---|---|
| Wilson per stratum (F22) | 435 to 950 ha | inside |
| Olofsson et al. 2014, normal approximation (F23) | 455 to 774 ha | outside |

The gap comes from one stratum. Ten judged boxes on the unmapped half of the ground, none
of them burned, give the normal approximation no variance at all there, while Wilson's
upper bound of 28% gives it 222 ha. Fifty judged boxes per stratum is the floor Olofsson et
al. 2014 recommends, and reaching it narrows the interval to roughly plus or minus 115 ha.
**That is what the judging is for**: at that width, 614 and 819 either separate or they do
not, for a reason other than sample size.

So the work is not cosmetic, and partial work still helps. Every box judged narrows the
interval a little.

## Before you start: which Python

Three Python interpreters are installed on this machine and only one runs these scripts.

| interpreter | has | use it for |
|---|---|---|
| `.venv` | shapely, no geopandas | nothing here. Scripts die with `ModuleNotFoundError: No module named 'geopandas'` |
| **conda env `geolibre`** | geopandas, rasterio, pyproj, sklearn, pytest | **every script in this guide** |
| QGIS 3.44 LTR python | geopandas, osgeo, no rasterio | only `label_qgis_project.py` and `label_second_pass.py`, which import `qgis.core` |

Set two environment variables with it, or pyogrio warns `Could not detect GDAL data files`
and the CRS work becomes unreliable:

```
GDAL_DATA=C:/Users/User/.conda/envs/geolibre/Library/share/gdal
PROJ_LIB=C:/Users/User/.conda/envs/geolibre/Library/share/proj
C:/Users/User/.conda/envs/geolibre/python.exe scripts/label_check.py
```

Where this guide says `python scripts/…`, it means that interpreter with those two
variables set, except for the two scripts the table sends to QGIS.

## What you are looking at

| layer | what it is |
|---|---|
| **LABELS — draw here** | 142 boxes of 60 x 60 m, already placed. You fill in the class |
| random_box seed points, 42 of them | the points the first 42 boxes were centred on. The other 100 boxes have no point here |
| VIIRS footprints (strata, not truth) | 375 m circles round the detections, the frame two strata were drawn from |
| VIIRS/MODIS detections | the individual satellite detections |
| S2DR4 1 m imagery | SWIR and true colour, three dates per event |
| Sentinel-2 20 m | before the event, 23 August, 28 August |

Only the 1 m SWIR image of 28 August for E0313 is switched on at the start. Tick the others
as you go.

**There is no dNBR+ layer, on purpose.** These labels judge that product, so seeing it
while judging would make the comparison worthless. Do not add it.

## The dates, and why there are three

All three events ran until 25 August, so no single image shows the whole story.

| date | 1 m | 20 m | what it shows |
|---|---|---|---|
| before the event | no | yes | the ground as it was, two to twelve weeks earlier |
| 23 August | yes | yes | mid-episode, the clearest scene of the run, and the field survey's basemap |
| 25 August | yes | no | the last detection day |
| 28 August | yes | yes | after, and the image dNBR+ compared against |

**A fresh scar reads bright orange on 23 August and fades to dull brown by 28 August.** That
fading is the most reliable sign you have. Ground that was already open before the event
looks the same on all three dates, and that is the difference between burnt and merely bare.

So the question to answer for each box is not "does this look burnt" but **"did this change
between the dates, and does the change look like burning"**. dNBR+ measures change between
two looks; judging one date alone asks something different, and the two then disagree for
reasons that have nothing to do with accuracy.

## The imagery

**SWIR (B12/B8A/B4) is the one to judge from.** In it:

| what you see | what it is |
|---|---|
| bright green | healthy vegetation, the greener the denser |
| brown to maroon, dull red | burnt or bare ground — this is what you are looking for |
| pale green to cream | grass, dry or sparse cover |
| near black | water |
| white, sharp edges | roofs and paved surfaces |

Switch to true colour when you want to check what a feature is — a roof, a track, a bare
field — because true colour looks like a photograph and SWIR does not.

The three channels share one fixed brightness scale, so these colours mean the same thing
in every tile and can be compared between events. (An earlier version of this imagery
stretched each channel separately, which showed vegetation orange and burnt ground blue;
if you see that, the imagery is stale — re-run `scripts/label_prepare.py`.)

The 1 m detail is super-resolved, which means a model generated it from 10 m pixels. Trust
the shape of a patch and the contrast between patches. Do not trust a single sharp edge or
a small isolated object: those are the parts a super-resolution model invents.

## The job: judge the boxes

There is nothing to draw. The label layer holds **142 boxes of 60 x 60 m**, 0.36 ha each,
which is 9 pixels of the 20 m product being tested. Your job is the judgement only: what is
inside each box.

Why fixed boxes rather than outlines: the sample location has to come from the random draw.
Choosing where to draw, by eye, around a scar that is visible turns the reference into a
collection of obvious cases, and the agreement figure then measures the easy ones only.

### Three strata, and what is left in each

| `sampling` | how many | judged | drawn from |
|---|---|---|---|
| `random_box` | 42 | 42, done | random points, 7 inside and 7 outside each event's VIIRS footprint |
| `map_burned` | 50 | 25, **25 left** (`MAP26`–`MAP50`) | random points inside the dNBR+ polygons of the three events |
| `footprint_unmapped` | 50 | 0, **50 left** (`B01`–`B50`) | random points inside the footprints, on ground the polygons do not claim |

The first 42 produced only 3 burned boxes, and all 3 sit on ground the map already claims.
Only 10 of the 42 land in the stratum that matters most — inside a footprint, on ground the
map does not claim — and none of those 10 is burned, which is why the omission term rests on
a Wilson upper bound of 28% rather than on evidence. `map_burned` samples the map being
tested, so the burned class is well represented there. `footprint_unmapped` samples the
unclaimed ground directly, which is where omission shows up. Together the strata give a
corrected area estimate with an interval.

The three strata are never pooled. Each came from its own frame, so each carries its own
inclusion probability, and mixing them would make those probabilities unknowable. The 42
`random_box` boxes keep their place and are still used, but only for the stratum their own
draw supports.

Sampling by the map is not circular, because the map is never shown while judging. Judging
by the map would be. That is why there is still no dNBR+ layer in the project.

### The steps

1. Open the project, select **LABELS — draw here**, and open the attribute table (**F6**).
2. Toggle editing (**Ctrl+E**).
3. Sort by `class` to bring the empty rows together, or filter the table to them.
4. Click a row, then **Zoom to feature**, so the map shows that box.
5. **Look at the three dates in turn**, which is the part that decides the answer.
6. Fill `class` with `burned`, `unburned` or `unsure`, and `confidence` with `high`,
   `medium` or `low`. Use `notes` only if something needs saying.
7. Save (**Ctrl+S**) often.

Step 5 is three questions, in this order:

| look at | ask |
|---|---|
| 1 m SWIR, 23 August | is the box orange, meaning freshly burnt? |
| 1 m SWIR, 28 August | has it gone dull brown, as a scar does in five days? |
| 20 m before | was it already open and bare before the event? |

The table also has a **form view** at the bottom right, which shows one box at a time if
that reads more comfortably than the grid.

Spelling matters, and `scripts/label_check.py` catches anything unexpected.

### What each pattern means

| before | 23 Aug | 28 Aug | read it as |
|---|---|---|---|
| green | orange | brown | burnt during the episode, the clearest case |
| green | green | brown | burnt between 23 and 25 August |
| brown or bare | same | same | open ground already, not a scar |
| green | dark patch | green | cloud or its shadow, not a scar |

### If a box straddles two cover types

Judge what covers most of it. If it is close to half and half, that is exactly what `unsure`
is for.

## The rules that keep this honest

- **`unsure` is a real answer.** Thin smoke, cloud shadow, a patch you would argue about —
  mark it `unsure` and move on. The estimator drops those and reports how many there were.
  A guessed label is worse than no label, because it silently moves the accuracy figure.
- **Do not move a box** to somewhere easier to judge, and do not resize it. The points were
  drawn at random from a fixed seed; shifting them onto convenient ground is exactly the
  bias the random draw exists to prevent. A box on water, on a roof or under cloud gets
  `unsure` and a note.
- **Inside the footprint does not mean burned.** The footprint only says a satellite saw
  heat within 375 m at some point. Plenty of ground inside it did not burn, and that is
  precisely what the labels are meant to establish. Judge each patch on the imagery.
- **Outside the footprint does not mean unburned** either. If it looks burned, label it
  burned.
- **Inside a dNBR+ polygon does not mean burned.** You cannot see the polygons, which is the
  point, but 25 of the boxes left are inside one. Five of the 25 already judged in that
  stratum came back `unburned`. The stratum is where the map says it burned, not where it
  did.
- **Do not use the detections as evidence.** They tell you where heat was seen, which is
  the very thing the product is trying to convert into area. Use them to orient yourself,
  not to decide.
- **Change is the question, not appearance.** Bare ground that looks the same on every date
  is `unburned`, however brown it is. That distinction is the whole reason three dates are
  in the project.
- **Re-judging a box is allowed, and expected.** The first pass was made on one date only.
  If a box reads differently with the sequence in front of you, change it and say why in
  `notes`. Nothing is gained by defending an earlier call.

## When you are done, or partway through

```
python scripts/label_check.py
python scripts/label_accuracy.py
```

`label_check.py` reports how many boxes exist, the class counts by stratum, the polygon
sizes, and anything malformed or misspelled. It changes nothing.

`label_accuracy.py` is the one that produces the answer. It prints the two-stratum estimate
with **both** intervals, the Wilson one and the Olofsson one, says whether each puts the
map's 819 ha inside or outside, and reports how many boxes are still unjudged and therefore
counted nowhere. It writes `data/processed/label_accuracy.json`.

Partial work is fine. Both scripts say what is left and the interval simply stays wider.

When all 100 drawn boxes are judged, re-run `src/burn_classifier.py` as well: more
positives in the unmapped stratum is what its weakest fold needed. **Do not retune it**
because the sample grew — same features, same defaults, same leave-one-event-out folds.

## The scripts, in the order you need them

| script | interpreter | what it does |
|---|---|---|
| `scripts/label_prepare.py` | geolibre | already run: builds the 1 m imagery, the sample points and the first 42 boxes |
| `scripts/label_pre_imagery.py` | geolibre | already run: pulls the 20 m before, mid and after chips from Earth Engine |
| `scripts/label_qgis_project.py` | **QGIS** | rebuilds `biak_labels.qgz`. Never touches the GeoPackage, so judgements survive a rebuild. Refuses to run if the project holds polygon annotations, unless you pass `--force` |
| `scripts/label_add_boxes.py` | geolibre | draws more `map_burned` or `footprint_unmapped` boxes at random, at least 150 m from any existing one |
| `scripts/label_fill_ids.py` | geolibre | only if you add polygons by hand: fills `sample_id` and `event_id` from the point inside each polygon |
| `scripts/label_check.py` | geolibre | reports what is there and what is wrong. Changes nothing |
| `scripts/label_accuracy.py` | geolibre | the estimate and both intervals. Changes nothing but its own JSON |
| `scripts/label_second_pass.py` | **QGIS** | the second-interpreter machinery. Nobody is running it — see below |

Never invent a label, a geometry or a coverage number to get a script to finish. If a box
cannot be drawn, a file cannot be read or a count does not come out, the script exits
non-zero and names the problem. A fabricated reference label is worse than a missing one: it
moves the accuracy figure and leaves no trace that it did.

## The second interpreter: not happening

**No second person is available, and F24 records that as a permanent limitation rather than
a gap to be filled later.** Do not build towards it, and do not fill
`data/processed/label_agreement.json` with a number: `compared: 0` and a null kappa are the
honest state.

Every figure in this project comes from one person reading one set of images. The write-up
says so in these words: *the reference is one interpreter's reading, and inter-interpreter
agreement was not measured.* Not "the labels were validated", and not "ground truth".

**A second pass has to be a different person.** The same person re-judging measures how
consistent one reader is with themselves. That is a real thing to measure and it may be
worth doing, but it is not agreement between interpreters and must never be reported as one.

The machinery stays, because it costs nothing to keep and works the day someone is
available, for part of the boxes as well as all of them:

```
python scripts/label_second_pass.py            # build the second file and its project
python scripts/label_second_pass.py --compare   # kappa, agreement, disagreements
```

The first command writes `data/labels/biak_labels_pass2.gpkg` and `biak_labels_pass2.qgz`:
the same 142 boxes and the same imagery, with `class`, `confidence` and `notes` emptied, so
the second reader cannot see the first answers. **Do not open the pass-2 project for your
own judging** — the boxes you are filling in live in `biak_labels.qgz`, and anything entered
in the pass-2 file is either lost or mistaken later for a second reader's work.

`--compare` counts only the boxes both passes judged and reports the rest as `not_compared`,
so a partial second pass still gives a usable figure. Neither answer wins automatically:
the disagreement rate is the result, and deciding a reconciled label is the owner's job, box
by box, with a reason recorded.
