# Task 04 — recurrence flagging (Phase 2, persistent-source filter)

Flag locations that produce hotspots repeatedly over the historical record, so a reader can tell
recurrent burning from a one-off fire. Build this in a new `src/recurrence.py`, wired into the
ingest and surfaced in the brief.

Read `AGENTS.md` first. Reference: PLAN.md sections 3 (Phase 2 item 1), 8 and **11**, which
carries the measured baseline this task is calibrated against. Read section 11 before writing
code — the thresholds below come from it.

---

## What the data says

The store holds 1,078 detections over 2023-09-01 to 2026-08-27. Binned into ~375 m cells and
counted by distinct WIT days, the distribution is sharply bimodal: 483 cells appear on one day,
87 on two, tailing through 22 / 16 / 2 / 1 — and then one cell at **-1.1449, 136.0353**
(Yendidori) carries **66 distinct days**, six times the next highest.

Its immediate neighbours carry 11 and 7 days. That is one physical source smeared across
adjacent cells by geolocation jitter.

## Required behaviour

### 1. Cluster by radius, not by grid

Group detections whose coordinates fall within a configurable radius, default **750 m**, and
count the **distinct WIT days** on which the cluster produced at least one detection. A grid
undercounts by splitting a source across cell boundaries — that is the specific defect to avoid,
and the 66 / 11 / 7 neighbours are your test case: they must land in one cluster.

Use `shapely` (already a dependency) or plain arithmetic. Do not add a clustering library.

### 2. Flag, never delete

Add columns: `recurrent_site_id` (null when not part of a flagged site), `recurrent_site_days`
(distinct-day count for its cluster), `recurrent_site` (boolean).

**No detection is ever removed, and the brief must never silently exclude flagged rows.** PLAN.md
section 11.2 explains why this is more than an AGENTS.md rule here: nobody knows what is at that
location. It may be an unmapped landfill; it may equally be a farmer burning the same plot each
season. Deleting it would erase real fire activity, and calling it industrial in published output
would be an unsupported claim about a named hamlet.

Wording in the brief must stay neutral: **"recurrent location"** — never "false positive",
"industrial", or "non-fire".

### 3. Refuse to run on insufficient history

A recurrence claim needs a long record. Require a configurable minimum, default **365 days**,
between the earliest and latest detection in the store. Below that, emit no flags at all and
record the reason. Do not scale the threshold down to fit a short record: a mask computed from
fifteen days would have flagged the six-day August airport cluster as infrastructure and deleted
a real fire.

### 4. The mask is a reviewable data file, regenerated from data

Write `data/processed/recurrent_sites.json`: one entry per flagged cluster with its id, centroid,
distinct-day count, detection count, first and last date, and the distrik it falls in. Regenerate
it whenever recurrence is recomputed; never hand-edit it. PLAN.md section 3 Phase 2 requires this
explicitly.

### 5. Thresholds

Default: flag a cluster when it has detections on **at least 10 distinct days** *and* those days
span **at least 90 days**. Both values live in `config.yaml`.

The second condition is what keeps this honest. Ten days inside one week is a fire that burned
for a week, not a recurrent site — without the span condition the August 2026 event would be
flagged wholesale.

---

## Pinned expected values

Against the current store (1,078 detections, 2023-09-01 to 2026-08-27):

```
The cluster containing (-1.1449, 136.0353) is flagged, and absorbs the neighbouring
cells at 11 and 7 distinct days into a single site.

Detections within 3 km of Frans Kaisiepo airport (-1.190, 136.108) are NOT flagged:
39 detections across only 10 distinct days, 35 of them in August 2026 — the day-span
condition excludes them.

No detection is dropped: the store still holds 1,078 rows after flagging.
```

If your numbers differ, say so rather than adjusting code until they match.

## The checks

No network. Build small synthetic stores where the expected answer is unambiguous, and also
assert against the real store where it is available.

1. Three detections at 375 m spacing on different days land in **one** cluster, not three.
2. A cluster with 10 distinct days inside a 7-day span is **not** flagged; the same count spread
   over 200 days **is**.
3. A store spanning under 365 days produces zero flags and records the reason.
4. Flagging never changes the row count and never changes any `detection_id`.
5. `recurrent_sites.json` is regenerated deterministically from the same input.
6. The existing 30 tests still pass.

## Out of scope

METAR corroboration and the SiPongi comparison (Phase 2 items 4 and 5) are separate tasks.
Coastline and glint checks are already covered by the existing `on_land` flag — do not add a
second mechanism. Nothing from PLAN.md phases 3 to 6. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
