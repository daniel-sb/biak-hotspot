# Task 10 — Drought context panel

PLAN.md §2.5. The dashboard states how many hotspots were detected. It says nothing
about the conditions they were detected in. August 2026 is an outlier in the record
(§11.1) and the reason is partly meteorological: the dry season of 2026 was extreme by
the 46-year CHIRPS record. That belongs on the page, with the caveats that make it
honest.

This task adds one panel. It does not add an analysis framework, a chart library, or a
second data pipeline.

## What to build

### 1. `src/drought_gee.py` — compute, then write one JSON

A standalone script, run by hand, not by the daily cron. Earth Engine needs interactive
credentials and CHIRPS lags real time by roughly a month; a daily run would spend an API
call to re-publish an unchanged number.

Reads the AOI from `config.yaml` (AGENTS always-4). Masks to land using
`ESA/WorldCover/v200`, treating class 80 (permanent water) as not-land — the AOI box is
mostly ocean, and an unmasked mean is a mean of the sea.

Writes `docs/data/drought.json` with:

- `monthly`: for each month from 2021-01 to the last complete CHIRPS month, the AOI land
  mean of CHIRPS precipitation (mm) and MOD16A2 evapotranspiration (mm), and their
  difference.
- `climatology`: for each calendar month, the 1981–2025 CHIRPS mean and standard
  deviation, plus the count of years contributing.
- `current`: the most recent complete month — its precipitation, its z-score against that
  month's climatology, and its rank among all years of that month.
- `coverage`: the last CHIRPS date, the last MOD16A2 date, and the date the file was
  generated. All three, because they differ and the difference is the point.

Every number land-masked the same way. In the previous exploratory run the July rank was
computed unmasked while the monthly series was masked, and the two were not comparable.

### 2. Panel on `docs/index.html`

Below the existing timeline, in the same visual idiom as `#timeline-wrap` — plain SVG,
no library, drawn from the JSON.

Two things shown, not one:

- **Water balance P−ET by month**, 2021 to now. This is the panel's actual claim.
  Rainfall alone does not describe drying; a month can take 115 mm of rain and still lose
  water, and July 2026 did.
- **Precipitation against the 1981–2025 climatology** for the same months, so the reader
  can see whether the rainfall was unusual rather than take the word for it.

### 3. Caveats that must appear on the panel, not in a footnote

- **CHIRPS lags.** State the last CHIRPS date on the panel. If the brief's day is more
  recent than that date — it always will be — the panel is describing a period that ended
  before the hotspots it sits under. A reader who assumes the two are contemporaneous
  will draw a causal conclusion the data does not support.
- **Drought is not ignition.** Dry fuel makes burning easier; it does not start a fire.
  The panel must not read as an explanation of why Biak burned. PLAN §8: small-scale
  burning is lawful and long-established in Papua, and a page that quietly implies weather
  did it is as wrong as one that implies a person did.
- **No NDVI, no NDMI.** They were computed and they are excluded. MODIS composite quality
  correlates with July NDVI at r = +0.883 across 2001–2026 (NDMI +0.591): a dry month is a
  clear month, so its composite is built from more and better observations, and residual
  cloud depresses the wet-month values it is compared against. The "record-high vegetation
  index in the driest July" reading is an artifact of the compositing, not a signal. Record
  the exclusion in the panel copy in one sentence — a reader who knows the literature will
  otherwise ask why the obvious index is missing.

### 4. The all-clear ban applies

`tests/test_dashboard.py::test_no_all_clear_wording_in_page` bans "clear" and "safe" as
whole words anywhere in the file, comments included. Wet weather is not an all-clear
either: a wet month with hotspots in it is still a month with hotspots in it.

## Acceptance criteria

- `python src/drought_gee.py <project>` regenerates `docs/data/drought.json` and prints
  the figures it wrote.
- The panel renders from the committed JSON with no network call beyond the page's own
  data directory — `test_pinned_cdn_only` must still pass unchanged.
- The panel degrades like every other block: a missing or malformed `drought.json`
  produces a stated error, not an empty box and not a zero.
- A test asserts the JSON's internal consistency: `p_minus_et == precip_mm - et_mm` per
  month, months dense and sorted, climatology covering all 12 calendar months.
- A `render_check.py` check asserts the panel draws, names its last CHIRPS date, and
  carries the lag caveat.
- `python -m pytest tests/` passes.

## Out of scope

- Any daily automation of the Earth Engine call.
- NDVI, NDMI, or any vegetation index on the page.
- Forecast, fire-danger index, or any forward-looking statement (PLAN Phase 5).
- Per-district drought. CHIRPS is 5 km; Biak Numfor is roughly 20 desa wide in places.
  A district-level rainfall figure would imply a resolution the product does not have.
