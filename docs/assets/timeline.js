"use strict";
/* timeline: linear-scale SVG bars over the full record */
function drawTimeline(daily) {
  const W = 1000, H = 200, padL = 40, padB = 24, padT = 14;
  const svg = document.getElementById("timeline");
  const max = Math.max(1, ...daily.map((d) => d[1]));
  const iw = W - padL - 10, ih = H - padT - padB;
  const bw = iw / daily.length;
  const y = (n) => padT + ih - (n / max) * ih;
  const parts = [];
  parts.push("<line x1='" + padL + "' y1='" + (padT + ih) + "' x2='" +
             (W - 10) + "' y2='" + (padT + ih) + "' stroke='#9a9a9a'/>");
  [[max, "#c9c9c9"], [max / 2, "#e4e4e4"]].forEach(([v, col]) => {
    parts.push("<line x1='" + padL + "' y1='" + y(v) + "' x2='" + (W - 10) +
               "' y2='" + y(v) + "' stroke='" + col + "' stroke-dasharray='3,3'/>");
    parts.push("<text x='" + (padL - 4) + "' y='" + (y(v) + 3) +
               "' font-size='10' text-anchor='end' fill='#777'>" + v + "</text>");
  });
  let lastYear = "";
  daily.forEach(([d, n], i) => {
    const x = padL + i * bw;
    const yr = d.slice(0, 4);
    if (yr !== lastYear) {
      parts.push("<text x='" + (x + 2) + "' y='" + (H - 8) +
                 "' font-size='10' fill='#777'>" + yr + "</text>");
      lastYear = yr;
    }
    if (n > 0) {
      const hgt = Math.max(0.5, (n / max) * ih);
      parts.push("<rect x='" + x.toFixed(2) + "' y='" + (y(n)).toFixed(2) +
                 "' width='" + Math.max(bw - 0.4, 0.4).toFixed(2) +
                 "' height='" + hgt.toFixed(2) + "' fill='#c26a1e'>" +
                 "<title>" + d + ": " + n + "</title></rect>");
    }
  });
  const peak = daily.reduce((a, b) => (b[1] > a[1] ? b : a), daily[0]);
  parts.push("<text x='" + (padL + daily.indexOf(peak) * bw) + "' y='" +
             (y(peak[1]) - 4) + "' font-size='10' fill='#7a3010'>" + peak[1] +
             " on " + peak[0] + "</text>");
  svg.innerHTML = parts.join("");
}
