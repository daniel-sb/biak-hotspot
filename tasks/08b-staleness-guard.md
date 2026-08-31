# Task 08b — two defects in the daily job

Task 08 is otherwise accepted. The store is tracked, the registry survives a fresh checkout,
the schedule reasoning is right, failure stops before the commit step, and `--allow-stale`
is genuinely absent. One line undoes the protection all of that was for.

Read `AGENTS.md`, then PLAN.md sections **8** and **9.6**.

---

## What happens today

`.github/workflows/daily.yml` runs:

```yaml
- name: Build the daily brief and dashboard data
  run: python src/report_daily.py --day "$(date -u +%F)"
```

In `src/report_daily.py` the guard lives inside the `else` branch:

```python
if args.day:
    covered = args.day
else:
    covered = latest
    today_wit = now_utc.astimezone(WIT).date().isoformat()
    if covered != today_wit and not args.allow_stale:
        sys.exit("store covers up to WIT day ... Refusing to republish old data as current.")
```

So passing `--day` skips the check entirely. Run against the current store, which ends
2026-08-27:

```
$ python src/report_daily.py --day 2026-08-31
covered 2026-08-31: 0 detections, 0 offshore

# Biak hotspot daily brief — 2026-08-31 (WIT)
*Generated 2026-08-31 00:58:34 UTC. Covers WIT day 2026-08-31 only.*
**0 thermal anomaly detections**: 0 on land, 0 offshore/water
```

Four days with no data at all, published as a completed observation of a quiet day. A reader
cannot tell that from a day we actually watched. That is AGENTS.md rule 2 — never report a
failed fetch as zero results — reached by a different route, and the PLAN.md 8 failure of
true parts assembled into a false impression.

**It is worse than the flag task 08 banned.** With `--allow-stale` the brief still carries the
store's real date, so the page shows its real age, which is what PLAN.md 9.6 asks for. With
`--day <today>` the brief stamps today's date onto data that does not exist.

The workflow comment states the opposite:

> *"Naming the complete day explicitly is not the same as clearing staleness wholesale - that
> override stays out of this workflow on purpose."*

The intent was right and the reasoning about the cron hour was right. The effect is not what
the comment claims, and the comment is the reason nobody would look again. Check the behaviour,
not only the flag.

## Why `--day` was reached for, and why the guard is wrong anyway

The reasoning in the workflow comment is sound: at 16:30 UTC it is already 01:30 WIT the next
day, so `today_wit` is a day that cannot possibly have data, and the default path refuses every
time. Passing `--day` was a reasonable response to a guard that does not work at that hour.

So fix the guard rather than bypassing it. But do not simply shift it by a day, because
**`max(date_wit)` is the wrong freshness signal in the first place.** A WIT day with genuinely
zero detections is normal here — the 2023-2025 baseline is 2.68 detections per week, so most
days in the record are empty. A guard built on "the store has a row for that day" will refuse
on quiet days when nothing is wrong, and the first person on call will reach for an override
again.

The question is not *are there detections for day D*. It is *did a successful fetch cover day
D*. The project already records exactly that, in three states, in `run_manifest.json`. Use it.

## Required

**Base the guard on provenance, not on detection counts.** Before writing a brief for WIT day
D, `report_daily.py` must confirm from the run manifest that D was covered by a fetch that
succeeded. If it was not, refuse — with a message that distinguishes "no fetch covered this
day" from "the day was observed and was quiet".

**Make the guard apply when `--day` is given.** An explicit day must not be a way past it.
Keep `--allow-stale` as the single deliberate human override, and keep it out of CI.

**Remove `--day` from the workflow** once the guard works at the cron hour. If you find a
reason it must stay, say so in your report and explain why the guard alone is not enough.

**A day the manifest says was observed, with zero detections, must still publish**, and must
still read as an observation. Do not make quiet days fail.

## Out of scope

The schedule, the tracked store, the commit step, the concurrency group, the test gate,
Himawari, Pages. Everything else in task 08 is accepted. No new dependencies.

## The checks

1. `report_daily.py --day D` refuses when no successful fetch covered D, and says so in words
   that do not mention detection counts.
2. `report_daily.py --day D` succeeds when the manifest says D was observed and there were zero
   detections, and the brief reads as an observation of a quiet day.
3. Against the store as it stands today, building a brief for the current date fails.
4. `--allow-stale` still overrides, and still appears nowhere in `.github/`.
5. A run whose ingest failed publishes nothing.
6. The existing 76 tests still pass.

## Before you finish

Name every decision this task did not specify, per AGENTS.md. State plainly which claims in
your task 08 report you verified by running, and which you asserted from reading the code.

---

# Part 2 — the job cannot reach FIRMS from GitHub Actions

The first real run (`workflow_dispatch`, run 33346219378) failed. Not on credentials — the
secret resolves correctly: the runner's env group shows the key name against a masked value,
and the request path reads `/api/area/csv/***/`, which is what GitHub prints when a non-empty
secret has been substituted; an empty one would leave `csv//` in that path. All twelve
chunks failed like this:

```
ERROR FETCH FAILED VIIRS_SNPP_NRT 2026-08-17: ... Failed to establish a new connection:
[Errno 101] Network is unreachable
INFO summary: 0 fetched, 0 served from cache, 12 failed, 0 unavailable of 12 chunks
ALL FIRMS requests failed and no cached raw responses exist - no data parsed,
existing store left untouched.
```

**The failure handling was exactly right and needs no change.** Twelve failures were recorded
in the provenance as failures rather than as zeros, the store was left untouched, the process
exited non-zero, the job stopped before the commit step, and the published page still shows
2026-08-27 with its real age. That is AGENTS.md rule 2 and PLAN.md 9.6 both holding under a
genuine failure. Do not touch any of it.

## The probable cause

`firms.modaps.eosdis.nasa.gov` publishes both records:

```
A     198.118.194.34
AAAA  2001:4d0:241a:40c0::34
```

GitHub's Ubuntu runners have no IPv6 route. `getaddrinfo` returns the AAAA record, the
connection is attempted over IPv6, and the kernel answers `Errno 101 Network is unreachable`
before any traffic leaves. Retrying cannot help, which is why all twelve chunks failed
identically over twelve minutes.

Treat this as the leading hypothesis, not as established fact — **verify it before fixing it**.
A one-off debug step that resolves the host and attempts an IPv4-only connection from the
runner will settle it in under a minute. If the cause turns out to be different — NASA
blocking cloud IP ranges would look similar — report what you actually found and fix that
instead.

## Required, if the hypothesis holds

Prefer IPv4 **in the workflow, not in `src/`**. The ingest works correctly on every network
that has a working IPv6 route or none at all; the defect is in the runner's environment, and
that is where it should be corrected. A step that disables IPv6 on the runner, or sets IPv4
precedence in `/etc/gai.conf`, is enough. Comment it with the reason, so the next person does
not delete a line that looks like superstition.

Do not add a retry loop, do not lengthen the existing backoff, and do not add a dependency to
control socket families.

## Additional checks for Part 2

7. A manually dispatched run completes, commits the updated store and brief, and pushes.
8. `data/processed/run_manifest.json` after that run records the chunks as fetched, not failed.
9. The published `docs/data/summary_latest.json` advances past 2026-08-27.
10. The fix carries a comment naming the cause.
