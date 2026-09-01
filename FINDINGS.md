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
