# The interpretation boxes are published as a map layer

ADR 0006 drew a line between an observation of ground state, which publishes at
native resolution, and a model's inference about a place, which publishes only
as a distrik aggregate. The 142 interpretation boxes sit on the inference side
of that line: each one is one person's reading of 1 m imagery for a 60 m patch
of land in a populated area. Claude raised that before they went on the map.
The project owner, a Biak resident, decided to publish them anyway, because a
layer the reader cannot see is a sampling design they have to take on trust.

They are therefore published, with three limits that cost nothing and remove
most of the risk:

- The free-text `notes` column is not published. Seventy-one of the 142 boxes
  carry notes written during interpretation, about specific patches of land,
  and nothing about a public map needs them. `drawn_on` is dropped for the same
  reason. Only `sample_id`, `event_id`, `sampling`, `class` and `confidence`
  reach `docs/`.
- The layer starts switched off. A reader who wants the sampling design can
  find it; a reader who came for the fire record is not shown a judgement about
  someone's garden by default.
- The popup states what the interpreter read and the limitation around it: that
  no second interpreter checked it, so agreement between interpreters was never
  measured (F24), and that the box is evidence about the product rather than a
  statement about that land or anyone on it. It never renders as a verdict.

## Consequences

This narrows ADR 0006 rather than overturning it. Modelled fuel is still
distrik-aggregated on the public pages, because a fuel class is produced by a
model for every pixel, whereas these boxes are a declared sample whose purpose
is to be audited.
