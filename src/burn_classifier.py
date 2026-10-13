"""A learned burn classifier from the hand-drawn labels, and the first
agreement figure this project has had (Task 22; PLAN.md Phase 5 step 3).

The labels are one interpreter's reading of S2DR4 1 m imagery, which is
model output, not observation (F18). Nothing here is an accuracy against
ground truth: every number is agreement with that interpretation, and the
wording is binding (PLAN.md section 8) - "changed like a burn", never a
cause and never a person.

Two jobs in one run:

  measurement  the Task 18 rule (a pixel's dnbr_plus above its event's own
               threshold) and the trivial "inside a VIIRS footprint" rule,
               scored on the same labelled pixels without any training;
  learning     HistGradientBoostingClassifier, RandomForestClassifier and
               a depth-3 DecisionTreeClassifier, trained on two events'
               pixels and tested on the third.

The unit is the 20 m pixel, and the features come from native Sentinel-2
at 20 m - the same pre/post looks, Cloud Score+ masking and scale Task 18
uses, so a pixel's features and its Task 18 verdict describe the same
observation. They deliberately do NOT come from the 1 m imagery the
labels were drawn on: a classifier trained on the super-resolved pixels
would be scored against a threshold that never saw them.

Folds leave one event out, so no polygon's pixels straddle a fold and
neither does an event's weather or look date. Figures are reported per
pixel and per polygon (a box's prediction is the majority over its
pixels; a tie goes to unburned and is counted): per-pixel numbers describe
pixels, the per-polygon table carries the real sample size. The two
sampling strata are never silently pooled - every block carries the
stratum split beside the pooled numbers.

The feature table is extracted once from Earth Engine and persisted before
any modelling (AGENTS always-2) as
data/raw/labels_features/features_<date>.csv, tracked in the repository.
A run without --fetch reads the newest one and never touches the network:

    python src/burn_classifier.py --fetch <google-cloud-project-id>
    python src/burn_classifier.py

If Earth Engine refuses a request the run stops with the event named and
writes nothing - no placeholder rows, no stand-in reflectance.

Writes data/processed/burn_classifier.json (sorted keys, indent 1, no
timestamp) and prints the per-fold tables and the comparison against the
Task 18 threshold rule.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from shapely import wkb
from shapely.geometry import Point, mapping
from shapely.ops import unary_union
from sklearn.ensemble import (HistGradientBoostingClassifier,
                              RandomForestClassifier)
from sklearn.inspection import permutation_importance
from sklearn.tree import DecisionTreeClassifier, export_text

from baseline import average_precision
from burned_area_gee import footprint, nearest_look
from events import membership

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config.yaml"
GPKG = ROOT / "data/labels/biak_labels.gpkg"
RAW = ROOT / "data/raw/labels_features"
AREAS = ROOT / "data/processed/burned_areas.json"
EVENT_FILE = ROOT / "data/processed/events.json"
DETECTIONS = ROOT / "data/processed/detections.parquet"
OUT = ROOT / "data/processed/burn_classifier.json"

# Reflectance bands at 20 m. B8 (10 m) is deliberately absent: the whole
# feature set has to live on one 20 m observation, the one Task 18 acted on.
REF_BANDS = ("B2", "B3", "B4", "B8A", "B11", "B12")
FEATURES = tuple(
    [f"pre_{b}" for b in REF_BANDS]
    + [f"post_{b}" for b in REF_BANDS]
    + [f"d_{b}" for b in REF_BANDS]
    + ["dnbr_plus", "dnbr", "dndvi", "dnbr_swir", "pre_lag", "post_lag"])
CLASSIFIERS = ("hist_gradient_boosting", "random_forest",
               "decision_tree_depth3")
RULES = CLASSIFIERS + ("task18_threshold", "trivial_footprint")
STRATA = ("random_box", "map_burned", "footprint_unmapped")
PERMUTATION_REPEATS = 10
COLUMNS = (("sample_id", "event_id", "sampling", "class", "lon", "lat",
            "pre_valid", "post_valid") + FEATURES)

CAVEATS = [
    "The labels are one interpreter's reading of S2DR4 1 m imagery, which "
    "is model output, not observation. These figures are agreement with "
    "that interpretation, not accuracy against ground truth.",
    "Features come from native Sentinel-2 at 20 m, not from the 1 m "
    "imagery the labels were drawn on.",
    "Folds leave one event out, so no polygon's pixels appear in both "
    "training and testing. Per-pixel figures describe pixels; the "
    "per-polygon table carries the real sample size.",
    "A learned classifier that beats the threshold rule here has beaten it "
    "on three events of one island in one season, and nothing more "
    "(PLAN.md section 8).",
]


# --------------------------------------------------------------------------
# Labels

def gpkg_geometry(blob):
    """GeoPackage binary to shapely geometry: 'GP' magic, version, flags,
    srs id, then an optional envelope whose length the flags give, then WKB.
    Read with sqlite3 alone - no GeoPackage dependency for one table."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob")
    envelope = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(blob[3] >> 1) & 0x07]
    return wkb.loads(blob[8 + envelope:])


def read_labels(path=GPKG):
    """The labels layer: one record per 60 x 60 m box, geometry included.
    An unjudged box carries no class and is not guessed either way."""
    con = sqlite3.connect(path)
    try:
        rows = con.execute('SELECT sample_id, event_id, sampling, "class", '
                           "geom FROM labels ORDER BY sample_id").fetchall()
    finally:
        con.close()
    return [{"sample_id": r[0], "event_id": r[1], "sampling": r[2],
             "class": r[3], "geometry": gpkg_geometry(r[4])} for r in rows]


def label_counts(df):
    """Box counts, by class and stratum and event - the record the drop
    below is measured against. Boxes, not pixels: a box is one judgement."""
    boxes = df.drop_duplicates("sample_id")
    cls = boxes["class"].fillna("no class")
    by_stratum, by_event = {}, {}
    for st, sub in cls.groupby(boxes["sampling"], sort=True):
        by_stratum[str(st)] = {str(k): int(v) for k, v in
                               sub.value_counts().sort_index().items()}
    for ev, sub in cls.groupby(boxes["event_id"], sort=True):
        by_event[str(ev)] = {str(k): int(v) for k, v in
                             sub.value_counts().sort_index().items()}
    return {"n_boxes": int(len(boxes)),
            "by_class": {str(k): int(v) for k, v in
                         cls.value_counts().sort_index().items()},
            "by_stratum": by_stratum, "by_event": by_event}


def model_table(df):
    """The rows the modelling may use: boxes judged burned or unburned,
    pixels with every feature finite. Returns (kept, dropped counts).

    Nothing is guessed and no missing reflectance becomes a zero: an
    `unsure` box and a pixel whose look is missing are dropped and
    counted, by stratum and by event, so the record stays auditable."""
    judged = df["class"].isin(("burned", "unburned"))
    unjudged = df[~judged].drop_duplicates("sample_id")
    kept = df[judged].copy()
    kept["y"] = (kept["class"] == "burned").astype(int)
    kept["stratum"] = kept["sampling"]
    ok = np.isfinite(kept[list(FEATURES)].to_numpy(dtype=float)).all(axis=1)
    bad = kept[~ok]
    per_box = kept.assign(_ok=ok).groupby("sample_id")["_ok"].any()
    empty = sorted(per_box.index[~per_box])
    boxes = kept.drop_duplicates("sample_id").set_index("sample_id")
    dropped = {
        "boxes_not_judged_burned_or_unburned": {
            "total": int(len(unjudged)),
            "by_stratum": {str(k): int(v) for k, v in
                           unjudged["sampling"].value_counts()
                           .sort_index().items()},
            "by_event": {str(k): int(v) for k, v in
                         unjudged["event_id"].value_counts()
                         .sort_index().items()},
        },
        "pixels_incomplete": {
            "total": int(len(bad)),
            "missing_pre_look": int((bad["pre_valid"] == 0).sum()),
            "missing_post_look": int((bad["post_valid"] == 0).sum()),
            "by_event": {str(k): int(v) for k, v in
                         bad["event_id"].value_counts().sort_index().items()},
        },
        # A judged box every one of whose pixels lost a look cannot be
        # voted on: it leaves the polygon table and is named here.
        "boxes_with_no_complete_pixel": {
            "total": len(empty),
            "sample_ids": empty,
            "by_stratum": {str(k): int(v) for k, v in
                           boxes.loc[empty, "sampling"].value_counts()
                           .sort_index().items()},
            "by_event": {str(k): int(v) for k, v in
                         boxes.loc[empty, "event_id"].value_counts()
                         .sort_index().items()},
        },
    }
    return kept[ok].reset_index(drop=True), dropped


# --------------------------------------------------------------------------
# Metrics

def metrics(y_true, y_pred, scores=None):
    """Confusion counts and the burned-class metrics, ties-safe on empty
    denominators: a figure that cannot be computed is null, never 0.
    average_precision reuses baseline.average_precision so the number is
    comparable with F12 and F17."""
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    tnr = tn / (tn + fp) if tn + fp else None
    balanced = (recall + tnr) / 2 if recall is not None and tnr is not None \
        else None
    ap = average_precision(scores, y_true) if scores is not None else None
    out = {"n": int(len(y_true)), "tp": tp, "fp": fp, "tn": tn, "fn": fn}
    for key, value in (("precision", precision), ("recall", recall),
                       ("f1", f1), ("balanced_accuracy", balanced),
                       ("average_precision", ap)):
        out[key] = None if value is None else round(float(value), 6)
    return out


def threshold_rule(dnbr_plus, event_id, thresholds):
    """The Task 18 rule on the labels: burn-like when the pixel's dNBR+
    exceeds ITS OWN event's threshold from burned_areas.json, never a
    threshold borrowed from another event."""
    cut = np.array([thresholds[e] for e in event_id], dtype=float)
    return (np.asarray(dnbr_plus, dtype=float) > cut).astype(int)


def fold_frames(df):
    """Leave one event out: [(test event, train rows, test rows)]."""
    return [(eid, df[df["event_id"] != eid], df[df["event_id"] == eid])
            for eid in sorted(df["event_id"].unique())]


def rules_for_fold(train, test, thresholds, params):
    """Fit the three classifiers on the training events and predict the
    held-out one; add the two no-training rules. Returns (models, frame)."""
    rs = int(params["random_state"])
    x_train = train[list(FEATURES)].to_numpy(dtype=float)
    y_train = train["y"].to_numpy(dtype=int)
    x_test = test[list(FEATURES)].to_numpy(dtype=float)
    models = {
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            random_state=rs),
        "random_forest": RandomForestClassifier(random_state=rs),
        "decision_tree_depth3": DecisionTreeClassifier(max_depth=3,
                                                       random_state=rs),
    }
    frame = test.copy()
    for name, model in models.items():
        model.fit(x_train, y_train)
        frame["pred_" + name] = model.predict(x_test)
        frame["prob_" + name] = model.predict_proba(x_test)[:, 1]
    frame["pred_task18_threshold"] = threshold_rule(
        frame["dnbr_plus"], frame["event_id"], thresholds)
    frame["pred_trivial_footprint"] = frame["in_footprint"].to_numpy(dtype=int)
    return models, frame


def polygon_frame(frame):
    """One row per labelled box: the majority class over its pixels. A
    tie resolves to unburned and keeps its `tied_` flag, which is counted."""
    grouped = frame.groupby("sample_id", sort=True)
    poly = pd.DataFrame({"y": grouped["y"].first(),
                         "stratum": grouped["stratum"].first()})
    for rule in RULES:
        vote = grouped["pred_" + rule].mean()
        poly["pred_" + rule] = (vote > 0.5).astype(int)
        poly["tied_" + rule] = vote == 0.5
        if "prob_" + rule in frame.columns:
            poly["prob_" + rule] = grouped["prob_" + rule].mean()
    return poly


def rule_metrics(frame, ties_frame=None):
    """Every rule, pooled and per stratum, at one level. The stratum split
    is always beside the pooled figure: the two strata are different
    designs and a pooled score alone would be an accuracy of nothing."""
    out = {}
    for rule in RULES:
        pred = frame["pred_" + rule].to_numpy(dtype=int)
        scores = (frame["prob_" + rule].to_numpy(dtype=float)
                  if "prob_" + rule in frame.columns else None)
        block = {"all": metrics(frame["y"], pred, scores)}
        if ties_frame is not None:
            block["all"]["ties"] = int(ties_frame["tied_" + rule].sum())
        for st in STRATA:
            rows = frame["stratum"].to_numpy() == st
            sub = metrics(frame["y"][rows], pred[rows],
                          None if scores is None else scores[rows])
            if ties_frame is not None:
                sub["ties"] = int(ties_frame.loc[
                    ties_frame["stratum"] == st, "tied_" + rule].sum())
            block[st] = sub
        out[rule] = block
    return out


def score_frame(frame):
    """The pixel and polygon metric blocks for one set of predictions."""
    poly = polygon_frame(frame)
    return {"pixel": rule_metrics(frame),
            "polygon": rule_metrics(poly, ties_frame=poly)}


def importances(models, x_test, y_test, params):
    """Permutation importance on the held-out fold (never the impurity
    kind, which favours high-cardinality features), scored by balanced
    accuracy like the tables above, for the two classifiers."""
    rs = int(params["random_state"])
    out = {}
    for name in ("hist_gradient_boosting", "random_forest"):
        got = permutation_importance(
            models[name], x_test, y_test, n_repeats=PERMUTATION_REPEATS,
            random_state=rs, scoring="balanced_accuracy")
        out[name] = {f: round(float(v), 6) for f, v in
                     zip(FEATURES, got.importances_mean)}
    return out


def classify(df, thresholds, params):
    """The three folds and the pooled out-of-fold block. `df` is the
    model table already (judged boxes, finite features)."""
    folds, frames = {}, []
    for eid, train, test in fold_frames(df):
        models, frame = rules_for_fold(train, test, thresholds, params)
        boxes = test.drop_duplicates("sample_id")["y"].value_counts()
        folds[eid] = {
            "n_train_pixels": int(len(train)),
            "n_train_burned_pixels": int(train["y"].sum()),
            "n_test_pixels": int(len(test)),
            "n_test_burned_pixels": int(test["y"].sum()),
            "n_train_boxes": int(train["sample_id"].nunique()),
            "n_test_boxes": int(boxes.sum()),
            "n_test_burned_boxes": int(boxes.get(1, 0)),
            "tree_rule": export_text(models["decision_tree_depth3"],
                                     feature_names=list(FEATURES)),
            "importances": importances(
                models, test[list(FEATURES)].to_numpy(dtype=float),
                test["y"].to_numpy(dtype=int), params),
        }
        folds[eid].update(score_frame(frame))
        frames.append(frame)
    pooled = pd.concat(frames, ignore_index=True)
    return {"folds": folds, "pooled": score_frame(pooled)}


# --------------------------------------------------------------------------
# Bring the pieces together

def latest_features(raw=RAW):
    files = sorted(Path(raw).glob("features_*.csv"))
    if not files:
        raise SystemExit(
            f"no feature table in {raw} - run once with --fetch <project> "
            "(Earth Engine), after which this run reads it offline")
    return files[-1]


def add_footprints(df, cfg):
    """The trivial rule's flag: is the pixel inside the event's VIIRS
    footprint. Rebuilt offline from the tracked detections and registry,
    exactly as Task 18 drew it (375 m around each member detection)."""
    doc = json.loads(EVENT_FILE.read_text(encoding="utf-8"))
    det = pd.read_parquet(DETECTIONS)
    det["detection_id"] = det["detection_id"].astype(str)
    det["event_id"] = det["detection_id"].map(membership(doc))
    radius = cfg["burned_area"]["footprint_m"]
    shapes = {}
    for eid in sorted(df["event_id"].unique()):
        members = det[det["event_id"] == eid]
        if members.empty:
            raise SystemExit(f"{eid}: no member detections, cannot rebuild "
                             "its VIIRS footprint - nothing written")
        shapes[eid], _ = footprint(members["latitude"].tolist(),
                                   members["longitude"].tolist(), radius)
    df = df.copy()
    df["in_footprint"] = [shapes[e].contains(Point(x, y)) for e, x, y in
                          zip(df["event_id"], df["lon"], df["lat"])]
    return df


def evaluate(cfg, feature_path=None):
    """A run without --fetch: read the newest feature table, model, and
    return the document that goes to burn_classifier.json."""
    path = Path(feature_path) if feature_path else latest_features()
    df = add_footprints(pd.read_csv(path), cfg)
    assessed = json.loads(AREAS.read_text(encoding="utf-8"))["assessed"]
    areas = {r["event_id"]: r for r in assessed}
    thresholds = {eid: float(r["threshold"]) for eid, r in areas.items()
                  if r.get("threshold") is not None}
    missing = sorted(set(df["event_id"].unique()) - set(thresholds))
    if missing:
        raise SystemExit("no Task 18 threshold for: %s - nothing written"
                         % ", ".join(missing))

    params = cfg["burn_classifier"]
    kept, dropped = model_table(df)
    doc = classify(kept, thresholds, params)
    doc["labels"] = label_counts(df)
    doc["labels"]["dropped"] = dropped
    doc["features"] = {
        "file": path.name,
        "n_pixels_sampled": int(len(df)),
        "n_pixels_modelled": int(len(kept)),
        "n_boxes": int(df["sample_id"].nunique()),
        "columns": list(df.columns),
    }
    doc["parameters"] = {
        "random_state": int(params["random_state"]),
        "classifiers": {
            "hist_gradient_boosting": "scikit-learn defaults",
            "random_forest": "scikit-learn defaults",
            "decision_tree_depth3": {"max_depth": 3},
        },
        "folds": "leave one event out; train on two, test on the third",
        "feature_columns": list(FEATURES),
        "scale_m": int(cfg["burned_area"]["scale_m"]),
        "cs_min": float(cfg["burned_area"]["cs_min"]),
        "threshold_rule": "d nbr_plus above the event's own Task 18 "
                          "threshold",
        "trivial_rule": "every pixel inside the VIIRS footprint is called "
                        "burn-like",
        "permutation_importance": {"scoring": "balanced_accuracy",
                                   "n_repeats": PERMUTATION_REPEATS},
    }
    doc["caveats"] = list(CAVEATS)
    return doc


# --------------------------------------------------------------------------
# Fetch (--fetch <project>): Earth Engine lives only here

def sample_pixels(ee, image, polygons, scale):
    """Every 20 m pixel centre inside the label polygons, with the pixel's
    coordinates. Callers sample an image whose bands are valid everywhere
    for the pixel inventory, and the feature image separately, because
    sampleRegions drops a pixel the moment any band is masked."""
    got = image.sampleRegions(collection=polygons, scale=scale,
                              geometries=True, tileScale=4).getInfo()
    rows = []
    for feature in got["features"]:
        props = dict(feature["properties"])
        props["lon"], props["lat"] = feature["geometry"]["coordinates"]
        rows.append(props)
    return rows


def feature_image(ee, pre, post):
    """One multi-band image per event: pre and post reflectance of the six
    20 m bands, their post-minus-pre differences, the four differenced
    indices and the two look lags. The indices come from
    burn_indices_gee.indices_of - the same functions F11 was built on."""
    from burn_indices_gee import BANDS, indices_of, scaled

    pre_s, post_s = scaled(pre), scaled(post)
    ipre = indices_of({b: pre_s.select(b) for b in BANDS})
    ipost = indices_of({b: post_s.select(b) for b in BANDS})

    def ndvi(img):
        nir, red = img.select("B8A"), img.select("B4")
        return nir.subtract(red).divide(nir.add(red))

    bands = []
    for b in REF_BANDS:
        bands.append(pre_s.select(b).rename("pre_" + b))
        bands.append(post_s.select(b).rename("post_" + b))
        bands.append(post_s.select(b).subtract(pre_s.select(b))
                     .rename("d_" + b))
    bands.append(ipost["NBR+"].subtract(ipre["NBR+"]).rename("dnbr_plus"))
    bands.append(ipost["NBR"].subtract(ipre["NBR"]).rename("dnbr"))
    bands.append(ipost["NBRSWIR"].subtract(ipre["NBRSWIR"])
                 .rename("dnbr_swir"))
    bands.append(ndvi(post_s).subtract(ndvi(pre_s)).rename("dndvi"))
    bands.append(pre.select("lag").rename("pre_lag"))
    bands.append(post.select("lag").rename("post_lag"))
    return ee.Image.cat(bands)


def event_rows(ee, event, area, labels, cfg):
    """All label pixels of one event, with the same pre/post windows, the
    same Cloud Score+ masking and the same 20 m scale as Task 18. A
    record for every 20 m pixel in the boxes; a pixel whose look is
    missing keeps its flags and empty feature cells, never a zero."""
    scale = int(cfg["burned_area"]["scale_m"])
    cs_min = cfg["burned_area"]["cs_min"]
    region = ee.Geometry(mapping(unary_union([l["geometry"] for l in labels])))
    pre, n_pre = nearest_look(ee, region, *area["windows_utc"]["pre"],
                              event["first_seen_utc"], True, cs_min)
    post, n_post = nearest_look(ee, region, *area["windows_utc"]["post"],
                                event["last_seen_utc"], False, cs_min)
    if not n_pre.getInfo() or not n_post.getInfo():
        raise RuntimeError("no Sentinel-2 scene in the pre or post window")
    polygons = ee.FeatureCollection([
        ee.Feature(ee.Geometry(mapping(l["geometry"])),
                   {"sample_id": l["sample_id"], "event_id": l["event_id"],
                    "sampling": l["sampling"], "class": l["class"]})
        for l in labels])
    flags = ee.Image.cat([
        pre.select("B2").mask().unmask(0).rename("pre_valid"),
        post.select("B2").mask().unmask(0).rename("post_valid")])
    cover = sample_pixels(ee, flags, polygons, scale)
    values = {(p["sample_id"], round(p["lon"], 6), round(p["lat"], 6)): p
              for p in sample_pixels(ee, feature_image(ee, pre, post),
                                     polygons, scale)}
    rows = []
    for pixel in cover:
        key = (pixel["sample_id"], round(pixel["lon"], 6),
               round(pixel["lat"], 6))
        found = values.get(key, {})
        row = {"sample_id": pixel["sample_id"], "event_id": pixel["event_id"],
               "sampling": pixel["sampling"], "class": pixel["class"],
               "lon": round(pixel["lon"], 6), "lat": round(pixel["lat"], 6),
               "pre_valid": int(pixel["pre_valid"]),
               "post_valid": int(pixel["post_valid"])}
        row.update({f: found.get(f) for f in FEATURES})
        rows.append(row)
    return rows


def fetch_features(project, cfg, labels_path=GPKG):
    """Extract every label pixel's features and persist the table. Any
    failed request stops the run with the event named and writes nothing:
    a failed fetch is not an empty extraction (AGENTS never-2)."""
    import ee

    ee.Initialize(project=project)
    labels = read_labels(labels_path)
    events = {e["event_id"]: e for e in
              json.loads(EVENT_FILE.read_text(encoding="utf-8"))["events"]}
    assessed = json.loads(AREAS.read_text(encoding="utf-8"))["assessed"]
    areas = {r["event_id"]: r for r in assessed}
    rows = []
    for eid in sorted({l["event_id"] for l in labels}):
        if eid not in events or areas.get(eid, {}).get("threshold") is None:
            raise SystemExit(f"{eid}: no registry entry or no assessed "
                             "burned_areas record - cannot reuse the Task 18 "
                             "windows; nothing written")
        try:
            got = event_rows(ee, events[eid], areas[eid],
                             [l for l in labels if l["event_id"] == eid], cfg)
        except Exception as err:                       # EE refusal or network
            raise SystemExit(f"{eid}: Earth Engine request failed ({err}) - "
                             "nothing written")
        rows += got
        print(f"{eid}: {len(got)} label pixels extracted")
    table = pd.DataFrame(rows, columns=list(COLUMNS))
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"features_{date.today().isoformat()}.csv"
    table.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------
# Output

def table(doc, level, which=None):
    """stdout rows: (group label, rule, metrics) for one block."""
    block = (doc["pooled"] if which is None else doc["folds"][which])[level]
    rows = []
    for rule in RULES:
        if which is None:
            for key in ("all",) + STRATA:
                rows.append((key, rule, block[rule][key]))
        else:
            rows.append(("all", rule, block[rule]["all"]))
    return rows


def fmt(value, width=6, digits=2):
    return " " * width if value is None else f"{value:{width}.{digits}f}"


def print_block(title, rows):
    print(f"\n{title}")
    head = ("  group             rule                    n    tp    fp    tn"
            "    fn   prec   rec     f1   bacc     ap")
    print(head)
    for group, rule, m in rows:
        print(f"  {group:<16s} {rule:<20s} {m['n']:4d}  {m['tp']:4d}  "
              f"{m['fp']:4d}  {m['tn']:4d}  {m['fn']:4d}"
              f"{fmt(m['precision'])} {fmt(m['recall'])} "
              f"{fmt(m['f1'])} {fmt(m['balanced_accuracy'])} "
              f"{fmt(m['average_precision'])}")


def print_report(doc):
    for eid, fold in sorted(doc["folds"].items()):
        print(f"\n=== fold {eid} === train {fold['n_train_pixels']} pixels "
              f"({fold['n_train_burned_pixels']} burned), test "
              f"{fold['n_test_pixels']} pixels "
              f"({fold['n_test_burned_pixels']} burned), "
              f"{fold['n_test_boxes']} boxes "
              f"({fold['n_test_burned_boxes']} burned)")
        print_block("pixels", table(doc, "pixel", eid))
        print_block("polygons (majority vote over each box's pixels)",
                    table(doc, "polygon", eid))
    print_block("pooled out of fold, pixels", table(doc, "pixel"))
    print_block("pooled out of fold, polygons", table(doc, "polygon"))

    print("\nbalanced accuracy, learned rules vs the Task 18 threshold "
          "(pixels | polygons):")
    for label, level in (("pixels", "pixel"), ("polygons", "polygon")):
        print(f"  {label:<8s} " + "".join(f"{r[:12]:>14s}" for r in RULES))
        rows = [("pooled", doc["pooled"][level])] + [
            (eid, fold[level]) for eid, fold in sorted(doc["folds"].items())]
        for name, block in rows:
            print(f"  {name:<8s} " + "".join(
                fmt(block[r]["all"]["balanced_accuracy"], width=14)
                for r in RULES))
    print("\ndecision tree, max_depth 3, printed in full:")
    for eid, fold in sorted(doc["folds"].items()):
        print(f"\n--- fold {eid} ---")
        print(fold["tree_rule"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", metavar="PROJECT",
                    help="extract the feature table from Earth Engine; the "
                         "only path that touches the network")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    path = None
    if args.fetch:
        path = fetch_features(args.fetch, cfg)
        print(f"wrote {path.relative_to(ROOT)}")
    doc = evaluate(cfg, path)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print_report(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
