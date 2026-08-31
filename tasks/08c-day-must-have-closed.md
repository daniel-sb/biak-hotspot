# Task 08c — a fetch can cover a day that has not happened yet

Task 08b is accepted. The provenance guard is the right mechanism, the two refusal messages
name the gap without mentioning detection counts, the old `today_wit` comparison is gone,
`--day` no longer walks past the guard, and the gai.conf step is the correct place to fix a
runner's routing.

One hole remains, and **it is in my specification of 08b, not in your implementation.** Task 08b
said "a day the manifest says was observed, with zero detections, must still publish." I did not
account for the manifest being able to claim coverage of a day that had not yet ended.

Read `AGENTS.md`, then PLAN.md section **8**.

---

## What still happens

Run at 14:14 WIT on 2026-08-31, with WIT day 2026-08-31 still nine hours from closing:

```
$ python src/report_daily.py --day 2026-08-31
covered 2026-08-31: 0 detections, 0 offshore     (exit 0 - it published)
```

The manifest entry that let it through:

```json
{"chunk_start": "2026-08-27", "days": 5, "outcome": "fetched",
 "source": "MODIS_NRT", "utc": "2026-08-31T02:30:04Z", "rows": 1}
```

Nominally that chunk covers 2026-08-27 through 2026-08-31, and `_covers()` is right about the
interval. But it **ran at 02:30 UTC, which is 11:30 WIT on 2026-08-31**. Half the WIT day had
not happened, and the afternoon VIIRS overpass at roughly 13:30 WIT had not happened either. The
brief nonetheless states that the day was observed and was quiet.

That is the same failure the guard was built to stop, one step further in: a day published as
observed when it was not observed. The refusal for a genuinely uncovered day works — 2026-09-30
exits 1 with the right wording — so the mechanism is sound. The coverage test is what is
incomplete.

## The fix

**A successful chunk only counts for WIT day D if it ran after D closed.** WIT is UTC+9, so day
D ends at 15:00 UTC on D. The manifest already records `utc` per chunk, so this needs no new
field and no new config — only a stricter definition of "covered" inside `provenance_refusal`.

Add a third refusal for the case where covering chunks exist and succeeded, but every one of
them ran before the day ended. Say which it is: that the day has not closed yet, or that the
only fetches covering it predate its end. Keep the existing two messages as they are.

**The cron is unaffected**, and confirming that is part of the task: it runs at 16:30 UTC and
reports the WIT day that closed at 15:00 UTC the same day, so its covering fetch always runs
after the close. This change should make no difference to a scheduled run, and a test should
pin that so nobody later "fixes" the guard by loosening it.

**Do not add a latency margin.** FIRMS near-real-time latency is roughly three hours and the
last overpass of WIT day D falls near 04:30 UTC on D, so a fetch after 15:00 UTC on D already
has everything. A configurable grace period would be a constant to tune, and tuning constants
is how guards get quietly disabled.

`--allow-stale` stays the single deliberate override and stays out of `.github/`.

## The checks

1. Asking for a WIT day that has not closed refuses, with a message saying so, and exits 1.
2. A day whose only covering fetches ran before it closed refuses, and the message says that
   rather than claiming no fetch covered it.
3. A day whose covering fetch ran after it closed still publishes, including when it had zero
   detections.
4. A run at the cron's own hour and date publishes the just-closed WIT day — the scheduled path
   is unchanged.
5. `--allow-stale` still overrides all of it, and appears nowhere in `.github/`.
6. The existing 83 tests still pass.

## Out of scope

The two existing refusal messages, `_covers()` itself, the workflow's network step, the ingest,
the dashboard, task 09. No new dependencies, no new configuration keys.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
