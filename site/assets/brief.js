"use strict";
/* brief.html - the daily brief and the previous evening's Himawari result.
   Both are present tense, which is why they are no longer on the front page
   (adr/0001). The front page is a record of the 2026 season; this page is
   what the satellites saw most recently. */
(async () => {
  const summary = await loadSummary();
  if (!summary) {
    $("evening").innerHTML = "<p class='error'>Evening product unavailable \u2014 " +
      "summary data failed to load. A gap in the record is not a zero.</p>";
    $("brief").innerHTML = "<p class='error'>Brief unavailable \u2014 summary data " +
      "failed to load.</p>";
    return;
  }

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
