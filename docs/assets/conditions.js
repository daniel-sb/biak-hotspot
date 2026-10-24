"use strict";
/* conditions.html - water balance and the vegetation indices with their
   composite-quality confound. */
(async () => {
  await loadSummary();
  /* drought — monthly water balance and precipitation vs climatology */
  try {
    drawDrought(await loadJSON("data/drought.json"));
  } catch (e) {
    $("drought-error").innerHTML = "<p class='error'>drought.json failed to load — " +
      "the drought context is unavailable, which is not a statement about the " +
      "weather. " + esc(e.message) + "</p>";
  }

  /* vegetation — NDVI/NDMI anomalies with their composite-quality confound */
  try {
    drawVegetation(await loadJSON("data/vegetation.json"));
  } catch (e) {
    $("veg-error").innerHTML = "<p class='error'>vegetation.json failed to " +
      "load — the vegetation indices and their good-pixel shares are " +
      "unavailable. " + esc(e.message) + "</p>";
  }
})();
