"""Offline checks for the burn classifier (Task 22).

Earth Engine is never reachable from a test, so the frames are built here:
the `unsure` drop, leave-one-event-out folds, the per-polygon vote (ties
to unburned), the Task 18 rule's per-event thresholds, balanced accuracy
on a hand-checked matrix, the dropped pixel with a missing look, and the
byte-identical JSON from the same feature CSV. The real feature table and
the committed GeoPackage are read when present - reading is offline, the
fetch is not.

    python -m pytest tests/test_burn_classifier.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import burn_classifier as bc  # noqa: E402


def pixel_rows(sample_id, event_id, sampling, cls, n, burned_dnbr=0.0,
               in_footprint=False, **extra):
    """n pixels of one 60 x 60 m box, every feature finite unless the
    caller overrides one."""
    rows = []
    for i in range(n):
        row = {f: 0.5 for f in bc.FEATURES}
        row.update({"sample_id": sample_id, "event_id": event_id,
                    "sampling": sampling, "class": cls,
                    "lon": 136.0 + i * 1e-4, "lat": -1.1,
                    "pre_valid": 1, "post_valid": 1,
                    "in_footprint": in_footprint, "dnbr_plus":
                        burned_dnbr if cls == "burned" else 0.0})
        row.update(extra)
        rows.append(row)
    return rows


def synthetic_frame():
    """Three events, three boxes each (burned, unburned, unburned in the
    map stratum), four pixels per box - both classes in every fold. The
    footprint flag stands in for the offline derivation."""
    rows = []
    for k, eid in enumerate(("E1", "E2", "E3"), start=1):
        rows += pixel_rows(f"{eid}-A", eid, "random_box", "burned", 4,
                           burned_dnbr=0.5, in_footprint=True)
        rows += pixel_rows(f"{eid}-B", eid, "random_box", "unburned", 4)
        rows += pixel_rows(f"{eid}-C", eid, "map_burned", "unburned", 4,
                           in_footprint=True)
    frame = pd.DataFrame(rows, columns=list(bc.COLUMNS))
    frame["in_footprint"] = [r["in_footprint"] for r in rows]
    return frame


THRESHOLDS = {"E1": 0.10, "E2": 0.13, "E3": 0.20}


def vote_frame(preds):
    rows = []
    for value in preds:
        rows.append({"sample_id": "S1", "stratum": "random_box", "y": 1,
                     **{f"pred_{rule}": value for rule in bc.RULES}})
    return pd.DataFrame(rows)


def test_unsure_and_unjudged_boxes_are_dropped_and_counted_by_stratum():
    rows = (pixel_rows("S1", "E1", "random_box", "burned", 3)
            + pixel_rows("S2", "E1", "random_box", "unsure", 3)
            + pixel_rows("S3", "E1", "map_burned", "unsure", 3)
            + pixel_rows("S4", "E2", "map_burned", "unburned", 3)
            + pixel_rows("S5", "E2", "map_burned", None, 3))
    kept, dropped = bc.model_table(pd.DataFrame(rows))
    assert len(kept) == 6
    assert dropped["boxes_not_judged_burned_or_unburned"] == {
        "total": 3,
        "by_stratum": {"map_burned": 2, "random_box": 1},
        "by_event": {"E1": 2, "E2": 1},
    }


def test_folds_leave_one_event_out_and_never_split_a_polygon():
    df = synthetic_frame()
    folds = bc.fold_frames(df)
    assert len(folds) == 3
    tested = []
    for eid, train, test in folds:
        assert set(test["event_id"]) == {eid}
        assert not set(train["sample_id"]) & set(test["sample_id"])
        tested += sorted(set(test["sample_id"]))
    assert tested == sorted(df["sample_id"].unique())


def test_polygon_vote_is_the_majority_and_a_tie_goes_to_unburned():
    won = bc.polygon_frame(vote_frame([1] * 7 + [0] * 3))
    assert won["pred_hist_gradient_boosting"].iloc[0] == 1
    assert not bool(won["tied_hist_gradient_boosting"].iloc[0])

    tie = bc.polygon_frame(vote_frame([1] * 4 + [0] * 4))
    assert tie["pred_task18_threshold"].iloc[0] == 0
    assert bool(tie["tied_task18_threshold"].iloc[0])


def test_the_task18_rule_reads_each_events_own_threshold():
    got = bc.threshold_rule([0.05, 0.15, 0.12], ["E1", "E1", "E2"],
                            {"E1": 0.10, "E2": 0.13})
    assert list(got) == [0, 1, 0]


def test_balanced_accuracy_on_a_hand_checked_confusion_matrix():
    m = bc.metrics([1, 1, 1, 0, 0, 0, 0, 0], [1, 1, 0, 1, 0, 0, 0, 0])
    assert (m["tp"], m["fp"], m["tn"], m["fn"]) == (2, 1, 4, 1)
    assert m["precision"] == m["recall"] == round(2 / 3, 6)
    assert m["f1"] == round(2 / 3, 6)
    assert m["balanced_accuracy"] == round((2 / 3 + 4 / 5) / 2, 6)
    assert m["average_precision"] is None      # a rule has no probability

    ap = bc.metrics([1, 0], [1, 0], scores=[0.9, 0.1])
    assert ap["average_precision"] == 1.0
    none = bc.metrics([0, 0], [0, 0], scores=[0.2, 0.1])
    assert none["average_precision"] is None   # no positive to rank


def test_a_pixel_missing_a_look_is_dropped_and_counted_not_filled():
    rows = pixel_rows("S1", "E1", "random_box", "burned", 4)
    rows[1]["pre_B2"] = float("nan")
    rows[1]["pre_valid"] = 0
    # a second judged box where EVERY pixel lost its look: it cannot be
    # voted on, leaves the polygon table, and is named in the counts
    rows += pixel_rows("S2", "E1", "map_burned", "unburned", 2)
    for row in rows[-2:]:
        row["post_B4"] = float("nan")
        row["post_valid"] = 0
    kept, dropped = bc.model_table(pd.DataFrame(rows))
    assert len(kept) == 3
    assert dropped["pixels_incomplete"] == {
        "total": 3, "missing_pre_look": 1, "missing_post_look": 2,
        "by_event": {"E1": 3}}
    assert dropped["boxes_with_no_complete_pixel"] == {
        "total": 1, "sample_ids": ["S2"],
        "by_stratum": {"map_burned": 1}, "by_event": {"E1": 1}}
    assert np.isfinite(kept[list(bc.FEATURES)].to_numpy(dtype=float)).all()


def test_the_same_feature_csv_gives_a_byte_identical_json(tmp_path):
    df = synthetic_frame()
    df.loc[df.index[-1], "post_B4"] = float("nan")   # one dropped pixel too
    df.loc[df.index[-1], "post_valid"] = 0
    path = tmp_path / "features_2026-01-01.csv"
    df.to_csv(path, index=False)

    params = {"random_state": 42}
    blobs = []
    for _ in range(2):
        kept, _ = bc.model_table(pd.read_csv(path))
        kept["in_footprint"] = True      # stands in for add_footprints()
        blobs.append(json.dumps(bc.classify(kept, THRESHOLDS, params),
                                indent=1, sort_keys=True))
    assert blobs[0] == blobs[1]
    pooled = json.loads(blobs[0])["pooled"]["pixel"]["random_forest"]["all"]
    assert pooled["n"] == len(df) - 1


def test_labels_are_read_from_the_committed_geopackage():
    labels = bc.read_labels()
    assert len(labels) > 0
    assert len({l["sample_id"] for l in labels}) == len(labels)
    assert {l["event_id"] for l in labels} == {"E0301", "E0313", "E0368"}
    assert {l["sampling"] for l in labels} <= set(bc.STRATA)
    assert {l["class"] for l in labels} <= {"burned", "unburned", "unsure",
                                            None}
    for label in labels:
        assert label["geometry"].geom_type in ("Polygon", "MultiPolygon")
        assert label["geometry"].area > 0


def test_the_committed_feature_table_evaluates_deterministically():
    """The real extraction and the whole pipeline, offline. Requires the
    tracked CSV - run `python src/burn_classifier.py --fetch <project>`
    once if it is missing."""
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    path = bc.latest_features()
    first = json.dumps(bc.evaluate(cfg, path), indent=1, sort_keys=True)
    second = json.dumps(bc.evaluate(cfg, path), indent=1, sort_keys=True)
    assert first == second
    doc = json.loads(first)
    assert set(doc["folds"]) == {"E0301", "E0313", "E0368"}
    assert doc["pooled"]["pixel"]["hist_gradient_boosting"]["all"]["n"] == \
        sum(f["n_test_pixels"] for f in doc["folds"].values())
    assert doc["caveats"][0].startswith("The labels are one interpreter's")


if __name__ == "__main__":
    import tempfile
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            if "tmp_path" in fn.__code__.co_varnames:
                fn(Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
