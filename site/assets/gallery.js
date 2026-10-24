"use strict";
/* The burn atlas. Everything on this page comes from data/gallery.json, which
   scripts/burn_atlas.py writes next to the plates it renders, so a plate and
   its caption cannot drift apart. */

function ha(v) {
  return v === null || v === undefined
    ? null
    : v.toLocaleString(undefined, { minimumFractionDigits: 1,
                                    maximumFractionDigits: 1 }) + " ha";
}

function witDay(stamp) {
  return typeof stamp === "string" ? stamp.slice(0, 10) : "";
}

function plateHtml(p) {
  const mapped = ha(p.changed_ha);
  const footprint = ha(p.footprint_ha);
  const extent = mapped
    ? "The product maps " + esc(mapped) + " of change inside a " +
      esc(footprint) + " footprint."
    : "No area was assessed for this event, because no usable local " +
      "reference existed. That is an absent figure, not a zero.";
  return '<figure class="mt-6 border border-rule bg-paper">' +
    '<a href="' + esc(p.file) + '">' +
    '<img class="block w-full h-auto" loading="lazy" src="' + esc(p.file) +
    '" alt="Cartographic plate of the ' + esc(p.desa) +
    " burn footprint, event " + esc(p.event) + ', Sentinel-2 ' +
    esc(p.date) + '" width="2100" height="1740"></a>' +
    '<figcaption class="border-t border-rule px-3 py-2 text-[0.86rem] leading-snug">' +
    "<strong>" + esc(p.desa) + " — " + esc(p.event) + ".</strong> " +
    esc(extent) + " Detected " + esc(witDay(p.first_seen_wit)) + " to " +
    esc(witDay(p.last_seen_wit)) + " WIT, " + esc(p.detections) +
    " detections. " + esc(p.n_label_boxes) +
    " interpretation boxes fall inside the frame. Scene of " +
    esc(p.date) + "; the strip runs " + esc(p.series_dates[0]) + " to " +
    esc(p.series_dates[p.series_dates.length - 1]) + "." +
    ' <a class="underline decoration-rule underline-offset-2 hover:decoration-ember" href="' +
    esc(p.file) + '">Full plate</a> · ' +
    '<a class="underline decoration-rule underline-offset-2 hover:decoration-ember" href="gallery/' +
    esc(p.event) + '.geolibre.json">GeoLibre project</a>' +
    "</figcaption></figure>";
}

(async () => {
  try {
    const index = await loadJSON("data/gallery.json");
    const plates = index.plates || [];
    if (!plates.length) {
      /* An empty index is a build that produced nothing, which must not read
         as "no footprints were mapped". */
      dataError("gallery", "The burn atlas index (gallery.json) loaded but " +
        "lists no plates. That is a build problem, not a statement that " +
        "nothing burned.");
      return;
    }
    $("gallery").innerHTML = plates.map(plateHtml).join("");
  } catch (e) {
    dataError("gallery", "The burn atlas (gallery.json) failed to load — no " +
      "plates are shown. " + e.message);
    $("gallery-error").textContent =
      "The atlas index did not load, so no plates are shown here.";
  }
})();
