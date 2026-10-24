"use strict";
/* The present tense, in three distinguishable states. State three, a failed
   fetch, is handled by the caller: a gap in the record is never a zero. The
   islands being observable is a fact about the satellites, not a reassurance,
   so the observation gap travels with it. */
function statusText(n, last, days, to) {
  if (n > 0) {
    return "<strong>" + n + " detection" + (n === 1 ? "" : "s") +
      " in the " + days + " days to " + esc(to) + " (WIT).</strong> " +
      "Most recent: " + esc(last) + ".";
  }
  return "<strong>No detections in the " + days + " days to " + esc(to) +
    " (WIT).</strong> The islands were observable and no thermal anomalies " +
    "were detected. Nothing observes Biak between 15:00 and 00:31 WIT.";
}

/* index.html - the record of the 2026 season: the headline figures and the
   map. Every figure is read from docs/data/headline.json, never written into
   the markup, so a number on this page can be traced to the product that
   produced it (src/headline_figures.py). */

/* The two area figures answer different questions over different ground, so
   the page states each one's scope next to it and never arithmetic between
   them. */
function fmtHa(n) {
  return n.toLocaleString("en-GB", { maximumFractionDigits: 0 }) + " ha";
}

/* The interval bar. The estimate sits on a 95% interval, and the product's
   mapped extent is a tick on the same scale - which falls OUTSIDE the
   interval, below it, because the product under-maps (F28, F29). Drawing them
   on one axis is the point: a reader sees the disagreement instead of having
   to subtract. */
function drawInterval(v) {
  const svg = $("fig-interval");
  if (!svg) return;
  /* An unlabelled bar is not a chart. The first version drew two marks on an
     invisible axis with "map 819" under one of them, and the question it got
     back was what the picture meant. Every mark now says its number and the
     caption says what the two colours are, because a reader should not have
     to be told how to read it. The blue is lifted from the results page's
     #2a78d6, which falls to 3.8:1 on the dark panel. */
  const BLUE = "#5fa8e8", ORANGE = "#e2714a", INK = "#e7e9e4",
        SOFT = "#9aa69f";
  const W = 300, padL = 10, padR = 10, y = 34;
  const lo = v.ci95_ha[0], hi = v.ci95_ha[1], mapped = v.mapped_in_footprints_ha;
  const min = Math.min(lo, mapped), max = Math.max(hi, v.estimate_ha);
  const pad = (max - min) * 0.1 || 1;
  const x = (val) => padL +
    ((val - (min - pad)) / ((max + pad) - (min - pad))) * (W - padL - padR);
  const n = (val) => Math.round(val).toLocaleString("en-GB");
  const text = (xx, yy, s, fill, size, anchor) =>
    '<text x="' + xx + '" y="' + yy + '" font-size="' + size + '" fill="' +
    fill + '" text-anchor="' + (anchor || "middle") + '">' + s + "</text>";
  svg.innerHTML = [
    // the interval, with a cap at each end and the estimate on it
    '<line x1="' + x(lo) + '" x2="' + x(hi) + '" y1="' + y + '" y2="' + y +
      '" stroke="' + BLUE + '" stroke-width="3"/>',
    '<line x1="' + x(lo) + '" x2="' + x(lo) + '" y1="' + (y - 6) + '" y2="' +
      (y + 6) + '" stroke="' + BLUE + '" stroke-width="2"/>',
    '<line x1="' + x(hi) + '" x2="' + x(hi) + '" y1="' + (y - 6) + '" y2="' +
      (y + 6) + '" stroke="' + BLUE + '" stroke-width="2"/>',
    '<circle cx="' + x(v.estimate_ha) + '" cy="' + y + '" r="5" fill="' +
      BLUE + '"/>',
    // what the product mapped, on the same axis
    '<line x1="' + x(mapped) + '" x2="' + x(mapped) + '" y1="' + (y - 10) +
      '" y2="' + (y + 10) + '" stroke="' + ORANGE + '" stroke-width="2.5"/>',
    // every mark says its number
    text(x(v.estimate_ha), y - 13, n(v.estimate_ha), INK, 11),
    text(x(mapped), y - 15, n(mapped), ORANGE, 10),
    text(x(lo), y + 19, n(lo), SOFT, 9),
    text(x(hi), y + 19, n(hi), SOFT, 9),
    // and the caption says what the colours are
    text(padL, y + 34, "orange: mapped by the product", ORANGE, 9.5, "start"),
    text(W - padR, y + 34, "blue: estimate, 95% interval", BLUE, 9.5, "end"),
  ].join("");
}

function drawFigures(doc) {
  const yr = doc.season_year;
  const det = doc.detections_by_year, ev = doc.events_by_year;
  const prior = Object.keys(det).filter((y) => y !== yr).sort();

  $("fig-counts").textContent =
    det[yr].toLocaleString("en-GB") + " in " + ev[yr].toLocaleString("en-GB");
  $("tile-counts").querySelector(".tile-k").textContent =
    "Detections in events, " + yr;
  $("fig-counts-prior").textContent = prior.length
    ? prior.map((y) => y + ": " + det[y] + "/" + ev[y]).join(" \u00b7 ") +
      " (detections/events)"
    : "";

  const m = doc.mapped;
  $("fig-mapped").textContent = fmtHa(m.ha);
  $("fig-mapped-note").textContent =
    m.events_with_area + " events carry an area; " +
    m.events_no_local_reference + " of " + m.events_listed +
    " could not be assessed and are excluded, not counted as zero. " +
    "A product output, with no interval.";

  const v = doc.validated;
  $("fig-validated").textContent = fmtHa(v.estimate_ha) + " (" +
    Math.round(v.ci95_ha[0]) + "\u2013" + Math.round(v.ci95_ha[1]) + ")";
  drawInterval(v);
  $("fig-validated-note").textContent =
    "Three labelled footprints only, where the product maps " +
    fmtHa(v.mapped_in_footprints_ha) + " \u2014 below the interval, so the " +
    "product under-maps here by about " + fmtHa(v.omission_ha) + ".";
}

(async () => {
  const summary = await loadSummary();

  if (summary) {
    /* The imagery follows the day the page describes, never the client clock.
       The daytime VIIRS overpass for a WIT day falls near 04:30 UTC on the
       same calendar date at this longitude, so the GIBS granule date and the
       WIT date coincide here; that is a property of 136E, not a general
       rule. */
    imageryDate = summary.covered_wit_date;

    /* status strip - the only present-tense element on this page. The window
       is the one hotspots_latest.geojson already covers, and the client clock
       is never consulted. */
    try {
      const fc = await loadJSON("data/hotspots_latest.geojson");
      const n = fc.features.length;
      const last = n > 0 ? fc.features
        .map((f) => f.properties.date_wit).sort().slice(-1)[0] : null;
      $("status").innerHTML =
        statusText(n, last, summary.geojson_window_days,
                   summary.covered_wit_date);
    } catch (e) {
      dataError("hotspots", "hotspots_latest.geojson failed to load \u2014 the " +
        "status strip is unavailable. " + e.message);
      $("status").innerHTML = "<span class='error'>Detection record " +
        "unavailable \u2014 a gap in the record is not a zero.</span>";
    }
  } else {
    $("status").innerHTML = "<span class='error'>Detection record " +
      "unavailable \u2014 a gap in the record is not a zero.</span>";
  }

  /* headline figures - a failed load leaves the tiles showing their em-dash
     placeholder and says why, rather than showing a zero. */
  try {
    drawFigures(await loadJSON("data/headline.json"));
  } catch (e) {
    $("figures-error").textContent = "headline.json failed to load \u2014 the " +
      "season's figures are unavailable, which is not a statement that " +
      "nothing burned. " + e.message;
  }
})();
