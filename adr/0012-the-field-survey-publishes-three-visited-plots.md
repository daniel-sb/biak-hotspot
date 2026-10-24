# The field survey publishes three visited plots and nothing else

`fieldwork/biak_ground_truth.gpkg` holds three tables of points: 3 plots a
surveyor visited on 2026-09-03, 281 planned burn targets, and 80 planned
control targets. The brief asked for the survey on the map, with the
photographs in the popup.

Only the three visited plots are published.

The 361 planned targets are a sampling design drawn over named desa in a
populated place. Nobody ever stood on them. A dot on a public map labelled
"burn target" beside somebody's garden is a claim this project cannot support,
and `prioritas`, `n_deteksi` and `frp_maks` on such a dot read as a ranking of
suspicion. They stay in the repository and out of `docs/`.

The three visited plots are the opposite: the surveyor stood there, recorded
what the ground looked like, and photographed it. All three were read as
`bakar` with confidence `pasti`, on the evidence of charcoal, ash and a charred
stem. That is the only ground truth this project has, and the popup says what
it cannot do: three plots cannot validate a map of the island; they say what
the ground looked like at three points, eleven days after the detections
stopped.

## The photographs

Three frames, one per plot, showing burned scrub, char and smoke. No people, no
buildings, no vehicles and no number plates appear in any of them, which was
checked before they went up.

EXIF is stripped on export. A phone photograph carries GPS to a few metres, the
device identifier and the exact second; the plot's own coordinate is already
published beside it at the accuracy the surveyor recorded, so the metadata adds
nothing a reader needs and carries things they should not get by accident.

## Consequences

This sits on the same side of ADR 0006 as the interpretation boxes in ADR 0009:
an observation of ground state, published at native resolution, with its limits
attached. It is a narrower claim than either, because three points is less than
142 boxes.
