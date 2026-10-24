# The web page is an event record, not a situation report

Both reference designs we benchmarked are operational situation reports: the
Alaska Interagency Coordination Center dashboard organises everything by
suppression lifecycle (New, Staffed, Active, Out), and its headline indicators
answer "what is burning now". We are not building that. Fires at the 2026 scale
appear to be rare on Biak rather than seasonal, so a page that leads with
current status would spend most of the year telling readers nothing while
implying there is something to watch. The page therefore leads with the 2026
event and what we know about it, and the current state is reduced to a single
status strip near the top.

The daily ingest cron keeps running regardless. It is already built and tested,
it costs nothing, and whether a season like 2026 recurs is an open question this
project should be able to answer rather than foreclose.

## Consequences

The detection record starts 2023-09-01, so "unprecedented" is not yet
supportable from our own data. Claiming the 2026 season is anomalous in living
memory requires a MODIS backfill toward 2000.
