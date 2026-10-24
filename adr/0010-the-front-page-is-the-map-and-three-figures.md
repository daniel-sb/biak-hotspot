# The front page is the map and three figures, and the brief has its own page

The first rebuild moved the existing panels onto their pages but left the front
page leading with the daily brief and the previous evening's Himawari result.
Reviewing it, the project owner asked for the AICC shape instead: the map, the
season's headline numbers, and a pointer to the methodology and results pages.

The brief and the evening product therefore move to `brief.html`. That
completes ADR 0001 rather than contradicting it: both are present tense, and
ADR 0001 said the front page is a record of the 2026 season with the current
state reduced to a status strip. Leaving the brief on the front page was the
part of that decision we had not actually carried out.

`index.html` now carries the ethics statement, the status strip, three figure
tiles, the observation-gap note, and the map with its layer switch and legend.

## Two area figures, not one

The front page publishes both burned-area numbers side by side, with each
one's scope attached, because they are not alternative answers to one question:

- **Mapped extent**, 2,179 ha across the season's assessed events. A product
  output. It has no interval, and events the product could not assess carry no
  area and are excluded rather than counted as zero.
- **Estimated burned**, 1,230 ha with a 95% interval of 1,060 to 1,342 ha,
  covering the three labelled footprints only, where the product maps 819 ha.

The second is not a correction of the first, because it does not cover the same
ground. Multiplying the season's mapped extent by the ratio between them would
extrapolate from three footprints to twenty-five events, which nobody has
tested, so no code in this repository does that arithmetic and the page says so
in the reader's own words.

The count tile reads "905 in 312": detections inside events. Neither is a count
of fires, and PLAN.md section 8 reserves that word for corroborated episodes.

Every figure is read from `docs/data/headline.json`, written by
`src/headline_figures.py`. None is typed into the markup, so a number on the
page can always be traced to the product behind it.

## Basemaps

Esri World Imagery is added, whose public ArcGIS REST endpoint permits
non-commercial use with attribution. Its note says it is a mosaic of many
dates with no single acquisition date, because a reader comparing an undated
mosaic against a 2026 burn polygon can otherwise read a difference that is
only a difference of years.

Google's satellite tiles were asked for and are deliberately absent. Pulling
them as XYZ outside Google's own APIs breaks their terms, and the licensed
route needs a key, which cannot live in a public static page without breaking
the rule against committing secrets. Esri covers the same need.

Land cover is not yet a layer. The public WorldCover tile service did not
respond from the machine this was built on, which is a failed fetch rather than
an absent service, so the toggle is left out until there is a source that
works rather than shipped as a control that does nothing.
