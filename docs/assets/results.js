"use strict";
/* results.html - the two area figures, the strata behind the estimate, and
   what neither supports. Every number comes from docs/data/headline.json
   (src/headline_figures.py); none is written into the page. */

const ha = (n) => n.toLocaleString("en-GB", { maximumFractionDigits: 0 }) + " ha";

function areaTable(doc) {
  const m = doc.mapped, v = doc.validated;
  const rows = [
    ["Mapped extent, " + doc.season_year, ha(m.ha), m.scope],
    ["Estimated burned, labelled footprints",
     ha(v.estimate_ha) + " (" + Math.round(v.ci95_ha[0]) + "–" +
     Math.round(v.ci95_ha[1]) + ")", v.scope],
    ["Mapped extent inside those footprints", ha(v.mapped_in_footprints_ha),
     "The part of the figure above that the estimate can be compared with. " +
     "This is the number that falls outside the interval."],
  ];
  $("area-table").querySelector("tbody").innerHTML = rows.map((r) =>
    "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td><td>" +
    esc(r[2]) + "</td></tr>").join("");
}

/* One axis, three marks: the interval, the estimate on it, and the product's
   mapped extent as a tick that lands outside it. */
function drawInterval(v) {
  const svg = $("res-interval");
  const W = 560, padL = 30, padR = 30, y = 26;
  const lo = v.ci95_ha[0], hi = v.ci95_ha[1], mapped = v.mapped_in_footprints_ha;
  const min = Math.min(lo, mapped), max = Math.max(hi, v.estimate_ha);
  const pad = (max - min) * 0.14 || 1;
  const x = (val) => padL +
    ((val - (min - pad)) / ((max + pad) - (min - pad))) * (W - padL - padR);
  const label = (val, text, anchor) =>
    '<text x="' + x(val) + '" y="12" font-size="10" fill="#5a5a5a" ' +
    'text-anchor="' + anchor + '">' + text + "</text>";
  svg.innerHTML = [
    '<line x1="' + x(lo) + '" x2="' + x(hi) + '" y1="' + y + '" y2="' + y +
      '" stroke="#2a78d6" stroke-width="3"/>',
    '<line x1="' + x(lo) + '" x2="' + x(lo) + '" y1="' + (y - 6) + '" y2="' +
      (y + 6) + '" stroke="#2a78d6" stroke-width="2"/>',
    '<line x1="' + x(hi) + '" x2="' + x(hi) + '" y1="' + (y - 6) + '" y2="' +
      (y + 6) + '" stroke="#2a78d6" stroke-width="2"/>',
    '<circle cx="' + x(v.estimate_ha) + '" cy="' + y + '" r="5" fill="#2a78d6"/>',
    '<line x1="' + x(mapped) + '" x2="' + x(mapped) + '" y1="' + (y - 10) +
      '" y2="' + (y + 10) + '" stroke="#eb6834" stroke-width="2.5"/>',
    label(v.estimate_ha, "estimate " + Math.round(v.estimate_ha) + " ha", "middle"),
    label(mapped, "product " + Math.round(mapped) + " ha", "middle"),
    '<text x="' + x(lo) + '" y="' + (y + 20) + '" font-size="9" fill="#5a5a5a" ' +
      'text-anchor="middle">' + Math.round(lo) + "</text>",
    '<text x="' + x(hi) + '" y="' + (y + 20) + '" font-size="9" fill="#5a5a5a" ' +
      'text-anchor="middle">' + Math.round(hi) + "</text>",
  ].join("");
  $("res-interval-note").textContent =
    "Blue: the stratified estimate and its 95% interval. Orange: what the " +
    "product mapped over the same ground, " + ha(mapped) + ", which is " +
    ha(v.omission_ha) + " short of the estimate and below the interval.";
}

function strataTable(v) {
  const rows = Object.entries(v.strata).map(([name, s]) =>
    "<tr><td>" + esc(name.replace(/_/g, " ")) + "<br><span class='muted'>" +
    esc(s.sample) + "</span></td><td>" + esc(ha(s.area_ha)) + "</td><td>" +
    s.judged + "</td><td>" + s.burned + "</td><td>" +
    (s.rate * 100).toFixed(1) + "% (" + (s.ci95[0] * 100).toFixed(1) +
    "–" + (s.ci95[1] * 100).toFixed(1) + ")</td></tr>");
  $("strata-table").querySelector("tbody").innerHTML = rows.join("");
  $("strata-what").textContent = v.events;
}

(async () => {
  await loadSummary();
  try {
    const doc = await loadJSON("data/headline.json");
    areaTable(doc);
    drawInterval(doc.validated);
    strataTable(doc.validated);
  } catch (e) {
    $("results-error").innerHTML = "<p class='error'>headline.json failed to " +
      "load — the figures on this page are unavailable, which is not a " +
      "statement about what burned. " + esc(e.message) + "</p>";
  }
})();
