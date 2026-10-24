# Administrative boundaries follow SNI 6502.2:2010

The desa layer was a plain grey hairline, which says "there is an edge here"
and nothing else: not which level of government the edge belongs to, and not
that the edge is unofficial. The project owner asked for BIG symbolisation
instead.

The rule is in SNI 6502.2:2010, *Spesifikasi penyajian peta rupa bumi skala
1:25.000*, Lampiran A table e) "Batas administratif", read from the standard
itself rather than from a secondary description of it. All five levels are
black, CMYK 0/0/0/100, type Garis. The three this project needs:

| Level | Weight | Pattern |
|---|---|---|
| Batas kabupaten/kota | 0,3 mm | dash 3,0, gap 1,0, dot, gap 0,4, dot |
| Batas kecamatan | 0,2 mm | dash 2,0, gap 0,5, four dots at 0,2 |
| Batas kelurahan/desa | 0,2 mm | dash 3,0, gap 0,8, three dots at 0,2 |

MapLibre measures `line-dasharray` in multiples of the line width, so each
pattern is its millimetres divided by that level's weight. A screen has no
millimetres: the weights here keep the standard's ratios at a legible size and
do not claim a printed scale.

## A shared edge is drawn once

Section 6.3 of the same standard: where the boundaries of two levels coincide,
the lower level is not drawn. `export_vector_layers.py` therefore subtracts
every higher level from each lower one before writing. Every higher level, not
only the one immediately above: a desa in the middle of a distrik still meets
the sea, and that edge is the kabupaten boundary without being a distrik
boundary. Of 29.4 degrees of raw desa boundary, 10.7 survive as desa lines.

## The two things the page has to say

**These lines are not an official reference.** Section 6.3 says so in as many
words, about the rupabumi map itself. The methodology page repeats it and the
popup on every boundary repeats it again. Nothing here settles where a
boundary runs.

**The kabupaten line is the coast.** Biak Numfor and Supiori are separate
islands and share no land edge, so that layer is the shoreline the basemap
already draws. It is published, because it is correct, and switched off by
default, because drawing it only doubles the coast.
