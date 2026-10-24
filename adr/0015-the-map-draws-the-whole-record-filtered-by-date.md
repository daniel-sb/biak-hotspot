# The map draws the whole detection record, filtered by date

The front page said "905 detections in 312 events" above a map showing two
dots, and the project owner read that as a layer that had failed to load. It
had not. The map drew `docs/data/hotspots_latest.geojson`, which is a
seven-day rolling window, and in a quiet week that is two points.

The layer was doing exactly what it was built for. What it was built for was
the status strip, not a record of a season, and nothing on the page said so.

## What changed

`scripts/export_vector_layers.py` publishes `docs/data/detections.geojson`:
the whole store the project holds, 1,166 detections from 2023 onward, with
`frp` kept and `confidence` left as the raw instrument code it is. The map
filters it on the page by WIT day and opens on 2026, so the first thing a
reader sees is the season the page is a record of.

`date_wit` is an ISO day string, so a string comparison is a date comparison
and the filter needs no date parsing in the browser at all.

The seven-day file stays. It is what the status strip and the brief cover, and
the detections inside that window are now ringed on top of the filtered record
so the current state stays visible whatever range the reader has chosen.

## Freshness

`detections.geojson` is rebuilt by the daily workflow, because the store gains
a day whenever the ingest runs and a map built once would silently stop at the
day it was built. Only the detections: the same script also writes roads and
administrative boundaries, and those come from inputs that never change, so a
scheduled job must not rewrite them (ADR 0003). That is what `--only` is for.
