# Task 20 — When burning is first seen from the geostationary orbit (PLAN.md Phase 4, item 4)

VIIRS looks at Biak about twice a day, around 13:00 and 01:00 WIT. An event's `first_seen`
(Task 16) is therefore the first *polar-orbit look* that caught it. It is not when the
burning began, and nothing in the project can say when it began. What Himawari-9 can do,
every 10 minutes at 2 km, is narrow the gap: **the last slot at which the event's pixels
were clear and quiet, and the first slot at which they were anomalously hot.** This task
computes that bracket for the largest events and records the diurnal cycle of the peak
days.

## Read first: what this may and may not be called

- PLAN.md Phase 4 item 4 calls this "ignition timing" and says the hour discriminates
  natural from human causes. **Section 8 overrides that sentence.** No field, key, comment,
  caveat or line of your final message may contain "ignition", "ignite", "started", "set",
  "cause", "natural", "human", "arson", or anything that assigns a reason or a person. The
  words are "first Himawari flag", "onset bracket", "last quiet slot".
- An onset bracket is **when Himawari first registered heat above its detection floor**.
  At 2 km, a small or smouldering fire can burn for hours below that floor (PLAN.md 13.5).
  The bracket is an upper bound on when heat was present, never a start time.
- PLAN.md section 13 is required reading: the reader, the provisional thresholds, the
  land-pixel restriction, and the one pixel that decayed after sunset all come from there.

## Reuse the existing reader. Do not write a second one.

`src/himawari.py` (Task 05/06) already reads AHI L1b from the public AWS bucket
`noaa-himawari9` over plain HTTPS: `read_hsd`, `counts_to_bt`, `lonlat_grid`, `locate_aoi`,
`segment_window`, `flag_anomalies`, `slot_key`, `fetch_slot_file`. Import them. Write the
new code in `src/himawari_onset.py`.

**One fix in the shared code first, because it breaks AGENTS never-2 today.**
`fetch_slot_file` returns `None` for *any* non-200 response, so a throttled or failed
request (403, 500, 503, timeout) looks exactly like a slot that does not exist upstream.
Change it so that:

- HTTP 404: the slot is absent upstream. Return `None`, as now.
- Any other non-200, or a 200 body under 10,000 bytes: **raise**, naming the key and the
  status. It is a failed request, not an empty slot.
- A `requests` exception propagates as it does now.

Fix it in `fetch_slot_file` itself, so the evening product gets the same behaviour. Check
that nothing calls it expecting `None` for a failure (the evening product runs by hand, not
from the cron; confirm in `.github/workflows/` and say what you found).

## Which events, and which pixels

- **Events:** `n_detections ≥ himawari_onset.min_detections` in `data/processed/events.json`
  (5, the burned-area bar; 31 events when this task was written, 21 of them between 19 and 24
  August 2026).
- **Event pixels:** for each member detection (positions from the store by `detection_id`,
  via the membership in `events.json`, as `burned_area_gee.py` does), the AHI pixel whose
  centre is nearest. The event's pixel set is the union. Record the pixel count per event.
  No buffer: a 2 km pixel already covers several VIIRS pixels.
- The segment(s) an event needs come from the navigation block via the existing
  `locate_aoi`/`segment_window`, never hard-coded. Fetch only the segments an event's pixels
  and their background window need.

## The window

From `floor10(first_seen_utc) − lookback_hours` to `floor10(first_seen_utc) +
after_minutes`, at 10-minute cadence, where `floor10` rounds down to the slot.

- `lookback_hours: 12` reaches back to about the previous VIIRS night overpass. Say so in
  config.
- `after_minutes: 30` keeps the slots at and just after the VIIRS look. They are the
  **validation**: if Himawari does not flag the event at the time VIIRS saw it, it cannot
  time it either.

## Per slot, per event: three states that must stay apart

For every slot in the window, the event is in exactly one state:

1. `missing`: a band-segment it needs is absent upstream (404). Not a zero (AGENTS
   never-2).
2. `obscured`: every event pixel has `bt14 < cloud_bt14_k`. Cloud tops are cold; a cloudy
   pixel cannot show heat underneath it. **Obscured is not quiet.**
3. `flagged`: at least one non-obscured event pixel is flagged by `flag_anomalies` with the
   configured `himawari_min_anomaly_k`, `himawari_min_bt_diff_k` and
   `himawari_background_window_px` (the existing top-level keys; do not duplicate them).
4. `quiet`: none of the above: at least one pixel was clear, and none was flagged.

`cloud_bt14_k: 285`. Its basis: over the 727 land pixels of the 2026-08-22 evening run,
night-time B14 had a median of 294.9 K and a 5th percentile of 286.7 K, and the 37 flagged
pixels were all above 299 K. It is provisional and it is **not a cloud mask**; thin cirrus
passes it. Say that in config and in the caveats, and report the per-event distribution of
the minimum event-pixel B14 so the reviewer can see where the threshold bites.

## The bracket, per event

- `first_flag_utc` / `_wit`: the earliest `flagged` slot in the window, or null.
- `last_quiet_utc` / `_wit`: the latest `quiet` slot **before** `first_flag_utc`, or null.
- `gap_minutes`: `first_flag − last_quiet`; the bracket width.
- `gap_states`: counts of `missing` and `obscured` slots inside the gap. A wide gap full of
  cloud says the onset is unknown within it; the reader must see that.
- `seen_at_viirs`: whether any slot in `[floor10(first_seen_utc), floor10(first_seen_utc) +
  after_minutes]` is `flagged`.
- `lead_minutes`: `floor10(first_seen_utc) − first_flag_utc`, positive when Himawari
  flagged the event before VIIRS saw it.
- `state_counts`: per state, over the whole window.
- the per-slot state list itself (`slot_utc`, `state`, max anomaly and max B07−B14 over the
  clear event pixels, min B14 over all event pixels), so every bracket can be checked.

**Pre-registered reading, in this order.** Do not change it after seeing the results.

1. `too_few_slots`: fewer than `min_slot_share` of the window's slots are not `missing`.
2. `not_resolved`: `seen_at_viirs` is false. Himawari did not register the event even when
   VIIRS did, so no bracket is reported for it; `first_flag_utc` is still stored, but
   the event is excluded from every summary below.
3. `flagged_from_window_start`: the first slot of the window is already `flagged`. The
   bracket is open on the left: the heat predates the lookback.
4. `bracketed`: there is a `last_quiet_utc`.
5. `no_quiet_slot`: flagged, but every earlier slot is `missing` or `obscured`.

Summary: counts per reading; for `bracketed` events, the WIT hour of `first_flag` as a
table, the median and range of `lead_minutes` and `gap_minutes`. Say how many events share
their first-flag slot with another event (the August events overlap; one plume of heat is
not many onsets, as `n_concurrent_events` said for METAR in F15).

## Two named cases

1. **Peak-day diurnal cycle.** For the WIT days `diurnal_days` (2026-08-21 to 2026-08-24),
   every 10-minute slot, AOI-wide over land pixels (the existing land test, as the evening
   product uses it): `n_land_px`, `n_obscured`, `n_flagged`, and the slot's day/night label
   from the existing `is_night`. This is the burning's own diurnal curve, measured, and it
   sits beside F15's smoke-at-the-airport hour table. Report per WIT hour: flagged pixels
   summed and obscured share.
2. **Anjareuw, 4 September 2026.** F10 records that the surveyor photographed E0463's
   ground actively smoking on 4 September at 13:53 WIT and that nothing was detected that
   day. For E0463's pixels, the per-slot state list for WIT day 2026-09-04. The question is
   only whether the pixels were `obscured` around the VIIRS looks of that day. Use E0463's
   member detections as the pixel set. **Nothing from `fieldwork/` is read**, and no
   surveyor position enters any file.

## Configuration

```yaml
himawari_onset:
  min_detections: 5
  lookback_hours: 12
  after_minutes: 30
  cadence_minutes: 10
  cloud_bt14_k: 285
  min_slot_share: 0.8
  diurnal_days: ["2026-08-21", "2026-08-24"]   # inclusive WIT days
  named_case: {event_id: E0463, wit_day: "2026-09-04"}
```

Every value gets a comment giving its reason. AGENTS always-5: nothing hard-coded in the
module.

## Fetching and disk

- `python src/himawari_onset.py --fetch` downloads; without `--fetch` it reads the raw files
  already present and **exits non-zero naming the first slot it lacks**. Never from the cron.
- Raw band-segments go to `data/raw/himawari/` as now (gitignored, AGENTS always-2). About
  1,600 unique slots, 2 bands, 1-2 segments: **roughly 8-17 GB.** Before downloading,
  print the number of files to fetch and their estimated size, and state the real total in
  your final message. Files already present are not fetched again.
- A raise from `fetch_slot_file` stops the run and writes nothing. **No placeholder file,
  no synthetic brightness temperatures, no generator of stand-in values**, not to make a test
  pass, not to fill a gap, not labelled as synthetic either.

## Output

`data/processed/himawari_onset.json`, sorted keys, indent 1, no timestamp; add it to the
`data/processed/` allowlist in `.gitignore`. It holds the parameters (including the three
existing threshold keys as used), the events assessed and those below the bar, the
per-event records with their state lists, the reading counts and summaries, both named
cases, and a `caveats` list, verbatim:

- "A first Himawari flag is when heat first rose above a 2 km sensor's detection floor. Burning
  can run below that floor for hours, so the onset bracket bounds when heat was present; it
  is never a start time."
- "Obscured means the event's pixels were colder than the cloud threshold (B14). It is not a
  cloud mask: thin cloud passes it, and an obscured slot says nothing about the ground."
- "In daylight, reflected sunlight raises the 3.9 um band. The anomaly is measured against the
  local background, which removes most of it; the thresholds remain provisional (PLAN.md
  13.4)."
- "Timing says nothing about why land was burned or who burned it (PLAN.md section 8)."

Print the reading counts, the first-flag WIT-hour table, the diurnal hour table and the
E0463 state list to stdout.

## Do not write the finding

**Do not add an entry to `FINDINGS.md`,** as in Tasks 17 and 19. It is written at review
from `himawari_onset.json`. Put the reading counts, the tables and the real download size
in your final message.

## Check

`tests/test_himawari_onset.py`, offline, synthetic arrays and state lists built inside the
test. Raw Himawari files are gitignored and must not be read by a test.

1. States: a slot with a 404 band is `missing`; all event pixels below `cloud_bt14_k` is
   `obscured` even if one is flagged; one clear flagged pixel is `flagged`; one clear pixel
   and no flag is `quiet`.
2. Bracket: `quiet, obscured, obscured, flagged` gives `last_quiet` at slot 0,
   `gap_minutes` 30 and `gap_states` {obscured: 2}.
3. Readings in order: an event not flagged at the VIIRS slots is `not_resolved` even with
   earlier flags; a window whose first slot is flagged is `flagged_from_window_start`;
   `missing` above the share makes `too_few_slots` whatever else holds.
4. `fetch_slot_file` with `requests.get` replaced inside the test: 404 returns `None`;
   503 raises; a 200 with 500 bytes raises. No network.
5. Pixel matching: two detections inside one synthetic AHI pixel give one pixel, not two.
6. `floor10` and the window edges: first_seen 04:47 UTC gives slots 16:40 the previous day
   to 05:10.
7. No key in the output contains "ignit", "cause" or "start".
8. The same state lists give byte-identical JSON.

## Out of scope

- Changing the evening product, its thresholds, or its cron status. The fetch fix is the only
  change to `src/himawari.py`.
- A real cloud mask, fire-radiative power from Himawari, spread mapping, or any event not
  above the bar.
- JAXA P-Tree and its WLF fire product (credentials; PLAN.md 2.1).
- The dashboard, the brief, `docs/`.
