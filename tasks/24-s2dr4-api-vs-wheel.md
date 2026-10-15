# Task 24 — Does the credited API reproduce the imagery the labels were judged on?

Every 1 m chip in `data/labels/imagery/` came from one route: the
`s2dr4-20260126.1-cp312` wheel, run on Colab's free scene tier in
`notebooks/s2dr4_biak_colab.ipynb`. The 142 label boxes were judged on those
chips, and F20 to F23 rest on those labels. The owner now holds a Gamma Earth
balance of **6,085 credits** on the academic researcher tier, and a second route exists: the REST API.

**The question is whether the two routes give the same pixels.** If they do, the
labels and every figure resting on them are route-independent, and the API
becomes the way to reach ground the free tier cannot. If they do not, that is a
caveat the write-up has to carry, and this task measures how large it is.

This changes no published figure. It does not touch `docs/`, the brief or the
cron, and it does not re-judge a single box.

## What the documentation says the routes differ in

Read on 2026-10-15 from gamma.earth and help.gamma.earth.

| | wheel, as the project ran it | REST API v1.0 |
|---|---|---|
| unit of work | fixed 4100 x 4100 px tile at 1 m = **16.81 km²**, centred on a point | `aoi` bounding box, `minx miny maxx maxy`, up to 150 km² |
| date | requested date is **silently substituted**. Asking 23 Aug returned 25 Aug on all three tiles; asking 20 Aug returned 23 Aug. Undocumented, notebook section 7c | `date_range` defaults to **7**, so a request that omits it searches a week back and substitutes too. Sending `date_range: 0` asks for the date itself, and even then the catalogue may return up to three days after it. Check the returned `date` |
| cost | free scene tier, 20 scenes | bills the balance, per area per date. Reprocessing a date already run is free |
| provenance | a hashed tile id in the path, nothing citable | `job_id` and `pid` returned, and a job row in the dashboard |
| credential | none | `GE_API_KEY`, in the URL path |
| model | S2DR4. Output is named `S2L3Ax10_*` | **S2DR3**, output `S2L2Ax10_*` |

**The model row is settled, and it settles the task.** REST API v1.1, read
2026-10-15, documents S2DR3 and `S2L2Ax10_*`; S2DR4 is reached only through its
own wheel, which needs a CUDA GPU. So this is a comparison of two models and not
of two routes, and it has to be reported as that. The newer S2DR4 wheel
(`s2dr4-20261014.1-cp313`) now spends credits too, which makes it, and not this
API, the route to more 1 m imagery of the kind the labels were judged on.

## The budget

**The academic application was granted on 2026-10-15**: the dashboard reads
**6,085 credits** on the RESEARCHER tier, against the 85 it held before. In
Region C, where Biak falls, that is roughly 12,000 km² — about 720 wheel-sized
tiles, where the old balance was five. The nine km² this task spends is now
noise, and the constraint it was written around is gone.

What the grant costs: non-commercial research and teaching only, no resale, and
a citation of Akhtman 2023 in anything published from it. That citation is a
condition of use, not a courtesy, and it belongs in the write-up.

## What to build

### 0. Where this runs

**On the laptop, not in Colab.** The wheel needed Colab for its CUDA GPU; the
API does the processing on Gamma Earth's side, so the client is two HTTP calls
and a download. `scripts/s2dr4_api.py` is that client: standard library only,
`GE_API_KEY` from the environment or `.env`, and it sends nothing without
`--submit`.

### 1. A probe, before anything else

First, the free call. It proves the key works and reserves nothing:

```
python scripts/s2dr4_api.py --balance
```

Then one small AOI, one date, on an event already covered by the wheel. It
answers the questions no document does: what it bills for a 1 km² request, which
scene date comes back for `date_range: 0`, and whether the output naming is the
documented `S2L2Ax10_*`.

```
python scripts/s2dr4_api.py --label probe --date 2026-08-28     --aoi "136.035105 -1.138913 136.044089 -1.129864" --submit     # 1 km2
```

Report the job's `state`, the returned `pid`, the file names, and the balance
before and after. **If the billed area does not match the requested area, stop
and say so** — every number below assumes it does.

### 2. The comparison itself

A 2 km box on the same event and date, well inside the wheel tile:

```
python scripts/s2dr4_api.py --label compare --date 2026-08-28     --aoi "136.030613 -1.143438 136.048581 -1.125340" --submit     # 4 km2
```

The wheel's file for that ground is

```
data/raw/s2dr4_biak_2026-08-28/output/ID/T53MPU/T53MPU-0c59f172e/S2L3Ax10_T53MPU-0c59f172e-20260828_MS.tif
```

Then run what is already written:

```
python scripts/s2dr4_compare.py <wheel MS> <api MS> --json data/processed/s2dr4_route_compare.json
```

It reports the overlap, the per-band median difference and RMSE as a percentage
of the band's own 2nd-to-98th percentile span, the share of pixels that are
identical, and whether either file has its bands in a different order. Band
order is tested rather than assumed, because F19 found S2DR4 writes
**B2 B3 B4 B8 B5 B6 B7 B11 B12 B8A** and labels none of them, which is how F18
came to publish a near-infrared composite it called SWIR.

Say in the final message which of these the numbers support:

- **the same pixels** — identical share near 100%, RMSE near zero. The labels are
  route-independent and the API is simply a wider door to the same imagery;
- **the same model, differently tiled** — RMSE a few percent of the band span,
  no band permutation. Edge effects and tiling, and the labels stand with a
  sentence saying so;
- **a different product** — RMSE in the tens of percent, or a band permutation.
  The reference imagery is route-specific, and that is a finding.

For scale, the wheel's own 23 August against its 28 August over the same ground
runs 5% to 19% of the band span. Two routes on **one** date should be far below
that, and anything approaching it means the routes disagree as much as five days
of burning did.

### 3. The date question, only if step 2 says the routes agree

The wheel substitutes dates without saying so, and the API does too unless
`date_range` is pinned to 0. Same 4 km² AOI, `date 2026-08-23`, which is the
date the wheel refused to give, and `--date_range 0`. Read the `date` the
response returns rather than the one that was asked for:

- a 23 August scene comes back — the API honours what the wheel would not, and
  that is the route for any future date, the September 2026 episode included;
- the request fails — the scene is genuinely absent from the catalogue the API
  reads, and the wheel's substitution was it doing the only thing available.

Either answer is worth the 4 km². Do not run this before step 2 has shown the
two routes agree on a date they both have.

## Budget for the whole task

| step | area | running balance |
|---|---|---|
| start | | about 12,000 km² (6,085 credits) |
| 1. probe | 1 km² | 6,084.5 credits |
| 2. comparison | 4 km² | 6,082.5 |
| 3. date question | 4 km² | 6,080.5 |

Nine km², under a tenth of one percent, and the rest stays for the September 2026 episode,
which has no polygon and no area yet.

## Constraints

- **The key comes from `os.environ`**, read from `.env` as `GE_API_KEY`. Never a
  tracked file, never echoed in output or in a log, and never in a URL that gets
  printed — this API puts the key in the path, so a printed URL is a leaked key.
- **Persist the raw response before parsing**, under `data/raw/`, as AGENTS
  always-2 requires. The job metadata is the only record of what was bought.
- **Never report a failed fetch as zero results**, and never fill a missing
  download with anything. If a job fails, say which job and why, and exit
  non-zero. A fabricated chip would move a published figure and leave no trace.
- Do not re-judge, move or re-draw a label box. The 75 unjudged boxes of Task 23
  are untouched by this.
- No new dependency. `rasterio`, `numpy` and the standard library cover it;
  `urllib.request` is enough for two HTTP calls.

## Do not write the finding

As with Tasks 17 and 19 to 23. Put the comparison table, the billed areas and the
date answer in the final message; the entry is written at review.

## Out of scope

- Re-downloading the existing chips through the API. The question is whether the
  routes agree, not whether the project can afford to change route.
- The September 2026 episode. It needs its own task, and this one only
  establishes whether the API is the right way to reach it.
- Changing any figure in F20 to F23.
