# Working rules for this repository

Read this before every task. It is short on purpose — obey all of it.

`PLAN.md` is the project reference. **Do not implement it end to end.** You will be given one
scoped task at a time from `tasks/`. Build exactly that task. If you notice something else
that needs doing, write one line about it in your final message; do not build it.

## Never do these

1. **Never write a secret into a tracked file.** Keys come from `os.environ` only. A
   pre-commit hook blocks credentials and it will reject your commit.
2. **Never report a failed fetch as zero results.** An empty response and a failed request are
   different facts and must stay distinguishable in stored output and in exit codes.
3. **Never cast the FIRMS `confidence` column to a number.** VIIRS returns `l`/`n`/`h` and
   MODIS returns 0–100 in the same column. Casting silently discards most rows.
4. **Never drop the `frp` column.** Fire Radiative Power is the intensity measure and most of
   the analytical value.
5. **Never delete rows during quality control.** Add a boolean flag column instead. Filters
   must be reversible and auditable.
6. **Never edit `PLAN.md`.** It is the human-maintained spec.
7. **Never add a dependency for what the standard library does.** Ask in your final message
   if you think one is genuinely needed.

## Always do these

1. **Store timestamps in UTC and derive a WIT (UTC+9) column.** Daily aggregations are on WIT
   local days. Getting this wrong shifts night detections into the wrong day.
2. **Persist raw API responses before parsing**, under `data/raw/`. Re-parsing is free;
   re-fetching expired near-real-time data is not.
3. **Leave one runnable check** per non-trivial module: an `assert`-based `demo()` under
   `if __name__ == "__main__"`, or one `test_*.py`. No test frameworks beyond `pytest`, no
   fixtures directory, no per-function suites.
4. **Use the committed fixtures in `data/raw/` for tests.** They are real FIRMS responses from
   2026-08-13 to 2026-08-27. Tests must not hit the network.
5. **Read values from `config.yaml`.** No hard-coded coordinates, dates, thresholds, or paths.

## Style

Small, boring, obvious code. Prefer the shortest thing that works and is correct on edge
cases. No abstraction with one implementation, no configuration for a value that never
changes, no scaffolding for phases you have not been asked to build.

## When you finish

State in your final message: what you built, what you deliberately did not build, how to run
the check, and anything you are unsure about. Do not claim something works unless you ran it.

**Name every decision the task did not specify.** If you had to choose a file name, a default
value, an ordering, or the handling of an edge case the task was silent about, say so
explicitly rather than picking one quietly. Across tasks 01 and 02, every defect found in
review lived in a decision the task left open — none came from a misread instruction. Surfacing
those choices is the single most useful thing your final message can do.
