# Mapping burned area on a small tropical island: a false-alarm-controlled index threshold, audited against 1 m reference imagery

Draft manuscript. Every figure traces to a numbered entry in `FINDINGS.md` and to the commit named there.

## Abstract

Burned-area products are usually validated where fires are large, fuels are well described, and reference imagery is plentiful. Biak, a raised coral island in Papua, Indonesia, meets none of those conditions: burning is small, deliberate, and daytime; cloud dominates every optical scene; and no local fuel map or burn-scar reference exists. We mapped burned area for 23 burning events between 2023 and 2026 by thresholding bi-temporal NBR+ against a locally estimated, false-alarm-controlled threshold, and then audited the result against 142 hand-labelled 60 m boxes read on 1 m reconstructed Sentinel-2 imagery.

Three results matter beyond this island. First, index choice is decided by where an index is certainly wrong, not by where it looks right: of seven burned-area indices tested over open sea and cloud, only NBR+ kept false alarms near zero in both conditions. ATBI, a recently published index, flagged 43.5% of water pixels against NBR+'s 0.0%. Second, the product under-maps rather than over-maps. The stratified estimate is 1,230 ha (95% CI 1,060 to 1,342 ha) against 819 ha mapped, with commission almost absent (49 of 50 mapped boxes confirmed) and omission at 428 ha. Reading the same labels as a classification problem agrees: the threshold's recall on unclaimed ground inside footprints is 0.27 against 0.96 or better for classifiers on the identical bands. Third, the "before" image is staler than the "after" image. The per-pixel clear look preceding an event lagged by a median of 12.2 days against 2.9 days after it, and on 14 events carrying 1,368 ha a prior hotspot predates that before-image, so the reference scene may already hold an older scar.

We argue that the pre-image selection step, rarely reported in burned-area work, is a first-order source of omission in cloudy tropical settings, and that its audit costs nothing beyond the lag statistics most compositing pipelines already compute.

## 1. Introduction

Global burned-area products are calibrated where they can be: boreal and temperate forest, Mediterranean shrubland, savanna. Humid tropical islands with small, fragmented, deliberately lit fires are a poor fit, and the reasons compound. Fires are short and rarely survive the night, so coarse thermal sensors see them once. Cloud cover removes most optical observations. Fuels are mapped by global products built on continental training data. Reference data are absent.

This study works in that setting and reports what survives it. Our aim is not a new index or a new algorithm. It is an honest accounting of a conventional method, a bi-temporal spectral index above a threshold, when every supporting assumption is weak, and an identification of which weak assumption costs the most.

We make three contributions.

We show that index selection in this setting is best framed negatively. With no burn-scar reference, we rank indices by their false-alarm rate over strata where burning is impossible or near impossible: permanent water, cloud and cloud shadow, and land that has never carried a thermal detection. This reverses the usual validation logic and needs no ground truth.

We report a stratified accuracy assessment following Olofsson et al. (2014), and we report it twice, because the first assessment rested on a sample too small to settle the question and the second reversed its conclusion. Keeping both visible is part of the result.

We introduce a diagnostic for the pre-event image that, to our knowledge, is not routinely reported: the lag between the chosen pre-event look and the most recent prior thermal detection inside the same footprint. When a prior detection precedes the pre-image, the reference scene may already be dark, and the index measures change from burned ground.

## 2. Study area

Biak Numfor and Supiori lie off the north coast of Papua, Indonesia, near 1°S. The islands are raised coral limestone, not peatland. This distinction governs the analysis. Peat-fire frameworks developed for Sumatra and Kalimantan assume smouldering ground fire with long residence time, high radiative power, and slow extinction. Nothing in that description applies here.

The burning regime is daytime and repetitive. In the first full season examined, 651 of 653 detections were daytime and 2 were at night. Fires that do not survive the night, recurring at the same places across consecutive days, are the signature of deliberate land clearing rather than escaped wildfire. Three recurrent sites met our persistence criteria; the largest, at Saramom, carried 120 detections across 74 distinct days between September 2023 and August 2026.

A corridor of 141,141 ha of land, defined by the field survey targets with a 5 km buffer, frames every area figure below.

![**Figure 1.** The study area. (a) Biak, Supiori and Numfor with all 1,166 stored detections, 2023 to 2026; the box marks the detail in (b). (b) The dNBR+ burned area for the assessed events, with the 142 reference boxes by sampling design. Boxes are drawn at their centroids and are 60 m across, so they are not to scale at this zoom.](figures/fig1_study_area.png)

### 2.1 Two episodes, corroborated from the ground

An independent record confirms that the 2026 burning was exceptional and locates it in time. The airport meteorological station at Biak reported smoke (`FU`) on no day in 2023, 2024 or 2025, and on 17 days in 2026, in two runs: 14 and 22 to 29 August, then 3 and 12 to 18 September. Of 488 events tested against 51,838 reports, 124 are corroborated by smoke from the right direction within 50 km, and every one of them began in August or September 2026.

The corroboration is of episodes, not of events. The median corroborated event shares its reports with 120 others, and only 6 share with five or fewer. Two events 44 degrees apart as seen from the station are corroborated by the same two reports, because the upwind test uses a 90 degree sector. A smoke report is strong evidence that smoke reached the airport; its absence is close to no evidence at all.

### 2.2 What limits observation

Dry days are clear days, and an optical or thermal sensor sees more on them. Any association between dryness and detected burning is therefore confounded with observability, and we measured the size of that confound rather than assuming it away.

Splitting 1,076 scored days by the airport's reported sky at the time of the afternoon overpass:

| sky at the day pass | days | days with a detection | share |
|---|---|---|---|
| no broken or overcast layer | 734 | 101 | 13.8% |
| broken or overcast | 342 | 3 | 0.9% |

On a cloudy day there is almost never a detection, whatever burned. Restricting to clear days removes the obvious part of the confound, and the association survives it: fuel dryness indices from the Canadian Fire Weather Index system, computed from ERA5-Land, still rank days with burning well above a day-of-year climatology, with average precision of 0.701 against 0.207 in 2023 and 0.623 against 0.258 in 2026. The airport is one point and its sky is not the sky over every plot, so this removes the obvious part of the confound rather than all of it.

The practical consequence for this study is that absence of detection is weak evidence of absence of burning, and the burned-area footprints inherit that weakness, since they are built from detections.

## 3. Data

### 3.1 Active fire detections

We used NASA FIRMS VIIRS and MODIS detections, 1,166 rows spanning 2023-08-31 to 2026-09-23, stored with acquisition time in UTC and a derived local day in WIT (UTC+9). Daily aggregation uses the local day, because night detections otherwise fall into the wrong date.

Two handling rules are worth stating because both are easy to get wrong. The `confidence` column holds two vocabularies at once: VIIRS returns `l`, `n`, `h` while MODIS returns 0 to 100. Coercing that column to a number silently discards most VIIRS rows; in one early sample it would have dropped 642 of 653. We keep it as text. Fire radiative power is retained throughout, since it is the only intensity measure available.

### 3.2 Events

Detections were grouped into events by space-time DBSCAN with a 750 m spatial radius, a 30 hour temporal radius, and a minimum of 2 samples. The 30 hour window follows from overpass geometry rather than from a calendar day: VIIRS passes between 12:34 and 14:21 WIT and Aqua as late as 15:48, so a plot burned on two consecutive afternoons is re-detected 21 to 27 hours later. A 24 hour window, the obvious choice, puts 36% of 1,808 measured same-place pairs outside it. The grouping yields 488 events, of which 31 carry at least 5 detections.

### 3.3 Optical imagery

Sentinel-2 L2A surface reflectance supplied the index work, masked per pixel by Cloud Score+ `cs_cdf` at a 0.6 threshold. Reflectance was divided by 10,000 before any arithmetic.

Reference imagery came from S2DR4 (Gamma Earth), which reconstructs 1 m imagery from Sentinel-2 by inferring ground conditions beneath cloud and haze from other acquisitions. This is central to interpreting the reference labels and we return to it in Section 7.

### 3.4 Land cover

Three products were used, each for what the others cannot do: ESA WorldCover v200 (2021, 10 m) as the base, Dynamic World (10 m, contemporary) as an independent reading, and JRC Tropical Moist Forest (Landsat, 30 m, December annual maps) to separate closed forest from regrowth on previously cleared land.

## 4. Methods

### 4.1 Index selection without reference data

Seven indices were compared over MGRS tile 53MPU: NBR, NBRSWIR, NDSWIR, MIRBI, BAIS2, NBR+ (Alcaras et al., 2022), and ATBI (Bilal, 2025). Four disjoint strata were defined, three of them conditions where a burned-area index should not fire:

- permanent water (WorldCover class 80),
- cloud and cloud shadow (Scene Classification Layer classes 3, 8, 9),
- land beyond 3,000 m of every stored detection,
- land within 1,500 m of a detection strictly preceding the post-image, the single burning-plausible stratum, which is never treated as truth.

All six pairwise stratum overlaps are zero and all counts fall inside one tile footprint. The false-alarm rate for each index is the share of a non-burnable stratum exceeding the 95th percentile of the burning-plausible stratum. This is a rate against a weak reference, not an accuracy.

Both temporal forms were computed: uni-temporal on the post-image alone, and bi-temporal as the difference between a pre-image and a post-image.

ATBI was added later and is NBR multiplied by the SWIR/NIR ratio. Writing `r = B12/B8A`, ATBI equals `r(r-1)/(r+1)`, which is minimised at `r = sqrt(2)-1` with value `-(3-2*sqrt(2)) = -0.171573` and is unbounded above. The published minimum over never-detected land is -0.1716, the arithmetic confirming itself on real data. A `B8A > 0` mask is required to avoid division by zero; it removed 1,576 of 1,482,657 water pixels (0.1%) and nothing outside water.

### 4.2 Burned area

For each event with at least 5 detections, the footprint is the union of 375 m circles around its member detections, one VIIRS pixel each, which also absorbs geolocation jitter. Burning outside the footprint is not attributed to the event.

Pre- and post-images are not single scenes. For each pixel independently, the pipeline takes the latest clear look within 60 days before `first_seen` and the earliest clear look within 30 days after `last_seen`, masked at `cs_cdf >= 0.6`, and records the lag in days from the anchor. The 30 and 60 day windows are search windows, not averaging windows. The event day itself is excluded on both sides, since a same-day look may hold the burning or may not, and neither is a clean before or after.

The threshold is local and event-specific: the 99th percentile of dNBR+ over land within 10 km of the event centroid that lies farther than 3,000 m from every stored detection. By construction, 1% of never-detected land nearby exceeds it. A stratum with fewer than 2,500 clear pixels (100 ha) yields no threshold and the event is not assessed. All index work is at 20 m.

### 4.3 Reference labelling

A 60 m box, nine 20 m pixels of the product under test, is small enough to hold one cover type and large enough to judge on 1 m imagery. Boxes were sampled under three designs with a minimum separation of 150 m:

- `map_burned`, drawn inside the dNBR+ polygons,
- `footprint_unmapped`, drawn by area inside footprints on ground the map does not claim,
- `random_box`, drawn at random points.

142 boxes were judged as burned, unburned, or unsure by a single interpreter on S2DR4 1 m chips at six dates. Boxes judged `unsure` are excluded from the denominator rather than assigned. The strata are never pooled, because their inclusion probabilities differ and `map_burned` is biased in the product's favour by construction.

### 4.4 Area and accuracy estimation

Burned area is estimated as the area-weighted sum over two area-carrying strata: ground the map claims (A), and ground inside a footprint that the map does not claim (B). Stratum B is sampled by two designs and both are carried. Boxes outside the footprints are counted and reported but carry no area, since their stratum has no defined extent short of the whole island.

Weights are the areas each stratum actually covers, restricted to land inside the 1 m imagery frame: a box the interpreter cannot see is not a sample unit.

Intervals are reported two ways. Wilson score intervals at 95% behave at zero successes, where the normal approximation collapses to a point. The Olofsson et al. (2014) estimator, which uses the normal approximation, is reported beside them. In the first assessment the two disagreed about whether the mapped figure lay inside the interval, and that disagreement was the result (Section 6.4).

### 4.5 A second view of the same labels

Area estimation reads the labels one way. To read them another way, we also treated the problem as per-pixel classification and asked a different question: given the same spectral evidence the threshold sees, how much of what the threshold decides is forced by the data rather than by the threshold.

Features are the native 20 m reflectance the product itself uses, from the same pre- and post-event looks: six bands before, six after, their six differences, four difference indices (dNBR+, dNBR, dNDVI, dNBR over the short-wave infrared pair), and the two look lags. That is 24 columns. The 1 m imagery is only ever the reference and is never an input. Three classifiers were fitted, a depth-3 decision tree, histogram gradient boosting, and a random forest, with folds leaving one event out, so no event is scored by a model that saw it.

Two rules are scored beside them: the Task 18 threshold itself, and a trivial rule that claims the whole footprint burned. Results are reported per stratum and never pooled, for the reason given in Section 4.3, and at box level as well as pixel level, since the box is the unit the reference was judged on.

This is a diagnostic, not a proposed replacement. No burned-area figure in this paper is derived from a classifier.

## 5. The fuel question

`PLAN.md` for this project states a local correction and asks for it to be checked: expect savanna, grassland, secondary shrub and shifting-cultivation plots, not peat. We built a six-class fuel map by reclassifying the three land-cover products, with TMF splitting WorldCover's single tree class into closed forest and regrowth.

Over 141,141.4 ha of corridor land:

| fuel class | ha | share |
|---|---|---|
| grass and savanna | 3,857.5 | 2.73% |
| shrub and regrowth | 8,056.3 | 5.71% |
| cultivation mosaic | 2.2 | 0.0015% |
| closed forest | 128,321.6 | 90.92% |
| mangrove | 106.5 | 0.08% |
| non-fuel | 797.3 | 0.56% |

The expectation is wrong about what is there. Moving all 15,418.8 ha of TMF-degraded forest into shrub still leaves closed forest at 79.99% against shrub at 16.63%. No reclassification rescues it.

The expectation is right about what burns. Grass is 2.73% of the corridor and 13.98% of detections; shrub is 5.71% against 23.33%; closed forest is 90.92% against 59.09%. Over mapped burned area the shares are 13.04%, 32.22% and 54.26%.

These are different claims and we keep them apart. The enrichment is an association: detections are where satellites saw heat, not a random sample of land, and we offer no significance test.

Two limits bound every figure above. Dynamic World labels only 66.14% of corridor land, and unevenly: 66.6% over forest, 59.8% over grass, 43.8% over mangrove, so the two-product comparison is thinnest where the products disagree most. The largest off-diagonal is WorldCover forest read as Dynamic World non-fuel, 1,495.2 ha. The cultivation class at 2.2 ha is a product limitation, not evidence that no gardens exist; TMF deforested and regrowth, 8,056.3 ha, is their likely home.

We did not use the FGBFM 40 scheme (Scott and Burgan, 2005). It is calibrated on United States fuels and has no Papuan analogue, and importing it would repeat the peat-frame error in another form.

## 6. Results

### 6.1 Index comparison

False-alarm shares over the non-burnable strata:

| index | uni, open sea | uni, cloud | bi, open sea | bi, cloud |
|---|---|---|---|---|
| NBR | 16.5% | 0.8% | 0.1% | 39.7% |
| NBRSWIR | 98.3% | 0.6% | 0.4% | 51.2% |
| NDSWIR | 0.2% | 0.9% | 0.4% | 18.4% |
| MIRBI | 99.8% | 1.9% | 0.5% | 39.1% |
| BAIS2 | 99.1% | 0.9% | 0.3% | 19.0% |
| NBR+ | 0.0% | 1.0% | 1.5% | 5.1% |

Uni-temporally, NBRSWIR, MIRBI and BAIS2 flag essentially the entire sea inside the tile, which disqualifies them for an area that is mostly ocean whatever they scored elsewhere. Differencing cancels the static water signature for every index, but the cloudy check pair shows where the bi-temporal form then breaks: cloud pushes five of six indices above the reference across 18% to 51% of cloud pixels, while NBR+ stays at 5.1%, because smoke and cloud drive NBR+ negative rather than positive.

ATBI, added later, inverts the pattern in the one place that matters here:

| index | water | cloud | never-detected land |
|---|---|---|---|
| NBR+ | 0.0000 | 0.0099 | 0.0002 |
| ATBI | 0.4352 | 0.0090 | 0.0006 |

43.5% of water pixels clear ATBI's threshold against none of NBR+'s. ATBI is published here as a distribution, not as a threshold or an area. Scoring it against the reference boxes, with the separability index its source paper reports as 1.38 against dNBR's 1.29, was not performed.

All seven indices separate the burning-plausible stratum from never-detected land in the bi-temporal form, so the separation the indices exist for is present on the scar side as well.

![**Figure 2.** False alarms where burning is impossible or near impossible, as a percentage of each stratum above the burning-plausible stratum's 95th percentile. NBR+ is highlighted. Uni-temporally, three indices flag essentially the whole sea; differencing cancels that, and then cloud breaks five of the seven on a cloudy pair. ATBI is the only index whose water false alarms rise after NBR+'s fall to zero.](figures/fig3_false_alarms.png)

### 6.2 Burned area

23 of 31 eligible events carry an area; 8 lack a sufficient local reference stratum.

| | ha |
|---|---|
| footprint, land | 6,291 |
| clear in both looks | 5,899 |
| changed like a burn | 2,415 |
| upper bound if every cloud-gap pixel had changed | 2,807 |
| false-alarm allowance the threshold admits | 59 |

40.9% of the clear footprint changed. The per-event median is 62 ha; the largest, E0301 at Anjareuw with 142 detections in August 2026, is 503 ha of 924 ha, all of it clear. One event returned 0.0 ha against a threshold of 0.271, the method's own answer that nothing there changed more than nearby never-burned land. Thresholds span 0.0164 to 0.2710 with a median of 0.0838, a sevenfold spread that is precisely why a single fixed threshold was refused.

### 6.3 What burned, as two products describe it

Read against Esri's annual 10 m land cover, 74.8% of the changed area was trees the year before. Read against TMF, 14.7% was undisturbed forest.

| TMF class | clear footprint ha | changed ha | share of changed | share of class changed |
|---|---|---|---|---|
| undisturbed forest | 1,534.9 | 354.2 | 14.7% | 23.1% |
| other land | 1,490.4 | 691.7 | 28.6% | 46.4% |
| degraded forest | 1,118.8 | 426.1 | 17.6% | 38.1% |
| regrowth | 966.5 | 537.5 | 22.3% | 55.6% |
| deforested earlier | 787.2 | 405.3 | 16.8% | 51.5% |

Intact forest burned at 23.1% of its extent; regrowth at 55.6%. A single-class "trees" product cannot show that, and reporting only Esri's figure would have supported the opposite reading of what this burning does.

### 6.4 Accuracy, reported twice

The first assessment used 67 boxes from two strata. The second used 136 decided boxes from three, after the interpreter re-read every box against a later 1 m chip and changed 91 of 142 rows.

| | 67 boxes | 136 boxes |
|---|---|---|
| A, mapped | 36/41 = 87.8% | 49/50 = 98.0% |
| B, unmapped in footprint | 6/26 = 23.1% | 31/58 = 53.4% |
| estimate | 903.8 ha | 1,230.3 ha |
| 95% CI (Wilson) | 698 to 1,112 ha | 1,060 to 1,342 ha |
| mapped figure, 819 ha | inside | outside |
| boxes excluded as unsure | 21 | 6 |

The conclusion reverses rather than shifts. Commission falls to almost nothing: the map claims 49 of 50 boxes correctly. Omission rises to 427.6 ha (CI 326 to 525) from 184.6 ha. The Olofsson estimator agrees at 1,230 ha (CI 1,122 to 1,339), and for the first time the two estimators concur that the mapped figure falls outside the interval. The zero-count problem that split them in the first assessment is gone, because stratum B is no longer 0 of 10.

The product under-maps. That is the opposite of what the first assessment concluded, and we report both because the first was not a mistake in method; it was a sample too small to answer the question.

### 6.5 Did the re-labelling measure the wrong fire?

The re-read leaned on a 17 September chip while the product was computed from looks a few days after August burning. If those boxes burned in September, counting them as omission would penalise the map for fire that had not yet happened. The detection record runs to 2026-09-23, so the concern is concrete.

It does not survive measurement. The latest detection within 375 m of any of the 142 boxes is 2026-09-03, and no box has a detection postdating the 17 September chip. Seventeen boxes have one postdating the 28 August chip: 9 `footprint_unmapped`, 5 `map_burned`, 3 `random_box`.

| stratum | judged | burned | also post-28 August |
|---|---|---|---|
| `footprint_unmapped` | 46 | 26 | 4 |
| `map_burned` | 50 | 49 | 5 |
| `random_box` | 40 | 19 | 1 |

Removing all four from stratum B still leaves 27 of 58 (47%) against the 23% the first assessment rested on, and 819 ha still falls outside the interval. The omission term survives. The September 2026 episode occurred away from the reference boxes.

One named case is refuted outright. The single box whose note records a date, reading "very obviously burned" on 17 September, has its latest detection within 375 m on 2026-08-24 and its nearest on 2026-08-23 at 19.4 m. Nothing burned near it after the 28 August chip.

### 6.6 The pre-image is staler than the post-image

Across the 23 assessed events:

| | median of p50 | maximum of p50 | events with p50 above 14 days |
|---|---|---|---|
| post-event lag | 2.9 d | 12.4 d | 0 |
| pre-event lag | 12.2 d | 29.1 d | 7 |

Those seven events carry 620.66 ha of the 2,414.9 ha total, the worst at 29.1 days. The asymmetry has a plain cause: the post window searches forward into clear dry-season skies while the pre window searches backwards through the cloudier build-up.

![**Figure 3.** Each assessed event's burned area against the age of the clear look the pipeline chose for its median pixel, before the fire (a) and after it (b). Marker shape and colour give the direction defined in the text. The shaded band is more than 14 days from the event: seven events carrying 620.66 ha fall inside it on the pre-event side and none does on the post-event side.](figures/fig2_look_lag.png)

Writing `P` for the pre look, `D` for the most recent prior detection inside the footprint, and `F` for `first_seen`:

| condition | interpretation | events | ha |
|---|---|---|---|
| `D < P < F` | scar may already be in the pre-image; area understated | 14 | 1,367.8 |
| `P < D < F` | earlier burning counted as this event; area overstated | 5 | 828.3 |
| no prior detection | neither | 4 | 218.8 |

57% of the assessed hectares fall in the first row. These two directions are never summed: they move the area in opposite senses, and a single count of events at risk would hide that.

Two limits stop this being a correction. The pipeline stores the pre-event lag only as two percentiles over each event's pixels, never per pixel and never as a date, so each pre-look date here is a percentile estimate and is labelled as one. And a VIIRS pixel is 375 m: a prior detection inside a footprint makes contamination possible, not established. No area was recomputed and no correction is proposed.

### 6.7 The same omission seen from per-pixel classification

Section 6.4 measures omission by stratified area estimation. This subsection measures it a second way, from the same labels but by classification rather than by area, and the two agree.

Box-level precision and recall, pooled over leave-one-event-out folds, on 1,230 modelled pixels in 142 boxes:

| rule | `random_box` | `map_burned` | `footprint_unmapped` |
|---|---|---|---|
| trivial: all of the footprint burned | 0.68 / 0.68 | 0.98 / 1.00 | 0.57 / 1.00 |
| Task 18 threshold | 0.86 / 0.63 | 1.00 / 0.90 | 0.88 / 0.27 |
| decision tree, depth 3 | 0.77 / 0.89 | 1.00 / 1.00 | 0.87 / 1.00 |
| histogram gradient boosting | 0.74 / 0.89 | 1.00 / 0.98 | 0.86 / 0.96 |
| random forest | 0.80 / 0.84 | 1.00 / 0.98 | 0.87 / 1.00 |

The threshold's precision is high everywhere: 0.86 in the random sample, 1.00 inside its own polygons, 0.88 on unclaimed ground inside footprints. All three classifiers are worse than it on precision in the random stratum. Whatever is wrong with the product, it is not that it claims ground which did not burn.

Recall is where it fails, and the figure that matters is 0.27 in `footprint_unmapped`. Of 26 boxes that burned inside a footprint on ground the map does not claim, the threshold finds 7 and misses 19. Every classifier recovers essentially all of them, at 0.96 to 1.00, while holding precision near 0.87. The spectral evidence to separate those boxes is present in the same 20 m bands the threshold reads; a single local cut on one index does not extract it.

This is the 427.6 ha of Section 6.4 seen from a different direction. The two methods share only the labels: one estimates area from stratum weights and sample proportions, the other fits per-pixel decision rules and scores them per box. They are not independent of the reference, and they are independent of each other in everything else.

Permutation importance puts raw post-event short-wave infrared, `post_B12`, first in five of six model and fold combinations. The difference indices that the threshold is built on rank below it.

We draw no product change from this. A classifier trained on three events of one island in one season, against one interpreter's labels, is a diagnostic of where the threshold loses information, not a replacement for it.

## 7. Discussion

### 7.1 Negative validation is enough to choose an index

With no burn-scar reference, we could not ask which index is most accurate. We could ask which index is wrong where wrongness is certain, and that question has a clean answer here. The three indices that flag 97% to 100% of open sea are unusable on an archipelago regardless of their published performance in Mediterranean settings, and the one index that stays near zero over both water and cloud is the one the burned-area product was built on.

This framing is cheap and transferable. It needs a water mask, a cloud mask, and a hotspot archive, all of which exist globally. We suggest it as a first screen wherever reference data are absent, before any threshold is chosen.

### 7.2 Pre-image selection is a first-order error source

The burned-area literature reports post-event compositing choices carefully and pre-event choices rarely. Our results suggest the asymmetry is backwards in cloudy tropical settings. The post-event look is easy: the dry season follows the burning, skies clear, and the median pixel is observed 2.9 days after the fire. The pre-event look is hard: the search runs backwards into the cloudier build-up, and the median pixel is 12.2 days old, the worst event 29.1 days.

Age alone is not the problem. The problem is what can happen inside that age. On land with repeated burning, and 3 recurrent sites here carried 74, 30 and fewer distinct detection days, a pre-image chosen as the latest clear look may already hold a scar from an earlier fire. The index then measures change from darkened ground, the difference is small, the threshold is not met, and the omission is invisible in every quality metric the pipeline reports. Our stratified assessment found 428 ha of omission; 57% of assessed area sits in events where this mechanism is possible. We cannot attribute one to the other with the data available, and we do not.

The diagnostic itself costs nothing. Any pipeline that selects a nearest clear look already computes the lag. Crossing that lag against a hotspot archive is arithmetic. We recommend reporting it alongside burned area as a matter of routine.

### 7.3 Reporting a reversed conclusion

Our first assessment concluded that the product over-claims by about a quarter. The second concluded the opposite. The difference is not a corrected error but a larger sample: 67 boxes became 136, and the stratum that drove the reversal moved from 0 of 10 to 5 of 12 in one design and 6 of 16 to 26 of 46 in the other.

We report both. A zero-count stratum carrying half the study area produced, under the normal approximation, an interval of exactly zero width for that stratum, and the Wilson interval disagreed with it about the headline. That disagreement was the honest result at the time: the sample could not settle the question either way. Publishing only the second assessment would present as a finding what was actually the resolution of an acknowledged uncertainty.

### 7.4 What the reference is, and is not

The reference is one interpreter's reading of reconstructed imagery. Both halves of that sentence are limitations.

One practical trap deserves recording, because it cost us a complete set of experiments before it was caught. S2DR4 writes its ten bands in the order B2, B3, B4, B8, B5, B6, B7, B11, B12, B8A, the four 10 m bands first and then the 20 m ones, and labels none of them. Reading the file in documented Sentinel-2 band order puts near-infrared in the red channel. We verified the true order against native Sentinel-2 medians over water, canopy and burnt ground for the same date and tile: band 9 matches B12 to within 5%, band 8 matches B11 to within 7%, and band 10 is B8A. The error was first noticed visually, as vegetation rendering orange where it should be green, not by any numerical check. Anyone building a short-wave infrared composite from this product should confirm the order before trusting it.

S2DR4 infers ground conditions beneath cloud by drawing on acquisitions across a 180 day window. On a date with 37.5% tile cloud, a substantial share of any chip is reconstruction rather than observation, and reconstruction grows more confident as the window fills with post-burn scenes. A box that reads as more obviously burned on a later chip may reflect ground change, delayed severity development as rain strips bright ash to expose dark char, or the model's increasing confidence. Separating those needs an interpreter comparing the native 20 m series against the 1 m one, which we did not do.

We also observed the resolution artefact in the opposite direction: a 20 m pixel averages 400 m² of ground, so surviving green patches smaller than that vanish into a brown mean, and the 1 m chip shows them. This makes 20 m overstate burn completeness within a box. It is not a regrowth signal, since it appears between two resolutions of the same date.

![**Figure 4.** The same ground on the same date at two resolutions, short-wave infrared composite. (a) Sentinel-2 at 20 m. (b) The S2DR4 reconstruction at 1 m. The yellow square is one 60 m reference box. At 20 m the box reads as a nearly uniform brown; at 1 m, surviving green is visible inside and around it. Both panels are the imagery as delivered, with no re-stretching.](figures/fig4_resolution.png)

There is no second interpreter. A blind re-judge by the same person measures self-consistency, not agreement between readers, and we do not present one as a substitute. Published good practice has three analysts inspect each unit. The correct wording for our result is that the reference is one interpreter's reading and that inter-interpreter agreement was not measured. Not "validated", not "ground truth".

Finally, the sample unit is a 60 m box holding nine 20 m pixels, so it is a cluster treated as an independent unit. Olofsson et al. state explicitly that their variance estimators do not apply to such a unit. Both intervals reported here are therefore optimistic in a way neither number shows. The honest fix is a pixel unit or a cluster-aware variance; the obstacle is that a 20 m pixel cannot be judged reliably on the available imagery.

### 7.5 Why not a segmentation model

A reader may reasonably ask why a prompted segmentation foundation model was not used in place of a spectral threshold. We tested that. Each mask was scored by intersection over union against the threshold polygons inside the event footprint, against the trivial baseline of claiming the whole footprint burned, which scores 0.732, 0.580 and 0.308 for the three events with 1 m imagery. No prompting route, at 10 m or at 1 m, beat that baseline by a margin exceeding the rasterisation tolerance. We report this as a measured negative rather than an opinion.

## 8. Conclusions

A conventional bi-temporal index threshold works on this island, in the sense that what it claims is almost always burned: 49 of 50 reference boxes inside mapped polygons were confirmed. It fails in the other direction. The stratified estimate of 1,230 ha (95% CI 1,060 to 1,342) excludes the mapped 819 ha, and roughly 428 ha of burning inside the event footprints went unmapped. Read as per-pixel classification rather than as area, the same labels say the same thing: the threshold's box-level recall on unclaimed ground inside footprints is 0.27, where classifiers on the identical 20 m bands reach 0.96 or better at comparable precision. The information needed to find that ground is in the imagery the product already reads.

Three findings generalise beyond Biak.

Index selection can be settled without reference data by measuring false alarms where burning is impossible. On an archipelago, that test eliminates three of seven candidate indices outright and, for a recently published eighth, exposes a 43.5% water false-alarm rate that no accuracy figure over land would reveal.

The pre-event image deserves the scrutiny usually reserved for the post-event image. In cloudy tropical conditions its lag is four times larger, and when a prior fire predates it the resulting omission is invisible to every internal quality metric.

A land-cover product with a single woody class can invert the apparent meaning of a burned-area result. Esri's "trees" made 74.8% of the changed area look like forest loss; TMF showed 14.7% was undisturbed forest, with regrowth burning at more than twice the rate of intact forest.

The fuel expectation written into this project's plan was wrong about what the corridor holds, at 90.92% closed forest against an expectation of savanna and shrub, and right about what burns, with grass and shrub represented among detections at four to five times their share of the land.

## Data and code availability

All analysis code, task specifications, and the dated findings record from which every figure in this manuscript is drawn are in the project repository. Derived data products are committed alongside the code that produced them. Each figure here traces to a numbered findings entry and the commit named in it.

## Acknowledgements

S2DR4 reconstructed imagery was provided by Gamma Earth under an academic research grant. The grant is for non-commercial research and teaching and requires citation of Akhtman (2023); that citation is a condition of use.

Road network data are from OpenStreetMap contributors, licensed ODbL.

## References

Alcaras, E., et al. (2022). NBR+ and burned area mapping. *Remote Sensing*, 14(8), 1727.

Bilal, M. (2025). ATBI: a thermal-burn index for burned area mapping. *International Journal of Applied Earth Observation and Geoinformation*, 144, 104866.

Olofsson, P., Foody, G. M., Herold, M., Stehman, S. V., Woodcock, C. E., & Wulder, M. A. (2014). Good practices for estimating area and assessing accuracy of land change. *Remote Sensing of Environment*, 148, 42-57.

Scott, J. H., & Burgan, R. E. (2005). Standard fire behavior fuel models. USDA Forest Service, RMRS-GTR-153.

Akhtman, Y. (2023). [S2DR4; complete citation required by the grant terms before submission.]

---

## Notes for the author, not part of the manuscript

Citations needing completion before submission: Akhtman (2023), the full author list and title for Alcaras et al. (2022), the exact title and author initials for Bilal (2025), and added entries for CHIRPS, Dynamic World, JRC TMF, ESA WorldCover, Cloud Score+, Key and Benson's dNBR severity breaks, ERA5-Land, the Canadian Fire Weather Index system, and Lawson and Armitage (2008) for the day-length factor. Each is cited in the text above by name and none should go to a journal with the placeholder standing.

Section 6.7 replaces an earlier version of this comparison, recorded in the project's findings as F21, which was computed on 67 boxes in two strata before the second interpretation pass and reported threshold precision of 0.27 in the random-sample stratum against 1.00 for a classifier. On the finished labels that precision is 0.86 and the classifiers are worse than the threshold on precision, so the earlier reading, that a classifier refuses unburned ground better, was the wrong explanation of a real effect. The numbers in Section 6.7 come from the rerun on all 142 boxes.

Figures not yet made: the corridor map with event footprints and reference boxes; the per-event burned area against pre-event lag, which carries Section 6.6; the index false-alarm chart from the table in Section 6.1; and the two-panel 20 m against 1 m chip comparison supporting Section 7.4.

Not performed and stated as such in the text: ATBI Part B (separability scoring against the reference boxes), inter-interpreter agreement, and any attribution of the 428 ha omission to the stale pre-image mechanism.

Written in English to match the project repository and the comparator literature. Say the word and this becomes Indonesian.
