"""Measure the Task 18 burned-area product against the hand labels.

    python scripts/label_accuracy.py

Writes data/processed/label_accuracy.json.

**Two strata, both of which carry area.** The area under test is the part of
the event footprints that the interpreter can see, split by what the map says:

  A  mapped by dNBR+              sampled by `map_burned`, points drawn inside
                                  the polygons
  B  inside a footprint, unmapped sampled by two designs: the `random_box`
                                  points that fell inside a footprint on
                                  ground the map does not claim, and the
                                  `footprint_unmapped` boxes drawn by area
                                  alone (Task 23). How many came from each is
                                  reported beside the stratum.

Burned area is `A * p_A + B * p_B`, and the interval has to carry both terms.
An earlier version reported only the first, which made the map look wrong by a
quarter; with stratum B included the map's own figure sits inside the interval.
Zero of ten is not zero: its 95% upper bound is 28%, and 28% of 813 ha is 226 ha.

Boxes outside the footprints are counted and reported but carry no area here:
their stratum has no defined area short of the whole island, and nothing in this
sample supports extrapolating to it.

The weights are the areas the strata actually cover: land inside the S2DR4 1 m
imagery, because a box the interpreter cannot see is not a sample unit. The
ground excluded from the frame is reported, not silently folded in.

Intervals are Wilson score intervals at 95%, which behave at zero successes
where the normal approximation collapses to a point. The estimator published
in Olofsson et al. 2014 uses the normal approximation instead, and is reported
beside the Wilson one because the two disagree about whether the map's own
figure is inside the interval (F23). At 0 of 10 the normal approximation
reports zero variance for a stratum carrying half the area, so the Wilson
version is the one to quote.
"""
from __future__ import annotations

import json
import sys
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

GPKG = ROOT / "data/labels/biak_labels.gpkg"
BURNED = ROOT / "data/processed/burned_areas.geojson"
EVENTS_JSON = ROOT / "data/processed/events.json"
STORE = ROOT / "data/processed/detections.parquet"
OUT = ROOT / "data/processed/label_accuracy.json"
EVENTS = ("E0301", "E0313", "E0368")      # the events that have 1 m imagery
UTM = "EPSG:32753"
FOOTPRINT_M = 375.0                        # one VIIRS pixel, as Task 18 uses
Z = 1.96


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p, d = k / n, 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def olofsson(areas, counts):
    """The stratified estimator of Olofsson et al. 2014, Eqs. 9 to 11.

    areas and counts are per stratum: area in ha, and (burned, judged).
    Returns the proportion, its standard error, and the 95% interval in ha.
    """
    total = sum(areas)
    p = var = 0.0
    for a, (k, n) in zip(areas, counts):
        w, pi = a / total, (k / n if n else 0.0)
        p += w * pi
        if n > 1:
            var += w * w * pi * (1 - pi) / (n - 1)
    se = sqrt(var)
    return p, se, (total * (p - Z * se), total * (p + Z * se))


def footprint_union(to_utm):
    """The union of the three events' 375 m footprints, in UTM."""
    import pandas as pd
    from shapely.ops import transform as shp_transform, unary_union
    import events as ev
    import burned_area_gee as ba

    doc = json.loads(EVENTS_JSON.read_text(encoding="utf-8"))
    membership = ev.membership(doc)
    store = pd.read_parquet(STORE)
    parts = []
    for eid in EVENTS:
        ids = [d for d, e in membership.items() if e == eid]
        pts = store[store.detection_id.isin(ids)]
        geo, _ = ba.footprint(pts.latitude.tolist(), pts.longitude.tolist(), FOOTPRINT_M)
        parts.append(shp_transform(to_utm, geo))
    return unary_union(parts)


def land_union():
    """Desa boundaries for Biak Numfor and Supiori, in degrees."""
    from shapely.geometry import shape
    from shapely.ops import unary_union
    return unary_union([shape(f["geometry"]) for f in json.loads(
        (ROOT / "data/boundaries/biak_desa.geojson").read_text(
            encoding="utf-8"))["features"]])


def imagery_union():
    """The S2DR4 1 m chips' rectangles, in UTM: what the interpreter can see."""
    import rasterio
    from shapely.geometry import box
    from shapely.ops import unary_union
    tiles = []
    for eid in EVENTS:
        path = ROOT / f"data/labels/imagery/{eid}_swir.tif"
        if not path.exists():
            raise SystemExit(f"missing imagery {path} - run scripts/label_prepare.py")
        with rasterio.open(path) as r:
            tiles.append(box(*r.bounds))
    return unary_union(tiles)


def stratum_areas(to_utm, mapped, footprints):
    """The areas the estimator weights by, in ha.

    Both frames are clipped to land inside the S2DR4 1 m chips: that is where
    boxes can be drawn and judged, so it is the ground the sample speaks for.
    scripts/label_add_boxes.py draws from these same frames; the ground left
    out is returned so it can be reported rather than quietly counted.
    """
    from shapely.ops import transform as shp_transform
    land = shp_transform(to_utm, land_union()).intersection(imagery_union())
    area_A = mapped.intersection(land).area / 1e4
    unmapped = footprints.difference(mapped)
    area_B = unmapped.intersection(land).area / 1e4
    return area_A, area_B, unmapped.difference(land).area / 1e4


def stratum_frames(judged):
    """The four design groups of judged boxes, as pandas frames.

    Stratum membership follows the draw, not the box: every map_burned box was
    drawn from a point inside the polygons, so all of them belong to A even
    where the 60 m box overruns the polygon edge; every footprint_unmapped box
    was drawn from a point outside them, so all of them belong to B. Filtering
    either by how much of the box the polygons cover would drop exactly the
    edge cases the assessment is about, in the direction that flatters the map.

    Kept out of main() so the rule can be checked with pandas alone - no
    geopandas, and no GeoPackage, is needed to test it.
    """
    a = judged[judged.sampling == "map_burned"]
    b_random = judged[(judged.sampling == "random_box") & (judged.map_share < 0.5)
                      & judged.in_footprint]
    b_plain = judged[judged.sampling == "footprint_unmapped"]
    out_fp = judged[(judged.sampling == "random_box") & ~judged.in_footprint]
    return a, b_random, b_plain, out_fp


def main() -> int:
    import geopandas as gpd
    import pandas as pd
    from pyproj import Transformer
    from shapely.ops import unary_union

    to_utm = Transformer.from_crs("EPSG:4326", UTM, always_xy=True).transform

    labels = gpd.read_file(GPKG, layer="labels").to_crs(UTM)
    burned = gpd.read_file(BURNED).to_crs(UTM)
    burned = burned[burned.event_id.isin(EVENTS)]
    mapped = unary_union(burned.geometry.tolist())
    fp = footprint_union(to_utm)

    area_A, area_B, area_off = stratum_areas(to_utm, mapped, fp)
    area_fp = area_A + area_B

    # A box with no class has not been judged yet and is not a zero. Counting
    # it would move every rate in the file, in the direction that flatters the
    # map. Only `burned` and `unburned` are judgements; `unsure` is an answer
    # that carries no class and is dropped, and both are reported.
    unjudged = labels[labels["class"].isna()]
    judged = labels[labels["class"].isin(("burned", "unburned"))].copy()
    judged["map_share"] = [float(burned.intersection(g).area.sum() / g.area)
                           for g in judged.geometry]
    judged["in_footprint"] = [fp.intersects(g.centroid) for g in judged.geometry]

    # Stratum A is sampled by map_burned alone; stratum B by two designs, the
    # `random_box` points that fell inside a footprint outside the polygons and
    # the Task 23 `footprint_unmapped` boxes drawn from that frame by area
    # alone. A design is only used for the stratum it drew for; the rule and
    # its reasons live on stratum_frames().
    a, b_random, b_plain, out_fp = stratum_frames(judged)
    b = pd.concat([b_random, b_plain])

    kA, nA = int((a["class"] == "burned").sum()), len(a)
    kB, nB = int((b["class"] == "burned").sum()), len(b)
    kB1, nB1 = int((b_random["class"] == "burned").sum()), len(b_random)
    kB2, nB2 = int((b_plain["class"] == "burned").sum()), len(b_plain)
    kO, nO = int((out_fp["class"] == "burned").sum()), len(out_fp)
    pA, pB = (kA / nA if nA else 0.0), (kB / nB if nB else 0.0)
    loA, hiA = wilson(kA, nA)
    loB, hiB = wilson(kB, nB)
    loO, hiO = wilson(kO, nO)

    pO, seO, ciO = olofsson([area_A, area_B], [(kA, nA), (kB, nB)])
    _olof = {
        "note": ("Eqs. 9 to 11 of Olofsson et al. 2014, which use the normal "
                 "approximation. At 0 of 10 that gives stratum B zero variance "
                 "although it carries half the area, so this interval is "
                 "narrower than the sample supports. F23 says to quote the "
                 "Wilson one above."),
        "estimate_ha": round((area_A + area_B) * pO, 1),
        "se_ha": round((area_A + area_B) * seO, 1),
        "ci95": [round(ciO[0], 1), round(ciO[1], 1)],
    }

    doc = {
        "what": ("The Task 18 dNBR+ product measured against hand labels on 1 m imagery, "
                 f"over the footprints of {', '.join(EVENTS)}."),
        "areas_ha": {"footprints": round(area_fp, 1), "mapped": round(area_A, 1),
                     "inside_footprint_unmapped": round(area_B, 1),
                     "footprint_off_land_or_imagery": round(area_off, 1),
                     "note": ("mapped and unmapped are land inside the S2DR4 1 m "
                              "imagery, which is where boxes can be judged")},
        "strata": {
            "A_mapped": {"sample": "map_burned", "burned": kA, "judged": nA,
                         "rate": round(pA, 3), "ci95": [round(loA, 3), round(hiA, 3)],
                         "area_ha": round(area_A, 1)},
            "B_unmapped_in_footprint": {
                "sample": "random_box and footprint_unmapped",
                "burned": kB, "judged": nB, "rate": round(pB, 3),
                "ci95": [round(loB, 3), round(hiB, 3)],
                "area_ha": round(area_B, 1),
                "designs": {
                    "random_box": {"burned": kB1, "judged": nB1},
                    "footprint_unmapped": {"burned": kB2, "judged": nB2},
                },
            },
        },
        "burned_area_ha": {
            "estimate": round(area_A * pA + area_B * pB, 1),
            "ci95": [round(area_A * loA + area_B * loB, 1),
                     round(area_A * hiA + area_B * hiB, 1)],
            "mapped": round(area_A, 1),
            "commission_term_only": {
                "estimate": round(area_A * pA, 1),
                "ci95": [round(area_A * loA, 1), round(area_A * hiA, 1)],
            },
            "omission_term_only": {
                "estimate": round(area_B * pB, 1),
                "ci95": [round(area_B * loB, 1), round(area_B * hiB, 1)],
            },
        },
        "olofsson_2014": _olof,
        "outside_footprints": {"burned": kO, "judged": nO,
                               "rate": round(kO / nO, 3) if nO else None,
                               "ci95": [round(loO, 3), round(hiO, 3)],
                               "note": "counted only; this stratum carries no area here"},
        "unsure_dropped": int((labels["class"] == "unsure").sum()),
        "unjudged_boxes": {
            "total": int(len(unjudged)),
            "by_stratum": {str(k): int(v) for k, v in
                           unjudged["sampling"].value_counts().sort_index().items()},
            "note": ("boxes drawn but not yet judged; not counted as unburned "
                     "anywhere in this file"),
        },
        "caveats": [
            ("The reference is one interpreter's reading of S2DR4 1 m imagery, which is "
             "model output rather than observation. These are agreement figures, not "
             "accuracy against the ground."),
            (f"Stratum B holds {nB} judged boxes. Published good practice for map accuracy "
             "assessment asks for 50 to 100 per stratum, so the interval is wide enough "
             "that whether the map's own figure sits inside it is decided by the "
             "estimator, not by the sample."),
            ("The estimate covers the footprints of three events of August 2026, not the "
             "23 events F11 reports, and not the island."),
            ("Boxes are 60 m and the product is 20 m, so a box can hold both classes; "
             "those were judged by majority and the doubtful ones marked unsure."),
        ],
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")

    A, B = doc["strata"]["A_mapped"], doc["strata"]["B_unmapped_in_footprint"]
    ba_ = doc["burned_area_ha"]
    print(f"footprints {area_fp:.0f} ha = mapped {area_A:.0f} ha + unmapped {area_B:.0f} ha")
    print(f"A mapped    {A['burned']}/{A['judged']} burned = {A['rate']:.0%}"
          f"  CI {A['ci95'][0]:.0%} to {A['ci95'][1]:.0%}")
    print(f"B unmapped  {B['burned']}/{B['judged']} burned = {B['rate']:.0%}"
          f"  CI {B['ci95'][0]:.0%} to {B['ci95'][1]:.0%}"
          f"  ({kB1}/{nB1} random_box + {kB2}/{nB2} footprint_unmapped)")
    print(f"  frame off land or imagery and carrying no area: {area_off:.0f} ha")
    print(f"  unjudged boxes, counted nowhere: {len(unjudged)} "
          f"{doc['unjudged_boxes']['by_stratum']}")
    print(f"\nburned area {ba_['estimate']:.0f} ha  95% CI {ba_['ci95'][0]:.0f} "
          f"to {ba_['ci95'][1]:.0f} ha")
    inside = ba_["ci95"][0] <= area_A <= ba_["ci95"][1]
    print(f"the map claims {area_A:.0f} ha, which is "
          f"{'inside' if inside else 'outside'} that interval")
    print(f"  commission term {ba_['commission_term_only']['estimate']:.0f} ha "
          f"CI {ba_['commission_term_only']['ci95'][0]:.0f} to "
          f"{ba_['commission_term_only']['ci95'][1]:.0f}")
    print(f"  omission term   {ba_['omission_term_only']['estimate']:.0f} ha "
          f"CI {ba_['omission_term_only']['ci95'][0]:.0f} to "
          f"{ba_['omission_term_only']['ci95'][1]:.0f}")
    o_in = _olof["ci95"][0] <= area_A <= _olof["ci95"][1]
    print(f"\nOlofsson 2014 normal approximation {_olof['estimate_ha']:.0f} ha "
          f"CI {_olof['ci95'][0]:.0f} to {_olof['ci95'][1]:.0f} ha, "
          f"which puts the map's {area_A:.0f} ha "
          f"{'inside' if o_in else 'outside'} (F23)")
    print(f"\nwritten {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
