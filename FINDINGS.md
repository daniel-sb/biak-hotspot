# Findings

What the data turned out to say. `PLAN.md` is the spec — what we intend to build, and the
product rules that follow from what we learn. This file is the other half: results, with
their numbers, their caveats and the commit that produced them.

**How to write here.** Append only. Add a new dated entry at the end; never rewrite or
delete an earlier one. A number that turns out to be wrong is corrected by a new entry that
says so and names what it supersedes — the superseded figure stays visible, because a
finding that quietly changes to match the latest run is not a finding. Every entry names
the script and the commit behind it, so any figure here can be regenerated.

Agents may append to this file. `PLAN.md` stays human-maintained (AGENTS.md never-6).

---

## F1 — The 2026 dry season, and why the water balance says it better than rainfall (2026-09-01)

`src/drought_gee.py` → `docs/data/drought.json`, commit `f73e827`. Every figure is an AOI
**land** mean masked with `ESA/WorldCover/v200` class 80 (permanent water), because the AOI
box is mostly ocean and an unmasked mean is largely a mean of the sea.

July 2026 received **115.6 mm** against a 1981–2025 July mean of **245.9 mm** (s.d. 85.4,
45 years): **z = −1.53**, the **4th driest July of 46**.

Rainfall alone understates it. Against MOD16A2 evapotranspiration the monthly water balance
collapses through the season:

| 2026 | Apr | May | Jun | Jul |
|---|---|---|---|---|
| precipitation, mm | 335.0 | 251.5 | 187.2 | 115.6 |
| evapotranspiration, mm | 101.9 | 116.0 | 113.4 | 139.6 |
| **P − ET, mm** | **+233.1** | **+135.5** | **+73.8** | **−24.0** |

July 2026 is the **only month with a negative water balance in the entire MOD16A2 record for
this AOI** (2021-01 onward, 67 months). Evapotranspiration did not fall with the rain, it
rose to its highest value in the record — fewer clouds means more incoming radiation means
higher evaporative demand. The land lost water in a month it normally gains 100 mm or more.

That is the honest statement of the season: the burning of August 2026 (PLAN §11.1) happened
in meteorologically extreme conditions. It is **not** a statement of cause. Dry fuel makes
burning easier; it does not ignite. PLAN §8 applies in full.

**Coverage lag is part of the finding.** CHIRPS lags real time by roughly a month (latest
2026-07-31 as of 2026-09-01); MOD16A2 runs to 2026-08-13. `MOD16A2GF` is gap-filled and held
no 2026 data at all — do not substitute it. Any panel showing these series describes **the
season the hotspots occurred in, not the week**, and must say so where the reader sees the
numbers. The Earth Engine call is therefore run by hand when a new complete month appears,
never from the daily cron.

**Open against this entry:** MOD16A2 is a Terra product, and F4 below shows Terra's overpass
has drifted sharply since 2022. An ET series that ends at a record high deserves the same
question F4 asks of NDMI. Until that is done, the "only negative month in the record" claim
carries an untested instrument assumption.

---

## F2 — MODIS composite quality tracks the vegetation index, not the vegetation (2026-09-01)

`src/vegetation_gee.py` → `docs/data/vegetation.json`, commit `7f04983`. 307 months,
2001-01 to 2026-07.

The obvious next move after F1 is a vegetation index, and it produces a result that looks
like a finding and is not one: **NDVI and NDMI reached record highs in the driest July on
record.** July 2026 NDVI is **0.8375**, the highest July of the 26-year record (July range
0.6126–0.8375), anomaly **+0.1144**.

The cause is compositing. Each index correlates with the share of AOI land pixels passing
its own product's cloud test:

| | all months (n = 307) | July only (n = 26) |
|---|---|---|
| NDVI, MOD13A1 `SummaryQA <= 1` | r = 0.948 | **r = 0.965** |
| NDMI, MOD09A1 `StateQA` bits 0–1 | r = 0.489 | **r = 0.802** |

A dry month is a less cloudy month, so its 16-day composite is assembled from more and
better observations, while residual cloud and haze depress the wet-year values it is being
compared against. February 2026 is the same effect in reverse: good-pixel share 0.2584,
NDVI down to 0.6438.

**Supersedes an earlier exploratory figure.** PLAN §14.2 as originally written recorded
**r = +0.883** (July NDVI) and **+0.591** (July NDMI). Those came from a run that was not
land-masked and scaled consistently — the same comparability defect that was fixed in the
drought series before F1 was published. The direction was right and the magnitude was
understated. The figures in the table above are the ones computed by the committed,
re-runnable script.

This is a general hazard in the humid tropics, not a quirk of this AOI, and it is the kind
of result that gets published by accident. PLAN §2.4 already warns that absolute NDVI is
uninformative here and only the day-of-year anomaly is worth computing. This entry adds the
second condition: **an anomaly computed from composites of unequal quality is not an
anomaly.**

---

## F3 — NDVI dissolves under the quality control; NDMI does not (2026-09-01)

`src/vegetation_controls_gee.py` → `docs/data/vegetation_controls.json`, commits `d3b0933`
and `40c92e4`. July only, fitted by ordinary least squares on the normal equations.

Regressing each July index on its own good-pixel share and reading what is left over:

```
NDVI July 2026 residual  -0.0024   z -0.16   rank 11 of 26
NDMI July 2026 residual  +0.0206   z +1.90   rank 26 of 26
```

**The NDVI record is fully explained by observation quality.** Controlled for it, July 2026
is an ordinary July — mid-pack of 26. The record high is a satellite that happened to see
better, not a canopy that greened.

**The NDMI excess is not.** Task 12 added aerosol loading (`StateQA` bits 6–7) and
observation geometry (MOD13A1 view and solar zenith) as controls, and predicted July 2026
out of sample by refitting on the other 25 Julys:

| model | in sample | out of sample |
|---|---|---|
| quality only | z +1.90 | — |
| + aerosol high / climatology-fallback | z +1.84 / +1.60 | — |
| + view zenith | z +1.76 | **+2.80 sd** |
| + solar zenith | z +0.56 | **+1.76 sd** |
| all four controls | z +0.51 | **+1.64 sd** |

Aerosol is out: July 2026 has the **lowest climatology-fallback share of all 307 months**
(0.340 against a July range of 0.340–0.865), so the driest July also had the best-retrieved
atmosphere in the record. The smoke arrived in August.

Solar zenith appears to explain the year and does not. July 2026 sits at 100% of the July
solar-zenith range with leverage **h = 0.683** (5.9× mean), and removing it **halves** the
coefficient it is then judged against, +0.00084 → +0.00045 per degree. The in-sample
collapse from z +1.90 to +0.56 is the fit bending onto the point, which is why every model
is now also evaluated out of sample. `tests/test_vegetation_controls.py` pins the +1.76 and
+1.64 figures so a later change that makes the collapse look real has to break a test.

**What survives:** the July 2026 NDMI excess survives all four controls at +1.64 sd out of
sample. What that leaves is the possibility that the canopy genuinely did not dry — deep
roots through a one-month rainfall deficit — and that P − ET in F1 describes the surface
rather than the tree crowns.

**What this is not:** n = 25 fitted, one year predicted. This is a well-supported direction,
not a result. The cross-sensor test in `tasks/13-aqua-cross-check.md` is the next
discriminator, and its reading of each outcome is pre-registered there because agreement
between sensors would be strong evidence and disagreement would not.

---

## F4 — Terra's overpass has drifted, and it contaminates every Terra time series here (2026-09-01)

Same run as F3. Mean solar zenith over the AOI in July, from MOD13A1:

```
2001–2022   29.6° .. 32.8°   (stable, 22 years)
2023        36.4°
2024        41.0°
2025        47.7°
2026        54.55°
```

Monotone and accelerating, with no counterpart in the weather. This is Terra's equator
crossing drifting earlier since orbit maintenance ended, not anything about Biak. The 2026
value implies a morning overpass roughly an hour and a half earlier than the 2022 one.

It is not a nuisance parameter for one panel. **Any multi-year trend drawn from a Terra
product in this repository after 2022 is confounded with it**, and that includes
`MOD13A1`, `MOD09A1` and `MOD16A2` — the last being the evapotranspiration behind F1.

It also explains why solar zenith was the one control in F3 that appeared to work: it is
collinear with time, and 2026 is the extreme of both. It is not, however, collinear with
cloudiness — r(solar zenith, NDMI good-pixel share) = 0.23 in July, 0.117 across all
months — so it is a genuinely independent control, which is why the out-of-sample test
rather than a collinearity argument is what settles it.

Aqua carries the same instrument on an orbit whose drift runs the other way, which is what
`tasks/13-aqua-cross-check.md` exploits.

---

## F5 - The July 2026 NDMI excess appears on Aqua too, so Terra's drift is out (2026-09-01)

`src/vegetation_aqua_gee.py` -> `docs/data/vegetation_aqua.json`, commit `ac42529`. MYD09A1
and MYD13A1 over the same land mask, at the same 500 m scale and monthly-mean reducer as
F2/F3, with the bit layouts verified against the catalog as identical to the Terra products.
289 months (2002-07 to 2026-07), 25 Julys. The reading of each outcome was pre-registered in
the script and printed before the numbers, because deciding after seeing them is how a result
gets talked into existence.

Fitted entirely within Aqua (Aqua NDMI on Aqua's good-pixel share and Aqua's own aerosol and
geometry controls), the leave-2026-out prediction of July 2026:

| model                    | Aqua out of sample | Terra out of sample (F3) |
|---|---|---|
| base (quality only)      | **+2.41 sd** | +2.86 sd |
| + view zenith            | **+2.57 sd** | +2.80 sd |
| + solar zenith           | **+3.65 sd** | +1.76 sd |
| all four controls        | **+4.35 sd** | +1.64 sd |

Same direction, comparable or larger magnitude, on an independent instrument on an
independent orbit. The pre-registered informative outcome fired: **a Terra-specific artifact
cannot be the explanation. What remains is that the canopy did not dry, and the water balance
(P-ET, F1) describes the surface rather than the tree crowns.**

Three things the numbers added beyond the registration:

- **F4's expectation that Aqua's drift runs the other way is not what this AOI shows.** Aqua's
  July solar zenith rose 30.2 -> 56.5 deg over the same years Terra's rose 31.0 -> 54.6. So
  the cross-check does not oppose the two drifts; it rules out any *Terra-specific* artifact,
  and what rules out a geometry artifact generally is quantitative: the solar-zenith control
  fails out of sample on both sensors and only absorbs 2026 in sample, through leverage (July
  2026 h = 0.68 on Terra, 0.82 on Aqua, always at 100% of the predictor range).
- On Aqua too the in-sample z under solar controls looks small (+0.84) and means nothing; the
  out-of-sample row is the one to read, on either sensor.
- The free second opinion: Aqua July NDVI correlates with its own good-pixel share at
  **r = 0.953** (Terra: 0.965, F2) and July 2026's NDVI residual ranks **4 of 25** - the F2
  dissolution of NDVI reproduces on the second sensor as well.

**What this is not:** still not a causal claim about the hotspots, and still not a result in
the strong sense - two sensors, one year, n = 24-25 fitted per fit. It is the agreement branch
of a pre-registered test, which is the strong branch of that test, and it makes the canopy
finding the leading remaining explanation rather than a loose end. If a disagreement had come
back instead, it would have meant only that the sensors observe at different hours and could
not be reconciled by this design.

---

## F6 - The published water balance survives its own instrument question (2026-09-02)

`src/drought_et_check_gee.py` -> `docs/data/drought_et_check.json`, commit `1adf533`. F1
closed with an open question: its record-high July 2026 ET comes from MOD16A2, a Terra
product, and F4 shows Terra's overpass drifting - a record high at the end of a drifting
record is the shape an artifact takes. This entry answers it with the Aqua counterpart of
the same product, and **F1 stands as published; nothing in it is superseded.**

Record length first, because it decides the method: MOD16A2 v061 and MYD16A2 v061 both begin
**2021-01-01** (catalog and live collection agree; the MODIS Science Team did not produce
v061 data before 2021, and the pre-2021 recommendation is the gap-filled GF product F1 bans).
Six Julys. The task 12/13 regression machinery was **not fitted** - at n = 6 it is not a
sample - and `drought_gee.py`'s `SERIES_START = 2021-01-01` is correct, not a truncation
defect. Terra ET was re-fetched by drought_gee.py's exact method and reproduces
`drought.json` for all 67 months before anything else was allowed to run.

The pre-registered informative outcome fired - both sensors show July 2026 as the extreme ET
month, against each sensor's own record:

| July, per sensor | 2026 ET | rank of 6 | departure from own July mean |
|---|---|---|---|
| Terra (MOD16A2) | **139.6 mm** | **1** | +23.2 mm (+1.96 sd) |
| Aqua (MYD16A2) | **138.3 mm** | **1** | +21.9 mm (+1.91 sd) |

The two July series agree year by year to within about 2 mm (2023 and 2024 within 0.9 mm),
and the recomputed water balance under Aqua ET against the same CHIRPS precipitation keeps
**July 2026 as the only month with P - ET below zero: -22.7 mm** (Terra: -24.0 mm). The
published headline is about the atmosphere and the land, not about Terra.

Two things published for the first time here, per the rule that an index travels with its
quality share:

- Each product's own `ET_QC` bit-0 good share (0 = main algorithm, 1 = back-up algorithm or
  fill). July 2026 has the **highest** July share of each sensor's record (Terra 0.601, Aqua
  0.669), so the record high is not a masking artifact - and in the other direction, roughly
  40-55 percent of July pixels run on climatology-driven back-up, so the MOD16 series has
  always been partly model, and the share now published beside it says how much.
- The geometry series (copied from the vegetation files, not refetched), so a drift control
  on ET becomes runnable the day the record is long enough. At six Julys it is not: the
  question F4 poses *within* the Terra record stays open, and what settles F1 today is the
  cross-sensor agreement, which is the strong branch of the pre-registered test.

Scope caveat, stated in the script's output and worth keeping: MOD16 is Penman-Monteith on
daily reanalysis forcing plus MODIS inputs. The forcing does not move with the overpass; the
MODIS inputs do. ET is a model output, not a band, and this entry claims only that its
published headline is not a Terra-specific artifact - not that drift is impossible, which
six Julys cannot test.

---

## F7 - Six burned-area indices over Biak: only NBR+ refuses the sea and the cloud (2026-09-03)

`src/burn_indices_gee.py` -> `docs/data/burn_indices.json`, commit `272edb5`. Alcaras et al.
(Remote Sens. 14(8):1727, 2022) propose NBR+ because water and clouds produce false alarms in
NBR - and those are the two dominant conditions of this AOI. With no ground truth, the six
indices were judged by where they are certainly wrong: permanent water (WorldCover 80), cloud
and cloud shadow (SCL 3/8/9 from the 28 August scene - the primary post-image is 99.96% clear
over the corridor land it covers and would leave the stratum empty), land beyond 3000 m of
every hotspot detection ever stored, against one burning-plausible stratum (land within
1500 m of a detection strictly before the post scene - never truth) at 20 m in MGRS 53MPU.
The strata are disjoint (six pairwise overlaps, all zero) and every count is within one
tile's footprint.

The scene pair is the survey's measured one, re-derived from its own shares, not re-chosen:
53MPU 2026-07-19 -> 2026-08-23, 57.6% of corridor land usable in both, 80.2% of the event
captured - the post-image is MID-EVENT and the pre-image 35 days earlier, so nothing here is
a severity figure, an area, or a claim about the burning of 23-25 August. Those last two days
were checked separately on the full-coverage pair (-> 2026-08-28, 29.8%, 100.0%), never
pooled with the primary. Reflectance was scaled /10000 before any arithmetic; BAIS2's "+ 1"
sits outside the fraction per the PDF's equation (5); NBR follows equation (1), so HIGH means
burned - the paper's own prose states the USGS convention and contradicts its equation, and
mixing with dNBR literature inverts the scale.

The false-alarm shares (share of a non-burnable stratum above the adjacent stratum's 95th
percentile; a rate against a weak reference, never an accuracy):

| index | uni, open sea | uni, cloud | bi, open sea (primary) | bi, cloud (check pair) |
|---|---|---|---|---|
| NBR | 16.5% | 0.8% | 0.1% | 39.7% |
| NBRSWIR | 98.3% | 0.6% | 0.4% | 51.2% |
| NDSWIR | 0.2% | 0.9% | 0.4% | 18.4% |
| MIRBI | 99.8% | 1.9% | 0.5% | 39.1% |
| BAIS2 | 99.1% | 0.9% | 0.3% | 19.0% |
| NBR+ | **0.0%** | 1.0% | 1.5% | **5.1%** |

Uni-temporally, NBRSWIR, MIRBI and BAIS2 flag essentially the entire sea inside the tile
(97-100%) - disqualified for an AOI that is mostly ocean whatever they scored in Sicily -
and NBR flags 16.5% of it. NBR+ flags none of it, which is equation (6) doing exactly what
section 3.2 claims: blue and green subtraction sends water dark. Differencing (post minus
pre) cancels the static water signature for every index, but the check pair shows where the
bi-temporal form then breaks: cloud, on a scene with cloud to spare, pushes five of the six
indices above the reference over 18-51% of cloud pixels - while NBR+ stays at 5.1%, because
smoke and cloud drive NBR+ negative instead of positive. All six separate the
burning-plausible stratum from far land in the bi-temporal form (adjacent vs far medians,
dNBR+ 0.179 vs 0.027), so the separation the indices exist for is present on the scar side
too; the late-burning clusters of 23-25 August read weaker on 28 August than the 19-22
ground does on 23 August (dNBR+ median 0.027 vs 0.179) - five extra days of tropical
regrowth, or the cloudy scene, or both; one number cannot say which.

**The finding for Phase 4:** on this AOI, in both temporal forms, NBR+ is the only index
whose false alarms stay near zero over the two conditions that dominate every scene here,
while matching the others on the burning-plausible stratum. If Phase 4 proceeds, it should
be built on NBR+ computed bi-temporally, with uni-temporal NDSWIR (0.2% sea, 18.4% cloud on
the cloudy scene) as the cheap second opinion - and with the thresholds still to be chosen
against the published per-stratum distributions by whoever has reference data this task did
not have. No threshold is chosen here and no burned-area total exists anywhere in the
output. This is a comparison of indices, not a map of what burned, and it is not a statement
about the hotspots beyond the geometry of the strata.
