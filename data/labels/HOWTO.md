# Judging the burn-scar labels

**28 boxes are waiting for a judgement, and they carry the widest part of the project's
headline number.** Open `data/labels/biak_labels.qgz` in QGIS 3.44 LTR, not 4.2, and fill in
the `class` and `confidence` of every box that still has neither.

These labels are the reference that the Task 18 burned-area product is measured against.
Nothing else in this project can do that job: the field survey was stopped by security
conditions, and F18 showed that no prompted segmentation model can stand in.

## What the 28 boxes settle

With 114 of 142 boxes judged, the estimate is **904 ha** and the map being tested claims
**819 ha**. Both defensible intervals now put the map inside, which is a change from the
state this guide described earlier:

| treatment | 95% interval | the map's 819 ha |
|---|---|---|
| Wilson per stratum (F22) | 698 to 1112 ha | inside |
| Olofsson et al. 2014, normal approximation (F23) | 748 to 1060 ha | inside |

So the question the remaining boxes answer is no longer whether the two intervals disagree.
It is how wide the interval stays, and that is decided almost entirely by one of the two
terms:

| term | estimate | 95% interval | width |
|---|---|---|---|
| commission — area the map claims that did not burn | 719 ha | 610 to 776 | 166 ha |
| **omission — area that burned and the map missed** | **185 ha** | **88 to 336** | **248 ha** |

The omission term is a quarter of the area and carries the larger uncertainty, because it
rests on **26 decided units standing for 800 ha of unmapped ground**. The 28 boxes left are
all in that stratum. Judging them raises the decided count from 26 towards 54, which roughly
halves the standard error on the 23% burned rate behind the 185 ha.

Partial work helps. Every box judged narrows the interval a little, and
`scripts/label_accuracy.py` counts the unjudged ones nowhere rather than guessing them, so
the figure above is already an honest n=114 result and not a placeholder.

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

The project holds 85 layers. Four are vectors, and the rest are imagery grouped by
acquisition date.

| layer | what it is |
|---|---|
| **LABELS — draw here** | 142 boxes of 60 x 60 m, already placed. You fill in the class |
| random_box seed points, 42 of them | the points the first 42 boxes were centred on. The other 100 boxes have no point here |
| VIIRS footprints (strata, not truth) | 375 m circles round the detections, the frame two strata were drawn from |
| VIIRS/MODIS detections | the individual satellite detections |
| one group per date: `17/09/2026` … `13/08/2026` | the imagery, 12 layers each |
| Sentinel-2 20 m: before, mid-episode, after (older, undated) | superseded, switched off, kept only because the dNBR+ product compared these particular chips |

Each date group holds the same 12 layers: for each of the three events, four images.

| layer in a date group | resolution | what it is |
|---|---|---|
| `E0313 Yendidori — SWIR B12/B8A/B4 — 1 m` | 1 m | S2DR4 super-resolved, the one to judge from |
| `E0313 Yendidori — true colour — 1 m` | 1 m | S2DR4 super-resolved, for identifying features |
| `E0313 Yendidori — SWIR B12/B8A/B4 — 20 m, as the sensor saw it` | 20 m | **native Sentinel-2, unprocessed** |
| `E0313 Yendidori — true colour — 10 m, as the sensor saw it` | 10 m | **native Sentinel-2, unprocessed** |

The project opens on the `23/08/2026` group with the three 1 m SWIR layers switched on.
Every other group starts collapsed and off. Tick them as you go.

**There is no dNBR+ layer, on purpose.** These labels judge that product, so seeing it
while judging would make the comparison worthless. Do not add it.

## The dates

All three events were first detected between 19 and 22 August and all three ran until
25 August, so no single image shows the whole story. Six dated scenes are in the project.

| date | relation to the events | tile cloud | sensor |
|---|---|---|---|
| **13 August** | **before all three**, 6 to 9 days ahead of the first detection | 39.4% | S2C |
| 23 August | mid-episode, the clearest scene in the set, and the field survey's basemap | **0.4%** | S2C |
| 25 August | the last detection day | 15.6% | S2A |
| 28 August | after, and the image dNBR+ compared against | 41.9% | S2B |
| 2 September | 8 days after the last detection | 20.1% | S2C |
| 17 September | 23 days after, and inside the September episode | 37.5% | S2B |

**A fresh scar reads bright orange on 23 August and fades to dull brown by 28 August.** That
fading is the most reliable sign you have. Ground that was already open before the event
looks the same on every date, and that is the difference between burnt and merely bare.

So the question to answer for each box is not "does this look burnt" but **"did this change
between the dates, and does the change look like burning"**. dNBR+ measures change between
two looks; judging one date alone asks something different, and the two then disagree for
reasons that have nothing to do with accuracy.

**13 August is the date that matters most for the boxes that are left.** They are all on
ground the map does not claim, where the judgement usually turns on whether a dull patch is
a scar or was already open. A dated pre-event image answers that directly, and until
2026-10-15 the project had only an undated Earth Engine chip for it.

The cloud column is there because it decides which date can be read at all over a given box.
23 August at 0.4% is clean nearly everywhere. 28 August at 41.9% is not, and a box that
looks dark there may be under cloud rather than burnt.

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

All four images in a date group share one fixed brightness scale, 1 m and native alike, so
these colours mean the same thing in every tile and can be compared between events and
between resolutions. (An earlier version of this imagery stretched each channel separately,
which showed vegetation orange and burnt ground blue. If you see that, the imagery is stale —
see the warning about `label_prepare.py` in the script table.)

### The 1 m image is a model's output, and it removes cloud, haze and smoke

This is the most important thing to understand about what is on the screen.

S2DR4 reads the native 10 and 20 m Sentinel-2 bands and generates a 1 m image from them. It
does not merely sharpen: it reconstructs, and part of what it reconstructs is **ground that
was hidden under cloud, haze or smoke**. Where the sensor saw smoke, the 1 m image shows
plausible ground instead.

That is why every date group carries the native 20 m and 10 m chips beside the 1 m pair.
**Use them.** The procedure is:

1. Judge on the 1 m SWIR, as before.
2. Before you commit a box, switch on `true colour — 10 m, as the sensor saw it` above the
   1 m layer and toggle it.
3. If the native image shows cloud, haze or smoke over the box, **the 1 m pixels under it
   are reconstruction, not observation**. Mark the box `unsure` and say so in `notes`.

This applies to the boxes already judged as much as to the ones left: the chips have always
had this property, and it has only now been made visible. 23 August, where most judging was
done, is the least affected date at 0.4% cloud. 28 August (41.9%), 17 September (37.5%),
13 August (39.4%) and 2 September (20.1%) are the ones to check.

Beyond the cloud question, the same caution as always: trust the shape of a patch and the
contrast between patches. Do not trust a single sharp edge or a small isolated object. Those
are the parts a super-resolution model invents.

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
| `map_burned` | 50 | 50, done | random points inside the dNBR+ polygons of the three events |
| `footprint_unmapped` | 50 | 22, **28 left** (`B23`–`B50`) | random points inside the footprints, on ground the polygons do not claim |

The 28 that are left split by event as follows:

| event | boxes left |
|---|---|
| E0301 Anjareuw | 14 |
| E0313 Yendidori | 8 |
| E0368 Insumarires | 6 |

`map_burned` samples the map being tested, so the burned class is well represented there: 36
of its 41 decided boxes came back `burned`. `footprint_unmapped` samples the unclaimed ground
directly, which is where omission shows up, and it is the thinner half of the evidence: 6 of
16 decided, pooled with 0 of 10 `random_box` boxes inside a footprint, is the whole basis of
the 23% rate behind the 185 ha omission term.

The three strata are never pooled across frames. Each came from its own draw, so each
carries its own inclusion probability, and mixing them would make those probabilities
unknowable. The 42 `random_box` boxes keep their place and are still used, but only for the
stratum their own draw supports.

Sampling by the map is not circular, because the map is never shown while judging. Judging
by the map would be. That is why there is still no dNBR+ layer in the project.

### The steps

1. Open the project, select **LABELS — draw here**, and open the attribute table (**F6**).
2. Toggle editing (**Ctrl+E**).
3. Sort by `class` to bring the empty rows together, or filter the table to them. The 28 that
   are left are `B23` to `B50`.
4. Click a row, then **Zoom to feature**, so the map shows that box.
5. **Look at the dates in turn**, which is the part that decides the answer.
6. Check the native chip for cloud, haze or smoke over the box.
7. Fill `class` with `burned`, `unburned` or `unsure`, and `confidence` with `high`,
   `medium` or `low`. Use `notes` only if something needs saying.
8. Save (**Ctrl+S**) often.

Step 5 is four questions, in this order:

| look at | ask |
|---|---|
| 1 m SWIR, 13 August | was this already open and bare before the event? |
| 1 m SWIR, 23 August | is the box orange, meaning freshly burnt? |
| 1 m SWIR, 28 August | has it gone dull brown, as a scar does in five days? |
| 1 m SWIR, 2 or 17 September | is the scar still there weeks later, as a real one is? |

The table also has a **form view** at the bottom right, which shows one box at a time if
that reads more comfortably than the grid.

Spelling matters, and `scripts/label_check.py` catches anything unexpected.

### What each pattern means

| 13 Aug | 23 Aug | 28 Aug | September | read it as |
|---|---|---|---|---|
| green | orange | brown | brown, fading | burnt during the episode, the clearest case |
| green | green | brown | brown | burnt between 23 and 25 August |
| brown or bare | same | same | same | open ground already, not a scar |
| green | dark patch | green | green | cloud or its shadow, not a scar |
| green | green | green | brown | burnt after the episode, in the September one. Not these events — `unburned` for this reference, with a note |

The last row matters because 2 and 17 September fall inside a second burning episode. These
labels judge the August events only.

### If a box straddles two cover types

Judge what covers most of it. If it is close to half and half, that is exactly what `unsure`
is for.

## The rules that keep this honest

- **`unsure` is a real answer, and it is dropped from the denominator.** Thin smoke, cloud
  shadow, a patch you would argue about — mark it `unsure` and move on. The estimator drops
  those and reports how many there were. A guessed label is worse than no label, because it
  silently moves the accuracy figure. Six of the 22 already decided in this stratum came back
  `unsure`, so expect roughly a quarter of the 28 not to add to the interval. That is the
  honest outcome, not a failure.
- **Check the native chip before committing.** Where cloud, haze or smoke covers the box in
  the 20 m or 10 m image, the 1 m pixels are generated. `unsure`, with a note.
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
  point. Five of the 50 boxes in that stratum came back `unburned` and nine `unsure`. The
  stratum is where the map says it burned, not where it did.
- **Do not use the detections as evidence.** They tell you where heat was seen, which is
  the very thing the product is trying to convert into area. Use them to orient yourself,
  not to decide.
- **Change is the question, not appearance.** Bare ground that looks the same on every date
  is `unburned`, however brown it is. That distinction is the whole reason six dates are
  in the project.
- **Re-judging a box is allowed, and expected.** The first pass was made on one date only,
  before the pre-event and post-event dates existed and before the native chips were there
  to check against. If a box reads differently with the sequence in front of you, change it
  and say why in `notes`. Nothing is gained by defending an earlier call.

## When you are done, or partway through

```
python scripts/label_check.py
python scripts/label_accuracy.py
```

`label_check.py` reports how many boxes exist, the class counts by stratum, the polygon
sizes, and anything malformed or misspelled. It changes nothing.

`label_accuracy.py` is the one that produces the answer. It prints the two-stratum estimate
with **both** intervals, the Wilson one and the Olofsson one, splits the figure into its
commission and omission terms, says whether each interval puts the map's 819 ha inside or
outside, and reports how many boxes are still unjudged and therefore counted nowhere. It
writes `data/processed/label_accuracy.json`.

Partial work is fine. Both scripts say what is left and the interval simply stays wider.

When all 100 drawn boxes are judged, re-run `src/burn_classifier.py` as well: more
positives in the unmapped stratum is what its weakest fold needed. **Do not retune it**
because the sample grew — same features, same defaults, same leave-one-event-out folds.

A new `FINDINGS.md` entry is owed once the 28 are judged: the 904 ha result and its crossover
against F20, written at review, as this project's convention requires.

## The scripts, in the order you need them

| script | interpreter | what it does |
|---|---|---|
| `scripts/label_prepare.py` | geolibre | already run, and **must not be run again**. It rewrites the sample points and renames the dated chips to plain names, which would break both the draw and the date groups |
| `scripts/label_imagery_add.py` | geolibre | the way to add or refresh imagery now. Writes the dated 1 m pairs and the native chips beside them. Leaves existing 1 m chips alone unless you pass `--force` |
| `scripts/label_pre_imagery.py` | geolibre | already run: pulled the undated 20 m before, mid and after chips from Earth Engine. Superseded by the dated groups |
| `scripts/label_qgis_project.py` | **QGIS** | rebuilds `biak_labels.qgz`, one group per date. Never touches the GeoPackage, so judgements survive a rebuild. Refuses to run if the project holds polygon annotations, unless you pass `--force` |
| `scripts/label_add_boxes.py` | geolibre | draws more `map_burned` or `footprint_unmapped` boxes at random, at least 150 m from any existing one |
| `scripts/label_fill_ids.py` | geolibre | only if you add polygons by hand: fills `sample_id` and `event_id` from the point inside each polygon |
| `scripts/label_check.py` | geolibre | reports what is there and what is wrong. Changes nothing |
| `scripts/label_accuracy.py` | geolibre | the estimate, both intervals, and the two terms. Changes nothing but its own JSON |
| `scripts/label_second_pass.py` | **QGIS** | the second-interpreter machinery. Nobody is running it — see below |
| `scripts/s2dr4_dates.py` | geolibre | what date a given request will actually return, and which scenes exist over a tile |
| `scripts/s2dr4_compare.py` | geolibre | compares two S2DR4 tiles pixel by pixel. How the 2026-10 run was shown to hold the same scenes as the 2026-08 one |
| `scripts/label_howto_pdf.py` | geolibre | renders this file to `data/labels/panduan-penilaian-label.pdf` |

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
