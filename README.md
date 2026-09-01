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

Phases 1 to 6 are built and tested. The daily job runs on GitHub Actions; the page is served
by GitHub Pages from `docs/`.

- **Ingest** — FIRMS VIIRS (S-NPP, NOAA-20, NOAA-21) and MODIS, with a three-year backfill.
  Raw responses are persisted before parsing; a failed fetch is never recorded as a zero.
- **Store** — 1,078 detections across 180 WIT days, 2023-09-01 to 2026-08-27.
- **Recurrence** — leader clustering at 750 m against a registry that keeps site IDs stable
  between runs (R001 to R003).
- **Evening** — Himawari-9 AHI read directly from the public AWS bucket, covering the
  15:00 to 01:00 WIT window that no polar orbiter observes.
- **Dashboard** — one static MapLibre page. No framework, no build step, no trackers.
- **Drought context** — CHIRPS precipitation against the 1981–2025 climatology and the
  monthly water balance against MOD16A2 evapotranspiration, refreshed by hand rather than
  by the cron because CHIRPS lags real time by about a month.

Next: event clustering and Sentinel-2 burn-area delineation (Phases 3 and 4).

## Verified so far

- FIRMS returns usable data for the AOI across four satellite sources (PLAN.md §10.4).
- METAR from WABB is public, half-hourly, unauthenticated, and independently corroborates a
  burning event on 19–25 August 2026 (PLAN.md §10.2).
- No ground air-quality station exists on Biak or anywhere in Papua (PLAN.md §9.5).
- August 2026 runs at 65 times the 2023-2025 baseline: 2.68 detections per week
  across 1,065 days, against 174 per week through August (PLAN.md §11.1).
- Himawari-9 shows thermal decay continuing past sunset and dropping below the VIIRS
  detection floor by about 20:00 WIT (PLAN.md §13.5).

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

## A note on what this publishes

A satellite hotspot is a thermal anomaly. It is not a confirmed fire, and it can never
identify who lit one. Small-scale shifting cultivation is lawful and long-established in
Papua. See PLAN.md §8 before publishing anything derived from this data.

## Licence

Code is MIT (see `LICENSE`). The datasets are not ours: NASA FIRMS, JMA Himawari-9 via the
NOAA public bucket, and administrative boundaries from BIG each keep their own terms. Cite
the source, not this repository, when reusing the data.
