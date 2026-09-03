# Task 15 — Six burned-area indices over Biak, judged by their false alarms

> **Revised 2026-09-03**, after `src/s2_scene_survey.py` measured what Sentinel-2 actually
> holds over this AOI. The first version of this file told you to pick "the least cloudy
> scene after 25 August". Doing that would have handed you 29.8% of the corridor and 47 of
> 74 strong hotspot clusters, while the clearest scene of the whole season — 23 August,
> 99.96% clear over corridor land — sat unexamined inside the burning window and was
> excluded by the very rule that was meant to keep the test clean. The scene pair, the cloud
> stratum and the hotspot-adjacent stratum below are all rewritten because of it. Run the
> survey script and read its output before you touch this task.

Source: Alcaras, Costantino, Guastaferro, Parente and Pepe, "Normalized Burn Ratio Plus
(NBR+): A New Index for Sentinel-2 Imagery", *Remote Sensing* 14(8), 1727, 2022 — in
`References/remotesensing-14-01727-v2.pdf`. Read section 3.1 and 3.2 of that paper before
writing any code; the formulas below are transcribed from it and one of them is ambiguous
in the extracted text.

PLAN.md Phase 4 lists dNBR for burn-area delineation. This task does not replace that
decision. It measures which index is worth building the phase on.

## Why this index, for this island

NBR+ exists to solve the failure this AOI is made of. From the paper's section 3.2: water
bodies are routinely mistaken for burned area by NBR, because burned ground and water
surfaces reflect similarly in the NIR–SWIR combination, and the usual remedy is a separate
water mask. NBR+ folds green and blue reflectance into the index itself so that water and
cloud fall negative without a mask.

Our AOI box is mostly ocean, and Papua is among the cloudiest places on earth. The two
false-positive sources the index was designed against are our two dominant conditions.

That is a reason to test it here, not a reason to adopt it. The paper validates on ~500 km²
of Mediterranean bushland in Sicily. Biak is humid tropical forest and small-scale shifting
cultivation, where a burned plot may be a hectare — 25 pixels at 20 m — and mixed pixels
will dominate.

## The test this task runs, and why it needs no ground truth

The paper evaluates with maximum-likelihood classification and confusion matrices against
test areas. We have no reference data. The only candidate is the FIRMS hotspot record, which
is the thing burned-area mapping is supposed to corroborate; using it as truth would make
the argument circular.

So invert the test. **Judge the indices by where they are certainly wrong.** Three strata a
burned-area index must not flag, known without any field data:

- **Permanent water** — `ESA/WorldCover/v200/2021` class 80, the same mask every other
  script here uses.
- **Cloud and cloud shadow** — from a scene's own `SCL` classification. **Not from the
  post-event scene of the primary pair.** 23 August is 99.96% clear over corridor land:
  cloud_medium covers 5 pixels and cloud_high 3, so this stratum would be empty and any
  false-alarm rate computed over it would be noise reported to four significant figures.
  Take it from the **28 August scene**, which is 46.4% clear and therefore has cloud to
  spare, and compute the cloud stratum **uni-temporally on that scene**. Say plainly in the
  output that the cloud stratum comes from a different date than the burn strata; that is a
  limitation to state, not a seam to hide.
- **Land with no hotspot anywhere near it in the whole record** — land pixels beyond a
  generous distance from every FIRMS detection ever stored for this AOI.

And one stratum where burning is plausible, which is **not** ground truth and must never be
called it:

- **Hotspot-adjacent land** — land within a stated distance of a FIRMS detection **that
  precedes the post-event scene**. With a 23 August post-image this means detections from
  19–22 August only: 517 of the 645 on-land detections, 80.2% of the event. The 128
  detections of 23–25 August mark ground that had not burned yet when the image was taken,
  and putting them in a "burning plausible" stratum would score an index as a false alarm
  for correctly seeing unburned ground. The script must derive this cut-off from the scene
  date rather than hard-coding a date.

  A 375 m VIIRS pixel locates a thermal anomaly, not a burn perimeter.

An index that separates the fourth stratum from the first three is useful here. An index
that flags open sea is disqualified for this AOI whatever it scored in Sicily.

## What to build

### `src/burn_indices_gee.py`

Run by hand with Earth Engine credentials:

    python src/burn_indices_gee.py <google-cloud-project-id>

Import the AOI read and `land_mask` from the existing scripts. Read the AOI from
`config.yaml` (AGENTS always-5). Write `docs/data/burn_indices.json` — a **new** file.
Nothing under `docs/data/` may be modified.

**Scene pair — already measured, do not re-choose by eye.** `COPERNICUS/S2_SR_HARMONIZED`,
MGRS tile **53MPU**, which alone reaches 71.4% of the corridor's land. The corridor spans
four tiles (53MNU, 53MNV, 53MPU, 53MPV) and no single scene covers it, so every stratum
count below is a count within one tile's footprint and must be reported as such.

```
primary   2026-07-19 -> 2026-08-23    57.6% of corridor land clear in BOTH   80.2% captured
check     2026-07-19 -> 2026-08-28    29.8%                                 100.0% captured
```

Run both. The primary pair carries the analysis; the check pair exists for one narrow
purpose, which is the ground that burned on 23–25 August and is therefore absent from the
primary post-image. Report the six indices on the primary pair, then report — separately,
never pooled — how the same indices behave over the late-burning clusters using the check
pair. Two pairs, two tables. Do not average them, do not mosaic them, and do not quietly
substitute one for the other where the primary has cloud.

Two properties of this pair have to be stated wherever its numbers are:

- **The post-image is mid-event.** 23 August sits inside the 19–25 August burning window, so
  it shows roughly four fifths of the event and none of its last two days. That is a
  deliberate trade: it doubles the usable area (57.6% against 29.8%) and raises the strong
  hotspot clusters on usable ground from 47 to 64 of 74. State the trade; do not describe
  the image as post-event.
- **The pre-image is 35 days earlier.** Between 19 July and 23 August the canopy changes for
  reasons that have nothing to do with fire, and a bi-temporal index cannot separate that
  from a burn. The nearest usable earlier scene, 8 August, leaves only 13.3% of the corridor
  and is not a serious alternative. Say what the gap is.

Record both scene identifiers, their `CLOUDY_PIXEL_PERCENTAGE`, and — because the granule
metadata describes 110 km of mostly ocean and is close to useless here — the measured clear
share over masked corridor land. If `src/s2_scene_survey.py` no longer reports these dates
as the best available, say so and stop rather than proceeding on a stale pair.

**Scale reflectance before computing anything.** Sentinel-2 surface reflectance is stored as
integers; divide by 10000 to get reflectance in 0–1. This is not optional bookkeeping:
NBR+, NBR, NDSWIR and NBRSWIR's ratio structure would survive it, but **NBRSWIR, MIRBI and
BAIS2 contain additive constants** (−0.02, +0.1, +2, +1) that are meaningless against
integer counts. Getting this wrong produces plausible-looking maps that are arithmetic
nonsense. Assert somewhere that the scaled reflectances lie in a sane range.

**The six indices**, as the paper defines them, on 20 m bands:

```
NBR      = (B12 - B8A) / (B12 + B8A)
NBRSWIR  = (B12 - B11 - 0.02) / (B12 + B11 + 0.1)
NDSWIR   = (B11 - B8A) / (B11 + B8A)
MIRBI    = 10*B12 - 9.8*B11 + 2
BAIS2    = (1 - sqrt(B6*B7*B8A / B4)) * ((B12 - B8A) / sqrt(B12 + B8A) + 1)
NBR+     = (B12 - B8A - B3 - B2) / (B12 + B8A + B3 + B2)
```

Two things to get right before you trust that block:

- **BAIS2's grouping is ambiguous in the extracted text** — whether the `+ 1` sits inside or
  outside the square root. Read equation (5) in the PDF and follow the paper, and state in a
  comment which reading you took.
- **This paper's NBR is sign-flipped from the usual convention.** It writes
  `(B12 - B8A) / (B12 + B8A)`, so *high* means burned; the USGS convention is
  `(NIR - SWIR2) / (NIR + SWIR2)`, where *low* means burned. Follow the paper so the six are
  mutually comparable, and say so in the output, or a later reader mixing this with standard
  dNBR literature will invert the severity scale.

Compute each index **uni-temporally** on the post-event scene and **bi-temporally** as
post minus pre, which is what the paper reports as the stronger approach.

### What to report

For every index, in both temporal forms, over each of the four strata, at 20 m: the pixel
count and the distribution — minimum, the 5th, 25th, 50th, 75th and 95th percentiles, and
maximum.

**Do not pick a threshold.** The paper derives one by supervised classification we cannot
reproduce, and choosing one by eye against our own strata is how a result gets manufactured.
Publishing the per-stratum distributions lets any threshold be evaluated later, including by
a reader who disagrees with us.

From those distributions, report one comparable number per index: the share of each
non-burnable stratum that exceeds the 95th percentile of the hotspot-adjacent stratum. Name
it plainly as a false-alarm rate against a weak reference, not as an accuracy.

Also print, because they are the specific traps here:

- how each index behaves over open sea, where sun glint can mimic a bright SWIR response;
- how each behaves over cloud, given that the smoke of late August 2026 is bright in blue
  and will push NBR+ negative — which suppresses false alarms but can also hide a real scar
  beneath smoke.

## Constraints

- **No data file without data.** If Earth Engine is unreachable, or no usable scene pair
  exists, the script writes nothing and says why. No placeholder, no synthetic series, no
  stand-in values.
- **Keep cloud pixels.** Do not apply a global cloud mask. Cloud is one of the strata being
  measured; masking it away deletes the experiment.
- **No page change**, and no burned-area total published anywhere. This task produces a
  comparison of indices, not a map of what burned.
- **Never write "fire", "kebakaran", or any attribution of cause or responsibility** into
  the output or the page. PLAN §8 applies in full: these are burned-area indices over pixels,
  and small-scale burning in Papua is lawful and long established. The whole-word ban on
  "clear" and "safe" in `docs/index.html` is not at issue only because you are not editing it.
- **Never edit `PLAN.md`** (AGENTS never-6). Append the result to `FINDINGS.md` as the next
  F-number after the last entry there (AGENTS always-6).
- No new dependency (AGENTS never-7).

## Acceptance criteria

- `python src/burn_indices_gee.py <project>` writes `docs/data/burn_indices.json` and prints
  both scene pairs with cloud percentages and measured clear shares, the stratum pixel
  counts, and the per-index distributions and false-alarm shares.
- A test asserts the hotspot-adjacent stratum was built only from detections earlier than
  the post-scene date, and that the cloud stratum records which scene and date it came from.
  Both are places where a later edit could silently reintroduce the errors this revision
  exists to remove.
- A test asserts the four strata are disjoint and non-empty, that every distribution is
  ordered (min ≤ p5 ≤ … ≤ max), and that the recorded reflectance range is consistent with
  scaled surface reflectance rather than raw integers. Skip cleanly when the file is absent,
  as the task 11 to 14 tests do.
- `git status` shows every existing file under `docs/data/` unmodified.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes unchanged.
- One commit for code and data, one for the `FINDINGS.md` entry.

## Out of scope

- Maximum-likelihood classification, any supervised classifier, or a burned/not-burned map.
- Severity classes, burn perimeters, or an area figure in hectares.
- Any use of the FIRMS record as ground truth.
- **HLS (`NASA/HLS/HLSL30/v002`, `NASA/HLS/HLSS30/v002`), Landsat Collection 2, VIIRS or
  MODIS burned-area products.** Checked on 2026-09-03: every one of them ends before the
  event's last day, so none can contribute a post-event image at all. Two structural reasons
  keep HLS out even once it catches up. Its Landsat half has no B8A and no red edge, so
  BAIS2 cannot be computed on it. And the two HLS collections reuse band names for different
  wavelengths — `B6` is red edge in HLSS30 and SWIR1 in HLSL30, `B11` is SWIR1 in HLSS30 and
  thermal in HLSL30 — so one formula written against both runs without error and returns
  nonsense. A fourth trap for the list above, avoided by staying on native Sentinel-2, where
  20 m also gives a 1 ha plot 25 pixels instead of 30 m's 11.
- Changing PLAN Phase 4's choice of index. This task informs that decision; it does not make
  it.

## When you finish

Per the AGENTS closing rule: what you built, what you deliberately did not, how to run the
check, and every decision this task left open — the scene identifiers and why those two, the
BAIS2 grouping you read from the PDF, the distances used for the two hotspot strata, the
scale you reduced at, and how many pixels each stratum actually contained.

State plainly which index you would build Phase 4 on, **including the case where the answer
is that this scene pair cannot separate them.** With one event and one pair of images, that
is a legitimate outcome, and it is more useful than a ranking the data does not support.

Name explicitly what the mid-event post-image and the 35-day pre-gap prevent this task from
settling, so that the next person does not read the result as stronger than it is.
