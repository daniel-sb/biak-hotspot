# Task 05 — Himawari-9 evening coverage

Close the 9.5-hour observation gap documented in PLAN.md section 12. Between 15:00 and 00:31 WIT
no polar-orbiting satellite passes over Biak. Himawari-9 scans the full disk every 10 minutes,
all night, and is the only open-access sensor that covers those hours.

Build `src/himawari.py`. Read `AGENTS.md` first. Reference: PLAN.md sections 2.1, 7 and
**12** — read section 12 before writing code, it is the reason this task exists.

---

## Access, already verified

The public AWS bucket `noaa-himawari9` serves Himawari-9 L1b anonymously over HTTPS. No account,
no credentials, no `boto3` — plain HTTP GET works. This was confirmed against the live bucket on
2026-08-28:

```
listing   https://noaa-himawari9.s3.amazonaws.com/?list-type=2&prefix=<prefix>
prefix    AHI-L1b-FLDK/YYYY/MM/DD/HHMM/          (HHMM in UTC, 10-minute slots)
object    HS_H09_{YYYYMMDD}_{HHMM}_{BAND}_FLDK_R20_S{NN}10.DAT.bz2
size      ~2.7 MB per band-segment, bzip2 compressed
latency   10-16 minutes behind real time
```

`R20` is the 2 km grid. The full disk is 5500 x 5500 pixels split into 10 segments of 550 lines,
numbered `S0110` through `S1010`.

Do not use JAXA P-Tree in this task. It requires manual approval and offers nothing AWS does not,
for the bands used here.

## Required behaviour

### 1. Fetch only the evening window, only the segments that matter

Default window **06:00 to 16:00 UTC** (15:00 to 01:00 WIT), at a default cadence of **30 minutes**,
both configurable in `config.yaml` as `himawari_window_utc` and `himawari_cadence_minutes`.

Ten-minute cadence is available but triples the download for little gain — these fires burn for
hours, not minutes. Do not default to it.

Fetch bands **B07** (3.9 um) and **B14** (11.2 um) only. Ignore the other 14 bands.

Fetch only the segment covering the AOI. **Determine the segment from the HSD navigation block,
do not hardcode it** — then assert it matches the expected value, so that a change in the product
layout fails loudly instead of silently returning ocean. Report which segment number you compute.

Persist every downloaded `.DAT.bz2` under `data/raw/himawari/` before parsing, per AGENTS.md. Add
that path to `.gitignore` alongside the existing `data/raw/` rule if it is not already covered —
this is roughly 100 MB per day and must never be committed.

### 2. Read HSD without adding a dependency

`bz2` is standard library and `numpy` is already installed. The Himawari Standard Data format is
a documented sequence of fixed-length header blocks followed by the count array. Write a minimal
reader for what this task needs: the navigation block, the calibration block, and the counts.

Do not add `satpy`, `xarray`, `dask`, or `pyresample`. Do not vendor a third-party reader.

Convert counts to radiance using the calibration coefficients in the header, then radiance to
brightness temperature using the Planck coefficients also in the header. Take both from the file.
Do not hardcode coefficients — they are updated over the instrument's life.

### 3. Validate the reader against FIRMS before trusting a single number

**This is the most important check in the task.** A hand-written binary reader that returns
plausible-looking numbers but misreads an offset is the realistic failure here, and it would
produce a fire history that is entirely fictional.

Pick a high-FRP daytime detection from the existing store, fetch the Himawari slot nearest its
acquisition time, and confirm B07 brightness temperature shows a clear anomaly at that location
relative to its surroundings. Report the actual numbers: background BT, pixel BT, difference.

Also assert sanity bounds: sea-surface pixels in B14 should sit near 297-303 K for tropical
ocean. A reader that is off by an offset will not land in that range.

If the validation does not show an anomaly, **stop and report that**. Do not adjust thresholds
until something appears.

### 4. Anomaly flagging, deliberately simple

For each AOI pixel and each time slot, record:

- `bt07`, `bt14`, and `bt07_minus_bt14`
- `bt07_background` — the median B07 over a surrounding window, excluding the pixel itself
- `bt07_anomaly` — pixel minus background

Flag a pixel when `bt07_anomaly` and `bt07_minus_bt14` both exceed configurable thresholds. Both
live in `config.yaml`. Suggested starting values are 10 K and 10 K; treat them as provisional and
say so in the output.

Do not implement the full Giglio contextual algorithm. Do not add a cloud mask. The goal is a
defensible time series, not a competing fire product.

### 5. Day and night are not comparable

Sunset at Biak is about 18:15 WIT (09:15 UTC). Before that, reflected sunlight contaminates the
3.9 um band and inflates B07 for reasons that have nothing to do with fire.

Record the WIT local time on every row and mark each as day or night. The 18:15 to 00:31 WIT
segment is fully dark and is the trustworthy part of this window. Daytime rows are recorded but
must be labelled as unreliable wherever they surface.

### 6. Output

Write `data/processed/himawari_evening_{WIT-date}.csv` — one row per AOI pixel per time slot,
carrying the columns above plus `acq_time_utc`, `acq_time_wit`, `lat`, `lon`, `is_night`,
`flagged`.

Do not write into `docs/` and do not touch `report_daily.py` in this task. Surfacing this in the
brief is a separate task, deliberately, because the wording needs its own review.

## Wording discipline, binding on any output this produces

Himawari-9 at 2 km resolution against VIIRS at 375 m is a **28-fold difference in pixel area**.
It sees only larger or hotter fires. Three claims are therefore forbidden in anything this code
emits or that is written about it:

- Never present a Himawari flag as equivalent to a FIRMS detection.
- Never write that "FIRMS missed a fire Himawari found" without stating that the detection floors
  differ.
- Never treat absence of a Himawari flag as evidence that nothing was burning. Section 12 exists
  because three instruments reported nothing while a resident stood in heavy smoke. Adding a
  fourth instrument that can also report nothing does not change that.

The honest framing is narrow and worth stating plainly: this is the first observation of any kind
during the evening hours. Partial coverage replacing none.

## The checks

No network in tests — commit a single real slot to `tests/fixtures/` as the fixture. One band-
segment is about 2.7 MB compressed; that is acceptable for a fixture, two bands is the limit.

1. The HSD reader returns the documented array shape for a known segment.
2. Brightness temperature over open ocean falls in 293-305 K.
3. A synthetic hot pixel injected into a real background is flagged; the unmodified background is not.
4. Day/night classification is correct at 18:00 and 20:00 WIT on a known date.
5. Segment selection computed from the header matches the asserted expected value.
6. The FIRMS cross-check in step 3 above, run against the real store, with numbers reported.
7. The existing tests still pass.

## Out of scope

The brief integration. The dashboard. P-Tree. Any other AHI band. Cloud masking. Smoke plume
detection from visible bands. Nothing from PLAN.md phases 3 to 6. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
