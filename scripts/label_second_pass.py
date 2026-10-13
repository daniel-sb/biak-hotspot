"""Copy the label boxes into a fresh file for a second interpreter (Task 23).

    python scripts/label_second_pass.py            # build the pass-2 file
    python scripts/label_second_pass.py --project  # a QGIS project for it
    python scripts/label_second_pass.py --compare  # kappa and agreement

Run under the QGIS 3.44 python (geopandas); --compare works under either, but
keep both under the same interpreter as the other label scripts.

Every agreement figure in F20, F21 and F22 comes from one person reading one set
of images, and that is the largest unmeasured uncertainty in the project. This
copies the boxes into data/labels/biak_labels_pass2.gpkg with `class`,
`confidence` and `notes` emptied and the first pass nowhere in the file, so a
second interpreter judges the same boxes blind. The first pass is opened
read-only and is never written: the copy is made with VACUUM INTO.

`class`, `confidence` and `notes` are blanked with the GeoPackage triggers
dropped, because their WHEN clauses call ST_IsEmpty, which plain sqlite3 does
not define. The triggers are restored verbatim afterwards.

--compare reads both files back and writes data/processed/label_agreement.json:
Cohen's kappa and the raw agreement per stratum, and every box the two
interpreters read differently, with both answers. Neither answer wins: the
disagreement rate is the result, and reconciling a box is the owner's decision.

    python scripts/label_second_pass.py --compare

An unjudged box is not a disagreement - only boxes both passes judged are
compared, and the rest are counted.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "data/labels/biak_labels.gpkg"
PASS2 = ROOT / "data/labels/biak_labels_pass2.gpkg"
OUT = ROOT / "data/processed/label_agreement.json"
JUDGED = ("burned", "unburned")     # `unsure` is an answer, but not a class
BLANK = ("class", "confidence", "notes")


def read_rows(path):
    """(sample_id, sampling, class) for one pass, ordered by sample_id."""
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        return con.execute(
            'SELECT sample_id, sampling, "class" FROM labels ORDER BY sample_id'
        ).fetchall()
    finally:
        con.close()


def copy_boxes(src, dst):
    """Write `dst` as a fresh copy of `src` with every judgement emptied.

    The source is opened read-only and read through VACUUM INTO, so nothing
    here can write to it even by accident.
    """
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise SystemExit(f"missing {src} - nothing copied")
    source = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    try:
        dst.unlink(missing_ok=True)
        # A byte copy of the file, not a fresh empty GeoPackage: the copy has
        # to carry the boxes themselves, and VACUUM INTO cannot touch the source.
        source.execute("VACUUM INTO ?", (str(dst),))
    except sqlite3.OperationalError as err:
        raise SystemExit(f"cannot copy {src.name} to {dst.name}: {err}")
    finally:
        source.close()

    con = sqlite3.connect(dst)
    try:
        # The GeoPackage triggers' WHEN clauses call ST_IsEmpty, which plain
        # sqlite3 does not define, so they are dropped for the blanking and
        # restored verbatim straight after.
        triggers = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
            " AND tbl_name='labels'").fetchall()
        for name, _ in triggers:
            con.execute(f'DROP TRIGGER "{name}"')
        try:
            con.execute('UPDATE labels SET "class"=NULL, confidence=NULL, notes=NULL')
        except sqlite3.OperationalError as err:
            raise SystemExit(f"{dst.name} is not a labels GeoPackage: {err}")
        for _, sql in triggers:
            con.execute(sql)
        left = judgements_left(con)
        if left:
            raise SystemExit(f"{left} judgements survived the copy - nothing written")
        boxes = con.execute("SELECT count(*) FROM labels").fetchone()[0]
        con.commit()
    finally:
        con.close()
    return boxes


def judgements_left(con):
    """How many boxes still carry a judgement. The whole point of the copy is
    that this is zero, so it is checked rather than assumed."""
    return con.execute(
        'SELECT count(*) FROM labels WHERE "class" IS NOT NULL'
        " OR confidence IS NOT NULL OR notes IS NOT NULL").fetchone()[0]


def kappa(pairs):
    """Cohen's kappa over (a, b) pairs, and the raw agreement.
    Returns (kappa, agreement, n). Both passes agreeing everywhere gives
    kappa 1.0: p_e is 1, and the ratio's denominator is zero."""
    n = len(pairs)
    if n == 0:
        return None, None, 0
    agree = sum(1 for a, b in pairs if a == b)
    p_o = agree / n
    labels = sorted({v for pair in pairs for v in pair})
    p_e = sum(
        (sum(1 for a, _ in pairs if a == v) / n) * (sum(1 for _, b in pairs if b == v) / n)
        for v in labels)
    if p_e == 1.0:
        return 1.0, p_o, n
    return (p_o - p_e) / (1 - p_e), p_o, n


def build() -> int:
    boxes = copy_boxes(GPKG, PASS2)
    print(f"copied {boxes} boxes to {PASS2.relative_to(ROOT)}, judgements emptied")
    print("the first pass is not in that file and is not modified.")
    print(f"\nbuild its QGIS project, then open it and judge the boxes blind:\n"
          f'  "C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" '
          f"scripts/label_second_pass.py --project")
    return 0


def project() -> int:
    """A QGIS project showing the pass-2 boxes over the same imagery.

    Built here rather than in scripts/label_qgis_project.py so the two passes
    cannot be confused: this hard-codes PASS2, and that script hard-codes the
    first pass. The imagery is the shared TIFFs, so both see the same pictures.
    """
    if not PASS2.exists():
        raise SystemExit(f"missing {PASS2} - run without --project first")
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,
                           QgsFillSymbol, QgsProject, QgsRasterLayer,
                           QgsSingleSymbolRenderer, QgsVectorLayer)

    out = PASS2.with_suffix(".qgz")
    qgs = QgsApplication([], False)
    qgs.initQgis()
    try:
        project_ = QgsProject.instance()
        project_.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        project_.setTitle("Biak burn-scar labelling - SECOND PASS, blind")

        labels = QgsVectorLayer(f"{PASS2}|layername=labels", "LABELS PASS 2", "ogr")
        if not labels.isValid():
            raise SystemExit(f"labels layer in {PASS2.name} is not valid")
        labels.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
            {"color": "255,255,0,60", "outline_color": "#ffd400",
             "outline_width": "0.6"})))
        project_.addMapLayer(labels)

        group = project_.layerTreeRoot().insertGroup(0, "S2DR4 1 m imagery")
        for eid in ("E0301", "E0313", "E0368"):
            for kind in ("swir", "tci"):
                path = ROOT / f"data/labels/imagery/{eid}_{kind}.tif"
                if not path.exists():
                    print("missing imagery:", path)
                    continue
                rl = QgsRasterLayer(str(path), f"{eid} {kind}")
                if not rl.isValid():
                    print("raster not valid:", path)
                    continue
                project_.addMapLayer(rl, False)
                group.addLayer(rl).setItemVisibilityChecked(
                    eid == "E0301" and kind == "swir")
        project_.write(str(out))
    finally:
        qgs.exitQgis()
    print(f"written {out}")
    print("Open it, judge every box with class and confidence, and save. "
          "The first pass is not in this project.")
    return 0


def compare() -> int:
    if not PASS2.exists():
        raise SystemExit(f"missing {PASS2} - run without --compare first")
    first = {r[0]: r for r in read_rows(GPKG)}
    second = {r[0]: r for r in read_rows(PASS2)}
    if set(first) != set(second):
        raise SystemExit("the two passes hold different boxes - nothing written")

    per_stratum: dict[str, list] = {}
    disagreements = []
    unjudged = 0
    for sid in sorted(first):
        _, stratum, cls1 = first[sid]
        cls2 = second[sid][2]
        if cls1 not in JUDGED or cls2 not in JUDGED:
            unjudged += 1
            continue
        per_stratum.setdefault(stratum, []).append((cls1, cls2))
        if cls1 != cls2:
            disagreements.append({"sample_id": sid, "sampling": stratum,
                                  "pass1": cls1, "pass2": cls2})

    blocks = {}
    for stratum in sorted(per_stratum):
        pairs = per_stratum[stratum]
        k, agreement, n = kappa(pairs)
        blocks[stratum] = {
            "n": n, "agreement": None if agreement is None else round(agreement, 3),
            "kappa": None if k is None else round(k, 3),
            "pass1_burned": sum(1 for a, _ in pairs if a == "burned"),
            "pass2_burned": sum(1 for _, b in pairs if b == "burned"),
        }
    pooled = [p for pairs in per_stratum.values() for p in pairs]
    k, agreement, n = kappa(pooled)
    doc = {
        "what": ("Two interpreters' readings of the same label boxes on S2DR4 "
                 "1 m imagery. These are agreement between two readings of model "
                 "output, not accuracy against ground (F18)."),
        "compared": n,
        "not_compared": unjudged,
        "pooled": {"n": n, "agreement": None if agreement is None else round(agreement, 3),
                   "kappa": None if k is None else round(k, 3)},
        "per_stratum": blocks,
        "disagreements": disagreements,
        "note": ("Neither answer wins where they disagree: a reconciled label is "
                 "the owner's decision, taken box by box and recorded with a reason."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    print(f"{n} boxes judged by both passes, {unjudged} not compared"
          + (" (one pass called them unsure or left them empty)" if unjudged else ""))
    print(f"\n{'stratum':<22s} {'n':>4s} {'agree':>7s} {'kappa':>7s}")
    for stratum, row in blocks.items():
        agree = "   none" if row["agreement"] is None else f"{row['agreement']:7.3f}"
        kappa_s = "   none" if row["kappa"] is None else f"{row['kappa']:7.3f}"
        print(f"{stratum:<22s} {row['n']:4d} {agree} {kappa_s}")
    if n:
        print(f"pooled {n} boxes: agreement {agreement:.3f}, kappa {k:.3f}")
    print(f"\n{len(disagreements)} disagree:")
    for d in disagreements:
        print(f"  {d['sample_id']} ({d['sampling']}): "
              f"pass1 {d['pass1']}, pass2 {d['pass2']}")
    print(f"\nwritten {OUT.relative_to(ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compare", action="store_true",
                    help="kappas and the disagreement list; writes nothing to either pass")
    ap.add_argument("--project", action="store_true",
                    help="build the pass-2 QGIS project over the same imagery")
    args = ap.parse_args()
    if args.compare:
        return compare()
    if args.project:
        return project()
    return build()


if __name__ == "__main__":
    sys.exit(main())
