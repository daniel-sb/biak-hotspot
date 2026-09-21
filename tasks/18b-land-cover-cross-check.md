# Task 18b — Cross-check the burned ground against a tropics-specific land cover

Task 18 reports what the burned ground was the year before using Esri's 10 m annual land
cover. F11 then read "74.8% of the changed area was trees". A check on 2026-09-21 showed
that reading does not survive a second product:

| on F11's changed area | Esri 2025 | JRC TMF Dec 2024 |
|---|---|---|
| trees / undisturbed forest | 70.6% | 15.2% |
| regrowth | - | 23.0% |
| degraded forest | - | 18.0% |
| deforested earlier | - | 16.2% |
| other land | - | 27.5% |

and 29.3% of it had a Hansen tree-cover loss between 2001 and 2025, against 12.1% of the
corridor. Esri's "trees" does not separate forest from regrowth on cleared land; TMF does,
because it was built for exactly that in the humid tropics.

This task adds the second and third products to the per-event record. It does not replace
Esri: the disagreement between products is part of the result, and choosing one silently
would hide it.

## Add, per assessed event

- **JRC Tropical Moist Forest** (`projects/JRC/TMF/v1_2024/AnnualChanges`, Landsat 30 m),
  band `Dec<year>` for the **year before the event, capped at the latest band the asset
  holds** (`tmf_latest_year` in config). Record the year actually used as `tmf_year`, so an
  event read against a map 20 months old says so. Classes: 1 undisturbed, 2 degraded,
  3 deforested, 4 regrowth, 5 water, 6 other. Report `clear_ha_by_tmf` and
  `changed_ha_by_tmf` the way Esri's two tables are reported.
- **Hansen Global Forest Change** (`UMD/hansen/global_forest_change_2025_v1_13`), band
  `lossyear`: `clear_ha_prior_loss` and `changed_ha_prior_loss`, the area whose recorded
  tree-cover loss happened in a calendar year **strictly before** the event's. Same-year
  loss is excluded, because it may be the event itself.

## Caveats to add, verbatim

- "TMF is read for the year before each event, capped at its latest map; tmf_year says
  which year was used. For 2026 events that is December 2024."
- "Hansen loss records tree-cover removal from any cause; prior loss is history, not a
  statement about why land was cleared."

## Check

Extend `tests/test_burned_area.py`: the TMF year rule (2026 event with latest 2024 → 2024;
2024 event → 2023) and the Hansen prior-loss cut-off (a 2026 event counts loss codes up to
25; a 2025 event up to 24).

## Out of scope

Classifying Sentinel-2 ourselves for a 2026 map. It is the only way to a true 2026 land
cover, and it needs labelled training points and validation this project does not have.
