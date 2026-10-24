# No scheduled job may change a published burned-area figure

The `daily` cron regenerates and commits the detection products every evening,
and that is correct for detections: they are a running record and the page
should show the latest one. Burned area is not like that. The mapped extent came
from a credentialled Earth Engine extraction, the area estimate came from a
hand-interpreted label set, and both are quoted in the manuscript with
confidence intervals. A scheduled job that recomputed either would silently
move a published number, and nobody would be watching the morning it happened.

The cron therefore writes `hotspots_latest.geojson`, `summary_latest.json`,
`daily_counts.json`, and `drought.json` and `vegetation.json` as new months
land. It never writes a burned-area product. Those are regenerated only by a
person running the script deliberately, and a new figure supersedes an old one
through a new `FINDINGS.md` entry, never by overwriting the page underneath it.
