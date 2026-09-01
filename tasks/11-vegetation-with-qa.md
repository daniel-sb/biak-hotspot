# Task 11 — NDVI and NDMI, published with their composite quality

PLAN.md §2.4 and §14. Read §14 before writing any code. It is short and it is the whole
reason this task is shaped the way it is.

## The situation you are walking into

Task 10 put a drought panel on the dashboard and deliberately left the vegetation indices
off it, because they produce a result that looks like a finding and is not one: **NDVI and
NDMI reached record highs in the driest July on record.** Across 2001–2026 the share of
AOI land pixels passing `SummaryQA <= 1` correlates with July NDVI at r = +0.883 (NDMI from
MOD09A1: +0.591). A dry month is a less cloudy month, so its 16-day composite is built from
more and better observations, while residual cloud depresses the wet years it is compared
against. The index is tracking observation quality.

The owner wants the indices in the product anyway, and that is the right call — but only in
the one form that is honest: **the index and its good-pixel share published together, on the
same chart, sharing an x axis.** A reader must be able to see the confound, not be told
about it in a sentence they can skip.

If you build a panel that shows NDVI without its QA series, you have built the mistake this
task exists to avoid. That is the single thing to get right.

## What to build

### 1. `src/vegetation_gee.py`

Model it on `src/drought_gee.py` — same shape, same conventions, same reasons. Read it
first; do not invent a second pattern.

- Run by hand, not by the daily cron. Earth Engine needs interactive credentials and these
  composites move every 8–16 days. `python src/vegetation_gee.py <google-cloud-project-id>`.
- Read the AOI from `config.yaml` (AGENTS always-5). No hard-coded coordinates.
- Land-mask with `ESA/WorldCover/v200`, class 80 = permanent water, exactly as
  `drought_gee.py` does. The AOI box is mostly ocean; an unmasked mean is a mean of the sea.
- Write `docs/data/vegetation.json`.

Compute, per calendar month from 2001-01 to the last month with data:

- `ndvi` — AOI land mean from `MODIS/061/MOD13A1`. The NDVI band is scaled by 1e-4; apply it.
- `ndvi_good_share` — the fraction of AOI land pixels in that month's composites with
  `SummaryQA <= 1`. This is the number that makes the panel honest. Compute it from the same
  pixels, with the same mask, at the same scale as the index itself; a share computed over a
  different pixel set is not the share of anything.
- `ndmi` — from `MODIS/061/MOD09A1`, `(NIR - SWIR) / (NIR + SWIR)` using `sur_refl_b02`
  (NIR) and `sur_refl_b06` (SWIR), scale 1e-4.
- `ndmi_good_share` — from the MOD09A1 `StateQA` bitfield: bits 0–1 = cloud state, where 0
  is "not cloudy". Use that, and say in a comment which bits you read. Do not reuse the
  MOD13 QA share for NDMI; they are different products with different masks.

Also compute and store, so the panel never hardcodes a number:

- `anomaly` — for each month, the index minus the mean of that **calendar month** across
  2001–2025. PLAN §2.4: absolute NDVI in the humid tropics is high and nearly flat, only the
  departure is informative.
- `qa_correlation` — Pearson r between the index and its good-pixel share, computed two
  ways and stored as both: over all months, and over July only (the month §14 quotes).
  Report the sample size `n` with each. Plain `statistics` and arithmetic; no new dependency
  (AGENTS never-7).
- `coverage` — last date of each collection, and the generation timestamp.

State in the printed output what you found. If the correlations come out materially
different from the ones quoted above, **say so in your final message and do not quietly
overwrite §14** — that is a finding about the earlier computation, not a bug to hide.

### 2. Panel on `docs/index.html`

Below the drought panel, same idiom (`#drought-wrap` shares its CSS with `#timeline-wrap`
via a comma-joined selector; extend that list, do not duplicate the rules).

Plain SVG drawn from the JSON. No chart library. `test_pinned_cdn_only` pins the page to
four hosts and will fail if you add one.

Show, sharing an x axis:

- **NDVI anomaly** and **NDMI anomaly** as lines (departure from the 2001–2025 calendar-month
  mean, so zero is the baseline).
- **Good-pixel share** for each, on its own sub-panel directly beneath, drawn from the same
  months. Not a footnote, not a tooltip — a plotted series a reader sees without asking.
- The correlation from the JSON, written on the panel as text: r, n, and what it means in
  one sentence.

The panel must state, in the page copy, that these indices **do not** support a drought
conclusion for this AOI, and why. Task 10's drought panel already carries a one-sentence
version; reword rather than repeat verbatim, and keep both.

### 3. Constraints that will fail your build if you miss them

- **The word ban.** `tests/test_dashboard.py::test_no_all_clear_wording_in_page` rejects
  "clear" and "safe" as whole words **anywhere in `docs/index.html`, comments included**.
  Writing "a dry month is a clear month" is the obvious phrasing and it will fail. This has
  caught two commits already. Run the test before you commit, not after.
- **Degrade honestly.** A missing or malformed `vegetation.json` produces a stated error in
  the panel's own error div, like `#drought-error` does — never an empty box, never a zero,
  never a hidden panel. Add the filename to the list in
  `test_data_files_referenced_with_error_handling`.
- **No backslash escapes through a shell heredoc.** Writing JavaScript string escapes
  (`\n`) into `docs/index.html` through a heredoc has corrupted this file before: the escape
  became a real newline, the string broke, and the entire page script died with
  `Invalid or unexpected token` while every source-level test still passed. Use the file
  editing tools.
- **Never edit `PLAN.md`** (AGENTS never-6). §14 is the reference for this task; if it needs
  changing, say so in your final message.

## Acceptance criteria

- `python src/vegetation_gee.py <project>` regenerates `docs/data/vegetation.json` and
  prints the series lengths, the coverage dates, and both correlations with their `n`.
- A pytest asserts the JSON's internal consistency: months dense and sorted; every
  `good_share` in [0, 1]; every anomaly equal to its index minus the stored calendar-month
  baseline; the correlations reproduced from the stored series by the test itself, not read
  back from the file it is checking.
- A pytest asserts the page cannot show an index without its QA share — for example, that
  the drawing function references both series, and that the panel's copy contains the
  non-conclusion sentence.
- A `scripts/render_check.py` check asserts the panel draws both the index and the share
  series, and that the correlation text appears with a number in it.
- `python -m pytest tests/` passes. `python scripts/render_check.py` passes.
- One commit, with a message that states what the correlation came out at.

## Out of scope

- Any daily automation of the Earth Engine call.
- Sentinel-2 NDMI. §2.4 lists it and it is a better instrument for this, but it is bound up
  with the Phase 3/4 imagery work and belongs there.
- SPI, KBDI, FWI, or any other index from §2.5. Not this task.
- Removing or rewording the drought panel's existing NDVI sentence beyond what is needed to
  avoid saying the same thing twice.
- Any forward-looking or fire-danger statement (Phase 5).

## When you finish

Follow the AGENTS closing rule: what you built, what you deliberately did not, how to run
the check, and **every decision this task left open** — the QA bit interpretation, the
scale you reduced at, how you handled months with no usable composite, and what you did if
a correlation disagreed with §14.
