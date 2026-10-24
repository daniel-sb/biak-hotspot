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

/* index.html - the 2026 event record. The brief and the evening product live
   here because they are evidence about the event; the status strip is the only
   present-tense element on the page (adr/0001). */
(async () => {
  const summary = await loadSummary();
  if (!summary) {
    $("status").innerHTML = "<span class='error'>Detection record unavailable " +
      "— a gap in the record is not a zero.</span>";
    $("evening").innerHTML = "<p class='error'>Evening product unavailable — " +
      "summary data failed to load. A gap in the record is not a zero.</p>";
    $("brief").innerHTML = "<p class='error'>Brief unavailable — summary data " +
      "failed to load.</p>";
    return;
  }

  /* status strip - the present tense, in three distinguishable states. The
     window is the one hotspots_latest.geojson already covers, and the client
     clock is never consulted: the page states the day it describes. */
  try {
    const fc = await loadJSON("data/hotspots_latest.geojson");
    const n = fc.features.length;
    const days = summary.geojson_window_days;
    const to = summary.covered_wit_date;
    const last = n > 0 ? fc.features
      .map((f) => f.properties.date_wit).sort().slice(-1)[0] : null;
    $("status").innerHTML = statusText(n, last, days, to);
  } catch (e) {
    dataError("hotspots", "hotspots_latest.geojson failed to load — the " +
      "status strip and the map points are unavailable. " + e.message);
    $("status").innerHTML = "<span class='error'>Detection record unavailable " +
      "— a gap in the record is not a zero.</span>";
  }

  /* The imagery follows the day the page is describing, never the client
     clock. The daytime VIIRS overpass for a WIT day falls near 04:30 UTC on
     the same calendar date at this longitude, so the GIBS granule date and
     the WIT date coincide here; that is a property of 136E, not a general
     rule. */
  imageryDate = summary.covered_wit_date;

  /* evening — after-dark result first; never a reassurance (PLAN.md 13.2) */
  try {
    const ev = summary.evening;
    const out = [];
    if (!ev || ev.state !== "ok") {
      out.push("<p class='warn'>Evening product unavailable for this night — a gap " +
               "in the record, not a zero.</p>");
    } else {
      out.push("<p>Slots retrieved: " + ev.slots_retrieved + " of " +
               ev.slots_expected + " expected.</p>");
      if (ev.slots_missing > 0)
        out.push("<p class='warn'>" + ev.slots_missing +
                 " expected slot(s) missing upstream — a missing slot is a gap " +
                 "in the record, not a zero.</p>");
      if (ev.night_flags > 0) {
        out.push("<p><strong>Pixels flagged after dark: " + ev.night_flags +
                 ".</strong></p>");
        out.push("<ul>" + ev.flags.map((f) =>
          "<li>" + esc(String(f.acq_time_wit).slice(11, 16)) + " WIT, " +
          f.lat + ", " + f.lon + " — B07 anomaly +" + f.anomaly_k + " K</li>"
        ).join("") + "</ul>");
      } else {
        out.push("<p><strong>" + EVENING_NONE_AFTER_DARK + "</strong></p>");
      }
      if (ev.daylight_flags > 0)
        out.push("<p>Daylight flags before sunset (unreliable — reflected " +
                 "sunlight): " + ev.daylight_flags + " pixels. Listed in the " +
                 "evening file.</p>");
      if (ev.closest_after_dark)
        out.push("<p>Closest to the flag condition after dark: +" +
                 ev.closest_after_dark.anomaly_k + " K anomaly with a " +
                 ev.closest_after_dark.diff_k + " K band difference at " +
                 ev.closest_after_dark.wit + " WIT (" +
                 ev.closest_after_dark.lat + ", " + ev.closest_after_dark.lon +
                 "). Below the flag thresholds and not a detection.</p>");
    }
    out.push("<p class='warn'>That is not evidence that nothing burned: AHI at " +
             "2 km resolves only larger or hotter fires than VIIRS at 375 m " +
             "(about 28 times the pixel area), and a smouldering fire without " +
             "flame may never cross a thermal threshold.</p>");
    $("evening").innerHTML = out.join("");
  } catch (e) {
    $("evening").innerHTML = "<p class='error'>Evening section failed to render: " +
      esc(e.message) + "</p>";
  }

  /* today's brief — most recent brief, hand-rolled markdown subset */
  try {
    const md = await loadText("briefs/" + summary.covered_wit_date + ".md");
    $("brief-date").textContent = "(" + summary.covered_wit_date + " WIT)";
    $("brief").innerHTML = miniMarkdown(md);
  } catch (e) {
    $("brief-date").textContent = "";
    $("brief").innerHTML = "<p class='error'>Brief for the latest day failed to " +
      "load (" + esc(e.message) + "). The Markdown files under docs/briefs/ are " +
      "the source of record.</p>";
  }
})();
