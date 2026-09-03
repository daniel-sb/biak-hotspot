"""Build the QGIS project for the field survey, ready to push to Mergin Maps.

    "C:\\Program Files\\QGIS 3.44.13\\bin\\python-qgis-ltr.bat" \\
        src/fieldwork_qgis_project.py

Writes fieldwork/biak_survey.qgz with the basemap, the two reference layers
and the survey layer already styled, its form already configured, and the
reference layers already locked.

Doing this in code rather than through the interface is not tidiness. The
form carries about twenty-five settings, one of which - whether the GPS
accuracy default reapplies on update - silently replaces the accuracy
measured at capture with the accuracy wherever the surveyor happens to be
standing later. A setting like that is wrong in a way nobody notices until
the data is being analysed, months after the trip. Written down it can be
read, reviewed and rebuilt identically.

Re-running overwrites the project file. It does not touch the GeoPackage, so
a project rebuilt after fieldwork keeps every record already collected.
"""

from __future__ import annotations

import sys
from pathlib import Path

from qgis.core import (
    Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsDefaultValue,
    QgsEditorWidgetSetup, QgsFieldConstraints, QgsMarkerSymbol,
    QgsPalLayerSettings, QgsProject, QgsRasterLayer, QgsRendererCategory,
    QgsCategorizedSymbolRenderer, QgsTextBufferSettings, QgsTextFormat,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parents[1]
FIELD = ROOT / "fieldwork"
GPKG = FIELD / "biak_ground_truth.gpkg"
MBTILES = FIELD / "biak_basemap.mbtiles"
OUT = FIELD / "biak_survey.qgz"

# The basemap is magenta, green and blue. Red and yellow disappear into it -
# the first attempt had yellow "lemah" targets and orange control points that
# were indistinguishable on screen. White and black are the two colours the
# imagery does not use, so the reference layers are drawn in them, and the
# survey layer takes the one bright colour left over.
WHITE, BLACK, YELLOW, CYAN = "#ffffff", "#000000", "#ffe700", "#00e5ff"

# Photo quality is a PROJECT setting, not a phone setting. There is no such
# control in the mobile app, and looking for one there is a dead end - the
# app resizes according to what the project tells it. Keys and values are the
# plugin's own (Mergin/project_settings_widget.py):
#   0 Original   1 High approx 2-4 MB   2 Medium approx 1-2 MB   3 Low approx 0.5 MB
# Medium, because the arithmetic decides it: 120 points at Original is 1.0
# to 1.4 GB and the free quota dies around the fiftieth point, in the field,
# with no signal to fix it. At Medium the same survey is about 180 MB, which
# with the 82 MB basemap leaves room to spare. Drop to 3 if the trip grows.
PHOTO_QUALITY = 2


def marker(shape, fill, stroke, size, width=0.6):
    return QgsMarkerSymbol.createSimple({
        "name": shape, "color": fill, "outline_color": stroke,
        "outline_width": str(width), "outline_width_unit": "MM",
        "size": str(size), "size_unit": "MM",
    })


def style_targets(layer):
    """Shape carries the priority, not colour: at arm's length in sunlight a
    circle and a diamond are still telling apart, two shades of the same
    colour are not."""
    cats = [
        QgsRendererCategory("kuat", marker("circle", WHITE, BLACK, 4.0),
                            "kuat - 3+ deteksi, 2 satelit atau 2 hari"),
        QgsRendererCategory("sedang", marker("diamond", WHITE, BLACK, 3.4),
                            "sedang - 2 deteksi"),
        # 147 single detections would bury the map and are not where anyone
        # is walking. The rows stay in the file; only the drawing is off.
        QgsRendererCategory("lemah", marker("circle", BLACK, WHITE, 1.6),
                            "lemah - deteksi tunggal (disembunyikan)",
                            render=False),
    ]
    renderer = QgsCategorizedSymbolRenderer("prioritas", cats)
    layer.setRenderer(renderer)

    lab = QgsPalLayerSettings()
    lab.fieldName = "target_id"
    fmt = QgsTextFormat()
    fmt.setFont(QFont("Arial", 9, QFont.Bold))
    fmt.setSize(9)
    fmt.setColor(QColor(WHITE))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.0)
    buf.setColor(QColor(BLACK))
    fmt.setBuffer(buf)
    lab.setFormat(fmt)
    lab.placement = Qgis.LabelPlacement.OverPoint
    lab.yOffset = 3.0
    # Labels only once zoomed in past 1:25000; at island scale 134 of them
    # overlap into a smear.
    lab.scaleVisibility = True
    lab.minimumScale = 25000
    lab.maximumScale = 0
    layer.setLabeling(QgsVectorLayerSimpleLabeling(lab))
    layer.setLabelsEnabled(True)


def style_controls(layer):
    """Inverted against the targets - black on white against white on black -
    so the two can never be confused at a glance."""
    layer.renderer().setSymbol(marker("circle", BLACK, WHITE, 3.0))


def style_survey(layer):
    """Categorised on the label so a finished point shows what it was called,
    which is the only way to see progress on a phone screen."""
    cats = [
        QgsRendererCategory("bakar", marker("star", YELLOW, BLACK, 5.0),
                            "bakar"),
        QgsRendererCategory("tidak_bakar", marker("square", CYAN, BLACK, 4.0),
                            "tidak bakar"),
        QgsRendererCategory("", marker("circle", YELLOW, BLACK, 4.0),
                            "belum diberi kelas"),
    ]
    layer.setRenderer(QgsCategorizedSymbolRenderer("kelas", cats))


def value_map(pairs):
    # QGIS keeps a value map ordered only when it is a list of one-key dicts.
    return QgsEditorWidgetSetup(
        "ValueMap", {"map": [{k: v} for k, v in pairs]})


def configure_form(survey, targets):
    aliases = {
        "plot_id": "ID plot", "target_id": "Target", "kelas": "Kelas",
        "tingkat_yakin": "Tingkat yakin", "bukti": "Bukti bakar",
        "akurasi_m": "Akurasi GPS (m)", "waktu": "Waktu",
        "foto": "Foto", "catatan": "Catatan",
    }
    widgets = {
        "plot_id": QgsEditorWidgetSetup("TextEdit", {}),
        "target_id": QgsEditorWidgetSetup("ValueRelation", {
            "Layer": targets.id(), "Key": "target_id", "Value": "target_id",
            "AllowNull": True, "OrderByValue": True, "UseCompleter": True,
            # 147 single-detection clusters are not survey destinations, so
            # they are not offered as answers either.
            "FilterExpression": "\"prioritas\" IN ('kuat','sedang')",
        }),
        "kelas": value_map([("bakar", "bakar"),
                            ("tidak_bakar", "tidak_bakar")]),
        "tingkat_yakin": value_map([("pasti", "pasti"),
                                    ("mungkin", "mungkin")]),
        "bukti": value_map([(v, v) for v in (
            "arang", "abu", "batang hangus", "tunggul terbakar",
            "tidak ada")]),
        "akurasi_m": QgsEditorWidgetSetup("TextEdit", {}),
        "waktu": QgsEditorWidgetSetup("TextEdit", {}),
        "foto": QgsEditorWidgetSetup("ExternalResource", {
            "FileWidget": True, "FileWidgetButton": True,
            "DocumentViewer": 1,        # show the photo in the form
            "RelativeStorage": 1,       # relative to the project, so it syncs
            "StorageMode": 0,
        }),
        "catatan": QgsEditorWidgetSetup("TextEdit", {"IsMultiline": True}),
    }
    defaults = {
        # Unique without depending on fid, which Mergin renumbers on sync.
        "plot_id": ("format_date(now(), 'yyyyMMdd-HHmmss')", False),
        "waktu": ("format_date(now(), 'yyyy-MM-dd HH:mm:ss')", False),
        # applyOnUpdate stays False. True would rewrite the accuracy every
        # time the form is reopened, replacing the value measured when the
        # point was taken with wherever the phone is standing now - and that
        # value is the only thing that lets a wandering fix be filtered out
        # later.
        "akurasi_m": ("@position_horizontal_accuracy", False),
    }

    for name, alias in aliases.items():
        idx = survey.fields().indexOf(name)
        assert idx >= 0, "field {} is missing from the survey layer".format(
            name)
        survey.setFieldAlias(idx, alias)
        survey.setEditorWidgetSetup(idx, widgets[name])
        if name in defaults:
            expr, on_update = defaults[name]
            survey.setDefaultValueDefinition(
                idx, QgsDefaultValue(expr, on_update))

    # Without kelas a record has no label, and the walk that produced it was
    # wasted. Hard constraint: the app refuses to save the feature.
    k = survey.fields().indexOf("kelas")
    survey.setFieldConstraint(k, QgsFieldConstraints.ConstraintNotNull,
                              QgsFieldConstraints.ConstraintStrengthHard)

    fid = survey.fields().indexOf("fid")
    if fid >= 0:
        survey.setEditorWidgetSetup(fid, QgsEditorWidgetSetup("Hidden", {}))


def verify(project, path):
    """Reopen the written file and assert the settings survived.

    Everything configured above lives in memory until project.write()
    serialises it, and a widget config that fails to round-trip leaves no
    error - just a form that behaves differently on the phone than it did
    here. Reading it back is the only check that means anything.
    """
    project.clear()
    assert project.read(str(path)), "cannot reopen {}".format(path)

    def layer(title):
        found = project.mapLayersByName(title)
        assert found, "layer {} missing from the reopened project".format(
            title)
        return found[0]

    survey = layer("survei")
    targets = layer("target_bakar")
    controls = layer("target_kontrol")

    assert targets.readOnly() and controls.readOnly(), \
        "reference layers came back editable"

    fields = survey.fields()
    acc = fields.indexOf("akurasi_m")
    dv = survey.defaultValueDefinition(acc)
    assert dv.expression() == "@position_horizontal_accuracy", dv.expression()
    assert not dv.applyOnUpdate(), (
        "akurasi_m reapplies on update - it would overwrite the accuracy "
        "measured at capture")

    kelas = fields.indexOf("kelas")
    assert (survey.fieldConstraints(kelas)
            & QgsFieldConstraints.ConstraintNotNull), "kelas is nullable"
    assert survey.editorWidgetSetup(kelas).type() == "ValueMap"
    assert [list(d)[0] for d in
            survey.editorWidgetSetup(kelas).config()["map"]] == \
        ["bakar", "tidak_bakar"]

    rel = survey.editorWidgetSetup(fields.indexOf("target_id"))
    assert rel.type() == "ValueRelation", rel.type()
    assert rel.config()["Layer"] == targets.id(), "value relation lost its layer"
    assert "prioritas" in rel.config()["FilterExpression"]

    photo = survey.editorWidgetSetup(fields.indexOf("foto"))
    assert photo.type() == "ExternalResource"
    assert int(photo.config()["RelativeStorage"]) == 1, \
        "photo paths are absolute and will not sync"

    cats = {c.value(): c.renderState() for c in targets.renderer().categories()}
    assert cats == {"kuat": True, "sedang": True, "lemah": False}, cats
    assert targets.labelsEnabled()

    quality, ok = project.readNumEntry("Mergin", "PhotoQuality")
    assert ok and quality == PHOTO_QUALITY, (ok, quality)
    naming, ok = project.readEntry(
        "Mergin", "PhotoNaming/{}/foto".format(survey.id()))
    assert ok and naming == '"plot_id"', (ok, naming)
    return len(fields) - 1


def main():
    for p in (GPKG, MBTILES):
        if not p.exists():
            raise SystemExit("{} is missing - run src/fieldwork_gpkg.py and "
                             "src/basemap_mbtiles.py first".format(p))

    QgsApplication.setPrefixPath(sys.prefix, True)
    app = QgsApplication([], False)
    app.initQgis()

    project = QgsProject.instance()
    project.clear()
    project.setTitle("Biak ground truth - survei lapangan")
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    # Relative paths, or the project breaks the moment the folder is synced
    # to a phone with a different filesystem layout.
    project.writeEntryBool("Paths", "/Absolute", False)

    basemap = QgsRasterLayer(str(MBTILES), "biak_basemap 2026-08-23", "gdal")
    assert basemap.isValid(), "basemap failed to load"
    project.addMapLayer(basemap)

    def vector(name, title):
        lyr = QgsVectorLayer("{}|layername={}".format(GPKG, name), title,
                             "ogr")
        assert lyr.isValid(), "{} failed to load".format(name)
        project.addMapLayer(lyr)
        return lyr

    controls = vector("target_kontrol", "target_kontrol")
    targets = vector("target_bakar", "target_bakar")
    survey = vector("survei", "survei")

    style_controls(controls)
    style_targets(targets)
    style_survey(survey)
    configure_form(survey, targets)

    # A stray thumb-drag must not move a target. These layers are the
    # reference the survey is measured against; only `survei` is edited.
    for lyr in (targets, controls):
        lyr.setReadOnly(True)

    project.writeEntry("Mergin", "PhotoQuality", PHOTO_QUALITY)
    # Name each photo after its plot, so a file separated from the database
    # can still be traced back to the point it was taken at.
    project.writeEntry(
        "Mergin", "PhotoNaming/{}/foto".format(survey.id()), '"plot_id"')

    # Read everything worth printing BEFORE exitQgis: it deletes the
    # underlying C++ objects and any later attribute access raises.
    summary = [
        "basemap  {} x {} px, {}".format(
            basemap.width(), basemap.height(), basemap.crs().authid()),
        "targets  {} features, lemah hidden, read-only {}".format(
            targets.featureCount(), targets.readOnly()),
        "controls {} features, read-only {}".format(
            controls.featureCount(), controls.readOnly()),
        "survei   {} fields configured, kelas is NOT NULL".format(
            len(survey.fields()) - 1),
    ]

    ok = project.write(str(OUT))
    if not ok:
        app.exitQgis()
        raise SystemExit("failed to write {}".format(OUT))
    n_fields = verify(project, OUT)
    app.exitQgis()

    print("wrote {}".format(OUT))
    for line in summary:
        print("  " + line)
    print("  photo quality {} (0 original, 3 lowest), photos named by "
          "plot_id".format(PHOTO_QUALITY))
    print("  reopened and verified: {} survey fields, GPS accuracy captured "
          "once, kelas required, photos relative".format(n_fields))


if __name__ == "__main__":
    sys.exit(main())
