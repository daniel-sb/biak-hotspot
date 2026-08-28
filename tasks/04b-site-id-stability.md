# Task 04b — stable site IDs, and two small fixes

Small follow-up to task 04. The implementation is otherwise accepted; these are the defects found
in review. Read `AGENTS.md` first, then PLAN.md section **11.4**, which corrects two claims the
original task file got wrong.

---

## 1. Site IDs must be stable across runs (the real defect)

Site IDs are currently assigned by sorting on `(-distinct_days, centroid_lat, centroid_lon)` and
numbering `R001` upward. Distinct-day counts change every time a site produces another detection,
so **the ordering changes and sites renumber.**

Today's brief published this sentence:

> Site R002 (Yendidori): 1 detection(s) today, at a location flagged as recurrent — hotspots have
> appeared there on 12 distinct days of the recorded history.

R002 currently has 12 distinct days. R001 has 74. If R002 overtakes another site, or a new site
appears, R002 becomes a different physical place — and every brief already published referring to
R002 silently becomes wrong. Briefs are permanent public output; an identifier in them must mean
the same thing forever.

**Required:** an ID identifies a place, not a rank.

Keep a registry inside `data/processed/recurrent_sites.json`. On each run, match every freshly
computed cluster against the previous file: if a new centroid falls within `radius_m` of a
previously recorded site's centroid, it inherits that site's ID. Only genuinely new sites get the
next unused number, and numbers are never reused after a site stops qualifying.

Consequences to handle explicitly, and to state in your report:

- The file is now **stateful**, which conflicts with task 04's requirement that it regenerate
  deterministically from data alone. Resolve it this way: regenerating from the same store *and
  the same prior registry* must still be byte-identical. Keep the no-timestamp rule.
- Deleting the file and rebuilding from scratch will renumber. That is acceptable, but the file
  must carry a `registry_version` integer that increments whenever a rebuild reassigns IDs, so a
  reader can tell that IDs before and after are not comparable.
- If two clusters both match one previous site (a site splitting in two), the larger by detection
  count keeps the ID; the other is new. Say so in the file.

## 2. Publish the mask

`data/processed/` is gitignored, so `recurrent_sites.json` never reaches a reader. Task 04 called
it "a reviewable data file" and it is not currently reviewable by anyone outside this machine.

Write a copy to `docs/data/recurrent_sites.json` as part of the daily run. It is a few hundred
bytes and it is the only way a reader can check what the brief's site references mean.

## 3. Fix the plural in the brief

`1 detection(s) today` should read `1 detection today` / `2 detections today`. This is published
prose, not a log line.

---

## Not defects — do not change these

Reviewed and confirmed correct; listed so they are not "fixed" by mistake:

- **Leader/centroid clustering over single-linkage.** The right call, for the reason given: single
  linkage chained the airport cluster. Verified order-independent — shuffling the input three ways
  produces identical sites, because the internal sort runs first.
- **Three Yendidori sites rather than one.** Not fragmentation. The centroids are 1.2 km and 2.0 km
  apart along a north-south line; VIIRS jitter is ~375 m. See PLAN.md 11.4.
- **No timestamp in the mask.** Verified byte-identical on rerun. Keep it.
- **The `docs/data/hotspots_latest.geojson` churn.** Verified as the 7-day window rolling from
  19-25 August to 21-27 August, not exclusion of flagged rows.

## Watch item, no code change

Site R003 has exactly 10 distinct days against a `min_days` of 10. One detection either way moves
it in or out of published output. Nothing to fix, but if the mask grows a margin field later, this
is why.

## The checks

1. A site keeps its ID when its detection count and distinct-day count change.
2. A site keeps its ID when another site overtakes it in distinct days.
3. Rebuilding from a deleted registry increments `registry_version`.
4. Same store plus same registry produces a byte-identical file.
5. Singular and plural both render correctly in the brief.
6. The existing 37 tests still pass.

## Out of scope

Everything in task 04 that is not listed above. Any change to `radius_m`, `min_days`, or
`min_span_days` — if you believe a threshold is wrong, say so in your report and change nothing.
No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
