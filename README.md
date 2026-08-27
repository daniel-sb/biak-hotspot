# Biak Hotspot Monitoring

Daily hotspot detection, chronological analysis, postmortem and fire-danger reporting for
Biak, Supiori and Numfor — Papua, Indonesia.

**Read [PLAN.md](PLAN.md) first.** It carries the data sources, the phase plan with
acceptance criteria, verified API access notes, and the publication ethics this project is
built under. Nothing here should be implemented without it.

## Status

Planning. No pipeline code yet. Phase 1 (FIRMS ingest, clip, daily brief) is the next build —
see PLAN.md §3.

## Verified so far

- FIRMS returns usable data for the AOI across four satellite sources (PLAN.md §10.4).
- METAR from WABB is public, half-hourly, unauthenticated, and independently corroborates a
  burning event on 19–25 August 2026 (PLAN.md §10.2).
- No ground air-quality station exists on Biak or anywhere in Papua (PLAN.md §9.5).

## Setup

```sh
cp .env.example .env    # then fill in your keys
git config core.hooksPath .githooks
```

The second command is required after cloning. It enables the pre-commit hook that blocks
credentials from being committed — this repository is public.

## A note on what this publishes

A satellite hotspot is a thermal anomaly. It is not a confirmed fire, and it can never
identify who lit one. Small-scale shifting cultivation is lawful and long-established in
Papua. See PLAN.md §8 before publishing anything derived from this data.
