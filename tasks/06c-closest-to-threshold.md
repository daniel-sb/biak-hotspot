# Task 06c — rank the after-dark line by distance to the flag condition

Task 06b is accepted; the section now leads correctly. One line in it is wrong, and the fault is
in task 06b's specification, not in your implementation of it. Read `AGENTS.md`, then PLAN.md 13.3
and 13.5.

---

## What you caught

You noted that the rendered line names the 23:30 WIT pixel at 135.4686E, which is the cloud-
artifact cluster from PLAN.md 13.3, not the airport pixel from 13.5. That was right, and task 06b
was wrong to use the airport pixel as its example.

The consequence is worse than one mislabelled example. **`bt07_anomaly` alone is dominated by
cloud edges**, so a daily bulletin would publish a meaningless number every night and give it
standing by repetition. That is the section 8 failure again, one layer down.

Ranking by `bt07_minus_bt14` instead is not the fix — it is worse. On this night the five largest
values, 13.5 to 13.8 K, all carry anomalies of **-5 to -8 K**: cold cloud tops, which are bright at
3.9 um and cold at 11.2 um. Neither statistic separates fire from cloud on its own.

## The fix

A pixel is flagged when `bt07_anomaly` and `bt07_minus_bt14` **both** clear their thresholds. The
honest measure of how close a night came to a flag is therefore the **weaker of the two tests**:

```
closeness = min(bt07_anomaly, bt07_minus_bt14)
```

Rank the after-dark land pixels by that and report the maximum. This is not a new heuristic — it
is the existing flag condition, read as a distance rather than as a boolean. Nothing else changes.

On 2026-08-22 it selects the right pixel, and the ordering is clean:

```
WIT     lat      lon       anomaly  B07-B14  closeness
18:30   -1.1857  136.1186    5.58     7.43     5.58     <- airport, PLAN 13.5
23:30   -0.8056  135.6856    5.27     5.08     5.08
23:30   -0.7875  135.7037    4.33     5.58     4.33
```

Reword the line to say what it now means. Something close to:

> Closest to the flag condition after dark: +5.6 K anomaly with a 7.4 K band difference at
> 18:30 WIT (-1.1857, 136.1186). Both tests must exceed 10 K to flag; this is not a detection.

Keep the "not a detection" clause mandatory, keep the thresholds rendered from config rather than
hardcoded, and keep your decision 1 — land only, ocean sample excluded.

**Do not add a cloud test, a spectral filter, or any other discriminator.** The point of using the
flag condition itself is that it introduces no new judgement. If you find yourself tuning a
constant, stop and report instead.

## The checks

1. Given a pixel with a high anomaly and a low band difference, and another with both moderate,
   the moderate one is reported.
2. A pixel with a large band difference and a negative anomaly is never reported.
3. The line still carries the "not a detection" clause and reads its thresholds from config.
4. On the real 2026-08-22 file the line names -1.1857, 136.1186 at 18:30 WIT.
5. The existing 60 tests still pass.

## Out of scope

Everything else in the evening section, which is now correct. Thresholds. Cloud masking. The
producer. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md.
