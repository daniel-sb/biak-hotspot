"use strict";
/* history.html - the full detection record. */
(async () => {
  await loadSummary();
  /* timeline — daily counts over the full record, linear axis */
  try {
    const daily = await loadJSON("data/daily_counts.json");
    drawTimeline(daily);
  } catch (e) {
    $("timeline-error").innerHTML = "<p class='error'>daily_counts.json failed " +
      "to load — the detection timeline is unavailable. " + esc(e.message) + "</p>";
  }
})();
