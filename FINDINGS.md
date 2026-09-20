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

---

## F8 - Two figures in F7 were percentiles wearing a median's name, and one comparison ran backwards (2026-09-10)

`docs/data/burn_indices.json`, unchanged since commit `272edb5`; this entry corrects the
prose of F7, not the data behind it. Nothing was recomputed to produce it - the numbers
below were read back out of the same file F7 quoted.

**First correction.** F7 reads "All six separate the burning-plausible stratum from far
land in the bi-temporal form (adjacent vs far medians, dNBR+ 0.179 vs 0.027)". Those two
numbers are 95th percentiles, not medians:

| dNBR+, bi-temporal, primary pair | p50 | p95 |
|---|---|---|
| adjacent | 0.0075 | 0.1795 |
| far | 0.0039 | 0.0268 |

The medians are 0.0075 and 0.0039. F7 describes a separation of roughly six times where
the statistic it names shows less than two.

**Second correction, and the one that matters.** F7 continues: "the late-burning clusters
of 23-25 August read weaker on 28 August than the 19-22 ground does on 23 August (dNBR+
median 0.027 vs 0.179) - five extra days of tropical regrowth, or the cloudy scene, or
both". The pair 0.027 / 0.179 is the same pair as the sentence before it, so this
comparison never touched the late-burning stratum at all. What that stratum actually says,
against the check pair's own adjacent stratum:

| index | late-burning p50 | check adjacent p50 | late-burning p95 | check adjacent p95 |
|---|---|---|---|---|
| NBR | 0.0977 | 0.0700 | 0.4022 | 0.3202 |
| NBRSWIR | 0.0117 | 0.0116 | 0.1211 | 0.1054 |
| NDSWIR | 0.0976 | 0.0664 | 0.3086 | 0.2695 |
| MIRBI | -0.0947 | -0.0955 | 0.3428 | 0.2800 |
| BAIS2 | 0.2421 | 0.2109 | 0.5702 | 0.5232 |
| NBR+ | 0.0273 | 0.0073 | 0.2227 | 0.1794 |

The late-burning ground reads **stronger**, not weaker, on every one of the six indices at
both percentiles. The regrowth-or-cloud speculation in F7 explains a pattern that is not
in the data, and it is withdrawn. Nothing replaces it: this comparison was never designed
to attribute a difference between two scene pairs, and one number still cannot say which
of several causes is at work - only that the sign of the difference is the opposite of
what was written.

**A third figure F7 never computed.** A median gap says little without the spread it sits
in. Normalised by the far stratum's own interquartile range, the bi-temporal separations
rank the other way round from the false-alarm table:

| index | (adjacent p50 - far p50) / far IQR |
|---|---|
| NBRSWIR | 0.71 |
| NBR | 0.49 |
| NDSWIR | 0.40 |
| BAIS2 | 0.32 |
| MIRBI | 0.29 |
| NBR+ | 0.24 |

NBR+ separates the burning-plausible stratum least of the six.

**The Phase 4 recommendation survives, for a reason F7 left implicit.** The false-alarm
table is not a second opinion on separation: its threshold is the adjacent stratum's own
95th percentile, which pins sensitivity at 5% for every index by construction. Under equal
sensitivity, the only thing left to compare is the false-alarm rate, and there NBR+ wins
by an order of magnitude on the two conditions that dominate this AOI. So the ranking
above does not overturn F7's conclusion - it says the conclusion rests on the false-alarm
column alone, and that F7's appeal to "matching the others on the burning-plausible
stratum" was the weakest sentence in it.

The scope caveats of F7 stand unchanged: mid-event post-image, no ground truth, no
threshold chosen, no burned-area total anywhere in the output.

---

## F9 - Terra and Aqua agree on ET partly because they are reading the same inputs (2026-09-10)

`References/MOD16_User_Guide_V61.pdf` (MODIS Land Team, v1.0, 2021-02-26) against
`docs/data/drought_et_check.json`, commit unchanged. This narrows F6; it does not
overturn it.

F6 tested whether the published July 2026 water-balance headline is an artifact of Terra's
orbital drift (F4) by recomputing it under Aqua, and found the two sensors agree. That test
is only as strong as the independence of the two ET series. The user guide says how
independent they are, and the answer is: less than the phrase "cross-sensor agreement"
suggests.

- **Albedo is already a combined product.** MCD43A2/A3, and the guide is explicit about
  what the letters mean: "Both Terra and Aqua data are used in the generation of this
  product ... designating it as an 'MCD,' meaning 'Combined,' product" (§3.2, guide page
  15). MOD16A2 and MYD16A2 take the same albedo.
- **Meteorology is a single stream.** GMAO/MERRA, "distributed at a resolution of 0.5 x 0.6
  degrees (MERRA GMAO) or 1.00 x 1.25" and interpolated from the four nearest cells to each
  0.5 km MODIS pixel (guide pages 20-21). There is no Terra meteorology and no Aqua
  meteorology.
- **Only LAI/FPAR is sensor-specific**: MOD15A2H for Terra, MYD15A2H for Aqua (guide pages
  17-18).
- **And the FPAR gap-fill is combined too.** Contaminated FPAR in MOD15A2H is backfilled
  from MCD15A2HCL - "MCD" again - built from "both MOD15A2H and MYD15A2H" over a five-year
  window (Figure 3.2 and guide page 17).

That last point is what makes this worth recording rather than filing as trivia. F6's own
quality shares say how many pixels are on the backup path in the month under test:

| July | ET_QC good share, Terra | Aqua |
|---|---|---|
| 2021 | 0.4767 | 0.4201 |
| 2022 | 0.5871 | 0.4778 |
| 2023 | 0.5339 | 0.4988 |
| 2024 | 0.4658 | 0.4269 |
| 2025 | 0.4501 | 0.4942 |
| **2026** | **0.6007** | **0.6686** |

July 2026 is the best-quality July of both records, and still 33% of Terra pixels and 40%
of Aqua pixels ran on backup or fill. On those pixels the two sensors are not two
measurements of the same thing; they are two products sharing an albedo, a meteorology,
and a gap-filled FPAR climatology drawn from both of them.

**What F6 may still claim.** That the published headline is not a Terra-drift artifact -
because drift acts through the MODIS observation path, and that path is where the two
products genuinely differ. What F6 may not claim, and did not, is that agreement between
them is an independent replication of the ET estimate. The shared inputs mean the test has
less power than its phrasing implies, and the honest reading is that it rules out one
specific alternative rather than confirming the number.

This does not touch F1: what F1 rests on is the water balance's shape across six years,
and the ET series enters it the same way in every year.

---

## F10 - Burning on Biak is mostly seen once, and a 24-hour event window cuts it on overpass timing (2026-09-19)

`src/events.py` -> `data/processed/events.json`, commit `7b20997`; parameters and their
reasons in `config.yaml` under `events:`. Task 16, PLAN.md Phase 3 items 1-2. Built on the
store as of 2026-09-16: 1,150 detections, 2023-09-01 to 2026-09-16.

**The unit.** Space-time DBSCAN, neighbours within 750 m and 30 h on `datetime_utc`,
`min_samples` 2. The store becomes **484 events, of which 337 (70%) are singletons** - one
pixel on one overpass. Of the 147 multi-detection events, the median has 2 detections and
lasts 0.6 h (two satellites minutes apart over the same afternoon); the 90th percentile has
8 detections and lasts 25.8 h; 49 span two or more WIT days. 2026 alone holds 308 of the 484,
so any per-event statistic here is mostly a statement about one season.

**Why 30 h and not PLAN.md's 24 h.** Burning here is daytime only (PLAN.md 10.4: 651 of 653
detections), so a plot burned on consecutive afternoons is re-detected about a day later.
But the satellites do not return at the same minute: VIIRS afternoon passes over the AOI fall
between 12:34 and 14:21 WIT across S-NPP, NOAA-20 and NOAA-21, and Aqua as late as 15:48.
Measured on the store, 1,808 pairs of detections within 750 m of each other and 18-30 h
apart have gaps from **21.1 to 26.9 h** (median 23.7 h), and **653 of them (36%) exceed
24 h**. A 24 h window separates those pairs on overpass timing alone, not on anything about
the ground. 30 h covers the observed spread with margin and stays far below the shortest
two-day gap (44.8 h). 36 h gives the same events to within one (484 vs 483), which is what
a threshold past the edge should do: once it clears the jitter, the answer stops moving.

(The commit message for `7b20997` says a 24 h window splits "roughly half" of these pairs.
That was stated before it was measured. The measured share is 36%, as above.)

**Why 750 m and not 1000 m.** At 1000 m the events touching the Saramom recurrent site
chain into one 4.5 km event across 19-25 August 2026; at 750 m the largest is 2.6 km -
close to the 2 km north-south feature PLAN.md 11.4 found there, rather than twice it. 750 m
is two VIIRS pixels, and the same value as `recurrence.radius_m`.

**Chaining did not happen.** The failure the task warned about - the south corridor
collapsing into one island-wide event - does not
occur at any setting tried, though 485 detections fell across the AOI on 21-22 August. The
largest event is 3.4 km across even at 1500 m / 48 h. Grid
(events, singletons, largest event's detections and extent):

| eps_m | eps_h | events | singletons | largest | extent km |
|---|---|---|---|---|---|
| 375 | 12 | 696 | 523 | 64 | 2.8 |
| 375 | 24 | 616 | 470 | 135 | 3.4 |
| 750 | 24 | 496 | 349 | 140 | 3.4 |
| **750** | **30** | **484** | **337** | **142** | **3.4** |
| 750 | 36 | 483 | 336 | 142 | 3.4 |
| 1000 | 24 | 450 | 311 | 141 | 3.4 |
| 1000 | 30 | 433 | 296 | 143 | 3.4 |
| 1500 | 48 | 371 | 250 | 143 | 3.4 |

The spread across the grid is in how *small* events are cut, not in whether large ones
merge: the event count moves from 696 to 371, the largest event barely moves at all.

**The four known events, at the chosen parameters:**

1. **19-25 August 2026** (PLAN.md 10.4): 647 detections in **139 events**, not one. The
   largest, **E0301**, is 142 detections in Anjareuw, first seen 19 August 12:47 WIT and last
   seen 144.5 h later, FRP sum 1,672 MW. Its centroid lies 1.3 km from the -1.185, 136.130
   cluster PLAN.md 10.4 named, but it does not hold the season's single strongest detection:
   its own maximum is 70.1 MW against 90.5 MW that week. Its convex hull is 684 ha; that is
   the envelope of pixel centres, not a burned area, and it can contain unburned ground
   between plots.
2. **Airport-adjacent, August 2026** (PLAN.md 11.3): 39 detections within 3 km in 11
   events; none chains across months.
3. **Saramom** (PLAN.md 11.2, 11.4): 121 detections within 750 m in **62 events** over three
   years - a recurrent *location* burned in many separate *episodes*, which is the
   distinction Task 04 and Task 16 exist to keep apart. The largest episode touching it,
   E0313, is the August 2026 one: 41 detections, 73% of them on the recurrent site.
4. **Anjareuw, 3-4 September 2026**: **E0463**, 4 detections from 12:47 to 13:04 WIT on
   3 September. The surveyor photographed the same ground actively smoking on 4 September
   at 13:53 WIT, and nothing was detected that day. E0463's `last_seen` is therefore 3
   September while the burning was not over - the worked example for why `last_seen` must
   never be read as "burning stopped".

**Road distance, and what it does not yet show.** The median distance from an event's
first-seen position to the nearest driveable OSM road is 295 m (multi-detection events:
283 m, 90th percentile 1,065 m). This is not yet evidence that burning concentrates near
roads. First, 295 m is inside one VIIRS pixel of positional uncertainty. Second, there is no
null distribution: how far random land on Biak lies from a mapped road has not been
computed, and without it a median distance has nothing to be compared against. Third, OSM
maps roads unevenly here, so a large distance may mean an unmapped track. The comparison
against random land is the next step before this number supports any sentence.

**Scope.** No field in the record claims ignition: `first_seen` is the first overpass that
caught heat. Nothing here attributes cause (PLAN.md section 8). Land cover at first-seen and
distance to settlement are not computed; there is no tracked land-cover raster and no
settlement layer in the repository.

---

## F11 - Burned area for 23 events, and the reference land the record has used up (2026-09-20)

`src/burned_area_gee.py` -> `data/processed/burned_areas.json` and `burned_areas.geojson`,
commit `ddc2d3b`, run by hand on 2026-09-20 against the store to 2026-09-16 and events
registry v1. PLAN.md Phase 4 items 1-3; Task 18.

**What was measured.** For each of the 31 events with at least 5 detections: the share of
its footprint (375 m around each member detection) whose dNBR+ rose above a local,
false-alarm-controlled threshold between the clear Sentinel-2 look nearest before the event
and the nearest after. The threshold is the 99th percentile of dNBR+ over land within 10 km
that lies farther than 3 km from every detection ever stored, so 1% of never-detected land
nearby exceeds it by construction. It is not calibrated against ground truth and carries no
accuracy.

**23 events carry an area. 8 do not**, and the reason is the finding below.

| | ha |
|---|---|
| footprint, land | 6,291 |
| clear in both looks | 5,899 |
| **changed like a burn** | **2,415** |
| upper bound if every cloud-gap pixel had changed | 2,807 |
| false-alarm allowance the threshold admits (1% of clear) | 59 |

40.9% of the clear footprint changed. Per event the median is 62 ha and the largest,
**E0301** (142 detections, Anjareuw, 19-25 August 2026), is 503 ha of 924 ha, all of it
clear. One event, E0462, returned 0.0 ha against a threshold of 0.271: the method's own
answer that nothing there changed more than nearby never-burned land.

Thresholds ranged 0.0164 to 0.2710 (median 0.0838) - a sevenfold spread that is exactly
why a single fixed threshold was refused. Post-event looks came a median of 2.9 days after
`last_seen`, the worst event's 90th percentile 20.9 days. 2026 holds 20 of the 23 assessed
events and 2,179 of the 2,415 ha.

**What the land was, the year before it changed** (Esri 10 m annual, so 2025 for a 2026
event):

| class | clear ha | changed ha | share changed |
|---|---|---|---|
| trees | 4,440.2 | 1,806.4 | 40.7% |
| rangeland | 1,209.7 | 545.2 | 45.1% |
| built | 227.7 | 57.3 | 25.1% |
| bare | 5.3 | 1.0 | 18.3% |
| crops | 2.2 | 1.0 | 45.0% |

**Three quarters of the changed area (74.8%) was mapped as trees the year before.** Read
it with care in both directions. Trees are also 75% of the footprint, so the *share* that
changed is nearly the same for trees (40.7%) and rangeland (45.1%): at this resolution the
burning is not selecting between them, it is following what is there. And Esri's "trees"
on Biak includes regrowth on land that was cleared before the record began, which F10's
shrub disagreement with Dynamic World already showed is contested ground.

**The reference land is nearly used up inside the burning corridor.** This is the result
that matters for method. The eight events with no area failed for one reason: within 10 km
of them, almost no land is farther than 3 km from *some* detection in the three-year
record. Measured on their own rings:

| event | ring land ha | of that, >3 km from every detection |
|---|---|---|
| E0339 | 18,705 | 25 |
| E0323 | 24,959 | 51 |
| E0341 | 25,705 | 72 |
| E0267 | 19,341 | 102 |
| E0109 | 19,045 | 83 |

Between 0.1% and 0.5% of nearby land qualifies. Three of the eight are from 21 August 2026,
the densest burning day in the record. **The threshold method degrades exactly where
burning is densest**, because its reference is defined by the absence of the thing being
measured, and three years of detections have covered the corridor.

Cloud is not the cause. Dropping the exclusion from 3 km to 1.5 km raises the reference
land on those same rings from 25-102 ha to 2,432-4,867 ha. That change is available but it
is not free: F7 treats land within 1,500 m of a detection as burning-plausible, so a 1.5 km
reference would include ground that may have burned, pushing the threshold up and the
measured area down. The conservative direction, but a different measurement. **No
parameter was changed for this entry**; the numbers above are all at 3 km, and the choice
is recorded here rather than made quietly.

**Scope.** Areas are "changed like a burn", not confirmed burned area: there is no
reference data on Biak, so no accuracy, no omission rate, and no severity class is
reported. Light burns below the local noise are missed. Nothing here says why any land was
burned or who burned it (PLAN.md section 8). 1,050 polygons are published alongside the
table in `burned_areas.geojson`, clipped to event footprints; they are not a burned-area
map of Biak, only of the 23 events assessed.
