# Task 06 — the evening product: storage, and saying nothing correctly

Task 05 is accepted. Two things follow from it: the output is far too large to run daily, and the
evening result now has to reach the brief without overclaiming. Read `AGENTS.md` first, then
PLAN.md sections 12 and **13** — section 13 is new and is the finding this task has to communicate.

---

## 1. The output is 51 MB per day

`data/processed/himawari_evening_2026-08-22.csv` is 465,885 rows and 51 MB for a single day. At
that rate a year of evenings is 18 GB, and the daily job would spend most of its time writing
ocean.

Two changes, both simple:

**Restrict to land.** 22,185 pixels per slot cover the whole AOI bounding box, and Biak plus
Supiori is a small fraction of it. Reuse the existing `on_land` mechanism from the ingest — the
boundary polygons are already loaded there. Do not build a second land test; PLAN.md and task 04
both forbid a parallel mechanism.

Keep a small fixed ocean sample — a few hundred pixels is plenty — because the ocean B14 sanity
check in task 05 is a genuinely useful daily health signal on the reader, and it is worthless if
the ocean is discarded. Mark those rows so they are never mistaken for AOI observations.

**Write Parquet, not CSV.** `pyarrow` is already installed and the store already uses it.

Report the resulting file size. If it is not under 2 MB per day, say so rather than compressing
harder — that would mean the pixel count is still wrong.

Nothing about the analysis changes. Same columns, same thresholds, same flags.

## 2. Surface it in the brief, and get the wording right

This is the part that needs care, and it is why task 05 deliberately left it out.

Add an evening section to `report_daily.py` covering the 15:00-01:00 WIT window for the brief's
WIT day. It must state:

- how many 10-minute slots were actually retrieved, and how many were expected
- whether any pixel was flagged, and if so where and at what time
- **when nothing was flagged, that this is not evidence that nothing burned**

The required framing, from PLAN.md 13.2: **"no evening thermal anomaly above threshold"** — never
"no fire", never "the evening was clear", never "conditions improved after dark".

Three claims are forbidden anywhere in this output, per task 05 and PLAN.md 13:

- presenting a Himawari flag as equivalent to a FIRMS detection
- writing that FIRMS missed something Himawari found, without stating that the detection floors
  differ by a factor of 28 in pixel area
- treating an unflagged evening as an all-clear

Daytime rows (before 18:15 WIT) must be labelled unreliable wherever they appear, and the brief
must not count a pre-sunset flag as an evening observation without saying it was in daylight.

If the run is missing slots — upstream gaps happen — the brief says how many, in the same
three-state way the FIRMS provenance already works. A missing slot is not a quiet zero.

## 3. Wire it into the daily job

The evening window for a WIT day ends at 01:00 WIT the following morning, so a brief written at
the end of a WIT day cannot include its own evening. Decide how to handle this and **state the
choice explicitly in your report** — either the brief covers the previous evening and says so, or
the evening section is written on a later pass. Do not leave it ambiguous in the output; a reader
must be able to tell which night the section describes.

## Out of scope

Cloud masking. Lowering the night thresholds — PLAN.md 13.4 explains what would come through
first, and the answer is cloud artifacts 45-75 km from any fire. Any other band. The dashboard.
P-Tree. No new dependencies.

## The checks

1. A day's output is under 2 MB and contains no all-ocean rows beyond the marked sample.
2. Land restriction uses the existing `on_land` mechanism, not a new one.
3. A run with zero flagged pixels renders the "no anomaly above threshold" wording, and does not
   render any all-clear phrasing.
4. A run with a pre-sunset flag labels it as daytime and unreliable.
5. A run with missing slots reports the count of missing slots rather than a silent zero.
6. Re-running over the same inputs produces identical output.
7. The existing 50 tests still pass.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
