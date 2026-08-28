# Task 07 — the public dashboard (Phase 6)

Everything this project has measured currently lives in Markdown inside a git repository. This
task gives it an audience. Read `AGENTS.md` first, then PLAN.md sections **8** and **9**, and
sections 11 to 13 for what the page has to communicate.

Build `docs/index.html`, served by GitHub Pages from `docs/`.

---

## Two corrections to PLAN.md section 9

**No PMTiles.** Section 9 specifies MapLibre plus PMTiles. The published GeoJSON is 624 features
and 500 KB. PMTiles requires `tippecanoe`, which is a build step, which contradicts the no-build-
step architecture in the same section. Serve plain GeoJSON. Revisit only if published data passes
a few MB.

**No precipitation chart, no AQI panel.** Both were in the original brief for this project. CHIRPS
is Phase 4 and does not exist yet; PLAN.md 9.5 established there are zero OpenAQ stations in
Papua. Do not stub either. A page that ships what the data supports is worth more than one with
two empty panels.

## What exists to publish

```
docs/data/hotspots_latest.geojson   500 KB   624 features, rolling 7 WIT days
docs/data/summary_latest.json       4.3 KB   totals, districts, sources, evening block
docs/data/recurrent_sites.json      941 B    R001-R003, centroids and day counts
docs/briefs/*.md                             one per WIT day
```

Two inputs are missing and this task adds them.

**`docs/data/daily_counts.json`** — detections per WIT day across the whole store, written by
`report_daily.py` on each run. Roughly 1,100 entries; keep it a flat array of `[date, count]` or
equivalent. This is what the timeline draws.

**`docs/data/biak_desa.geojson`** — the district boundaries. The source at
`data/boundaries/biak_desa.geojson` is 1.2 MB, too heavy to serve raw. Simplify with `ogr2ogr`
(`-simplify`, and drop attributes the page does not use) and add a script under `scripts/` so it
is reproducible. Target under 300 KB. Report the size you achieve and the tolerance used.

## The page

One `index.html`, no framework, no npm, no build step. MapLibre GL JS from a pinned CDN version.
Everything else is hand-written CSS and vanilla JS in the same file.

**Basemap.** Use a source that needs no API key — OpenFreeMap is the straightforward choice.
Attribution for the basemap and for OpenStreetMap must be visible on the map, not buried.

**Map layer.** Hotspots from the rolling GeoJSON, sized or coloured by FRP, with the desa
boundaries beneath. Clicking a hotspot shows date, WIT time, satellite, confidence, FRP, and
distrik. **Do not colour or scale by `confidence`** — VIIRS returns `l`/`n`/`h` and MODIS returns
0-100 in the same column; they are not comparable. Show the raw value in the popup and nothing
more.

**Recurrent sites.** Draw the three sites from `recurrent_sites.json` as a distinct layer, labelled
**"recurrent location"** and nothing else. Never "industrial", never "false positive", never
"non-fire". A tooltip may state the distinct-day count and the date range. PLAN.md 11.2 explains
why this wording is binding: nobody knows what is at those locations.

**Timeline.** Daily counts across the full record, with the three-year baseline visible. The point
PLAN.md 11.1 makes has to survive the rendering: 2023-2025 run at roughly two detections per week
and August 2026 is 65 times that. A linear axis showing a flat line and one spike is the honest
picture — do not use a log axis to make the baseline years look busier than they were.

**Today's brief.** Render the most recent brief's text on the page. Markdown to HTML with a small
hand-rolled converter is fine for headings, bold, lists and blockquotes; do not add a Markdown
library for this.

## Wording, binding

The standing ethics text from PLAN.md section 8 — a hotspot is a thermal anomaly, not a confirmed
fire; it cannot identify who started anything; small-scale burning is long-standing practice in
Papua — must appear **on the page itself**, not only inside the brief text it renders. A reader
who never scrolls to a brief still sees it.

The evening block from `summary_latest.json` is rendered with the same discipline task 06b and 06c
established: after-dark result first, "no evening thermal anomaly above threshold after dark", the
28x pixel-area floor, and never any phrasing that reads as an all-clear. If you find yourself
writing "clear" or "safe" anywhere on this page, stop.

State the AOI's observation gap somewhere a reader will find it: nothing observes Biak between
15:00 and 00:31 WIT except Himawari, at 2 km. PLAN.md 12 and 13 are the source.

## Constraints

- No trackers, no analytics, no fonts or scripts from anywhere except the pinned map CDN and the
  basemap tiles. This page is served to people in Biak on mobile connections.
- Must work on a phone. Test at 360 px wide.
- Must degrade honestly: if a data file is missing or fails to load, say so on the page. A blank
  map is not an empty island.
- No new Python dependencies. The page adds no Python at all beyond the two new output files.

## The checks

1. `daily_counts.json` regenerates deterministically and covers the full store span.
2. The simplified boundary file is under 300 KB and still contains all 306 desa.
3. The page renders with all data files present, and renders a stated error with each one absent.
4. No string in the page reads as an all-clear for the evening.
5. `confidence` is not used for any visual encoding.
6. The section 8 ethics text is present in the page source, outside the brief container.
7. The existing 63 tests still pass.

## Out of scope

Precipitation, AQI, NDVI, land cover, Sentinel-2 burn scars, the evening Parquet as a map layer,
historical brief navigation, search, any backend. Deployment settings on GitHub — the repository
owner enables Pages.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
