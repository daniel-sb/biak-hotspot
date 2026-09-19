# Task 16 — Group detections into burning events (PLAN.md Phase 3, items 1-2)

Everything downstream in this project that talks about "a fire" is currently talking about
detections: 1,127 points, each one a pixel that was hot at an overpass. Phase 4 postmortem,
per-event ignition timing, and every table the RS/GIS paper will need are about *events* -
the same patch of ground burning across one or several overpasses. This task builds the unit.

It does **not** build Phase 3 items 3 and 4 (the 30-day environmental overlay and the
generated chronology). See "Out of scope".

## The algorithm

Space-time DBSCAN on the stored detections, as PLAN.md Phase 3 specifies:

- two detections are neighbours when they are within `eps_m` metres **and** within
  `eps_hours` of each other, measured on `datetime_utc` (AGENTS always-1);
- a detection with at least `min_samples - 1` neighbours is a core point;
- an event is a set of core points connected through neighbours, plus the border points
  they reach.

Write it with the standard library and pandas. No scikit-learn (AGENTS never-7). Do not
build an n-by-n distance matrix: sort by time and compare each detection only with those
inside the `eps_hours` window after it, so the cost grows with the burning rate rather than
with the square of a store that grows every day.

Distances are metres on a local plane: latitude times `recurrence.M_PER_DEG`, longitude
times the same constant times cos(latitude). Reuse the constant; do not add a geodesy
library.

**Noise is not discarded.** A detection DBSCAN calls noise becomes an event of one, with
`singleton = true`. A single VIIRS pixel on a single overpass is the commonest thing a
small plot burn produces on this island, and dropping it would be AGENTS never-5 by another
name.

## Parameters live in config, and are tuned, not assumed

Add an `events:` block to `config.yaml` with `eps_m`, `eps_hours`, `min_samples`, each with
a comment giving the reason for its value. PLAN.md's starting point is 1000 m, 24 h, 2.

Then tune. Run a small grid - at least `eps_m` in {375, 750, 1000, 1500} and `eps_hours`
in {12, 24, 48} - and for each combination report: number of events, number of singletons,
the largest event's detection count, its duration, and its spatial extent in km. Print it;
put the chosen row and the reason in `FINDINGS.md`.

The failure to watch for is **chaining**. Single-linkage chained the airport fires to 2023
detections 2 km away in Task 04 (PLAN.md 11.4). Here the risk is worse: 21-22 August 2026
put 485 detections on the south corridor in two days, and with a generous `eps_m` the whole
corridor can collapse into one island-spanning "event" made of dozens of separate plots.
That result must be visible in the tuning table, not discovered later.

## Known events the parameters must get right

PLAN.md Phase 3 asks for at least three. Check these, and say in the output what each
parameter set does to them:

1. **The 19-25 August 2026 event** (PLAN.md 10.4) - corroborated by METAR, clean onset and
   decay. Expected: it is *many* events, not one. It spans Biak and Numfor, and islands
   40 km apart are not one fire.
2. **The August 2026 airport-adjacent burning** (PLAN.md 11.3) - 35 detections within 3 km
   of Frans Kaisiepo in August 2026. Expected: they cluster among themselves and do not
   chain to the November 2023 or April 2026 detections in the same area.
3. **The Saramom recurrent site** (PLAN.md 11.2, 11.4) - 74 distinct days over three
   years at one place. Expected: many separate short events at the same location. A
   recurrent *location* is Task 04's concept; an *event* is one burning episode, and a site
   that burns in 2023 and again in 2026 is two events, never one.
4. **3-4 September 2026, Anjareuw** - detected on 3 September, photographed still smoking by
   the surveyor on 4 September at 13:53 WIT and not detected that day. A field-corroborated
   event, and the reason `last_seen` must never be read as "burning stopped".

## Stable identity

IDs are `E0001`, `E0002`, ... and name an episode, not a rank. On a re-run, a new event
inherits the ID of the prior event it shares the most `detection_id`s with. Growth keeps the
ID. When two prior events merge, the merged event keeps the ID of the one that had more
detections, and the other ID is retired and recorded as merged into it. Numbers are never
reused.

Changing any parameter invalidates the correspondence. When the stored parameters differ
from `config.yaml`, rebuild from scratch, increment `registry_version`, and say so in the
file - the same contract `recurrence.py` already keeps for site IDs.

## Per-event record

For each event, at least:

- `event_id`, `singleton`, `n_detections`, `satellites` (sorted list), `n_overpasses`
  (distinct `datetime_utc` values)
- `first_seen_utc`, `last_seen_utc`, and the same two in WIT; `duration_hours`
- `frp_sum`, `frp_max` - NaN FRP is excluded from both and counted in `n_frp_missing`
- `centroid_lat`, `centroid_lon`; `first_lat`, `first_lon` (mean position of the detections
  at `first_seen_utc`)
- `hull_area_ha` - convex hull of detection centres via shapely, on the local metre plane;
  `null` below three non-collinear points. It is a lower bound: it ignores pixel footprint.
- `road_m`, `road_class` at the first-seen position, using `fieldwork_gpkg.load_roads` and
  `nearest_road` on the tracked OSM file
- `desa`, `distrik` - the most common among members; ties broken alphabetically
- `recurrent_share` - fraction of members carrying `recurrent_site = true`
- `on_land_share` - fraction with `on_land = true`

**Wording.** The column is `first_seen`, never `ignition`. A polar orbiter sees a patch of
ground twice a day at best; the first detection is the first overpass that caught heat, not
the moment anything was lit. PLAN.md section 8 applies to every field name and every line of
output: nothing here says why something burned or who burned it.

## Output

- `data/processed/events.json` - parameters, `registry_version`, `next_number`, retired
  IDs with what they merged into, the event records, and the membership map
  `detection_id -> event_id`. Tracked, because stable IDs depend on it. Written with sorted
  keys and no timestamp, so the same store yields byte-identical output.
- `data/processed/events.csv` - the event records flattened, one row per event, for reading
  and for the paper's tables.

Do **not** add a column to `detections.parquet`. The daily ingest rewrites that store, and
a column it does not know about is a column waiting to be silently dropped.

## Check

`tests/test_events.py`, offline, synthetic frames in the style of `tests/test_recurrence.py`:

1. two detections 800 m and 10 h apart are one event; at 1200 m they are two; at 30 h two
2. a fire seen on three consecutive days at the same spot chains into one event
3. an isolated detection becomes a singleton event, not a dropped row
4. every input `detection_id` appears in the membership map exactly once
5. re-running with one added detection that extends an event keeps its ID
6. a merge keeps the larger event's ID, retires the other, and the retired number is not
   handed to any later event
7. the same input yields byte-identical `events.json`

## Out of scope

Say these in your final message; do not build them:

- **Land cover at first-seen.** The only land-cover raster in hand is the Esri 2025 cache
  under `geolibre_data/`, which is gitignored and pulled from Earth Engine by hand. A
  tracked, offline land-cover layer is its own task.
- **Distance to settlement.** There is no settlement layer in the repository.
- **Phase 3 item 3**, the 30-day environmental overlay before each event.
- **Phase 3 item 4**, the generated chronology narrative.
- Wiring into the daily cron, and anything on the dashboard.
