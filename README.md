# Biak Hotspot Monitoring

Daily hotspot detection, chronological analysis, postmortem and fire-danger reporting for
Biak, Supiori and Numfor — Papua, Indonesia.

**Read [PLAN.md](PLAN.md) first.** It carries the data sources, the phase plan with
acceptance criteria, verified API access notes, and the publication ethics this project is
built under. Nothing here should be implemented without it.

[FINDINGS.md](FINDINGS.md) is the other half: what the data turned out to say, with the
numbers, the caveats and the commit behind each one. It is append-only — a figure that
turns out to be wrong is corrected by a later entry naming what it supersedes, rather than
edited in place.

## Status

All six phases are built and tested, and Phase 5 step 1 with them. The daily job runs on
GitHub Actions; the page is served by GitHub Pages from `docs/`.

- **Ingest** — FIRMS VIIRS (S-NPP, NOAA-20, NOAA-21) and MODIS, with a three-year backfill.
  Raw responses are persisted before parsing; a failed fetch is never recorded as a zero.
- **Store** — 1,166 detections across 198 WIT days, 2023-09-01 to 2026-09-23.
- **Recurrence** — leader clustering at 750 m against a registry that keeps site IDs stable
  between runs (R001 to R003).
- **Events** — 488 space-time clusters (750 m, 30 h), with IDs that survive a refresh by
  membership overlap. `first_seen` is the first overpass that caught an event, never an
  ignition time.
- **Burned area** — dNBR+ on Sentinel-2 at 20 m, thresholded per event against never-detected
  land nearby. 23 events assessed; the cloud gap is published beside every figure, and no
  accuracy is claimed because there is no reference data yet.
- **Corroboration** — 51,838 half-hourly METARs from Frans Kaisiepo. Smoke at the airport
  corroborates the August and September 2026 episodes as episodes, never a single event.
- **Evening** — Himawari-9 AHI read directly from the public AWS bucket, covering the
  15:00 to 01:00 WIT window that no polar orbiter observes.
- **Fire danger** — the Canadian FWI system and KBDI from ERA5-Land over 30 land cells,
  scored against the detection record by leaving one calendar year out.
- **Dashboard** — one static MapLibre page. No framework, no build step, no trackers.
- **Drought context** — CHIRPS precipitation against the 1981–2025 climatology and the
  monthly water balance against MOD16A2 evapotranspiration, refreshed by hand rather than
  by the cron because CHIRPS lags real time by about a month.

Next: a reference sample drawn by hand on 1 m imagery, and the first agreement figure for
the burned-area product (`tasks/22-burn-classifier.md`).

## Verified so far

- FIRMS returns usable data for the AOI across four satellite sources (PLAN.md §10.4).
- METAR from WABB is public, half-hourly, unauthenticated, and independently corroborates a
  burning event on 19–25 August 2026 (PLAN.md §10.2).
- No ground air-quality station exists on Biak or anywhere in Papua (PLAN.md §9.5).
- August 2026 runs at 65 times the 2023-2025 baseline: 2.68 detections per week
  across 1,065 days, against 174 per week through August (PLAN.md §11.1).
- Himawari-9 shows thermal decay continuing past sunset and dropping below the VIIRS
  detection floor by about 20:00 WIT (PLAN.md §13.5).
- The burned ground was mostly not intact forest: JRC TMF puts 14.7% of the changed area in
  undisturbed forest where Esri's land cover reads 70.6% trees (FINDINGS.md F14).
- FWI and its fast components rank burning days above the day-of-year climatology in every
  year, and most of that survives a check on cloud-free days only (F17).
- No prompted segmentation model — SAM 2.1, SAM 3, LangSAM — can outline a burn scar, at
  10 m or at super-resolved 1 m (F18, corrected by F19).

## Setup

```sh
cp .env.example .env    # then fill in your keys
git config core.hooksPath .githooks
```

The second command is required after cloning. It enables the pre-commit hook that blocks
credentials from being committed — this repository is public.

The drought panel is refreshed separately, from an environment with Earth Engine
credentials, and only when CHIRPS has published a new complete month:

```sh
python src/drought_gee.py <google-cloud-project-id>   # writes docs/data/drought.json
python src/vegetation_gee.py <google-cloud-project-id>   # writes docs/data/vegetation.json
```

`docs/data/vegetation.json` is not in the repository until that command has been run.
Until then the vegetation panel states that its data is unavailable, which is the
honest state: the panel shows measurements or it shows nothing.

The rest of the Earth Engine work runs the same way, by hand and never from the cron:
`src/burned_area_gee.py` for the burn-area delineation and `src/fire_danger.py --fetch` for
the ERA5-Land weather behind FWI and KBDI. `src/himawari.py` and `src/metar.py` fetch from
public archives instead, and both re-run offline from the files they persisted.

## Repository layout

| path | what is in it |
|---|---|
| `src/` | the pipeline: ingest, store, events, burn indices, Himawari, METAR, fire danger |
| `scripts/` | one-off tools — posters, the labelling package, the SAM pilot |
| `notebooks/` | the Colab notebooks, for the two jobs that need a GPU or Linux |
| `tasks/` | one scoped task per file, the unit of work this repository is built in |
| `data/processed/` | small tracked outputs; everything larger is gitignored and rebuilt |
| `docs/` | the published site, written only by the daily job |

## A note on what this publishes

A satellite hotspot is a thermal anomaly. It is not a confirmed fire, and it can never
identify who lit one. Small-scale shifting cultivation is lawful and long-established in
Papua. See PLAN.md §8 before publishing anything derived from this data.

## Licence

Code is MIT (see `LICENSE`). The datasets are not ours: NASA FIRMS, JMA Himawari-9 via the
NOAA public bucket, and administrative boundaries from BIG each keep their own terms. Cite
the source, not this repository, when reusing the data.
