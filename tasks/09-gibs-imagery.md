# Task 09 — daily satellite imagery on the map (NASA GIBS)

The page shows where detections are. It does not show what the island looked like. On
2026-08-22, the peak day, a reader in Biak could see the smoke from their own window; the
dashboard rendered it as orange dots.

This task adds two NASA GIBS imagery layers. Read `AGENTS.md` first, then PLAN.md sections
**8** and **9**, and task 07 for the constraints the page is built under.

Do this only after task 08b. The two are unrelated and should be reviewed separately.

---

## Why GIBS and not the obvious alternatives

**Google Maps tiles are out.** Google's terms forbid using their tiles outside Google's own
APIs. This is a licensing limit, not a technical one, and the repository and page are both
public.

**Esri World Imagery** responds and is widely used, but its terms expect an ArcGIS account for
production use. Grey enough to avoid when a clean option exists.

**GIBS is free, keyless, documented for reuse, and NASA-operated.** Both layers below were
verified against this AOI on 2026-08-22.

## The two layers

```
https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{LAYER}/default/{DATE}
    /GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg
```

Note the axis order: **`{z}/{y}/{x}`**, not the `{z}/{x}/{y}` MapLibre templates usually use.

| layer id | what it shows |
|---|---|
| `VIIRS_NOAA20_CorrectedReflectance_TrueColor` | true colour, 250 m — this is the one that shows the smoke |
| `VIIRS_SNPP_CorrectedReflectance_BandsM11-I2-I1` | SWIR false colour — active burning reads red, burn scars dark |

## Three traps, all verified

**1. Zoom 9 is the ceiling.** Measured against this AOI:

```
z=5  200    z=8   200
z=6  200    z=9   200
z=7  200    z=10  400   <- and every zoom above
```

The page's default view is already close to Biak, so a source without `maxzoom: 9` gives a
reader a layer that vanishes the moment they zoom in — or a wall of 400s. Set `maxzoom` and let
MapLibre overzoom the z9 tiles.

**2. Those 400s must not trip the error banner.** Task 07b added `map.on("error", ...)` so that
a failed basemap is stated rather than silent. A tile request outside a source's zoom range is
not that kind of failure. If overzoom or a missing date can raise a banner saying the map is
broken, the honest-degradation mechanism becomes noise and the next person will mute it.

**3. The date is the brief's day, not today.** The layer must show the WIT day the page is
describing. Read it from `summary_latest.json`, never from the client clock.

On the UTC/WIT question: the daytime VIIRS overpass for WIT day D falls near 04:30 UTC on the
same calendar date, so the GIBS granule date equals the WIT date here. That is a coincidence of
this longitude worth one comment in the source, not an assumption to leave implicit.

## Wording, binding

Imagery invites a reader to conclude things the data cannot support, so PLAN.md 8 applies with
full force.

- Label each layer with its **sensor, resolution and date**, visibly. "VIIRS 250 m, 2026-08-30"
  is the minimum.
- **One image per day, at 250 m, through cloud.** An absence of visible smoke is not an absence
  of smoke, and must never be presented as one. If you write "clear", stop.
- The false-colour layer is a **band combination**, not a fire detection. Red is reflectance in
  the SWIR, not a confirmed fire. Do not label it "fires".
- If tiles for the brief's date are unavailable, say the imagery is unavailable for that date.
  A blank layer must never read as an empty sky.
- NASA GIBS/Worldview attribution must be visible on the map, alongside the existing OSM and
  OpenFreeMap attribution, not buried.

## Placement

OpenFreeMap stays the basemap. These are toggleable overlays, off by default, drawn **below**
the desa boundaries and the hotspot circles — the vector layers are the product and imagery is
context. Only one imagery layer at a time; two stacked reflectance images mean nothing.

The toggle is plain HTML and CSS in the same file. No framework, no build step, no new
dependency, and nothing loaded from any host other than the pinned map CDN, the basemap, and
GIBS.

## The checks

1. With an imagery layer on, zooming past z9 keeps the imagery visible (overzoomed) and raises
   no error banner.
2. The requested date matches `covered_wit_date` from `summary_latest.json`, not the client clock.
3. A date with no imagery states that the imagery is unavailable, and does not render an empty
   layer silently.
4. Boundaries and hotspots stay above the imagery and stay legible on it.
5. No string on the page reads as an all-clear, and the false-colour layer is nowhere called a
   fire detection.
6. GIBS attribution is visible whenever a GIBS layer is on.
7. `python scripts/render_check.py` passes.
8. The existing tests still pass.

## Out of scope

Sentinel-2 imagery and dNBR (Phase 3), land cover, wind, the drought panel, animation across
dates, a date picker, any change to the brief generator or the ingest. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md. Say plainly whether you loaded
the page and zoomed past z9 yourself.
