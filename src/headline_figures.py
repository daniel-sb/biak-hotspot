"""The front page's headline figures, and the map layers it draws (Task 29b).

Everything on the front page is read from a file this script writes. No figure
is typed into the HTML, so a number on the page can always be traced to the
product that produced it, and a stale page shows a stale generation time rather
than a wrong total.

Two burned-area figures exist and they are NOT the same quantity. Both ship,
each with its scope attached, because a single tile would have to pick one and
would then be wrong about the other:

  mapped      dNBR+ polygons across the season's assessed events. A product
              output. It has no confidence interval, and 8 of the 31 assessed
              events carry status "no local reference" and no area at all.
  validated   the stratified estimate from the interpreted labels, with its
              95% interval. It covers the three labelled footprints ONLY, whose
              mapped extent is a subset of the figure above. Scaling one by the
              other's ratio would be an extrapolation nobody has validated, so
              this script never multiplies them.

Writes, all new files, nothing existing is modified:

    docs/data/headline.json        the figures, with scope strings
    docs/data/burned_areas.geojson the dNBR+ polygons
    docs/data/labels.geojson       the interpreted boxes

The label boxes carry sample_id, event_id, sampling, class and confidence. The
`notes` column is deliberately NOT published: 71 of the 142 boxes carry free
text written during interpretation, about specific patches of land in a
populated area, and PLAN.md section 8 governs what this project puts on a
public page. `drawn_on` is dropped for the same reason.

    python src/headline_figures.py

Self-check, which needs no network and no Earth Engine:

    python src/headline_figures.py --check
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data"
PROC = ROOT / "data" / "processed"

# Published label columns. Everything not listed here stays out of docs/.
LABEL_COLS = ("sample_id", "event_id", "sampling", "class", "confidence")


def load_config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def counts_by_year(store):
    df = pd.read_parquet(store)
    per_year = df.groupby(df["date_wit"].str[:4]).size()
    return {y: int(n) for y, n in per_year.items()}


def events_by_year(path):
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    out = {}
    for e in events:
        y = str(e["first_seen_wit"])[:4]
        out[y] = out.get(y, 0) + 1
    multi = {}
    for e in events:
        if not e["singleton"]:
            y = str(e["first_seen_wit"])[:4]
            multi[y] = multi.get(y, 0) + 1
    return out, multi


def mapped_area(path, year):
    """dNBR+ mapped hectares for one season, and what it could not assess.

    changed_ha is absent on events with status "no local reference". Those are
    counted and reported, never treated as zero: an event the product could not
    assess is not an event with no burning.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in doc["assessed"]
            if str(r["first_seen_wit"]).startswith(year)]
    with_area = [r for r in rows if r.get("changed_ha") is not None]
    return {
        "ha": round(sum(r["changed_ha"] for r in with_area), 1),
        "events_with_area": len(with_area),
        "events_listed": len(rows),
        "events_no_local_reference": len(rows) - len(with_area),
        "scope": (f"dNBR+ polygons across assessed events first seen in {year}. "
                  "A product output, with no confidence interval. Events the "
                  "product could not assess are excluded, not counted as zero."),
    }


def validated_area(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    b = doc["burned_area_ha"]
    return {
        "estimate_ha": b["estimate"],
        "ci95_ha": b["ci95"],
        "mapped_in_footprints_ha": b["mapped"],
        "omission_ha": b["omission_term_only"]["estimate"],
        "strata": {k: {kk: v[kk] for kk in ("area_ha", "judged", "burned",
                                            "rate", "ci95", "sample")}
                   for k, v in doc["strata"].items()},
        "events": doc["what"],
        "scope": ("Stratified estimate from the interpreted 1 m labels, "
                  "covering the three labelled footprints only. Its mapped "
                  "term is a subset of the mapped figure beside it, so the two "
                  "are not alternative answers to one question."),
    }


def gpkg_features(path, table, columns):
    """Read a GeoPackage layer read-only and return GeoJSON features.

    Read-only matters: a read-write connection checkpoints the WAL on close and
    rewrites the main .gpkg underneath QGIS if someone has it open.
    """
    import shapely.wkb
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        cols = ", ".join(f'"{c}"' for c in columns)
        rows = con.execute(f'select geom, {cols} from "{table}"').fetchall()
    finally:
        con.close()
    feats = []
    for row in rows:
        geom = shapely.wkb.loads(gpkg_wkb(row[0]))
        props = dict(zip(columns, row[1:]))
        feats.append({"type": "Feature",
                      "geometry": json.loads(shapely.to_geojson(geom)),
                      "properties": props})
    return feats


def gpkg_wkb(blob):
    """Strip the GeoPackage binary header, leaving plain WKB."""
    flags = blob[3]
    env = (0, 32, 48, 48, 64)[(flags >> 1) & 0x07]
    return blob[8 + env:]


def build():
    cfg = load_config()
    year = str(cfg["season_year"])
    det = counts_by_year(PROC / "detections.parquet")
    ev, ev_multi = events_by_year(PROC / "events.json")

    doc = {
        "season_year": year,
        "generated_utc": datetime.now(timezone.utc)
                                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "detections_by_year": det,
        "events_by_year": ev,
        "events_multi_overpass_by_year": ev_multi,
        "mapped": mapped_area(PROC / "burned_areas.json", year),
        "validated": validated_area(PROC / "label_accuracy.json"),
    }
    (OUT / "headline.json").write_text(
        json.dumps(doc, indent=1) + "\n", encoding="utf-8")

    for src, table, cols, name in (
            (PROC / "burned_areas.geojson", None,
             None, "burned_areas.geojson"),
            (ROOT / "data" / "labels" / "biak_labels.gpkg", "labels",
             LABEL_COLS, "labels.geojson")):
        if table is None:
            (OUT / name).write_text(src.read_text(encoding="utf-8"),
                                    encoding="utf-8")
        else:
            fc = {"type": "FeatureCollection",
                  "generated_utc": doc["generated_utc"],
                  "features": gpkg_features(src, table, cols)}
            (OUT / name).write_text(json.dumps(fc, separators=(",", ":")) + "\n",
                                    encoding="utf-8")

    return [OUT / "headline.json", OUT / "burned_areas.geojson",
            OUT / "labels.geojson"]


def demo():
    cfg = load_config()
    year = str(cfg["season_year"])

    det = counts_by_year(PROC / "detections.parquet")
    assert year in det and det[year] > 0, "no detections in the season year"
    assert len(det) >= 2, "no prior year to compare the season against"

    ev, ev_multi = events_by_year(PROC / "events.json")
    assert ev[year] >= ev_multi[year], "more multi-overpass events than events"

    m = mapped_area(PROC / "burned_areas.json", year)
    assert m["events_listed"] >= m["events_with_area"]
    assert m["events_no_local_reference"] == \
        m["events_listed"] - m["events_with_area"]
    assert m["ha"] > 0

    v = validated_area(PROC / "label_accuracy.json")
    lo, hi = v["ci95_ha"]
    assert lo < v["estimate_ha"] < hi, "estimate outside its own interval"
    # the finding this display exists to show: the product under-maps, so its
    # mapped term sits BELOW the interval rather than inside it (F28, F29)
    assert v["mapped_in_footprints_ha"] < lo, \
        "mapped extent is no longer outside the interval - recheck F28"
    # and the validated scope is a subset of the mapped figure, never a rival
    assert v["mapped_in_footprints_ha"] < m["ha"], \
        "labelled footprints map more than the whole season"

    # each stratum's burned count cannot exceed what was judged in it, and its
    # rate has to be that ratio rather than a separately stored number
    for name, s in v["strata"].items():
        assert s["burned"] <= s["judged"], name
        assert abs(s["rate"] - s["burned"] / s["judged"]) < 0.001, name
        assert s["ci95"][0] <= s["rate"] <= s["ci95"][1], name

    labels = gpkg_features(ROOT / "data" / "labels" / "biak_labels.gpkg",
                           "labels", LABEL_COLS)
    assert len(labels) == 142, f"expected 142 label boxes, got {len(labels)}"
    for f in labels:
        assert set(f["properties"]) == set(LABEL_COLS), f["properties"]
        assert "notes" not in f["properties"], "interpretation notes published"
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    classes = {f["properties"]["class"] for f in labels}
    assert classes <= {"burned", "unburned", "unsure"}, classes

    print(f"all checks passed: {det[year]} detections, {ev[year]} events, "
          f"{m['ha']} ha mapped, {v['estimate_ha']} ha validated, "
          f"{len(labels)} label boxes")


if __name__ == "__main__":
    if "--check" in sys.argv:
        demo()
    else:
        for p in build():
            print(p.relative_to(ROOT).as_posix())
        demo()
