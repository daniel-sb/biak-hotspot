# Burn polygons publish at native resolution, the fuel map does not

PLAN.md section 8 permits publishing detection coordinates, forbids publishing
inferred responsibility, and requires aggregation to district level wherever
individual attribution would otherwise be inferable. Biak is small enough that a
60 m burn box or a 10 m fuel class sits at roughly parcel scale, and "this plot,
this date, burned, high fuel load, burned before" reads as an accusation even
with no name anywhere on the page.

Burn polygons and fuel are different in kind. A polygon is an observation of
ground state, which section 8 explicitly allows. A fuel class is a model's
inference about a place.

Burn polygons therefore publish at native resolution, with no per-polygon
attribute table, no land-ownership or land-use join, and all counts aggregated
to distrik. `data/processed/burned_areas.geojson` already satisfies this: 1,050
polygons carrying only `event_id` and `threshold`. The fuel map publishes on the
site only as a distrik aggregate; the full-resolution raster appears in the
paper's figures and nowhere on the web.

At 1.25 MB the polygon layer ships as plain GeoJSON. PLAN.md section 9
recommends PMTiles for raster layers, and this file is small enough that the
recommendation does not apply.
