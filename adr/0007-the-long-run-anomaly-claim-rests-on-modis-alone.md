# The long-run anomaly claim rests on MODIS alone

The detection store starts 2023-09-01. Within it, 2026 is plainly anomalous:
905 detections against 100, 90 and 71 in the three preceding years, and a worst
day of 283 on 2026-08-22 against a prior record of 16 on 2023-11-16. But three
years cannot support "unprecedented", and the claim worth making is about the
sixteen years a resident has lived through.

The backfill therefore pulls `MODIS_SP` from November 2000 and
`VIIRS_SNPP_SP` from 2012, and the long-run comparison uses **MODIS against
MODIS only**. A series spliced from MODIS before 2012 and VIIRS after it rises
in 2012 because the pixels shrank from 1 km to 375 m, not because Biak started
burning, and a reviewer will say so. VIIRS is kept because it is strictly better
after 2012 and costs little to add, and it never enters the long-run series.

One consequence is favourable. 1 km MODIS misses many of the small fires 375 m
VIIRS catches, so a MODIS-only series undercounts every year, 2026 included. An
outlier that survives in a series which undercounts it is a stronger claim than
one measured on the best available sensor.

## Consequences

`config.yaml` sets `backfill_years: 3`, and the comment above it argues against
raising the value because "three years answers the question". The question
changed, so that premise no longer holds and the line needs revisiting as part
of the backfill task.
