# Task 19 — Corroborate burning events against airport smoke reports (PLAN.md Phase 2, item 4)

Field validation on Biak is blocked: three survey plots, no unburned controls, and security
conditions that stopped the last survey. The one **independent ground observation available
at scale** is the airport. Frans Kaisiepo (ICAO `WABB`) reports every 30 minutes, and its
present-weather group carries `FU` (smoke) and `HZ` (haze). PLAN.md 10.2 already showed it
corroborating the August 2026 episode by hand. This task does it systematically, for every
event in `data/processed/events.json` (Task 16).

## Read first: what a METAR can and cannot say

PLAN.md 2.6 and section 12 are not optional background. They define how the result may be
read:

- **An `FU` report is strong positive evidence.** 83 consecutive days before the August
  2026 episode had none at all (PLAN.md 10.2), so smoke at WABB is an anomaly, not noise.
- **The absence of `FU` is close to no evidence.** On the night of 2026-08-27 the airport
  reported 8000 m and no smoke for ten hours while a resident 6.5 km away was in smoke thick
  enough to bring out fire trucks (PLAN.md 12). One sensor, one point, a nocturnal
  inversion.

So the classes below are **asymmetric by design**. An event can be corroborated. It can
never be "refuted", "unconfirmed" or "not burning" on METAR evidence. No label, column
name, comment or sentence in your output may suggest otherwise.

## Source: fetch once, keep the raw file

The Iowa State Environmental Mesonet archive (PLAN.md 10.1):

```
https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py
  ?station=WABB&data=vsby&data=wxcodes&data=drct&data=sknt&data=metar
  &tz=Etc/UTC&format=onlycomma&report_type=3&report_type=4
  &year1=..&month1=..&day1=..&year2=..&month2=..&day2=..
```

- **`report_type=3&report_type=4` are required.** Without them the service returns an empty
  result that looks like a quiet station (PLAN.md 10.1).
- Fetch from `metar.archive_start` to today, **one calendar year per request**; the service
  is slow. Persist each response **before parsing** under `data/raw/metar/`, as
  `WABB_<start>_<end>.csv` (AGENTS always-2). Track the files: the analysis must re-run
  offline.
- **Never from the cron**, and not on every run: a script run with the raw files present
  parses them without fetching. Add a `--fetch` flag, in the style of
  `scripts/render_biak_poster.py`.
- **If the service is unreachable, returns an HTML page, or returns a CSV with no data
  rows for a year the store covers: exit non-zero, name the year, and write nothing for it.**
  A failed request is not a quiet year (AGENTS never-2). **No placeholder file, no synthetic
  observations, no generator of stand-in values** - not to make a test pass, not to fill a
  gap, not labelled as synthetic either.

Checked when this task was written: the archive holds WABB from 2023-09-01 at about 48
reports a day. The fields come back as `station,valid,vsby,wxcodes,drct,sknt,metar`.

## Parsing: the traps, all of which fail silently

PLAN.md 10.1 lists four. The first three below are **new**, found by reading real rows when
this task was written:

1. **`M` means three different things.** In `wxcodes`, `M` means *no present-weather
   group* - the normal case, not missing data. In `vsby`, `M` means the observation is
   *missing*. In `drct`, `M` means *variable wind* (`VRB02KT` arrives as `drct = M`). Keep the
   three cases apart. A missing visibility must never become a number, and a variable wind
   must never become a direction.
2. **Calm is `drct = 0.00, sknt = 0.00`** (`00000KT`). It is **not wind from the north**.
   When `sknt == 0`, the direction is undefined. Treat it exactly like variable.
3. **`drct` is where the wind blows *from*.** It is the most common way to get the upwind
   test backwards. See "Geometry".
4. **`vsby` is statute miles.** `9999` metres arrives as `6.21`, `9000` as `5.59`, `4000` as
   `2.49`. Name the column `vsby_sm`. The raw `metar` string carries metres; use it only to
   check the conversion in a test, never mixed into the same column (PLAN.md 10.1 trap 1).
5. **6.21 sm is a ceiling, "10 km or more", not a measurement.** It is censored. Never
   average across it. Report the share of observations at the ceiling instead (PLAN.md 10.1
   trap 2).
6. **`wxcodes` can hold several groups** (`FU HZ`, `-RA BR`). Match `FU` and `HZ` as whole
   space-separated tokens, never by equality with the whole field. Do not match `FU` inside
   another token (PLAN.md 10.1 trap 3).
7. **`valid` is UTC.** Derive WIT (UTC+9) as everywhere else (AGENTS always-1).

## Geometry

The station position goes in config (`metar.lat`, `metar.lon`: -1.190, 136.108 per PLAN.md
10.1). For each event, from its `centroid_lat`, `centroid_lon`:

- `distance_km`: station to event, on the same local plane `events.py` uses
  (`recurrence.M_PER_DEG`, longitude scaled by cos(latitude)). Reuse `events._plane`'s
  approach; do not add a geodesy library.
- `bearing_deg`: the compass bearing **from the station to the event**, 0 = north, 90 =
  east, measured clockwise.

**An observation's wind comes from the event** when its direction is known (not calm, not
variable) and the angular difference between `drct` and `bearing_deg` is at most
`metar.sector_half_width_deg`. The angular difference is `min(|a-b|, 360-|a-b|)`.

Worked example, which must be a test: an event at bearing 315 (north-west of the airport)
and a report with `drct = 320` → the wind blows from the event towards the airport →
**from the event**. The same report against an event at bearing 135 → not.

## The join, per event

**Window:** from `first_seen_utc` to `last_seen_utc + metar.lag_hours`. Smoke outlasts the
burning that makes it: in August 2026, burning peaked on 21-22 August and airport smoke on
23-24 (PLAN.md 10.4). Start `lag_hours` at 48 and say why in config.

For each event, report:

- `distance_km`, `bearing_deg`
- `n_obs`: METAR observations in the window; `coverage`: `n_obs` / expected half-hourly
  slots in the window
- `n_fu`, `n_hz`, `n_fu_from_event`: FU reports whose wind comes from the event, per the
  rule above
- `vsby_sm_min` among non-missing reports, and `share_at_ceiling`
- `n_concurrent_events`: how many *other* events' windows contain at least one of this
  event's FU reports. **Read this before reading anything else.** In the August 2026
  peak, dozens of events overlap in time, and one plume at the airport sits in all their
  windows at once. A report cannot tell them apart. An event "corroborated" together with
  forty others is corroborated as an episode, not as itself.

## Classes, pre-registered

Assign exactly one, in this order:

1. `unobserved`: `coverage` < `metar.min_coverage`. The station was not reporting enough to
   say anything. This is a data gap, not a negative (AGENTS never-2).
2. `beyond_range`: `distance_km` > `metar.max_km`. Numfor lies 126-148 km from the
   airport; a single station cannot speak for it.
3. `corroborated`: `n_fu_from_event` ≥ 1.
4. `smoke_other_direction`: `n_fu` ≥ 1 but none from the event, including reports where
   the wind was calm or variable.
5. `no_smoke_at_station`: none of the above. **This is the class most events will land
   in.** Its name states what was observed at one point, and nothing more.

Do not change the classes, their order or the rule after seeing the results. If you think
one is wrong, say so in your final message and leave it.

Also report class counts at `max_km` 25 and 100 beside the configured value. The range is
a judgement, and the reader should see how much it moves the counts.

## Station baseline

Across the whole archive, report per calendar year and per month: days with any `FU`,
days with any `HZ`, and the observation count, plus `FU` reports by WIT hour. That is what
makes "smoke at WABB is rare" a number rather than a sentence from PLAN.md, and the hour
table shows whether smoke reaches the station mostly at night, as section 12 suggests.

## Configuration

```yaml
metar:
  station: WABB
  lat: -1.190
  lon: 136.108
  archive_start: "2023-09-01"
  lag_hours: 48
  sector_half_width_deg: 45
  max_km: 50
  min_coverage: 0.5
```

Every value gets a comment giving its reason. AGENTS always-5: nothing hard-coded in the
module.

## Output

`src/metar.py`, runnable as `python src/metar.py [--fetch]`. It writes
`data/processed/metar_corroboration.json`, with sorted keys, indent 1 and no timestamp.
Add that file to the `data/processed/` allowlist in `.gitignore`. The file holds:

- the parameters; the archive span and the raw files it read; the observation count, and
  every day in the store's span with no METAR at all
- the station baseline tables
- one record per event, with the fields above and its class
- class counts at 25, `max_km`, and 100 km
- a `caveats` list, verbatim:
  - "A smoke (FU) report at WABB is strong evidence that smoke reached the airport. Its
    absence is close to no evidence: the station is one point, and smoke can pool a few
    kilometres away under a night inversion without reaching it (PLAN.md section 12)."
  - "Events that overlap in time share the same reports; n_concurrent_events says how
    many. A corroboration shared with many events corroborates the episode, not the
    event."
  - "Visibility is in statute miles; 6.21 is the '10 km or more' ceiling, not a
    measurement."
  - "Smoke at the airport says nothing about why land was burned or who burned it
    (PLAN.md section 8)."

Print the class counts and the FU-days-per-year table to stdout.

## Do not write the finding

**Do not add an entry to `FINDINGS.md`.** This overrides AGENTS always-6 on purpose, as it
did for Task 17. The entry is written at review from `metar_corroboration.json`. Put the
class counts and the baseline table in your final message.

## Constraints

- **The network is touched only with `--fetch`, and only for the IEM archive.** The
  events, the store, and everything else are read locally.
- AGENTS never-7: the standard library, pandas and requests already cover this. No
  metar-parsing package - the fields arrive already split, and the traps above are what a
  parser would hide.
- AGENTS never-3 does not arise (no FIRMS `confidence` is read). `events.json` and
  `detections.parquet` are read, never written.
- **Wording**, everywhere including your final message: "corroborated", "smoke reported at
  the station", "no smoke at the station". Never "confirmed fire", "false positive",
  "refuted", "not burning", or anything that assigns a cause or a person.

## Check

`tests/test_metar.py`, offline, with synthetic rows built inside the test. It may also read
a small slice of a real raw file once one is committed, but must not fetch.

1. Unit parsing: `6.21` → at the ceiling; `2.49` → not; `vsby = M` → missing, never 0.
2. `wxcodes = M` → no FU and no HZ, not missing. `FU HZ` → both. A made-up token
   containing the letters `FU` inside it → not FU.
3. Calm (`drct 0`, `sknt 0`) and variable (`drct M`) never count as wind from any event,
   including one at bearing 0.
4. The worked example: bearing 315 with `drct 320` → from the event; bearing 135 → not.
   Also 355 against 5, which crosses north (difference 10, not 350).
5. The window includes a report at `last_seen + lag_hours` and excludes one just after it.
6. Class order: an event beyond range with FU from its direction is `beyond_range`, not
   `corroborated`; an event with too little coverage is `unobserved` whatever else holds.
7. `n_concurrent_events`: two overlapping events sharing one FU report each count 1.
8. A year with no data rows makes the fetch step exit non-zero and write no file for it.
9. The same raw files give byte-identical `metar_corroboration.json`.

## Out of scope

- The live `aviationweather.gov` feed, the dashboard, the daily brief, and the cron.
- BMKG station data (needs registration), SiPongi, air-quality anything.
- Any visibility-based class, and any use of `HZ` in the classes. Haze here has other
  causes (humidity, sea spray), so it is reported, not used.
- Wind trajectories or plume modelling. The upwind test is one sector rule on the reported
  surface wind; say so rather than improving on it.
