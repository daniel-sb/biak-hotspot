# Task 01b — fixes to the FIRMS ingest

Task 01 was reviewed and accepted. The counts are correct, the constraints were honoured, and
the tests are sound. Seven defects were found, all in the caching and time-handling paths.
Fix them in `src/ingest_firms.py`, `config.yaml` and `tests/test_ingest_firms.py`.

Read `AGENTS.md` first. Do not build anything from PLAN.md phases 2 to 6. Do not restructure
code that is not named below.

## 1. Cache filename must encode the day range (high)

`fetch`/cache paths are `data/raw/{SOURCE}_{START}.csv`, which collides across different
lookback windows. Verified:

```
chunk_starts(2026-08-27, 15) -> [('2026-08-13', 5), ('2026-08-18', 5), ('2026-08-23', 5)]
chunk_starts(2026-08-15,  3) -> [('2026-08-13', 3)]
```

Both produce `VIIRS_SNPP_NRT_2026-08-13.csv`. A three-day run followed by a fifteen-day run
makes the second silently ingest two days less than requested, with no warning. For a fire
monitor an undercount means missed fires.

Change the filename to include the day count, for example
`{SOURCE}_{START}_{DAYS}d.csv`. Leave the twelve existing fixtures in `data/raw/` untouched —
they are committed test inputs. Add a short comment saying the old flat names are historical
fixtures and are not written by the current code.

## 2. Cache must expire for recent windows (high)

`if raw_path.exists() and not args.refetch` reuses cached responses forever. FIRMS updates
four to six times per day, so any schedule that runs more than once daily silently serves the
first snapshot of each chunk. `--refetch` is all-or-nothing and re-downloads the whole history,
wasting the rate limit.

Rule: a chunk whose window includes today or yesterday (UTC) is always refetched. A chunk whose
window lies entirely in the past may be served from cache. Keep `--refetch` as a manual
override that forces everything.

## 3. Window end must be UTC, not local (medium)

`date.today()` returns the machine's local date. On a UTC+9 machine it runs ahead of UTC for
nine hours a day, so the requested window ends in the future and FIRMS returns a short result
without raising an error. Use `datetime.now(timezone.utc).date()`.

## 4. Distinguish "fetched" from "served from cache" (medium)

If every network request fails but raw files exist, the run currently exits 0 and logs
"cached", which reads as success. Count fetched and cached separately, log both, and exit
non-zero when the run intended to fetch at least one chunk and fetched none.

## 5. Latitude and longitude should be numeric (low)

`pd.read_csv(dtype=str)` leaves coordinates as strings all the way into the Parquet file.
Convert `latitude` and `longitude` to float in `prepare()`.

**Leave `confidence` as a string.** It carries VIIRS `l`/`n`/`h` and MODIS 0–100 in one column
and must never be coerced. This is unchanged and the existing test for it must keep passing.

## 6. Test the real re-run path (low)

`test_parse_merge_is_idempotent` exercises `merge_tables` in memory only. The path that can
actually break is write Parquet, read back, merge, write again. Add a test using `tmp_path`
that does the full round trip and asserts the row count is unchanged, `detection_id` values are
identical, and `date_wit` values are identical. This currently passes — the point is to keep it
passing.

## 7. Use a fixture with more than one row (low)

`test_parse_merge_is_idempotent` uses `VIIRS_SNPP_NRT_2026-08-13.csv`, which contains a single
detection, so `len(twice) == len(once) > 0` passes trivially. Use
`VIIRS_SNPP_NRT_2026-08-18.csv` (195 detections).

## Acceptance

- All existing tests still pass, unmodified except where item 6 or 7 requires it.
- New tests cover items 1, 2 and 6.
- Item 1 has a test proving two different day ranges with the same start date produce different
  cache paths.
- Item 2 has a test proving a window including today is not served from cache. Do not hit the
  network — inject the current date or the cache-decision function.
- A full parse over the committed fixtures still yields 653 unique detections with the WIT
  daily table from PLAN.md section 10.4 unchanged.
- No new dependencies.
