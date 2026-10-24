"use strict";
const $ = (id) => document.getElementById(id);
// The mandated evening null sentence, kept whole in the source so the page
// always states it verbatim (Task 07 check 4).
const EVENING_NONE_AFTER_DARK =
  "No evening thermal anomaly above threshold after dark.";
const esc = (s) => String(s).replace(/[&<>"']/g,
  c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));

function dataError(name, message) {
  const li = document.createElement("li");
  li.textContent = message;
  $("data-errors").appendChild(li);
}

async function loadJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(url + ": HTTP " + r.status);
  return r.json();
}
async function loadText(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(url + ": HTTP " + r.status);
  return r.text();
}


function miniMarkdown(md) {
  const esc = (s) => String(s).replace(/[&<>]/g,
    (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;" }[c]));
  const inline = (s) => esc(s)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const lines = md.split(/\r?\n/);
  const out = [];
  let list = null, table = null, quote = null;
  const flush = () => {
    if (list)  { out.push("<ul>" + list.map((l) => "<li>" + inline(l) + "</li>").join("") + "</ul>"); list = null; }
    if (quote) { out.push("<blockquote>" + quote.map((l) => inline(l)).join("<br>") + "</blockquote>"); quote = null; }
    if (table) { out.push(table.html + "</table>"); table = null; }
  };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (/^\|/.test(line)) {
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;   // separator
      // First pipe row of a block is its header; the rest are body rows.
      // (flush() must NOT run here — it used to close the table after the
      // header, turning every body row into a header of its own table.)
      if (!table) {
        table = { html: "<table><tr>" +
          cells.map((c) => "<th>" + inline(c) + "</th>").join("") + "</tr>" };
      } else {
        table.html += "<tr>" +
          cells.map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>";
      }
      continue;
    }
    flush();
    if (/^### /.test(line)) out.push("<h4>" + inline(line.slice(4)) + "</h4>");
    else if (/^## /.test(line)) out.push("<h3>" + inline(line.slice(3)) + "</h3>");
    else if (/^# /.test(line)) out.push("<h2>" + inline(line.slice(2)) + "</h2>");
    else if (/^- /.test(line)) out.push("<p>• " + inline(line.slice(2)) + "</p>");
    else if (/^> /.test(line)) out.push("<blockquote>" + inline(line.slice(2)) + "</blockquote>");
    else if (line === "") out.push("");
    else out.push("<p>" + inline(line) + "</p>");
  }
  flush();
  return out.join("\n");
}

/* Every page says when its data was generated and which WIT day the brief
   covers. A failed summary is a gap in the record, never a zero, so the
   banner says so and the caller gets null rather than an empty object. */
async function loadSummary() {
  try {
    const summary = await loadJSON("data/summary_latest.json");
    $("generated").textContent = "Data generated: " + summary.generated_utc +
      " UTC. Brief day covered: " + summary.covered_wit_date + " (WIT).";
    return summary;
  } catch (e) {
    dataError("summary", "summary_latest.json failed to load — the generation " +
      "time and the covered day are unavailable. " + e.message);
    return null;
  }
}
