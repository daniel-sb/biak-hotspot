# Task 18 — Burned area per event (PLAN.md Phase 4, items 1-3)

Task 16 made the event the unit. This task asks, for each event large enough to see from
Sentinel-2: **how much ground burned, how sure can we be, and what was it before it burned.**
It is the central result the RS/GIS paper is missing: detections say where heat was seen,
burned area says what changed on the ground.

Items 1-3 of PLAN.md Phase 4. Item 4, Himawari ignition timing, is a separate task.

## Index: dNBR+, bi-temporal, as F7 and F8 settled

NBR+ = (B12 − B8A − B3 − B2) / (B12 + B8A + B3 + B2), on reflectance scaled /10000, HIGH
means burned. Reuse `burn_indices_gee.scaled` and `burn_indices_gee.indices_of` rather than
writing it again. dNBR+ = post − pre.

F7 chose NBR+ for its false alarms over sea and cloud. F8 recorded that NBR+ *separates*
burning-plausible land least well of the six indices, so this task must not assume the
index is strong; the threshold below is what keeps it honest.

## The threshold, without reference data

The NBR+ paper sets its threshold with a supervised classifier trained on field sites.
There are no field sites here - three survey plots and fourteen roadside photographs, no
unburned controls - and F7 declined to choose a threshold for exactly that reason.

So the threshold is **set by false-alarm rate, not by accuracy**, and it is local:

- Around each event, a **reference ring**: land within `ref_radius_m` of the event
  centroid, farther than `far_m` from **every detection in the store, any year** (F7's
  "far" stratum), excluding permanent water. Land that has never been seen hot.
- The event's threshold is the **`ref_quantile` (0.99) of dNBR+ over the clear pixels of
  that ring**, computed on the same composites as the event itself.
- By construction, 1% of never-detected land nearby exceeds it. A pixel in the event
  footprint above it is "changed more than 99% of nearby land that never burned".

Say this in the output in those words. It is a **false-alarm-controlled** threshold. It is
not calibrated against ground truth, it has no stated accuracy, and it will miss light
burns that change reflectance less than the local noise. Report it as an estimate of area
that changed like a burn, never as "burned area" without that qualifier.

**If the ring has fewer than `min_ref_px` clear pixels, the event gets no threshold and
no area.** Record `"no local reference"` and move on. No fallback threshold, no borrowed
threshold from another event, no fixed number.

## Composites: the nearest clear look, per pixel

Each event gets its own pre and post images, because events run from 2023 to 2026 and a
single pair cannot serve them.

- **Pre:** Sentinel-2 SR Harmonized in `[first_seen − pre_days, first_seen − 1 day]`.
- **Post:** `[last_seen + 1 day, last_seen + post_days]`.
- Mask cloud with Cloud Score+ (`GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED`,
  band `cs_cdf` ≥ `cs_min`), linked with `linkCollection`. Mask permanent water with
  `ESA/WorldCover/v200/2021` class 80, as `burn_indices_gee` does.
- For each pixel take the **clear observation nearest the event**: the latest one in the
  pre window, the earliest one in the post window. In Earth Engine that is
  `sort('system:time_start', ascending).mosaic()` for pre and descending for post; check
  which way `mosaic()` stacks before trusting it, and say in a comment how you checked.
  A median across the window would mix pre-fire and regrowth reflectance, and tropical
  regrowth is fast.
- Carry the acquisition date as a band through each mosaic, and report per event the
  median and 90th percentile of **days between the event and the look used**, pre and post.
  An area computed from a look 25 days after `last_seen` is not the same measurement as one
  from 3 days after, and the reader must be able to see which it is.

`post_days` is a trade: short means more cloud gap, long means more regrowth. Start at 30;
record the choice and its reason in config.

## Footprint

The event footprint is the union of `footprint_m`-radius circles around its member
detections' positions (read positions from the store by `detection_id` via the membership
in `events.json`). Start at 375 m: one VIIRS pixel, which also absorbs its geolocation
jitter. Burning outside the footprint is not attributed to the event.

## Which events

`n_detections ≥ min_detections` (start at 5; 31 events at the time of writing, 25 of them
in 2026). Everything below is listed in the output as not assessed, with the reason.

## Per-event record

- `event_id`, `first_seen_wit`, `last_seen_wit`, `n_detections`
- `footprint_ha`; `clear_ha` (clear in both pre and post); `clear_fraction`
- `threshold`, `ref_clear_px`, or `"no local reference"`
- `changed_ha`: clear footprint pixels with dNBR+ above the threshold
- `expected_false_ha`: `(1 − ref_quantile) × clear_ha` - what the threshold admits on
  land that never burned
- `changed_ha_upper`: `changed_ha + (footprint_ha − clear_ha)`, the bound if every
  cloud-gap pixel had changed. **The cloud gap is uncertainty, and PLAN.md Phase 4
  requires it published beside every area.**
- `dnbr_p50_changed`, and the pre/post look-lag statistics
- **Land cover before the event:** Esri 10 m annual land cover
  (`projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS`) for the **calendar
  year before** `first_seen` - 2025 for 2026 events, 2024 for 2025, and so on - so the
  class describes the land before it burned, not after. Report `changed_ha` by class **and**
  the footprint's clear area by class, so a reader can see whether burning favoured a class
  or merely followed what was there.

Why Esri and not Dynamic World: in the south-coast corridor the surveyor walked, Esri maps
14.3% shrub and Dynamic World 4.6%, with Dynamic World's tree label holding a median margin
of 0.647 over the runner-up - confident, and against what was seen on the ground. That is
recorded for review, not in `FINDINGS.md`, at the owner's instruction.

## Polygons

PLAN.md Phase 4 item 2. `reduceToVectors` on each event's changed mask, clipped to its
footprint, at 20 m, with `event_id` and `threshold` as properties. Write all events to
`data/processed/burned_areas.geojson`. Keep it out of `docs/`.

## Output

`src/burned_area_gee.py`, run by hand like the other `*_gee.py` scripts, never from the
cron. Writes:

- `data/processed/burned_areas.json` - parameters, per-event records, the list of events
  not assessed and why, and a `caveats` list;
- `data/processed/burned_areas.geojson` - the polygons.

Both are added to the `data/processed/` allowlist in `.gitignore`. Sorted keys, no
timestamp.

Caveats, verbatim:

- "Areas are pixels whose dNBR+ exceeds the 99th percentile of never-detected land within
  the event's reference ring. This controls false alarms on land that never burned; it is
  not an accuracy, and light burns below the local noise are missed."
- "Each pixel uses the clear Sentinel-2 look nearest the event, so dates vary within one
  event; the look-lag statistics say by how much."
- "changed_ha_upper assumes every cloud-gap pixel changed. The true area lies between
  changed_ha and changed_ha_upper, less expected_false_ha."
- "A change like a burn is not proof of burning, and says nothing about why land was
  burned or who burned it (PLAN.md section 8)."

## Constraints

- **If Earth Engine cannot be reached or refuses a request, stop and write nothing.** No
  placeholder file, no synthetic reflectance, no generator of stand-in values. AGENTS
  never-2: a refused request is not an empty area.
- Reuse `burn_indices_gee.scaled`, `indices_of`; the events and store are read, never
  written.
- Wording, everywhere: "changed like a burn", "burn-like change", "estimated". Never
  "destroyed", "deforested", "illegal", or anything that assigns cause.

## Check

`tests/test_burned_area.py`, offline. Earth Engine is not reachable from a test, so the
check covers the parts that do not need it:

1. footprint construction from member detections, including the union of overlapping
   circles;
2. the Esri year rule (event in 2026 → 2025 map; January 2026 → still 2025);
3. `changed_ha_upper`, `expected_false_ha` and `clear_fraction` arithmetic on hand values;
4. an event whose reference ring is below `min_ref_px` gets no area and the reason;
5. event selection by `min_detections`, with the rest listed as not assessed.

## Out of scope

- Himawari ignition timing (Phase 4 item 4) - its own task.
- Any accuracy figure. There is no reference data. The field plots and photographs may be
  overlaid by hand for a qualitative look, locally, and never enter a tracked file: they
  are GPS positions on people's land with no ethical clearance.
- Burn severity classes. dNBR+ has no published severity scale.
- The dashboard, the cron, `docs/`.
