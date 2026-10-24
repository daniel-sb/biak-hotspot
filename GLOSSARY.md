# Biak hotspot

Wildfire remote sensing for Biak, Papua, covering the anomalous 2026 dry season.
The project ingests thermal anomaly detections daily, maps burned area from
Sentinel-2, and publishes both to a public web page.

## Language

### What the page is

**Event record**:
A published account of a past fire season: what burned, when, and how
confidently we know it. Organised by the event, not by the calendar.
_Avoid_: dashboard, portal

**Situation report**:
A published account of what is burning now, organised by the operational
lifecycle of an incident. The Alaska Interagency Coordination Center publishes
one. This project does not.
_Avoid_: live dashboard, real-time dashboard

**Status strip**:
The one line on the event record that states the current detection count, so a
reader who arrives mid-season is not misled by a retrospective page. It is the
only situation-report element the event record carries.

### What the measurements are

**Detection**:
One thermal anomaly pixel reported by FIRMS or Himawari, located but not
confirmed as fire. A 375 m VIIRS pixel locates heat, never a perimeter and
never a person.
_Avoid_: fire, hotspot event, fire point

**Mapped extent**:
The area of the burned-area polygons the dNBR+ product actually drew. A product
output, not an estimate of the truth.
_Avoid_: burned area, total area

**Estimated burned area**:
The stratified area estimate computed from interpreted labels, published only
with its confidence interval. It is the project's best answer to how much
burned, and it is larger than the mapped extent.
_Avoid_: true area, actual area, corrected area

**Omission**:
Ground that burned and that the product did not map. The gap between estimated
burned area and mapped extent.

**Event**:
A cluster of detections treated as one fire, carrying a first-seen and
last-seen date.

**Stratum**:
One of the sampling classes the labelled boxes are drawn from. Strata are never
pooled, because the estimator's variance depends on keeping them separate.

### What the imagery is

**Nearest look**:
The compositing rule: per pixel, the latest clear observation before the event
started and the earliest after it ended. A search rule, never an averaging
window.
_Avoid_: composite window, median composite

**Clear look**:
An observation passing Cloud Score+ `cs_cdf >= 0.6`.

**Pre-look staleness**:
How old the pre-fire observation is at a given pixel. Large values mean the
pre-fire image may already contain an older scar.
