"""Build the QGIS project for hand-labelling burn scars on 1 m imagery.

Run with QGIS's own python, after scripts/label_prepare.py:

    "C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" \\
        scripts/label_qgis_project.py

Writes data/labels/biak_labels.qgz: the S2DR4 SWIR and true-colour images, the
VIIRS detections, the event footprints, the 42 sample points, and the empty
label layer with its form ready.

**No dNBR+ layer, on purpose.** These labels are the reference the dNBR+ product
will be judged against, so seeing it while drawing would make the comparison
worthless. The strata come from the VIIRS footprints, which owe nothing to any
Sentinel-2 threshold.

Re-running overwrites the project. It never touches the GeoPackage, so labels
already drawn survive a rebuild.
"""
from __future__ import annotations

import sys
from pathlib import Path

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsDefaultValue,
    QgsEditorWidgetSetup, QgsFieldConstraints, QgsFillSymbol, QgsLayerTreeGroup,
    QgsMarkerSymbol, QgsPalLayerSettings, QgsProject, QgsRasterLayer,
    QgsSingleSymbolRenderer, QgsTextBufferSettings, QgsTextFormat,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "data/labels"
GPKG = LAB / "biak_labels.gpkg"
OUT = LAB / "biak_labels.qgz"
EVENTS = {"E0301": "Anjareuw", "E0313": "Yendidori", "E0368": "Insumarires"}

CLASSES = {"burned": "burned — changed like a burn",
           "unburned": "unburned — no such change",
           "unsure": "unsure — leave it out of the reference"}
CONFIDENCE = {"high": "high — obvious either way",
              "medium": "medium", "low": "low — I would not defend this one"}


def vector(layer_name: str, title: str) -> QgsVectorLayer:
    lyr = QgsVectorLayer(f"{GPKG}|layername={layer_name}", title, "ogr")
    if not lyr.isValid():
        raise SystemExit(f"layer not valid: {layer_name} in {GPKG}")
    return lyr


def label_with(lyr: QgsVectorLayer, field: str, size: int = 9) -> None:
    s = QgsPalLayerSettings()
    s.fieldName = field
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", size))
    fmt.setColor(QColor("white"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(0, 0, 0, 200))
    fmt.setBuffer(buf)
    s.setFormat(fmt)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(s))
    lyr.setLabelsEnabled(True)


def value_map(lyr: QgsVectorLayer, field: str, mapping: dict) -> None:
    idx = lyr.fields().indexOf(field)
    lyr.setEditorWidgetSetup(idx, QgsEditorWidgetSetup(
        "ValueMap", {"map": [{v: k} for k, v in mapping.items()]}))


def main() -> int:
    if not GPKG.exists():
        raise SystemExit(f"run scripts/label_prepare.py first: {GPKG} missing")

    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    project.setTitle("Biak burn-scar labelling — S2DR4 1 m, 28 Aug 2026")

    root = project.layerTreeRoot()

    # --- the layer being drawn into -------------------------------------
    labels = vector("labels", "LABELS — draw here")
    sym = QgsFillSymbol.createSimple({"color": "255,255,0,60", "outline_color": "#ffd400",
                                      "outline_width": "0.6"})
    labels.setRenderer(QgsSingleSymbolRenderer(sym))
    value_map(labels, "class", CLASSES)
    value_map(labels, "confidence", CONFIDENCE)
    fields = labels.fields()
    labels.setDefaultValueDefinition(fields.indexOf("drawn_on"),
                                     QgsDefaultValue("format_date(now(),'yyyy-MM-dd')"))
    for required in ("sample_id", "class", "confidence"):
        i = fields.indexOf(required)
        labels.setFieldConstraint(i, QgsFieldConstraints.ConstraintNotNull,
                                  QgsFieldConstraints.ConstraintStrengthHard)
    project.addMapLayer(labels)

    # --- what to draw against, all read-only ----------------------------
    samples = vector("samples", "samples — one polygon each, 42 of them")
    samples.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "cross_fill", "color": "#00e5ff", "size": "3.5",
         "outline_color": "white", "outline_width": "0.4"})))
    label_with(samples, "sample_id")
    samples.setReadOnly(True)
    project.addMapLayer(samples)

    footprints = vector("footprints", "VIIRS footprints (strata, not truth)")
    footprints.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#ff5722", "outline_width": "0.5",
         "outline_style": "dash"})))
    footprints.setReadOnly(True)
    project.addMapLayer(footprints)

    detections = vector("detections", "VIIRS/MODIS detections")
    detections.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "255,87,34,140", "size": "2",
         "outline_color": "255,87,34,220", "outline_width": "0.2"})))
    detections.setReadOnly(True)
    project.addMapLayer(detections)

    # --- imagery, SWIR on top of true colour ----------------------------
    group = root.insertGroup(len(root.children()), "S2DR4 1 m imagery, 28 Aug 2026")
    for eid, desa in EVENTS.items():
        for kind, title in (("swir", "SWIR B12/B8A/B4"), ("tci", "true colour")):
            path = LAB / "imagery" / f"{eid}_{kind}.tif"
            if not path.exists():
                print("missing imagery:", path)
                continue
            rl = QgsRasterLayer(str(path), f"{eid} {desa} — {title}")
            if not rl.isValid():
                print("raster not valid:", path)
                continue
            project.addMapLayer(rl, False)
            node = group.addLayer(rl)
            node.setItemVisibilityChecked(kind == "swir" and eid == "E0313")

    project.write(str(OUT))
    qgs.exitQgis()
    print("written", OUT)
    print("open it, select LABELS, toggle editing, and draw one polygon per sample point.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
