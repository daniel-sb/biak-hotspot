# Task 02 — administrative assignment and the daily brief

Wire the desa boundaries into the ingest, then produce a daily brief and a GeoJSON export.
This completes PLAN.md Phase 1.

Read `AGENTS.md` first. Reference: PLAN.md sections 2.7, 3 (Phase 1), 6 and 9.6. Ignore
everything else — those are later phases you are not building.

Two deliverables:

- **A.** administrative assignment, added to `src/ingest_firms.py` at the hook already marked
  in `prepare()`
- **B.** `src/report_daily.py`, new

Tests go in `tests/test_ingest_firms.py` (for A) and a new `tests/test_report_daily.py` (for B).

---

## A. Administrative assignment

`config.yaml` already points at `data/boundaries/biak_desa.geojson` — 306 desa across 24
distrik in two regencies, EPSG:4326, RFC 7946 (lon, lat order).

Add these columns to every detection:

| Column | Source property | When outside all polygons |
|---|---|---|
| `desa` | `WADMKD` | null |
| `distrik` | `WADMKC` | null |
| `kabupaten` | `WADMKK` | null |
| `on_land` | derived | `False` |

**Never drop a detection that falls outside every polygon.** Flag it with `on_land = False`
and leave the name columns null. This is AGENTS.md rule 5, and those rows carry real
information — a detection just offshore is usually a coastal pixel, occasionally sun glint, and
Phase 2 needs to see them to tell the difference.

### Implementation decisions, already made

- **Use `shapely`** — `shapely.geometry.shape()` to build the polygons, `shapely.STRtree` to
  index them. Hand-rolling point-in-polygon for multipolygons with holes is the "flimsier
  algorithm" trap; this is a genuine dependency, take it.
- **Do not add `geopandas`.** It pulls GDAL and the whole stack for what `shapely` plus the
  standard library `json` module already does here.
- **Load the boundary file once**, not per detection. 306 polygons against a few hundred
  detections is trivial either way, but a per-row load will not survive a multi-year backfill.
- **`STRtree` returns candidates, not answers.** It queries bounding boxes; you must still test
  actual containment on each candidate.

### Pinned expected values

These were verified independently. If your numbers differ, something is wrong — say so rather
than adjusting code until they match.

```
(-1.1274, 136.0440)  ->  desa Sambawofuar, distrik Samofa,    kabupaten Biak Numfor
(-1.1853, 136.1297)  ->  desa Swapodibo,   distrik Biak Kota, kabupaten Biak Numfor
(-1.3000, 136.4000)  ->  outside all polygons, on_land = False

Across all 12 committed fixtures (653 detections):
  on_land = True   ->  651
  on_land = False  ->    2
  distinct distrik with at least one detection: 18 of 24
```

---

## B. The daily brief

`src/report_daily.py` reads `data/processed/detections.parquet` and writes three files.
It must not fetch anything from the network.

### Outputs

```
docs/data/hotspots_latest.geojson   rolling window, RFC 7946 Point features
docs/data/summary_latest.json       machine-readable counts
docs/briefs/YYYY-MM-DD.md           the brief, one file per WIT day
```

`docs/` is the GitHub Pages root, so these are published files. Treat them as public output.

### Which day the brief covers

The most recent WIT day present in the store. State the covered day and the window explicitly
in the brief — never leave the reader to infer it.

### What the brief must contain

1. The WIT date covered, and the generation timestamp in UTC and WIT.
2. Total detections, split by `on_land`.
3. **A table of all 24 distrik**, including those with zero detections, with counts, total FRP
   and maximum FRP.
4. **Which satellite sources returned data for that day.** This is not optional. Detections stop
   when cloud blocks the view — PLAN.md section 10.4 finding 3 documents exactly that, where
   FIRMS went silent on 2026-08-26 while smoke was still being reported at the airport. A brief
   that says "0 hotspots" without saying what was observed is misleading.
5. A plain statement that a hotspot is a thermal anomaly, not a confirmed fire, and that the
   data cannot identify who started one. PLAN.md section 8 is binding on published output.

### Zero is not the same as unobserved

A distrik with no detections on a day when satellites did observe the area reads
"0". A day where a source returned no data at all must say so separately. These are different
facts and the brief must keep them apart — this is the same defect as reporting a failed fetch
as an empty result, which AGENTS.md forbids.

### Determinism

A scheduled job will commit these files daily. Sort GeoJSON features by `detection_id` and
distrik rows by name so that a re-run with unchanged data produces an unchanged file apart from
the timestamp. Otherwise every run generates a meaningless diff and real changes become
invisible.

### Language

**Write the brief in English for now.** Put every user-facing string in a single dictionary at
the top of the module. PLAN.md section 6 requires Bahasa Indonesia for the local audience and
that translation is a known, scheduled requirement, not a hypothetical one — the dictionary is
what makes it a swap rather than a rewrite. Keep field names in the data files in English and
the BIG originals.

---

## The checks

Extend `tests/test_ingest_firms.py` for A and add `tests/test_report_daily.py` for B. No
network in either. Assert at least:

1. The three pinned coordinates above resolve as stated.
2. A detection outside every polygon is kept, with `on_land = False` and null name columns.
3. Across the fixtures: 651 on land, 2 off, 18 distrik represented.
4. The brief lists all 24 distrik even though only 18 have detections.
5. A day where one satellite source returned no data is reported differently from a distrik
   with zero detections.
6. Running the report twice over identical input produces identical output apart from the
   timestamp.

## Out of scope — do not build

PNG maps or any plotting (decided: the Phase 6 dashboard renders maps; revisit only if
messaging-app sharing becomes a requirement). The dashboard HTML. Quality-control filters,
the persistent-source mask, event clustering, Earth Engine, METAR, air quality, fire danger
indices. Anything in PLAN.md phases 2 through 6.

Do not add dependencies beyond `shapely`.
