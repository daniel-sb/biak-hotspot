# Task 15 — Six burned-area indices over Biak, judged by their false alarms

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
- **Cloud and cloud shadow** — from the scene's own `SCL` classification.
- **Land with no hotspot anywhere near it in the whole record** — land pixels beyond a
  generous distance from every FIRMS detection ever stored for this AOI.

And one stratum where burning is plausible, which is **not** ground truth and must never be
called it:

- **Hotspot-adjacent land** — land within a stated distance of an August 2026 FIRMS
  detection. A 375 m VIIRS pixel locates a thermal anomaly, not a burn perimeter.

An index that separates the fourth stratum from the first three is useful here. An index
that flags open sea is disqualified for this AOI whatever it scored in Sicily.

## What to build

### `src/burn_indices_gee.py`

Run by hand with Earth Engine credentials:

    python src/burn_indices_gee.py <google-cloud-project-id>

Import the AOI read and `land_mask` from the existing scripts. Read the AOI from
`config.yaml` (AGENTS always-5). Write `docs/data/burn_indices.json` — a **new** file.
Nothing under `docs/data/` may be modified.

**Scene pair.** `COPERNICUS/S2_SR_HARMONIZED`. One pre-event scene before 19 August 2026 and
one post-event scene after 25 August 2026, each the least cloudy available over the AOI.
The August 2026 burning ran 19–25 August, peaking at 283 detections on the 22nd. Record both
scene identifiers and their cloud percentages in the output; if no usable post-event scene
exists, say so and write nothing rather than reaching for a distant date.

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
  the scene pair with cloud percentages, the stratum pixel counts, and the per-index
  distributions and false-alarm shares.
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
- Landsat, VIIRS or MODIS burned-area products as a second opinion. Later, maybe.
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
