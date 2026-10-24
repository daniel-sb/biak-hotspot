"use strict";
function drawDrought(doc) {
  const rows = doc.monthly;
  const W = 1000, padL = 44, padR = 12;
  const topY = 18, topH = 92, botY = 154, botH = 92;
  const iw = W - padL - padR, bw = iw / rows.length;
  const x = (i) => padL + i * bw;
  const parts = [];
  const text = (xx, yy, s, extra) => "<text x='" + xx.toFixed(1) + "' y='" +
    yy.toFixed(1) + "' font-size='10' " + (extra || "") + ">" + s + "</text>";

  /* upper panel: water balance, diverging about zero */
  const bal = rows.map((r) => r.p_minus_et_mm).filter((v) => v !== null);
  const vmax = Math.max(0, ...bal), vmin = Math.min(0, ...bal);
  const yT = (v) => topY + topH * (vmax - v) / (vmax - vmin || 1);
  parts.push(text(padL, topY - 5, "Water balance P &#8722; ET (mm per month)",
                  "fill='#333'"));
  rows.forEach((r, i) => {
    if (r.p_minus_et_mm === null) return;
    const v = r.p_minus_et_mm, y0 = yT(0), y1 = yT(v);
    parts.push("<rect x='" + x(i).toFixed(2) + "' y='" + Math.min(y0, y1).toFixed(2) +
      "' width='" + Math.max(bw - 1, 0.6).toFixed(2) + "' height='" +
      Math.max(Math.abs(y1 - y0), 0.6).toFixed(2) + "' fill='" +
      (v < 0 ? "#b03a2e" : "#4b7f9c") + "'/>");
  });
  parts.push("<line x1='" + padL + "' y1='" + yT(0).toFixed(1) + "' x2='" + (W - padR) +
             "' y2='" + yT(0).toFixed(1) + "' stroke='#6a6a6a'/>");
  parts.push(text(padL - 4, yT(vmax) + 3, Math.round(vmax),
                  "text-anchor='end' fill='#777'"));
  parts.push(text(padL - 4, yT(0) + 3, "0", "text-anchor='end' fill='#777'"));
  // the deficit is small in millimetres next to a 400 mm surplus, so its tick
  // can land on top of the zero tick. Drop it rather than nudge it: the
  // callout below states the number, and a shifted tick would misplace it.
  if (vmin < 0 && yT(vmin) - yT(0) > 11)
    parts.push(text(padL - 4, yT(vmin) + 3, Math.round(vmin),
                    "text-anchor='end' fill='#777'"));

  /* lower panel: precipitation against the calendar-month climatology */
  const clim = (r) => doc.climatology[r.month.slice(5, 7)];
  const pmax = Math.max(...rows.map((r) => Math.max(
    r.precip_mm === null ? 0 : r.precip_mm, clim(r).mean_mm + clim(r).sd_mm)));
  const yB = (v) => botY + botH * (1 - v / (pmax || 1));
  const cx = (i) => x(i) + bw / 2;
  parts.push(text(padL, botY - 5,
    "Precipitation (mm), band = 1981&#8211;2025 mean &#177;1 s.d.", "fill='#333'"));
  const upper = rows.map((r, i) => cx(i).toFixed(1) + "," +
    yB(clim(r).mean_mm + clim(r).sd_mm).toFixed(1));
  const lower = rows.map((r, i) => cx(i).toFixed(1) + "," +
    yB(Math.max(0, clim(r).mean_mm - clim(r).sd_mm)).toFixed(1)).reverse();
  parts.push("<polygon points='" + upper.concat(lower).join(" ") +
             "' fill='#d9e2e8'/>");
  parts.push("<polyline fill='none' stroke='#8fa6b2' points='" +
    rows.map((r, i) => cx(i).toFixed(1) + "," + yB(clim(r).mean_mm).toFixed(1))
        .join(" ") + "'/>");
  parts.push("<polyline fill='none' stroke='#1f4e63' stroke-width='1.4' points='" +
    rows.filter((r) => r.precip_mm !== null)
        .map((r) => cx(rows.indexOf(r)).toFixed(1) + "," + yB(r.precip_mm).toFixed(1))
        .join(" ") + "'/>");
  [pmax, pmax / 2].forEach((v) => parts.push(
    text(padL - 4, yB(v) + 3, Math.round(v), "text-anchor='end' fill='#777'")));
  parts.push("<line x1='" + padL + "' y1='" + yB(0).toFixed(1) + "' x2='" + (W - padR) +
             "' y2='" + yB(0).toFixed(1) + "' stroke='#9a9a9a'/>");

  /* year ticks, and the driest month called out where it sits */
  let lastYear = "";
  rows.forEach((r, i) => {
    const yr = r.month.slice(0, 4);
    if (yr !== lastYear) {
      parts.push(text(x(i) + 1, 268, yr, "fill='#777'"));
      parts.push("<line x1='" + x(i).toFixed(1) + "' y1='" + topY + "' x2='" +
                 x(i).toFixed(1) + "' y2='246' stroke='#ececec'/>");
      lastYear = yr;
    }
  });
  /* A 24 mm deficit is a sliver beside a 400 mm surplus, and on a linear
     axis it looks like nothing. The axis stays linear - the callout carries
     what the pixels cannot, which is that it is the only month here that
     went negative at all. */
  const cur = doc.current;
  const negatives = rows.filter((r) => r.p_minus_et_mm !== null &&
                                       r.p_minus_et_mm < 0).length;
  const ci = rows.findIndex((r) => r.month === cur.month);
  if (ci >= 0) {
    const label = cur.month + ": " + cur.p_minus_et_mm + " mm" +
      (negatives === 1 ? ", the only month here that lost water" : "") +
      " — " + cur.precip_mm + " mm rain, z " + cur.z + ", " +
      cur.rank_driest + " driest of " + cur.rank_of;
    parts.push(text(Math.max(padL, Math.min(cx(ci) + 4, W - 6 * label.length)),
      yT(Math.min(cur.p_minus_et_mm, 0)) + 13, label, "fill='#7a1010'"));
  }

  /* one hover target per month, carrying the numbers behind the drawing */
  rows.forEach((r, i) => {
    const c = clim(r);
    parts.push("<rect x='" + x(i).toFixed(2) + "' y='" + topY + "' width='" +
      bw.toFixed(2) + "' height='" + (246 - topY) + "' fill='transparent'><title>" +
      r.month + " — precipitation " + r.precip_mm + " mm (mean " + c.mean_mm +
      " mm over " + c.years + " years), evapotranspiration " + r.et_mm +
      " mm, balance " + r.p_minus_et_mm + " mm</title></rect>");
  });
  $("drought").innerHTML = parts.join("");

  const cov = doc.coverage;
  $("drought-coverage").textContent =
    rows[0].month + " to " + cov.chirps_last_complete_month;
  $("drought-lag").textContent =
    "Coverage lag. CHIRPS precipitation runs to " + cov.chirps_last_date +
    ", so the last complete month here is " + cov.chirps_last_complete_month +
    "; evapotranspiration (MOD16A2) runs to " + cov.et_last_date + ". Both end " +
    "before the day the brief above covers. This panel describes the season the " +
    "hotspots occurred in, not the week they occurred in.";
}

/* vegetation: NDVI/NDMI anomalies with their good-pixel share on sub-panels.
   The confound is the point: the index tracks observation quality, so both
   series share an x axis (Task 11, PLAN.md 14). */
function drawVegetation(doc) {
  const rows = doc.monthly;
  const W = 1000, padL = 44, padR = 12;
  const topY = 16, topH = 110, gap = 16;
  const botY = topY + topH + gap, botH = 110;
  const H = botY + botH + 34;
  const iw = W - padL - padR, n = rows.length, bw = iw / n;
  const x = (i) => padL + i * bw;
  const parts = [];
  const text = (xx, yy, s, extra) => "<text x='" + xx.toFixed(1) + "' y='" +
    yy.toFixed(1) + "' font-size='10' " + (extra || "") + ">" + s + "</text>";

  /* filter to months with data (some months have NDVI but not NDMI, or
     neither, if a composite is missing) */
  const nd = rows.filter((r) => r.ndvi_anomaly !== null &&
    r.ndvi_good_share !== null);
  const nm = rows.filter((r) => r.ndmi_anomaly !== null &&
    r.ndmi_good_share !== null);
  const ndviI = rows.map((r) => r.ndvi_anomaly).indexOf(
    nd.length ? nd[0].ndvi_anomaly : null);

  /* helper: y for the anomaly panel (centred on zero) */
  const anomMax = Math.max(
    0.02, ...rows.map((r) => Math.abs(r.ndvi_anomaly || 0)),
    ...rows.map((r) => Math.abs(r.ndmi_anomaly || 0)));
  const ay = (v) => topY + topH / 2 - (v / anomMax) * (topH / 2);

  /* helper: y for the share panel (0 at bottom, 1 at top) */
  const sy = (v) => botY + botH - v * botH;

  /* zero baselines */
  parts.push("<line x1='" + padL + "' y1='" + ay(0) + "' x2='" + (W - 12) +
    "' y2='" + ay(0) + "' stroke='#9a9a9a'/>");
  parts.push("<line x1='" + padL + "' y1='" + sy(0) + "' x2='" + (W - 12) +
    "' y2='" + sy(0) + "' stroke='#9a9a9a'/>");
  parts.push("<line x1='" + padL + "' y1='" + sy(1) + "' x2='" + (W - 12) +
    "' y2='" + sy(1) + "' stroke='#e4e4e4' stroke-dasharray='3,3'/>");

  /* NDVI anomaly line */
  if (nd.length > 1) {
    const pts = nd.map((r) => {
      const i = rows.indexOf(r);
      return x(i).toFixed(1) + "," + ay(r.ndvi_anomaly).toFixed(1);
    }).join(" ");
    parts.push("<polyline points='" + pts + "' fill='none' " +
      "stroke='#2e7d32' stroke-width='1.5'/>");
  }

  /* NDMI anomaly line */
  if (nm.length > 1) {
    const pts = nm.map((r) => {
      const i = rows.indexOf(r);
      return x(i).toFixed(1) + "," + ay(r.ndmi_anomaly).toFixed(1);
    }).join(" ");
    parts.push("<polyline points='" + pts + "' fill='none' " +
      "stroke='#1565c0' stroke-width='1.5' stroke-dasharray='4,2'/>");
  }

  /* NDVI good-pixel share area + line */
  if (nd.length > 1) {
    const pts = nd.map((r) => {
      const i = rows.indexOf(r);
      return x(i).toFixed(1) + "," + sy(r.ndvi_good_share).toFixed(1);
    }).join(" ");
    parts.push("<polyline points='" + pts + "' fill='none' " +
      "stroke='#66bb6a' stroke-width='1.2'/>");
  }

  /* NDMI good-pixel share line */
  if (nm.length > 1) {
    const pts = nm.map((r) => {
      const i = rows.indexOf(r);
      return x(i).toFixed(1) + "," + sy(r.ndmi_good_share).toFixed(1);
    }).join(" ");
    parts.push("<polyline points='" + pts + "' fill='none' " +
      "stroke='#64b5f6' stroke-width='1.2' stroke-dasharray='4,2'/>");
  }

  /* sub-panel labels */
  parts.push(text(padL + 4, topY + 10, "anomaly (departure from 2001-2025 mean)",
    "fill='#2e7d32'"));
  parts.push(text(padL + 4, botY + 12, "good-pixel share",
    "fill='#66bb6a'"));
  parts.push(text(W - 12, topY + 10, "NDVI (solid green) \u00b7 NDMI (dashed blue)",
    "fill='#777' text-anchor='end'"));

  /* year ticks */
  let lastYear = "";
  rows.forEach((r, i) => {
    const yr = r.month.slice(0, 4);
    if (yr !== lastYear) {
      parts.push(text(x(i) + 2, H - 8, yr, "fill='#777' font-size='10'"));
      lastYear = yr;
    }
  });

  /* hover titles */
  rows.forEach((r, i) => {
    if (r.ndvi !== null || r.ndmi !== null) {
      const bits = [r.month];
      if (r.ndvi !== null) bits.push("NDVI " + r.ndvi.toFixed(4) +
        " (share " + (r.ndvi_good_share * 100).toFixed(0) + "%)");
      if (r.ndmi !== null) bits.push("NDMI " + r.ndmi.toFixed(4) +
        " (share " + (r.ndmi_good_share * 100).toFixed(0) + "%)");
      parts.push("<rect x='" + x(i).toFixed(2) + "' y='" + topY +
        "' width='" + bw.toFixed(2) + "' height='" + (botY + botH - topY) +
        "' fill='transparent'><title>" + bits.join(" | ") + "</title></rect>");
    }
  });

  /* anomalies scale label */
  parts.push(text(padL - 4, ay(0) + 3, "0", "fill='#777' font-size='10' " +
    "text-anchor='end'"));
  parts.push(text(padL - 4, ay(anomMax) + 3, "+" + anomMax.toFixed(2),
    "fill='#777' font-size='10' text-anchor='end'"));
  parts.push(text(padL - 4, ay(-anomMax) + 3, "\u2212" + anomMax.toFixed(2),
    "fill='#777' font-size='10' text-anchor='end'"));
  /* shares scale label */
  parts.push(text(padL - 4, sy(0) + 3, "0%", "fill='#777' font-size='10' " +
    "text-anchor='end'"));
  parts.push(text(padL - 4, sy(1) + 3, "100%", "fill='#777' font-size='10' " +
    "text-anchor='end'"));

  const svg = document.getElementById("veg");
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.innerHTML = parts.join("");

  const cov = doc.coverage;
  $("veg-coverage").textContent =
    rows[0].month + " to " + (cov.mod13a1_last_date || "").slice(0, 7);

  const corr = doc.qa_correlation;
  $("veg-corr").textContent =
    "Composite quality tracks the index: NDVI r = " + (corr.ndvi_all.r ?? "?") +
    " (n = " + (corr.ndvi_all.n ?? "?") + "), NDMI r = " +
    (corr.ndmi_all.r ?? "?") + " (n = " + (corr.ndmi_all.n ?? "?") +
    "); July only: NDVI r = " + (corr.ndvi_july.r ?? "?") + " (n = " +
    (corr.ndvi_july.n ?? "?") + "), NDMI r = " + (corr.ndmi_july.r ?? "?") +
    " (n = " + (corr.ndmi_july.n ?? "?") + "). A dry month is also a less " +
    "cloudy month: the composite is built from more and better observations, " +
    "and the index tracks observation quality, not vegetation.";
}

/* hand-rolled markdown subset: headings, bold, lists, tables, blockquotes.
   No library (Task 07). Underscore is deliberately NOT an emphasis marker:
   it appears inside satellite names and filenames (VIIRS_SNPP_NRT,
   hotspots_latest.geojson) and eating it corrupts exactly the strings a
   reader needs to be exact (Task 07b). The briefs use * for emphasis. */
