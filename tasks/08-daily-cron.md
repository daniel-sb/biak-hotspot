# Task 08 — the daily job (Phase 1 automation)

Everything in this repository runs because someone types a command. The store ends at WIT day
2026-08-27; today is 2026-08-30. The published brief is three days old and the page correctly
says so, which is the staleness guard working — but the fix is automation, not a wider guard.

Read `AGENTS.md` first, then PLAN.md section **9.6** (repository layout and acceptance
criteria). Build `.github/workflows/daily.yml`.

---

## 1. Fix this before writing any YAML

`.gitignore` excludes `data/processed/` and `data/raw/`. A GitHub Actions run starts from a
fresh checkout, so **the store does not exist in CI**. Three consequences, in order of severity:

**The site registry resets, and published site IDs get reassigned.** `src/recurrence.py` reads
the registry from `data/processed/recurrent_sites.json`, which is untracked. On a fresh
checkout it is absent, `next_number` restarts at 1, and R001 is assigned to whichever cluster
sorts first — not necessarily the Yendidori site that is already published as R001. Task 04b
existed specifically to make these IDs stable across runs; a cron job would undo it on day one
and nothing would fail loudly. The byte-identical copy at `docs/data/recurrent_sites.json` is
tracked and survives, but the code does not read it from there.

**The three-year history is lost and cannot be rebuilt from NRT.** `detections.parquet` holds
1,078 rows going back three years. The NRT endpoints do not reach back that far; the archive
(`*_SP`) does, but re-deriving history on every run is both slow and a different provenance
story from the one `run_manifest.json` records.

**Provenance goes with it.** The three-state "observed / no detections / fetch failed"
distinction depends on `run_manifest.json`. Losing it turns a failed fetch into a silent zero,
which AGENTS.md rule 2 forbids.

**Required: make the store durable by tracking it.** The sizes make this the obvious choice —
`detections.parquet` is 114 KB, `run_manifest.json` 140 KB, `recurrent_sites.json` 941 B, and
all 851 FIRMS raw CSVs together are 198 KB. That is less than the already-tracked
`docs/data/hotspots_latest.geojson`.

Narrow the ignore rules so these four are tracked, and commit them in this task. Keep ignoring
`data/raw/himawari/` (239 MB) and `data/processed/himawari_evening_*.parquet`.

Tracking the raw FIRMS responses also makes the pipeline re-derivable from source and gives
AGENTS.md rule 2 a durable meaning rather than a per-run one.

If you think a different persistence mechanism is better, say so in your report and build this
one anyway. Do not use `actions/cache`: cache entries are evicted and this data is not
reconstructible.

## 2. The workflow

Trigger on `schedule` and on `workflow_dispatch` — never on `push`, or the job's own commit
retriggers it. Add a `concurrency` group so two runs cannot overlap.

**Schedule: `30 16 * * *` (16:30 UTC).** A WIT day ends at 15:00 UTC. The last VIIRS overpass
of that day is around 04:30 UTC and FIRMS NRT latency is roughly three hours, so everything is
in well before 16:30. Actions cron fires late under load; the margin absorbs it.

Steps, in order:

1. Checkout, set up Python, install dependencies.
2. `python src/ingest_firms.py` — key from `secrets.FIRMS_MAP_KEY`.
3. `python src/report_daily.py`
4. `python -m pytest tests -q` — must pass before anything is committed.
5. Commit and push only the generated outputs, and only if they changed.

**Do not pass `--allow-stale`.** That flag exists for deliberate regeneration by a human. In a
cron job it disables the guard permanently and republishes old data as current, which is the
one failure PLAN.md 9.6 names explicitly.

**Check what `report_daily.py` defaults to for `--day`** before deciding whether to pass it. If
the default does not resolve to the WIT day that just closed, pass it explicitly and say in
your report what you found. Do not guess.

Set `core.hooksPath` to `.githooks` so the pre-commit credential check runs in CI too.

## 3. Failing correctly

PLAN.md 9.6: *"If the scheduled job fails, the previous data remains published and the page
shows its real age rather than silently presenting old data as current."*

So a failed run must commit nothing. Not a partial store, not a brief built from an incomplete
fetch. The existing exit codes already distinguish these cases — `ingest_firms.py` exits
non-zero when every fetch fails, and `report_daily.py` refuses on stale input. Let them fail
the job. Do not add `continue-on-error`, do not swallow a non-zero exit, and do not add a retry
loop around the fetch.

A failed run should be visible. A red X on the Actions tab is sufficient; do not add
notification services.

## 4. Himawari is not in this workflow

`src/himawari.py` downloads roughly 200 MB per evening and its window closes at 01:00 WIT, a
different schedule entirely. Keep it manual for now.

Confirm that the brief's evening section degrades honestly when no
`himawari_evening_*.parquet` exists for the day — it should already, from task 06's three-state
requirement. If it does not, report that; do not fix it here.

## 5. Secrets

`FIRMS_MAP_KEY` goes in repository Actions secrets. Nothing else is needed — Himawari is
anonymous and the Earth Engine credential in PLAN.md 9.6 belongs to a later phase.

## The checks

1. A fresh clone of the repository contains `detections.parquet`, `run_manifest.json`,
   `data/processed/recurrent_sites.json`, and the FIRMS raw CSVs.
2. Running `src/recurrence.py` against that fresh clone produces R001, R002, R003 with the
   same centroids as `docs/data/recurrent_sites.json` today — the IDs do not renumber.
3. The workflow commits nothing when the ingest fails. Prove it with a deliberately bad key.
4. The workflow commits nothing when nothing changed.
5. `--allow-stale` appears nowhere in the workflow.
6. The pre-commit hook runs in CI.
7. The existing 75 tests still pass.

## Out of scope

Himawari scheduling, Earth Engine, `scripts/render_check.py` in CI, notifications, retries,
matrix builds, caching Python dependencies, enabling Pages, any change to `src/` beyond what
check 2 requires. No new dependencies.

## Before you finish

Name every decision this task did not specify, per AGENTS.md. State explicitly what
`report_daily.py --day` defaults to and whether you had to override it.
