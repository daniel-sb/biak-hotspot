# Drawing the burn-scar labels

The project file is `data/labels/biak_labels.qgz`. Open it in QGIS 3.44 LTR.

These polygons become the reference that the Task 18 burned-area product is measured
against (Task 22). Nothing else in this project can do that: the field survey was stopped
by security conditions, and F18 showed that no prompted segmentation model can stand in.

## What you are looking at

| layer | what it is |
|---|---|
| **LABELS — draw here** | empty; your polygons go here |
| samples | 42 points, 7 inside and 7 outside each event's VIIRS footprint |
| VIIRS footprints | 375 m circles round the detections — where the samples were drawn from, not truth |
| VIIRS/MODIS detections | the individual satellite detections |
| S2DR4 1 m imagery | SWIR and true colour for each event, 28 August 2026 |

Only the SWIR image for E0313 is switched on at the start. Tick the others as you move
between events.

**There is no dNBR+ layer, on purpose.** These labels judge that product, so seeing it
while drawing would make the comparison worthless. Do not add it.

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

## The job: one polygon per sample point

1. Select **LABELS — draw here**, then toggle editing (the pencil, or Ctrl+E).
2. Zoom to a sample point. Its `sample_id` is drawn beside it, e.g. `E0313-IN03`.
3. Draw a polygon around the **homogeneous patch the point sits in**: same tone, same
   texture, bounded by whatever boundary you can actually see — a plot edge, a track, a
   tree line. Follow the patch, not a fixed shape.
4. Right-click to finish. The form opens.
5. Fill it in:
   - `sample_id` — copy the point's id exactly;
   - `event_id` — `E0301`, `E0313` or `E0368`;
   - `class` — `burned`, `unburned` or `unsure`;
   - `confidence` — `high`, `medium` or `low`;
   - `notes` — free text, only if something needs saying;
   - `drawn_on` fills itself with today's date.
6. Save the layer (Ctrl+S). Do it often; QGIS keeps edits in memory until you do.

Aim for a patch of roughly 0.5 to 3 hectares: big enough to hold several 20 m pixels,
small enough to stay genuinely uniform. A polygon of one hectare is 100 m by 100 m, which
is 25 pixels of the product being tested.

## The rules that keep this honest

- **`unsure` is a real answer.** Thin smoke, cloud shadow, a patch you would argue about —
  mark it `unsure` and move on. Task 22 drops those and reports how many there were. A
  guessed label is worse than no label, because it silently moves the accuracy figure.
- **Do not move a sample point** to somewhere easier to judge. The points were drawn at
  random from a fixed seed; moving them to convenient ground is exactly the bias the random
  draw exists to prevent. If a point lands in water, on a roof, or in cloud, draw the
  polygon anyway and mark it `unsure` with a note.
- **Inside the footprint does not mean burned.** The footprint only says a satellite saw
  heat within 375 m at some point. Plenty of ground inside it did not burn, and that is
  precisely what the labels are meant to establish. Judge each patch on the imagery.
- **Outside the footprint does not mean unburned** either. If it looks burned, label it
  burned.
- **One polygon per point.** Do not draw several small ones, and do not merge two points
  into one polygon.
- **Do not use the detections as evidence.** They tell you where heat was seen, which is
  the very thing the product is trying to convert into area. Use them to orient yourself,
  not to decide.

## When you are done

```
python scripts/label_check.py
```

It reports how many polygons exist, whether each holds its own sample point, the class
counts by stratum, and anything malformed. It changes nothing.

Partial work is fine — the check tells you what is left. Task 22 can run on fewer than 42
polygons, it will just say so and carry a wider uncertainty.
