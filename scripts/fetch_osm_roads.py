"""Fetch the road network for the AOI from OpenStreetMap, once.

    python scripts/fetch_osm_roads.py [--out PATH] [--timeout S]

Writes a compact GeoJSON of LineStrings carrying one property, `highway`.
The output is tracked, so src/fieldwork_gpkg.py and the tests read it offline
(AGENTS always-4). Re-run this only when the road network is worth
refreshing; it is not part of any daily or cron path.

Data: (c) OpenStreetMap contributors, ODbL. Cite it wherever the derived
road distances are published.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OVERPASS = "https://overpass-api.de/api/interpreter"

# Everything with a highway tag except the classes that are not ground you
# can stand on: a proposed road does not exist yet and a raceway is not
# access. Footways and paths are kept - the surveyor walks the last stretch,
# and which classes count as reachable is decided at use time, not here.
SKIP = {"proposed", "construction", "raceway", "corridor", "elevator"}

QUERY = """
[out:json][timeout:{timeout}];
way["highway"]({south},{west},{north},{east});
out geom;
"""


def fetch(bbox_wsen, timeout):
    west, south, east, north = bbox_wsen
    q = QUERY.format(timeout=timeout, west=west, south=south,
                     east=east, north=north)
    req = urllib.request.Request(
        OVERPASS, data=q.encode("utf-8"),
        headers={"User-Agent": "biak-hotspot (github.com/daniel-sb/biak-hotspot)"})
    with urllib.request.urlopen(req, timeout=timeout + 60) as r:
        body = r.read()
    # AGENTS never-2: an empty answer and a failed request are different
    # facts. Overpass answers 200 with an empty element list when it is
    # overloaded, so an empty result is refused rather than written.
    elements = json.loads(body).get("elements", [])
    if not elements:
        raise SystemExit("Overpass returned no ways - refusing to write an "
                         "empty road file; try again later")
    return elements


def to_features(elements):
    out = []
    for e in elements:
        cls = e.get("tags", {}).get("highway")
        geom = e.get("geometry")
        if cls in SKIP or not geom or len(geom) < 2:
            continue
        coords = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom]
        out.append({"type": "Feature", "properties": {"highway": cls},
                    "geometry": {"type": "LineString", "coordinates": coords}})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    out = args.out or ROOT / cfg["road_lines"]

    elements = fetch(cfg["aoi_bbox_wsen"], args.timeout)
    feats = to_features(elements)
    print("{} ways fetched, {} kept".format(len(elements), len(feats)))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"type": "FeatureCollection",
         "attribution": "(c) OpenStreetMap contributors, ODbL",
         "features": feats}, separators=(",", ":")), encoding="utf-8")
    print("wrote {} ({:.0f} KB)".format(out, out.stat().st_size / 1024))


if __name__ == "__main__":
    main()
