# Biak Hotspot Monitoring — Data Sources & Implementation Plan

**Status:** planning / architecture spec. Written for a downstream implementation model
(GLM-5.3-flash / DeepSeek-V4-flash). Each phase ends with acceptance criteria that the
reviewer will check against.

**Area of interest (AOI):** Biak, Supiori, Numfor and the Padaido islands, Papua, Indonesia.

```
BBOX_WSEN = (134.25, -1.39, 136.76, 0.99)   # west, south, east, north (EPSG:4326)
```

Use this bounding box for every API request, then clip precisely with the desa polygons
(see §2.7). The bbox is deliberately generous — a hotspot at the edge of the box that
falls in the sea after clipping is a useful false-positive signal, not an error.

**This box was widened on 2026-08-27 and the reason is worth keeping.** The original
`(134.60, -1.45, 136.70, -0.55)` covered the visible Biak-Supiori-Numfor cluster but excluded
four desa belonging to the two regencies: two on **Kepulauan Mapia** (Supiori Barat distrik,
around 134.30E / +0.94N, roughly 300 km northwest and north of the equator) and two in
**Aimando Padaido** east of 136.70. Publishing per-district counts under the old box would have
reported those districts as having zero hotspots when they had never been observed at all — the
same defect as §5.1 wearing different clothes. The enlarged area is almost entirely ocean,
which costs nothing: FIRMS returns only detections, and the polygon clip discards anything not
on land.

**Timezone:** Papua is UTC+9 (WIT). Satellites report UTC. Every ingest must store UTC and
derive a `local_datetime` column. A "daily" product must be defined against WIT local days,
or the two overpasses of a single night get split across two reports.

---

## 1. Guiding principles

1. **A hotspot is a thermal anomaly, not a confirmed fire, and never a confirmed culprit.**
   All published wording must reflect this. See §8 on publication ethics.
2. **Build the smallest thing that produces a correct daily brief, then extend.** Phase 1
   alone (FIRMS pull + clip + map + brief) is a genuinely useful public product. Do not
   build Phases 3–5 before Phase 1 has run unattended for a week.
3. **Prefer one platform.** Google Earth Engine (free for non-commercial/research use) hosts
   almost every raster listed below. Using it removes an entire download-and-mosaic layer
   from the project. Fall back to direct APIs only for what GEE does not carry
   (near-real-time FIRMS, Himawari, METAR, BMKG).
4. **Everything reproducible from a config file.** No coordinates, dates, thresholds, or
   API keys hard-coded in logic.

---

## 2. Data sources

### 2.1 Active fire / hotspot detection — PRIMARY

| Source | Sensor / resolution | Latency | Access |
|---|---|---|---|
| NASA FIRMS VIIRS S-NPP | 375 m, 2 overpasses/day | ~3 h (NRT), ~1 h (URT) | REST API, free MAP_KEY |
| NASA FIRMS VIIRS NOAA-20 | 375 m | ~3 h | same API |
| NASA FIRMS VIIRS NOAA-21 | 375 m | ~3 h | same API |
| NASA FIRMS MODIS Terra/Aqua | 1 km, 2 overpasses/day | ~3 h | same API |
| Himawari-9 AHI wildfire | 2 km, every 10 min | ~20 min | JAXA P-Tree FTP |
| Sentinel-3 SLSTR FRP | 1 km, night | ~3 h | Copernicus Data Space |
| SiPongi (KLHK) | national official hotspot portal | daily | sipongi.menlhk.go.id |

**FIRMS is the backbone.** Three VIIRS platforms give roughly 4–6 looks per day at 375 m,
which is the right resolution for an island of Biak's size. Register a free MAP_KEY at
`https://firms.modaps.eosdis.nasa.gov/api/map_key/`.

Endpoint shape:

```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{W,S,E,N}/{DAY_RANGE}/{START_DATE}
```

- `SOURCE` values for near-real-time: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`,
  `VIIRS_NOAA21_NRT`, `MODIS_NRT`. Archive equivalents replace `_NRT` with `_SP`.
- `DAY_RANGE` is capped at **5 days** per request, not 10. Exceeding it returns HTTP 400
  with the body `Invalid day range. Expects [1..5].` Backfill loops must chunk in fives.
- Check `https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{MAP_KEY}/all` before
  any historical pull. Each NRT source has a limited window and rolls over into its `_SP`
  archive counterpart; as of 2026-08-27, `VIIRS_SNPP_NRT` reached back only to 2026-04-28
  while `VIIRS_SNPP_SP` covered 2012-01-20 to 2026-04-27. A backfill that assumes NRT goes
  back years will return empty results rather than an error.
- Rate limit is roughly 5000 transactions per 10 minutes; a polite 1 s sleep between
  requests is enough.
- For the multi-year history needed by Phases 4–5, do **not** loop the API. Use the bulk
  archive download, or the GEE `FIRMS` collection (MODIS only) plus the archive VIIRS
  `VNP14IMGML` monthly files.

Two further FIRMS sources are available through the same API and were not in the original
source table:

- **`LANDSAT_NRT`** — active fire detections at 30 m. Far finer than VIIRS 375 m, which
  matters on an island this size, at the cost of a 16-day revisit. Use it opportunistically
  for detail on a known event, not as a monitoring backbone.
- **`BA_MODIS`** and **`BA_VIIRS`** — burned area products. These give a Phase 4 first cut
  without touching Earth Engine at all, and are worth trying before building the Sentinel-2
  dNBR chain in §2.2. Note both lag: as of 2026-08-27 they extended only to 2026-05-01.
- `GOES_NRT` covers the Americas and is irrelevant here.

Fields to retain: `latitude`, `longitude`, `bright_ti4`, `bright_ti5`, `scan`, `track`,
`acq_date`, `acq_time`, `satellite`, `instrument`, `confidence`, `version`, `frp`,
`daynight`. `frp` (Fire Radiative Power, MW) is the intensity proxy — keep it, it carries
most of the analytical value and is routinely discarded by naive pipelines.

**Himawari-9** is the source that makes chronological analysis possible. VIIRS gives
snapshots; Himawari's 10-minute full-disk cadence gives ignition time and spread sequence.
Biak at 136°E sits comfortably inside the disk (sub-satellite point 140.7°E). Access is the
JAXA P-Tree FTP service (`ftp.ptree.jaxa.jp`), free registration, wildfire product under
`/pub/himawari/L3/WLF/`. Raw AHI L1b is also mirrored on AWS Open Data at
`s3://noaa-himawari9/` with no credentials required.

**Priority raised 2026-08-28.** This is no longer a Phase 4 convenience. Section 12
establishes that the polar-orbiting constellation does not observe Biak at all between
15:00 and 00:31 WIT. Himawari-9 is the only open-access sensor covering that window. It is
coarser at 2 km and will miss small fires, but it is the difference between partial evening
data and none. The JAXA P-Tree registration requires manual approval, so apply immediately
regardless of when the code gets written.

**Cross-validation with SiPongi** matters for credibility with Indonesian institutions.
SiPongi applies its own confidence filtering to the same underlying NASA data, so counts
will differ from a raw FIRMS pull. Report both, and explain the difference rather than
silently picking one.

### 2.2 Burned area / burn scar — for postmortem

- **Sentinel-2 MSI L2A**, 10–20 m, ~5-day revisit. GEE: `COPERNICUS/S2_SR_HARMONIZED`.
  This is the postmortem workhorse. Compute NBR = (NIR − SWIR2)/(NIR + SWIR2) using bands
  B8 and B12, then dNBR = NBR_pre − NBR_post.
- **Cloud masking is the hard part, not the index.** Equatorial Papua is heavily clouded.
  Use `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` rather than the SCL band or the QA60
  bitmask — it is materially better over tropical cloud and costs one join.
- **Landsat 8/9 OLI L2**, 30 m, 16-day. GEE: `LANDSAT/LC09/C02/T1_L2` and `LC08`. Gap-fill
  when Sentinel-2 is clouded out for a whole window.
- **MODIS MCD64A1** burned area, 500 m monthly. GEE: `MODIS/061/MCD64A1`. Too coarse for
  individual Biak fires but correct for multi-year trend context.
- **FireCCI51**, 250 m. GEE: `ESA/CCI/FireCCI/5_1`. Historical only (ends 2020); useful for
  building the training label set in Phase 5, not for current events.

Standard dNBR severity breaks (Key & Benson) are a defensible starting point but were
derived for temperate forest. State that in the output, and treat the classes as
indicative until locally calibrated.

### 2.3 Land cover and fuel type

- **ESA WorldCover v200**, 10 m, 2021. GEE: `ESA/WorldCover/v200`. Best free global 10 m
  product; correct default.
- **Dynamic World**, 10 m, near-real-time probabilistic. GEE: `GOOGLE/DYNAMICWORLD/V1`.
  Use this when you need land cover *contemporary with the fire* rather than a 2021 snapshot.
- **KLHK Penutupan Lahan** (Indonesian Ministry of Environment and Forestry national land
  cover). Authoritative for domestic use and uses locally meaningful classes. Obtain the
  shapefile from the KLHK geoportal.
- **Hansen Global Forest Change**, 30 m annual tree cover loss. GEE:
  `UMD/hansen/global_forest_change_YYYY_v1_XX` — check the catalog for the current year and
  version suffix rather than copying an ID from this document.
- **Global Mangrove Watch** for the coastal fringe.

**Important local correction: Biak is a raised coral limestone island, not a peatland.**
Do not import the Sumatra/Kalimantan peat-fire analytical frame. Expect fuel to be savanna
and grassland, secondary shrub, and shifting-cultivation plots — fast-moving,
low-residence-time surface fires, not smouldering ground fire. This changes everything
downstream: FRP distributions, burn duration, dNBR interpretation, emissions estimates, and
which drought index is actually diagnostic. Verify the fuel assumption against WorldCover
before building on it, but do not carry a peat model in by default.

### 2.4 Vegetation condition and fuel moisture

- **MODIS MOD13Q1** NDVI/EVI, 250 m, 16-day composite. GEE: `MODIS/061/MOD13Q1`. Has the
  20+ year record needed for a meaningful anomaly baseline.
- **VIIRS VNP13A1**, 500 m, 8-day. GEE: `NASA/VIIRS/002/VNP13A1`. Shorter record, better
  cadence — use it for current condition, use MODIS for the climatology it is compared
  against.
- **NDMI / NDWI** from Sentinel-2 (B8, B11) as a live fuel moisture proxy. Cheap to compute
  from imagery already pulled for §2.2.
- **Land surface temperature**: `MODIS/061/MOD11A1` (daily 1 km) and
  `NASA/VIIRS/002/VNP21A1D`.

The analytically useful quantity is not NDVI but **NDVI anomaly against the same
day-of-year across the baseline period** (2001–2020, or the full available record).
Absolute NDVI in the humid tropics is high and nearly flat; only the departure is
informative. This is a common implementation error — check for it in review.

### 2.5 Precipitation and drought

- **CHIRPS**, 0.05°, daily, 1981–present. GEE: `UCSB-CHG/CHIRPS/DAILY`. Best choice for
  tropical drought anomaly work — the long record is what makes SPI computable.
- **GPM IMERG V07**, 0.1°, half-hourly. GEE: `NASA/GPM_L3/IMERG_V07`. Late run for
  operations, Final for retrospective analysis.
- **GSMaP** (JAXA), 0.1°, hourly, tuned for the Asia-Pacific.
  GEE: `JAXA/GPM_L3/GSMaP/v8/operational`.
- **ERA5-Land daily aggregates**. GEE: `ECMWF/ERA5_LAND/DAILY_AGGR` — 2 m temperature,
  dewpoint, wind components, soil moisture at four depths. The meteorological backbone for
  any index you compute yourself.
- **SMAP L4** soil moisture. GEE: `NASA/SMAP/SPL4SMGP/007`.

Derived indices to compute:

- **Days since last rain > 1 mm** — the crudest and often the most predictive single feature
  for this fire regime. Compute it first.
- **SPI** at 1, 3, and 6 months from CHIRPS.
- **KBDI** (Keetch-Byram Drought Index) from daily rainfall, daily maximum temperature, and
  mean annual rainfall. BMKG publishes KBDI for Indonesia, so computing it locally gives a
  directly comparable number.
- **FWI** (Canadian Fire Weather Index). Either compute from ERA5-Land, or take the
  ready-made Copernicus product: CEMS/GWIS publishes ERA5-based historical FWI and an 8-day
  forecast at `https://gwis.jrc.ec.europa.eu/`. Taking the ready-made one first is the right
  call — implement your own only if the resolution proves too coarse.

### 2.6 Climate drivers and ground truth

- **ENSO indices** — ONI, Niño 3.4, SOI from NOAA CPC; **IOD Dipole Mode Index** from BMKG
  or JAMSTEC. Both matter for Papua. Plain text/CSV, trivially fetched. These provide the
  seasonal framing the project's premise rests on, so pull them early and check that the
  claimed El Niño signal is actually present in the local rainfall record — do not assume it.
- **BMKG station data** — Biak Frans Kaisiepo, WMO 97560 / ICAO WABB. Register at
  `dataonline.bmkg.go.id`.
- **METAR from WABB** — free, hourly, no registration via the `aviationweather.gov` API or
  NOAA ISD. Gives temperature, dewpoint, wind, and — critically — **visibility and present
  weather codes `FU` (smoke) and `HZ` (haze)**. This is the cheapest independent ground
  truth in the entire project: a satellite hotspot cluster upwind of the airport coinciding
  with reported smoke and falling visibility is a corroborated fire. Wire this in during
  Phase 2, not later.

  **But it is one point, and section 12 shows how badly that can fail.** On the night of
  2026-08-27 the airport reported 8000 m visibility and no smoke code for ten consecutive
  hours while a resident 6.5 km away was in smoke heavy enough to bring out fire trucks.
  Under a calm nocturnal inversion smoke pools locally and a sensor a few kilometres away
  is in different air entirely. A `FU` report is strong positive evidence; the absence of
  one is close to no evidence at all. The brief must never treat a clear METAR as
  confirmation that nothing is burning.

### 2.7 Terrain, infrastructure, boundaries

- **Copernicus DEM GLO-30**. GEE: `COPERNICUS/DEM/GLO30`. Better than SRTM for coastal and
  small-island terrain. Derive slope and aspect for spread modelling.
- **OpenStreetMap** roads, settlements, land use — via the Geofabrik Indonesia extract.
  Distance to road and distance to settlement are the two strongest human-ignition proxies.
- **WorldPop** 100 m population. GEE: `WorldPop/GP/100m/pop`.
- **Google Open Buildings v3** — `GOOGLE/Research/open-buildings/v3/polygons`. Better
  building coverage than OSM in this region.
- **Administrative boundaries — obtained 2026-08-27.** `data/boundaries/biak_desa.geojson`,
  1.2 MB, **306 desa** (Biak Numfor 268, Supiori 38) across **24 distrik**, EPSG:4326.

  **Checked against local knowledge by the project owner on 2026-08-27 and confirmed correct.**
  This matters: the counts and distrik names can be verified programmatically for consistency
  but not for truth, and every district figure this project publishes rests on them.

  Derived by `scripts/extract_boundary.sh` from the BIG RBI 1:10,000 national administrative
  geodatabase (`ADMINISTRASI_AR_DESAKEL`, 83,486 features, 340 MB, 2023-09-28 edition). The
  source `.gdb` is gitignored and must be downloaded manually; only the extract is tracked.

  The extraction **filters by attribute, never by bounding box**:
  `WADMKK IN ('Biak Numfor','Supiori')`. A bbox clip would cut desa polygons at the box edge and
  silently truncate both regencies. Those two strings are the complete and exact set, verified
  against the source.

  Two properties of this dataset affect implementation:

  - The geometry is 3D measured multipolygon on a compound CRS (WGS 84 + EGM2008 height).
    `-dim XY -t_srs EPSG:4326` drops the vertical component; without it, downstream tools that
    expect 2D coordinates behave unpredictably.
  - **`KDEBPS` and `KDCBPS` — the BPS statistical codes — are null throughout.** Joins to other
    Indonesian datasets must therefore use the name fields (`WADMKD`, `WADMKC`, `WADMKK`), which
    is fragile: names carry spelling variants and change over time. If a join to BPS statistics
    is needed later, source the code lookup separately rather than assuming it is present here.

---

## 3. Phase plan

### Phase 1 — Daily hotspot ingest and brief (build this first)

1. `config.yaml`: AOI bbox, admin polygon path, FIRMS map key (read from an environment
   variable, **never committed**), source list, output paths.
2. `ingest_firms.py`: pull the last N days from all four FIRMS sources, concatenate,
   deduplicate, clip to the admin polygon, write to a local SQLite or Parquet store keyed by
   a stable detection ID.
3. Persist raw API responses to a dated `raw/` directory before any parsing. Re-parsing is
   free; re-fetching a day that has aged out of the NRT window is not.
4. `report_daily.py`: counts by district, by satellite, by confidence class; FRP total and
   maximum; a static PNG map; a GeoJSON export; a Markdown brief.
5. Schedule daily. Windows Task Scheduler is sufficient — do not introduce Airflow.

**Acceptance criteria**

- Re-running the same day is idempotent: no duplicate rows, no changed detection IDs.
- The pipeline exits non-zero and writes a clear log line when the FIRMS API fails or
  returns an HTML error page instead of CSV. It must never silently write an empty day —
  "zero hotspots" and "the fetch failed" are different facts and must be distinguishable in
  the stored output.
- Timestamps stored in UTC with a derived WIT local column; the brief is built on local days.
- All four satellite sources are pulled, and the brief states which ones actually returned
  data.
- One runnable self-check covering dedup and the UTC→WIT day boundary.

### Phase 2 — Quality control and corroboration

1. **Persistent-source filter.** Cluster detections across the full history; any location
   producing hotspots on a large fraction of days is infrastructure (airport, port, flare,
   industrial), not a fire event. Maintain the resulting mask as a reviewable data file, not
   as code constants.
2. **Confidence handling.** VIIRS confidence is categorical (`l`/`n`/`h`); MODIS is 0–100.
   Do not average them or coerce one into the other. Report separately.
3. **Sun-glint and coastline checks.** Detections on water or within one pixel of the
   shoreline warrant a flag.
4. **METAR corroboration** (§2.6) — join daily hotspot clusters to WABB visibility and
   present-weather codes.
5. Compare daily counts against SiPongi and record the discrepancy as a time series.

**Acceptance criteria**

- Every filter is a flag column, never a deleted row. Nothing is destructive.
- The persistent-source mask is regenerated from data on a schedule, not frozen by hand.
- The QC report states how many detections each filter touched, per day.

### Phase 3 — Event clustering and chronological analysis

1. Cluster detections into fire **events** with space-time DBSCAN (ST-DBSCAN, or plain
   DBSCAN on scaled x/y/t). Suggested starting parameters: 1 km spatial, 24 h temporal,
   `min_samples=2`. These are a starting point and must be tuned against known events —
   leave them in config.
2. Per event: first and last detection, duration, detection count, total and peak FRP,
   centroid track, convex hull area, land cover composition at ignition, distance to nearest
   road and settlement.
3. Overlay the environmental time series (§2.4, §2.5) for the 30 days preceding ignition.
4. Chronology narrative generated from the event record, not free-written.

**Acceptance criteria**

- Clustering parameters live in config with a documented rationale.
- Events have stable IDs across re-runs as new detections arrive — an event that grows must
  not be reassigned a new identity.
- At least three known events are used as a check on the parameter choice.

### Phase 4 — Postmortem

1. Sentinel-2 pre/post dNBR for each event above a size threshold, with Cloud Score+ masking.
2. Burned-area polygon extraction and area estimate, with an explicit statement of cloud gap
   and therefore of uncertainty.
3. Cross-tabulate burned area against land cover to describe what actually burned.
4. Himawari-9 10-minute reconstruction of ignition timing and spread for the largest events.
   Ignition hour is the strongest available discriminator between natural and human causes —
   a fire starting at 14:00 local in dry grass near a road is a very different narrative from
   one starting at 03:00.

**Acceptance criteria**

- Every burned-area figure is published with a cloud-cover percentage for its scene pair.
- Where no usable post-fire image exists, the output says so rather than falling back to a
  stale scene.

### Phase 5 — Fire danger and prediction

Sequence matters here; do not skip to step 3.

1. **Fire danger index first.** Publish daily FWI and KBDI for the AOI, using the Copernicus
   product plus your own computation from ERA5-Land forecast fields. This is defensible,
   explainable, internationally standard, and requires no training data. For most of this
   project's actual utility, this is sufficient — ship it and stop unless there is a clear
   reason to continue.
2. **Climatological baseline.** Probability of a detection per grid cell per day-of-year,
   from the full history. Any statistical model must beat this to justify its existence.
3. **Statistical model only if 1 and 2 are running.** Gradient boosting (LightGBM) or
   logistic regression on a daily grid. Features: FWI components, KBDI, days since rain,
   NDVI anomaly, land cover class, slope, distance to road and settlement, detection history
   in the cell, ENSO/IOD indices.
   - **Split temporally, by fire season — never randomly.** Random splits leak, badly, in
     spatiotemporally autocorrelated fire data and will produce an impressive and entirely
     fictitious score.
   - Evaluate with AUC-PR, Brier score, and a reliability curve. Plain accuracy and ROC-AUC
     are near-meaningless under this class imbalance.
   - Requires at least 3–5 years of history. Biak is a small island: the positive-class
     sample may simply be too small for a stable model, and finding that out is a valid
     result. Say so rather than shipping an overfitted one.
4. **Do not use deep learning here.** The sample size does not support it.

**Acceptance criteria**

- Baseline comparison is published alongside every model metric.
- Any predictive output carries a calibration statement and an explicit uncertainty range.
- The temporal split is visible in the code and described in the output.

### Phase 6 — Dissemination

- Daily Markdown/PNG brief; GeoJSON and CSV for anyone who wants the raw data.
- Static site, GitHub Pages, generated by the same cron. No backend, no database server.
- Bahasa Indonesia output for local audiences. This is a real requirement, not a nicety —
  the stakeholders who can act on a Biak hotspot report read Indonesian.
- Stable public URL for the current-day GeoJSON so others can build on it.

---

## 4. Suggested layout

```
biak_hotspot/
  config.yaml
  src/
    ingest_firms.py
    ingest_met.py
    qc.py
    events.py
    report.py
  data/raw/YYYY-MM-DD/
  data/processed/
  outputs/daily/
  tests/
```

Python. `requests`, `pandas`, `geopandas`, `shapely`, `rasterio`, `xarray`, `scikit-learn`,
`matplotlib`, plus `earthengine-api` for Phases 4–5.

---

## 5. Known failure modes to watch for in review

1. Reporting a failed fetch as zero hotspots.
2. Mixing UTC and local dates, which shifts night-overpass detections into the wrong day.
3. Averaging VIIRS and MODIS confidence into one meaningless number.
4. Random train/test split in Phase 5.
5. Persistent industrial heat sources counted as fire events.
6. Discarding FRP at ingest.
7. Using absolute NDVI instead of an anomaly.
8. Importing a peat-fire model for a limestone island.
9. Silent cloud-masking failure producing a confidently wrong burned-area figure.
10. Detection IDs that change between runs, breaking every downstream join.

---

## 6. Cost and access notes

Every source listed is free. Registration is needed for: NASA FIRMS (instant), JAXA P-Tree
(manual approval, apply early — this is the long pole), Copernicus Data Space (instant),
Google Earth Engine (project registration, non-commercial use), BMKG data online.

Apply for the P-Tree account during Phase 1 even though Himawari is not used until Phase 4.

---

## 7. Deliverable priority

If effort is limited, the order of value is: Phase 1, Phase 2, **Himawari evening coverage
(section 2.1)**, Phase 6, Phase 3, Phase 5 step 1, Phase 4, Phase 5 step 3.

Himawari was moved forward on 2026-08-28. The evening blind window documented in section 12
is not a gap in analysis quality, it is a gap in observation covering exactly the hours when
residents experience smoke.

A reliable, corroborated, plainly-worded daily hotspot brief in Bahasa Indonesia is worth
more to Biak than an unvalidated prediction model.

---

## 8. Publication ethics

This project publishes geolocated evidence of burning in a populated area. That carries real
risk to real people.

- **Publish coordinates of detections, never inferred responsibility.** A 375 m VIIRS pixel
  cannot identify who lit a fire. Attributing a hotspot to a named landowner, company, or
  village is unsupportable from this data and exposes both the project and the named party
  to serious harm.
- Aggregate to district level in public-facing summaries where individual attribution would
  otherwise be inferable.
- Use "hotspot" or "thermal anomaly" in publication. Reserve "fire" for corroborated events.
- State the false-positive caveats and the QC flags alongside the counts, every time.
- Where the analysis distinguishes agricultural burning from wildfire, note that small-scale
  shifting cultivation is a lawful and long-established practice in Papua. A monitoring
  product that frames every detection as illegal misrepresents the data and damages its own
  credibility with the communities it depends on.

---

## 9. Dashboard architecture and tech stack

The dashboard is the first deliverable the user actually wants: a map with switchable
layers (land cover, NDVI, derived indices, hotspots), a daily precipitation chart with a
month selector, and an hourly air-quality panel.

### 9.1 The architectural decision

**Split the data by how often it changes, and pre-compute everything.**

| Layer | Changes | Therefore |
|---|---|---|
| Land cover | Yearly | Static raster, generated once |
| NDVI / NDMI composites | 8–16 days | Static raster, regenerated on schedule |
| Daily precipitation series | Daily | Small JSON time series |
| Hourly air quality | Hourly | Small JSON time series |
| Hotspot detections | ~4x daily | GeoJSON, small |

Nothing here requires a server to answer a browser request. All the expensive work — Earth
Engine queries, FIRMS pulls, raster processing — happens in a scheduled job that writes
small files. The browser only reads files. This makes the entire dashboard a static site.

### 9.2 Stack

**Compute layer — GitHub Actions, on a cron schedule**

Python. `earthengine-api`, `geemap`, `leafmap`, `requests`, `pandas`, `geopandas`,
`rasterio`. Runs the Phase 1–2 pipeline, then exports products into the published data
directory. The Earth Engine service-account key lives in GitHub Actions secrets and is never
exposed to the browser. On a public repository, Actions minutes are unlimited.

**Frontend — a single `index.html`, no build step**

- MapLibre GL JS (from CDN) for the map, layer toggles, and popups.
- The `pmtiles` MapLibre plugin for raster layers. PMTiles is a single-file tile archive read
  over HTTP range requests, so raster layers work with no tile server at all. For a single
  small island this is the correct trade — one file per layer, served statically.
- Chart.js (from CDN) for the precipitation bars and the air-quality line, with a month
  selector that swaps which JSON is loaded.

No React, no Vite, no bundler, no npm. A single hand-written HTML file is both easier for an
implementation model to produce correctly and easier to review. Introduce a framework only
when the single file demonstrably stops being workable.

**Hosting — GitHub Pages**

Free, no cold start, no idle sleep. The compute job and the site live in the same repository,
so there is one place to look when something breaks. Vercel would also serve this fine, but
its Hobby-tier cron (once daily, short function timeout) cannot run the Earth Engine job, so
the compute would stay in GitHub Actions regardless — which makes Pages the simpler choice.

Watch the limits: 100 MB per file (a git constraint), ~1 GB total site size. For an AOI the
size of Biak this is not close to binding, but a careless national-scale export would blow
through it.

### 9.3 Where leafmap and geemap belong

Both are Qiusheng Wu's packages and both are worth using — as **authoring and processing
tools, not as the hosted dashboard**. They are Python libraries; static hosting has no Python
runtime, and `leafmap.to_html()` produces a snapshot without the ability to re-query data.

Use them for:

- Notebook exploration: choosing thresholds, inspecting NDVI anomalies, verifying cloud
  masking before committing it to a pipeline.
- `geemap` export helpers (`ee_export_image`, `ee_to_geojson`) inside the Actions job.
- Prototyping the layer stack with `leafmap.maplibregl` before hand-writing the final HTML.

Note there is no package named "geolibre"; the MapLibre backend lives inside `leafmap`.

### 9.4 The alternative, and when to take it

Streamlit plus geemap, deployed on Streamlit Community Cloud (free), is the pattern Qiusheng
Wu demonstrates in `streamlit-geospatial`. It works, and it is the right answer if users need
to drive arbitrary Earth Engine queries interactively. The costs are a cold start of roughly
30 seconds, sleeping when idle, and community-tier quotas. It cannot deploy to Vercel, whose
serverless model does not fit Streamlit's websocket session.

For a dashboard with a fixed set of layers and a date selector, the static approach wins on
load time, cost, reliability, and maintenance. Take Streamlit only when on-demand
user-defined computation is a real requirement.

### 9.5 Air quality — check before building

**Confirmed 2026-08-27: there is no ground-based air quality station on Biak, and none
anywhere in Papua.** Queried against the OpenAQ v3 API: zero locations returned for the AOI
bbox, and zero for a wide Papua sweep (130-141E, -9.5 to 0.5). Indonesia has 58 OpenAQ
locations in total, all low-cost PM sensors, and the nearest one to Biak is approximately
2,439 km away in Bali. There is therefore no measured AQI for this AOI and no prospect of one.

The dashboard's air quality panel must be built on modelled and satellite data from the
outset. Do not scaffold a station-ingest path "for later" — there is no station to ingest.
Re-run the OpenAQ query on a slow schedule (quarterly is plenty) so that a station appearing
in future is noticed, but treat that as a bonus validation layer, never as the foundation.

Realistic sources, in order of fit:

- **Sentinel-5P TROPOMI UV Aerosol Index** — GEE `COPERNICUS/S5P/NRTI/L3_AER_AI`, daily,
  ~7 km. A direct smoke-plume signal and the best match for this project's purpose.
  Sentinel-5P also carries CO (`L3_CO`), which responds to biomass burning.
- **CAMS global atmospheric composition** (Copernicus, free) — modelled PM2.5 and PM10,
  3-hourly. This is what an "hourly AQI" for Biak would actually be.
- **METAR visibility and present-weather from WABB** (§2.6) — hourly, genuinely observed,
  crude but real.

If the displayed value is modelled rather than measured, the dashboard must say so on the
panel itself, not in a footnote. People make health decisions from air quality numbers, and
presenting a coarse global model output as a local measurement is a misrepresentation with
real consequences.

### 9.6 Suggested repository layout

```
biak_hotspot/
  .github/workflows/daily.yml    # cron: run pipeline, commit outputs
  src/                           # ingest, qc, events, export (see §4)
  docs/                          # GitHub Pages root
    index.html                   # the entire frontend
    data/
      hotspots_latest.geojson
      precip_daily.json
      aqi_hourly.json
      layers/*.pmtiles
```

**Acceptance criteria**

- The site loads and renders correctly with no network access beyond its own origin and the
  named CDNs.
- Every data file carries a generation timestamp, and the page displays it. A stale dashboard
  that looks live is worse than one that is visibly stale.
- The Earth Engine credential appears only in Actions secrets — never in the repository,
  never in the published output.
- If the scheduled job fails, the previous data remains published and the page shows its real
  age rather than silently presenting old data as current.

---

## 10. Verified access notes and observed baseline (checked 2026-08-27)

### 10.1 METAR from WABB — confirmed working, no authentication

Biak Frans Kaisiepo (ICAO `WABB`, WMO 97560, -1.190, 136.108, elevation 12 m) reports
approximately every 30 minutes, giving roughly 48 observations per day. Both access paths
were tested and both work with no API key and no registration.

**Live feed** — `https://aviationweather.gov/api/data/metar?ids=WABB&format=json&hours=N`
Returns fields including `temp`, `dewp`, `wdir`, `wspd`, `visib`, `wxString`, `clouds`,
`rawOb`, `obsTime`. Use for the operational dashboard.

**Historical archive** — Iowa State Environmental Mesonet ASOS service at
`https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`, with
`station=WABB&data=vsby&data=wxcodes&tz=Etc/UTC&format=onlycomma&report_type=3&report_type=4`.
The `report_type` parameters are required; omitting them returns an empty result. This
endpoint is slow — fetch it once, cache the result, and never call it from the daily cron.

**Implementation traps, all of which will silently corrupt output:**

1. The JSON `visib` field is in **statute miles**; the raw METAR string is in **metres**.
   5000 m corresponds to 3.11 sm. Mixing the two units produces a roughly 60% error that
   looks entirely plausible on a chart.
2. A visibility of 6.21 sm (9999 m) is a **reporting ceiling meaning "10 km or more"**, not
   a measurement. It is censored data. Do not compute means across it and present the result
   as an average visibility; treat it as a bounded value or exclude it explicitly.
3. `wxString` may contain several codes at once (`FU HZ`, `-RA BR`). Match by substring,
   never by equality.
4. Observations are timestamped UTC. The same WIT conversion required everywhere else in
   this project applies here.

### 10.2 Observed smoke baseline and the event in progress

Visibility and present-weather codes were pulled for 2026-06-01 through 2026-08-27 (4,293
observations) and aggregated by day:

| Period | Days with smoke/haze codes | Median visibility |
|---|---|---|
| 2026-06-01 to 2026-08-21 | 0 (one isolated pair on 08-14) | 6.2 sm (at the 10 km ceiling) |
| 2026-08-22 | 4 observations | 5.6 sm |
| 2026-08-23 | 28 observations | 2.5 sm |
| 2026-08-24 | 39 observations | 3.1 sm |
| 2026-08-25 | 26 observations | 3.1 sm |
| 2026-08-26 | 30 observations | 3.1 sm |
| 2026-08-27 (partial) | 7 of 7 observations | 3.1 sm |

This establishes two useful things.

**A clean local baseline.** Eighty-three consecutive days at the visibility ceiling with no
smoke codes at all. Any `FU` report at WABB is therefore a strong anomaly rather than
background noise, which makes this a far better corroboration signal than it would be at a
station with chronic haze.

**An active event, in progress.** Onset on 2026-08-22, sharp escalation on 08-23, sustained
through the time of writing — day five and continuing. Winds through the episode were light
and variable from roughly 230-260 degrees. This is consistent with a local source, but METAR
alone cannot establish that the fire is on Biak rather than upwind of it; that requires
joining to FIRMS detections.

**Use this event as the primary tuning case for Phase 3 clustering.** It has a firm onset
date, an independent ground observation of its severity, and it is recent enough that
Sentinel-2 post-fire imagery will become available shortly for the Phase 4 postmortem.
Two further historical events should be identified for comparison before the clustering
parameters in §3 are considered settled.

### 10.3 OpenAQ — confirmed absent

See §9.5. Query executed 2026-08-27 against the OpenAQ v3 API returned zero locations for
both the AOI and a wide Papua sweep.

### 10.4 Validated event: 19-25 August 2026 (FIRMS pull executed 2026-08-27)

FIRMS was queried across all four sources for the AOI, 2026-08-13 to 2026-08-27, returning
653 detections. Aggregated to WIT local days:

| WIT day | S-NPP | NOAA-20 | NOAA-21 | MODIS | Total | Sum FRP (MW) | Max FRP |
|---|---|---|---|---|---|---|---|
| 08-13 | 1 | 0 | 1 | 0 | 2 | 10.9 | 6.7 |
| 08-15 | 0 | 1 | 0 | 0 | 1 | 1.3 | 1.3 |
| 08-18 | 0 | 2 | 1 | 0 | 3 | 11.2 | 6.0 |
| 08-19 | 4 | 1 | 10 | 1 | 16 | 85.0 | 9.8 |
| 08-20 | 5 | 7 | 6 | 0 | 18 | 172.7 | 18.8 |
| 08-21 | 97 | 67 | 35 | 3 | 202 | 1195.5 | 23.9 |
| 08-22 | 89 | 140 | 48 | 6 | 283 | 2605.1 | 90.5 |
| 08-23 | 8 | 29 | 32 | 0 | 69 | 377.9 | 17.4 |
| 08-24 | 8 | 10 | 22 | 1 | 41 | 251.1 | 22.6 |
| 08-25 | 6 | 1 | 11 | 0 | 18 | 88.6 | 7.6 |
| 08-26, 08-27 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Spatial extent of detections: latitude -1.199 to -0.666, longitude 134.808 to 136.588. The
western extreme falls on Numfor, confirming the AOI bounding box in the header is correctly
sized and that the event was not confined to Biak proper. The highest-FRP cluster sits around
-1.127, 136.044 and -1.185, 136.130, in south-central Biak.

**This independently corroborates the METAR record in §10.2, with a physically sensible lag.**
Fire activity peaks 21-22 August; airport smoke observations peak 23-24 August. Smoke
accumulating and persisting for roughly a day after peak burning is exactly what should
happen. Two unrelated instruments, one consistent story. The project premise holds.

Four findings that should shape the implementation:

**1. The fire regime is daytime ignition, not sustained wildfire.** Of 653 detections, 651
were daytime and 2 were night. Fires that do not survive the night, recurring across
consecutive days, is the signature of deliberate daytime land clearing rather than an escaped
wildfire front. This corroborates the fuel assumption in §2.3 and argues against importing a
wildfire-spread model. It also has direct bearing on §8: this pattern is consistent with
ordinary agricultural burning, and the analysis must not be written as though it were not.

**2. The confidence-column trap is real and present in this data.** The single `confidence`
column returned `n` (491), `l` (139), `h` (12) from VIIRS alongside numeric values 0, 31, 36,
38, 56, 66, 68, 71 from MODIS. Any code that coerces this column to a number will silently
discard 642 of 653 VIIRS detections. This is the failure mode listed at §5.3, confirmed live.

**3. Detections stop on 08-25 while METAR still reports smoke on 08-26 and 08-27.** Two
readings are possible: the fires burned out and smoke lingered, or cloud cover masked still-
active fires from the satellites. Distinguishing them requires a cloud check. Do not assume
either. This divergence is the single best argument for keeping METAR in the pipeline, and it
should be preserved as a worked example in the documentation.

**4. The highest-FRP cluster is roughly 2.4 km from the airport.** Close enough that the
Phase 2 persistent-source filter must be built and validated before any of this is published.
The detections are almost certainly genuine fires rather than airport infrastructure, given
they appear for six days and then stop, but "almost certainly" is not the standard for a
public product.

**Use this event as the primary Phase 3 clustering test case.** It has a clean baseline before
it, a defined onset, a sharp peak, an observable decay, independent ground corroboration, and
a known spatial extent. Two further events should be identified from the `_SP` archive for
comparison before the clustering parameters are fixed.

Raw responses from this pull are stored under `data/raw/` and should be committed as
regression fixtures for the ingest tests.

---

## 11. Three-year baseline (backfill executed 2026-08-27)

A full backfill was run over 2023-09-01 to 2026-08-27: 851 chunks fetched, 1 range recorded
unavailable (NOAA-21 before its 2024-01-17 window opens), **1,078 unique detections**, 1,076 on
land.

### 11.1 August 2026 is not a normal fire season

| Year | Detections |
|---|---|
| 2023 (from September) | 100 |
| 2024 | 90 |
| 2025 | 71 |
| 2026 | 817 |

Of the 2026 total, **671 fell in August alone** — in 27 days — against 407 detections across the
preceding ~1,065 days. That is a **65-fold increase over the baseline daily rate**. Only 180 of
1,093 calendar days in the record carry any detection at all; the normal state of this island is
no fire.

2026 runs elevated all year (April 38, June 20, July 62) rather than spiking only in August,
which is the signature of a developing drought rather than a single ignition event. The
secondary peak in the record, November 2023 (65 detections), coincides with the 2023-24 El Nino
and is the closest analogue available.

**This materially strengthens the project's premise, which until now was an assumption.** It
also sets the bar for the daily brief: against a baseline of roughly two detections per week,
any day in double figures is genuinely exceptional and should read that way.

### 11.2 Persistent-source candidates

Detections were binned into ~375 m cells and counted by distinct WIT days:

```
cells seen on  1 day : 483        cells seen on  5 days :  2
cells seen on  2 days:  87        cells seen on  7 days :  1
cells seen on  3 days:  22        cells seen on 11 days :  1
cells seen on  4 days:  16        cells seen on 66 days :  1
```

613 distinct cells, and the distribution is sharply bimodal. **One cell at -1.1449, 136.0353
(Yendidori distrik, near Saramom hamlet) carries 66 distinct days and 89 detections** — six
times the next-highest cell.

Two things follow.

**Grid cells fragment a single source.** That cell's immediate neighbours carry 11 days and 7
days. Geolocation jitter spreads one physical source across adjacent cells, so a per-cell count
undercounts it. Recurrence must be computed by clustering within a radius, not by binning.

**What is there is unknown, and that matters.** An OpenStreetMap query returns only residential
landuse at Saramom — no landfill, no industrial site, no power infrastructure. OSM coverage in
Papua is sparse, so an unmapped facility is entirely possible; so is repeated agricultural
burning of the same plot. 66 days out of 1,093 is 6% — high recurrence, but nothing like the
near-daily signature of a gas flare.

**Therefore the persistent-source filter must flag and never delete.** If this site is recurrent
land management rather than infrastructure, removing it erases real fire activity, and
describing a repeatedly-burned plot beside a hamlet as "industrial" would be wrong in the way
section 8 exists to prevent. Publish the count, flag the recurrence, and let a reader who knows
Biak tell us what is actually there.

### 11.3 The airport cluster is resolved

Section 10.4 finding 4 flagged that the highest-FRP cluster sat 2.4 km from Frans Kaisiepo and
had to be cleared before publication. Across three years, detections within 3 km of the airport
number **39 across only 10 distinct days**, of which **35 fall in August 2026** (the rest: two
days in November 2023, two in April 2026).

That is a fire signature, not infrastructure. A permanent heat source would appear on hundreds
of days. This finding is now closed: the August 2026 cluster near the airport is real burning.

---

### 11.4 What radius clustering changed (2026-08-28)

Task 04 implemented recurrence by clustering within 750 m rather than by grid cell. Two things
in the sections above have to be corrected in light of what it found.

**Saramom is not one source, it is three along a 2 km line.** Section 11.2 read the 66-day cell
and its 11-day and 7-day neighbours as a single source smeared by geolocation jitter. That was
half right. Clustering absorbs the neighbours into one site of **74 distinct days and 120
detections** at -1.1447, 136.0347 — but it also surfaces two further sites at -1.1336, 136.0339
(12 days) and -1.1268, 136.0363 (10 days), which no single grid cell had revealed because each
was itself spread across cell boundaries.

Those three centroids sit **1.2 km and 2.0 km apart, almost due north-south along 136.034E**.
VIIRS geolocation jitter is on the order of 375 m, so this is not one point smeared out. It is a
2 km linear feature, and a line is a road, a plot boundary, or a strip burned progressively, not
a landfill or a flare. The dominant site remains the southernmost, which is the one the project
owner has independently confirmed as the main source.

**The span condition does not protect the airport. The radius does.** Section 11.3 and the task
file both stated that Frans Kaisiepo escapes flagging because its 10 distinct days fail the
90-day span test. That is wrong, and it was verified wrong: within 3 km of the airport there are
39 detections on 10 distinct days spanning **1,018 days**. Both threshold conditions are met at
that scale. The airport is unflagged only because no single 750 m cluster inside it accumulates
10 days.

This matters because it is a silent dependency. Anyone who later widens `radius_m` to catch a
diffuse site will, at some width, flag the airport and publish it as a recurrent location -
exactly the outcome section 8 exists to prevent. Any change to `radius_m` must re-run the airport
check, not merely the tests.

An earlier single-linkage implementation demonstrated this concretely: transitive closure chained
the August 2026 airport fires to scattered 2023 detections about 2 km away into one 12-day
flagged site.


## 12. The evening blind window, and the night of 2026-08-27

### 12.1 When the satellites actually look

Every FIRMS acquisition over Biak in the three-year record falls into two windows:

```
00:31 - 01:58 WIT     night pass    S-NPP, NOAA-20, NOAA-21
09:00 - 15:00 WIT     day passes    VIIRS (12:00-14:00), Terra (09:00-10:00), Aqua (13:00-15:00)
```

**Nothing observes Biak between 15:00 and 00:31 WIT — a 9.5-hour blind window.** This is not a
data gap that better processing can close. The polar-orbiting constellation is sun-synchronous;
those are the only times it passes. Terra contributes 3 detections in 1,078 and Aqua 18, all
afternoon, so in practice the record is VIIRS at midday and VIIRS after midnight.

Night detections are 114 of 1,078 across three years (10.6%), every one of them between 00:31
and 01:58 WIT. Fires burning past midnight are therefore common enough to be well observed when
they occur. In the August 2026 event specifically, only 1 of 661 detections in ten days was at
night — a sharp departure from the three-year rate, consistent with daytime ignition that does
not persist.

### 12.2 The night of 2026-08-27

At 22:16 WIT the project owner, in Sorido, reported smoke strong enough inside the house to be
unpleasant, and fire trucks passing roughly two hours earlier.

What the instruments said at that moment:

| Source | Reading |
|---|---|
| FIRMS, most recent pass | 15:44 WIT, 6.5 hours earlier |
| FIRMS overnight pass (00:31-01:58 WIT) | **zero night detections** |
| WABB METAR, 13:00 WIT onward | 8000 m visibility, **no `FU` smoke code**, for ten consecutive hours |

The last `FU` at the airport was 04:00Z (13:00 WIT). From then until past midnight the airport,
6.5 km from Sorido, reported clear air.

**All three instruments reported nothing. The only detector that worked was a person standing
in the smoke.**

The day's detections place the likely source: a cluster 3.0-5.0 km NNW of Sorido at bearing
326-336 degrees, adjacent to the recurrent site in section 11.2, burning at 13:17-13:36 WIT.
Evening wind at the airport was 300-340 degrees — blowing from precisely that bearing onto
Sorido — before falling to `VRB02KT`, effectively calm, by 22:00.

### 12.3 What this means for the product

**Three separate failure modes, all real, all now dated:**

1. **No evening observation exists.** Between 15:00 and 00:31 WIT the project is blind. Himawari-9
   is the only open-access remedy and its priority is raised accordingly (§2.1, §7).
2. **A clear METAR is not evidence of clear air.** Under a calm nocturnal inversion smoke pools
   locally; a sensor 6.5 km away is in different air entirely. A `FU` report corroborates; its
   absence corroborates nothing.
3. **VIIRS detects radiant heat, not smoke.** A smouldering fire with no flame produces heavy
   smoke and little radiance. "No hot combustion detected" is a much weaker claim than "no fire",
   and the brief must not blur them.

**And one thing the project does not yet have: ground reports.** No remote sensing available here
covers the evening hours when residents actually experience smoke. A simple reporting channel —
a form, or a WhatsApp number, capturing time, place and severity — would outperform every
satellite in this document for that window, at near-zero cost. It belongs in the plan as a data
source, not as outreach.

This section exists because the alternative was to publish a brief for 2026-08-27 stating that
no thermal anomalies were detected overnight and the airport reported clear air. Both statements
would have been true, and together they would have been badly misleading.

---

## 13. What Himawari-9 found in the blind window: nothing

Task 05 built the evening product and ran it over **2026-08-22**, the largest fire day in the
record — 283 FIRMS detections. The result is a null, and it is the most useful thing this project
has measured since the backfill.

### 13.1 The numbers

```
21 slots, 06:00-16:00 UTC (15:00-01:00 WIT), 22,185 AOI pixels per slot

daytime  (15:00-18:15 WIT)   155,295 rows    38 flagged
night    (18:15-01:00 WIT)   310,590 rows     0 flagged

peak daytime B07 anomaly    +44.2 K   (346 K, on the FIRMS fire cluster)
peak night   B07 anomaly     +6.6 K   (below the 10 K threshold)
```

Every flag falls between 15:00 and 17:30 WIT, all of it before sunset. **After dark, on the worst
fire day of the crisis, Himawari-9 flagged nothing at all.**

### 13.2 Two readings, one operational conclusion

Either the fires genuinely stop burning hot at sunset — consistent with section 12, where only 1
of 661 detections in ten days was at night — or a 2 km sensor cannot see a smouldering fire that
VIIRS at 375 m would catch. Both are plausible and this data cannot separate them.

They lead to the same place. **Himawari does not close the blind window for detection.** It closes
it for *observation*: there is now a measured brightness-temperature series across hours that
previously held nothing. That is worth having, and it is a much smaller claim than the one this
project set out to make on 2026-08-28.

The honest sentence for the brief is therefore: *no evening thermal anomaly above threshold*, and
never *no fire*. Section 12.2 is the standing proof of why — the owner stood in heavy smoke at
22:16 WIT while three instruments reported clear.

### 13.3 The sub-threshold structure, recorded because it will be asked about

The largest night anomalies are not on the fire. Nine of the top twelve cluster at 23:30 WIT
around 135.5-135.7E, **45-75 km from the fire cluster**, with B07 minus B14 of only 3-5 K. A real
fire drives that difference much higher. These read as cloud-edge artifacts, and they are what a
cloud mask would exist to remove.

One exception is worth naming. At 18:30 WIT a single pixel at -1.1857, 136.1186 shows B07 305.6 K,
anomaly +5.6 K, and the highest B07 minus B14 in the night set at 7.4 K. That is **1.3 km from
Frans Kaisiepo**, inside the August 2026 burning that section 11.3 established as real fire.

It is one sub-threshold pixel. It is not a detection and must never be published as one. It is
recorded here because it is the only night signal in the run with a fire-like spectral signature,
and because if the evening thresholds are ever revisited, this is the pixel to revisit them
against.

### 13.5 Correction: the fires do not stop at sunset, they decay (2026-08-28)

Section 13.2 said this data could not separate "the fires stop burning hot at sunset" from "2 km
cannot see what 375 m would". After task 06 restricted the product to land pixels, it partly can.

The pixel named in 13.3, 1.3 km from Frans Kaisiepo, has a coherent time series:

```
WIT     B07      anomaly   B07-B14
18:30   305.6 K   +5.58 K    7.43     sunset 18:15
19:00   303.5     +3.65      5.72
19:30   302.8     +3.10      5.37
20:00   300.8     +1.15      3.38
20:30   300.9     +1.25      3.67
21:00   299.9     +0.53      2.87
21:30   299.3     -0.10      2.52
22:00   298.3     -0.76      1.94
```

Across all land pixels that night the anomaly field sits at a median of about -1.0 K with a
standard deviation near 1.5 K. The 18:30 value is therefore roughly **4.4 standard deviations**
above the field and the single hottest land pixel in the AOI; 19:00 is about 3. By 20:00 it is
inside the noise.

Two things follow. **The anomaly is measured against the local background, so general nocturnal
cooling is already removed** — this pixel cooled faster than everything around it, which is a heat
source dying, not the ground losing heat. And **combustion continued after sunset**, detectably
for roughly 75 minutes, then fell below what a 2 km pixel can resolve.

So the correct statement is not that fires stop at dark. It is that they **decay through the early
evening and drop under the detection floor**, somewhere around 20:00 WIT on this night. Whether
they then go out or smoulder on unseen is still unresolved, and section 12.3 lesson 3 is the
reason it matters: a smouldering fire produces heavy smoke and little radiance. That is the exact
combination that would put smoke in a house at 22:16 WIT with every instrument reading clear.

This is one pixel on one night and it is below the flag threshold. It is not a detection and must
not be published as one. It is the strongest physical evidence the project has that the evening
smoke problem is real and simply unobservable at this resolution.

### 13.4 What this changes

- Himawari stays in the pipeline. A measured null across the evening is a real observation, and a
  night that departs from it will be visible.
- The provisional 10 K thresholds are not validated for night. Night backgrounds are far cleaner
  than daytime ones, so a lower night threshold is defensible — but the 45-75 km cloud artifacts
  above show what lowering it would let through first. Do not lower it without a cloud test.
- Ground reports (section 12.3) remain the only source that covered the evening of 2026-08-27.
  Nothing in this section changes that, and this null result strengthens the case for building
  that channel.

