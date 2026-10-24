# The instruments are dark and the map is light

Asked what the reasoning behind the palette was, the honest answer was that it
had one — karst for Biak's raised coral, canopy for standing forest, scar for
the burn, ember for the shortwave response, sea for Cenderawasih Bay — and
that the reasoning had produced a page where every surface was light. The
figures, the layer panel and the map were all pale, so nothing told a reader
where to look, and the one element that genuinely has to be light, a map with
a light basemap under it, had no contrast against its own chrome.

So the surfaces split. The map stays light. Everything that reads it is dark:
the right-hand figures and the layer panel inside the map frame. That is the
arrangement of the AICC dashboard this work started from, and it is why the
figures stop competing with the map for attention.

## The dark steps

Selected against the dark surface rather than flipped from the light palette,
and measured rather than eyeballed:

| Token | Hex | On `night` |
|---|---|---|
| `night` | `#16201d` | the instrument surface |
| `night-line` | `#2f3e39` | dividers and control borders |
| `night-ink` | `#e7e9e4` | 13.6:1 |
| `night-soft` | `#9aa69f` | 6.6:1 |
| `flame` | `#e2714a` | 5.3:1 |

`flame` exists because `scar` (`#a3341f`) is too dark to sit on `night` at
all. It is the same hue a step up, not a second accent.

## What stays light, and why

The error banner above the map. It sits on the page ground rather than on an
instrument, and it is the one element whose job is to interrupt: a reader who
has stopped looking at the dark panels must still see that a file failed to
load.
