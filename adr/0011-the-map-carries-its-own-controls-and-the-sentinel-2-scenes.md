# The map carries its own controls, and the Sentinel-2 scenes it was drawn from

ADR 0010 put the map on the front page with a switch and a legend beside it.
Reviewing that, the project owner asked for an ordinary WebGIS instead: the
layer control inside the map frame, the figures moved off the top of the map
to its right, the view framed on Biak rather than on the whole AOI, and the
Sentinel-2 scenes from `data/labels/biak_labels.qgz` available as layers
rather than only inside QGIS.

## What changed

**The frame.** The map opens on `135.70, -1.34` to `136.42, -0.69`: Biak island
proper, the same box `scripts/render_biak_poster.py` frames its plates with.
The project AOI is 2.5 degrees wide and reaches desa 300 km to the north-west,
and opening on it put the island this page is about in the middle third of the
view.

**The furniture.** The layer switch, the legend, the background-imagery choice
and the scene controls live in one panel inside the map frame. MapLibre's zoom,
compass, fullscreen, geolocate and scale controls are on the map too. On a
viewport narrower than 48 rem the panel starts collapsed, because 17 rem of
panel over a 360 px map is the whole map; a `<details>` cannot be opened by a
media query, so two lines of script do it.

**One identify, not five.** There was a click handler per layer, so a click
where a burn polygon, an interpretation box and a detection overlap opened
three popups stacked on each other. There is now one handler that queries in
order of how specific the layer is — a plot somebody stood on, then a box
somebody interpreted, then a recurrent location, then a detection, then a
polygon covering half a square kilometre — and shows one record.

## The Sentinel-2 scenes

`scripts/export_site_layers.py` warps the 1 m S2DR4 scenes to WGS84 and
publishes them as WebP image sources with their corner quads: three events by
two band combinations by six dates. They are republished at about 3 m per
pixel, because the archive holds 24 to 38 MB per scene and thirty-six of those
do not belong in a git repository.

The true-colour tiles carry one contrast stretch per event, computed across all
six dates together and applied unchanged to each. Unstretched they are a layer
nobody can read: Sentinel-2 true colour over humid tropical forest sits in the
bottom of the byte range. Stretched per date they would be worse than
unstretched, because a burn darkens the frame, a per-date stretch brightens it
straight back, and the dates stop being comparable with each other. The note on
the layer says the stretch was applied. The false-colour tiles are left alone.

`scripts/export_site_layers.py` is deliberately not in the daily workflow. It
reads only inputs that never change, so a scheduled run could only reproduce
the same bytes, and a cron job that rewrites published imagery is what ADR 0003
forbids.

## What is still absent

Google's satellite tiles, for the reasons in ADR 0010. Land cover, because the
public WorldCover tile service still did not answer from the machine this was
built on, which is a failed fetch rather than an absent service.
