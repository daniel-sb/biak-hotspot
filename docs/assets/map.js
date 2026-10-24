"use strict";
/* ---------- map ----------
   The map initialises with an INLINE fallback style, so "load" fires without
   any network and the local GeoJSON layers (same origin as the page) are
   never hostage to a CDN. The OpenFreeMap basemap is fetched separately as
   an upgrade; if it fails, a banner says so and the data still draws. */
const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
const FALLBACK_STYLE = {
  version: 8,
  // glyphs come from the same basemap provider as the tiles, so the
  // recurrent-location label renders even before the basemap upgrade
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {},
  layers: [{ id: "background", type: "background",
             paint: { "background-color": "#dfe7ee" } }],
};
const map = new maplibregl.Map({
  container: "map",
  style: FALLBACK_STYLE,
  center: [135.5, -0.2],
  zoom: 7.4,
  attributionControl: { compact: false },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
map.fitBounds([[134.25, -1.45], [136.76, 1.0]], { padding: 24, duration: 0 });

const mapErrorsShown = new Set();
map.on("error", (e) => {
  /* GIBS tops out at zoom 9 (z10 returns HTTP 400), so panning or zooming
     in produces tile errors that are not failures of the page. Whether the
     imagery exists at all is settled once, by probe, before a layer is
     added — see setImagery. Letting overzoom raise the banner would turn
     the honest-degradation mechanism into noise, and the next person would
     mute it. */
  if (e && typeof e.sourceId === "string" && e.sourceId.startsWith("gibs-"))
    return;
  const where = e && e.sourceId ? " (" + e.sourceId + ")" : "";
  const msg = e && e.error ? e.error.message : "unknown map error";
  const full = "Map error" + where + ": " + msg;
  if (mapErrorsShown.has(full)) return;
  mapErrorsShown.add(full);
  dataError("map", full);
});

/* Local data is fetched once and (re)added to whatever style is current.
   addLocalLayers is idempotent: after a basemap upgrade replaces the style
   (setStyle drops everything the page added), the layers are rebuilt from
   the cached GeoJSON objects. */
const localData = { desa: null, hotspots: null, recurrent: null,
                    burned: null, labels: null };
/* Every source addLocalLayers() can create. The basemap-upgrade timer stops
   re-adding layers once they all exist, so this list has to be derived from
   localData rather than written out: naming three of five here is how the two
   newest layers silently stopped being added after a style swap. */
const LOCAL_SOURCES = Object.keys(localData);

/* ---------- NASA GIBS imagery ----------
   Google's tile terms forbid use outside Google's own APIs and Esri's
   expect an ArcGIS account for production, so neither belongs on a public
   page. GIBS is free, keyless and documented for reuse.

   Note the axis order: {z}/{y}/{x}, not the {z}/{x}/{y} most XYZ templates
   use. GoogleMapsCompatible_Level9 is the only matrix set these layers
   publish, so maxzoom is 9 and MapLibre overzooms beyond it; at level 9 the
   world is 131,072 px wide, about 300 m per pixel. */
const GIBS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" +
  "{LAYER}/default/{DATE}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg";
const GIBS_ATTRIB = '<a href="https://worldview.earthdata.nasa.gov/" ' +
  'target="_blank" rel="noopener">NASA GIBS/Worldview</a>';
const ESRI_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/" +
  "World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ESRI_ATTRIB = "Esri World Imagery (Esri, Maxar, Earthstar Geographics " +
  "and the GIS User Community)";

/* kind "gibs" is a dated WMTS layer, probed for availability on the day the
   page describes. kind "xyz" is a static mosaic with no single date, which is
   why its note has to say so: a reader comparing an undated mosaic against a
   2026 burn polygon can otherwise read a difference that is only a difference
   of years. */
const IMAGERY = {
  esri: {
    kind: "xyz",
    tiles: ESRI_URL,
    maxzoom: 19,
    attrib: ESRI_ATTRIB,
    label: "Esri World Imagery",
    note: "A mosaic assembled from imagery of many different dates, with no " +
          "single acquisition date for any one place. It shows the ground at " +
          "some time before now, not the ground during this season, so it " +
          "cannot date a change and must not be read against the burn " +
          "polygons as a before image.",
  },
  truecolor: {
    kind: "gibs",
    layer: "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
    label: "Corrected Reflectance (True Color, VIIRS, NOAA-20)",
    note: "Smoke appears as grey-brown haze. One image per day, served to " +
          "about 300 m per pixel, and cloud hides what is beneath it — an " +
          "absence of visible smoke is not an absence of smoke.",
  },
  swir: {
    kind: "gibs",
    layer: "VIIRS_SNPP_CorrectedReflectance_BandsM11-I2-I1",
    label: "Corrected Reflectance (M11-I2-I1, VIIRS, Suomi NPP)",
    note: "A band combination, not a fire detection: red is reflectance in " +
          "the shortwave infrared, which burned ground and active flame " +
          "both raise. It confirms nothing on its own.",
  },
};
let imageryDate = null;      // set from the brief's covered WIT day
let imageryChoice = "";      // "" | "truecolor" | "swir"
const imageryProbed = new Map();

const gibsUrl = (key, date) => GIBS_URL
  .replace("{LAYER}", IMAGERY[key].layer).replace("{DATE}", date);

/* One probe per layer/date settles availability, so runtime tile errors can
   be ignored without hiding a genuinely missing date. */
async function imageryAvailable(key, date) {
  const cacheKey = key + "|" + date;
  if (imageryProbed.has(cacheKey)) return imageryProbed.get(cacheKey);
  const probe = gibsUrl(key, date)
    .replace("{z}", "5").replace("{y}", "16").replace("{x}", "25");
  let ok = false;
  try { ok = (await fetch(probe, { method: "GET" })).ok; } catch (e) { ok = false; }
  imageryProbed.set(cacheKey, ok);
  return ok;
}

function imageryNote(text, unavailable) {
  const el = $("imagery-note");
  el.textContent = text;
  el.className = unavailable ? "unavailable" : "";
}

/* Rebuilt with the vector layers so the imagery survives the basemap
   upgrade, and added first so it always sits beneath them. */
function addImagery() {
  for (const key of Object.keys(IMAGERY)) {
    const id = "img-" + key;
    if (key === imageryChoice) continue;
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }
  if (!imageryChoice) return;
  const spec = IMAGERY[imageryChoice];
  if (spec.kind === "gibs" && !imageryDate) return;
  const id = "img-" + imageryChoice;
  if (!map.getSource(id))
    map.addSource(id, spec.kind === "gibs"
      ? { type: "raster", tileSize: 256, maxzoom: 9,
          tiles: [gibsUrl(imageryChoice, imageryDate)],
          attribution: GIBS_ATTRIB }
      : { type: "raster", tileSize: 256, maxzoom: spec.maxzoom,
          tiles: [spec.tiles], attribution: spec.attrib });
  if (!map.getLayer(id))
    map.addLayer({ id, type: "raster", source: id,
                   paint: { "raster-opacity": 0.85 } },
                 firstVectorLayer());
}

/* Imagery is inserted beneath whichever vector layer currently sits lowest,
   so it never covers the data regardless of which layers are switched on. */
function firstVectorLayer() {
  for (const id of ["burned-fill", "labels-fill", "desa-lines", "hotspots"])
    if (map.getLayer(id)) return id;
  return undefined;
}

async function setImagery(key) {
  if (!key) {
    imageryChoice = "";
    addImagery();
    imageryNote("");
    return;
  }
  if (IMAGERY[key].kind === "xyz") {
    imageryChoice = key;
    addImagery();
    imageryNote(IMAGERY[key].label + " — " + IMAGERY[key].note);
    return;
  }
  if (!imageryDate) {
    imageryNote("Imagery needs the brief's date, which has not loaded.", true);
    return;
  }
  imageryNote("Loading " + IMAGERY[key].label + "…");
  if (!await imageryAvailable(key, imageryDate)) {
    imageryChoice = "";
    addImagery();
    imageryNote("Imagery unavailable for " + imageryDate + " (" +
                IMAGERY[key].label + "). This is a gap in the imagery " +
                "record, not an observation.", true);
    return;
  }
  imageryChoice = key;
  addImagery();
  imageryNote(IMAGERY[key].label + " — " + imageryDate + " (WIT day of the " +
              "brief). " + IMAGERY[key].note);
}

document.querySelectorAll('input[name="imagery"]').forEach((el) => {
  el.addEventListener("change", () => setImagery(el.value));
});

function addLocalLayers() {
  addImagery();
  if (localData.desa) {
    if (!map.getSource("desa"))
      map.addSource("desa", { type: "geojson", data: localData.desa });
    if (!map.getLayer("desa-lines"))
      map.addLayer({
        id: "desa-lines", type: "line", source: "desa",
        paint: { "line-color": "#8a8a8a", "line-width": 0.7,
                 "line-opacity": 0.8 },
      });
  }
  if (localData.hotspots) {
    if (!map.getSource("hotspots"))
      map.addSource("hotspots", { type: "geojson", data: localData.hotspots });
    if (!map.getLayer("hotspots"))
      map.addLayer({
        id: "hotspots", type: "circle", source: "hotspots",
        paint: {
          // sized and coloured by FRP (MW); confidence is never an encoding
          "circle-radius": ["interpolate", ["linear"],
            ["to-number", ["get", "frp"], 0], 0, 3, 10, 5, 50, 9, 200, 14],
          "circle-color": ["interpolate", ["linear"],
            ["to-number", ["get", "frp"], 0], 0, "#ffb14a", 10, "#f2762b",
            50, "#e05515", 200, "#c22e12"],
          "circle-stroke-color": "#5a1408", "circle-stroke-width": 1,
          "circle-opacity": 0.85,
        },
      });
  }
  /* Burn polygons: an observation of ground state, published at native
     resolution with no attribute table beyond the event they belong to
     (adr/0006). */
  if (localData.burned) {
    if (!map.getSource("burned"))
      map.addSource("burned", { type: "geojson", data: localData.burned });
    if (!map.getLayer("burned-fill"))
      map.addLayer({
        id: "burned-fill", type: "fill", source: "burned",
        paint: { "fill-color": "#8c2f10", "fill-opacity": 0.38 },
      });
    if (!map.getLayer("burned-line"))
      map.addLayer({
        id: "burned-line", type: "line", source: "burned",
        paint: { "line-color": "#6d2309", "line-width": 0.6 },
      });
  }
  /* Label boxes: one interpreter's reading of 1 m imagery, not an
     observation. Coloured by the judgement, because hiding it would make the
     layer pointless, and the popup carries the limitation that no second
     interpreter ever checked it (F24). */
  if (localData.labels) {
    if (!map.getSource("labels"))
      map.addSource("labels", { type: "geojson", data: localData.labels });
    if (!map.getLayer("labels-fill"))
      map.addLayer({
        id: "labels-fill", type: "fill", source: "labels",
        paint: {
          "fill-color": ["match", ["get", "class"],
            "burned", "#1b6ec2", "unburned", "#1baf7a", "#8a7a3a"],
          "fill-opacity": 0.3,
        },
      });
    if (!map.getLayer("labels-line"))
      map.addLayer({
        id: "labels-line", type: "line", source: "labels",
        paint: {
          "line-color": ["match", ["get", "class"],
            "burned", "#12508c", "unburned", "#128055", "#6a5d2a"],
          "line-width": 1,
        },
      });
  }
  if (localData.recurrent) {
    if (!map.getSource("recurrent"))
      map.addSource("recurrent", { type: "geojson",
                                   data: localData.recurrent });
    if (!map.getLayer("recurrent-ring"))
      map.addLayer({
        id: "recurrent-ring", type: "circle", source: "recurrent",
        paint: { "circle-radius": 13, "circle-color": "transparent",
                 "circle-stroke-color": "#5b3fa8", "circle-stroke-width": 2.5 },
      });
    if (!map.getLayer("recurrent-label"))
      map.addLayer({
        id: "recurrent-label", type: "symbol", source: "recurrent",
        layout: { "text-field": "recurrent location",
                  "text-font": ["Noto Sans Regular"],
                  "text-offset": [0, 1.6], "text-size": 11 },
        paint: { "text-color": "#4a2f8f" },
      });
  }
  applyVisibility();
}

/* Layer-aware click/hover handlers are registered once: they fire whenever
   the layers exist, including after a basemap upgrade re-adds them. */
map.on("click", "hotspots", (e) => {
  const p = e.features[0].properties;
  const distrik = p.distrik ? p.distrik : "outside mapped desa (offshore/water)";
  new maplibregl.Popup()
    .setLngLat(e.lngLat)
    .setHTML(
      "<strong>" + esc(p.acq_date) + "</strong> — " +
      esc((p.datetime_wit || "").slice(11, 16)) + " WIT<br>" +
      "Satellite: " + esc(p.satellite) + "<br>" +
      "Confidence: " + esc(p.confidence) + " (raw instrument code)<br>" +
      "FRP: " + esc(p.frp) + " MW<br>" +
      "Distrik: " + esc(distrik))
    .addTo(map);
});
map.on("mouseenter", "hotspots", () => map.getCanvas().style.cursor = "pointer");
map.on("mouseleave", "hotspots", () => map.getCanvas().style.cursor = "");
map.on("click", "recurrent-ring", (e) => {
  const p = e.features[0].properties;
  new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
    "<strong>Recurrent location</strong><br>" +
    "Hotspots on " + esc(p.days) + " distinct days, " +
    esc(p.first) + " to " + esc(p.last) +
    ".<br><em>Recurrent location</em> describes how often hotspots have " +
    "appeared here. It does not say what is here.").addTo(map);
});

map.on("click", "burned-fill", (e) => {
  const p = e.features[0].properties;
  new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
    "<strong>Mapped burn polygon</strong><br>" +
    "Event: " + esc(p.event_id) + "<br>" +
    "dNBR+ threshold: " + esc(p.threshold) +
    "<br><em>A change like a burn is not proof of burning, and says nothing " +
    "about why. Per-event areas and their caveats are on the results page." +
    "</em>").addTo(map);
});
map.on("click", "labels-fill", (e) => {
  const p = e.features[0].properties;
  new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
    "<strong>Interpretation box " + esc(p.sample_id) + "</strong><br>" +
    "Read as: " + esc(p["class"]) + " (interpreter confidence " +
    esc(p.confidence) + ")<br>" +
    "Event: " + esc(p.event_id) + " · stratum: " + esc(p.sampling) +
    "<br><em>One interpreter's reading of 1 m imagery for this 60 m sample " +
    "box. No second interpreter checked it, so agreement between " +
    "interpreters was never measured. It is evidence about the product, not " +
    "a statement about this land or anyone on it.</em>").addTo(map);
});
for (const id of ["burned-fill", "labels-fill", "recurrent-ring"]) {
  map.on("mouseenter", id, () => map.getCanvas().style.cursor = "pointer");
  map.on("mouseleave", id, () => map.getCanvas().style.cursor = "");
}

/* ---------- layer switch and legend ----------
   One registry drives both, so a layer can never appear in the switch and be
   missing from the legend, or the reverse. `ids` are the MapLibre layers the
   checkbox owns; `swatch` is the legend mark. */
const LAYERS = [
  { key: "hotspots", label: "Thermal anomaly detections", on: true,
    ids: ["hotspots"], swatch: "dot-frp",
    note: "size and colour by FRP (MW)" },
  { key: "burned", label: "Mapped burn polygons", on: true,
    ids: ["burned-fill", "burned-line"], swatch: "#8c2f10" },
  { key: "labels", label: "Interpretation boxes", on: false,
    ids: ["labels-fill", "labels-line"], swatch: "class",
    note: "blue read as burned, green as unburned, olive unsure" },
  { key: "recurrent", label: "Recurrent locations", on: true,
    ids: ["recurrent-ring", "recurrent-label"], swatch: "ring" },
  { key: "desa", label: "Desa / kelurahan boundaries", on: true,
    ids: ["desa-lines"], swatch: "#8a8a8a" },
];
const layerOn = new Map(LAYERS.map((l) => [l.key, l.on]));

function applyVisibility() {
  for (const l of LAYERS)
    for (const id of l.ids)
      if (map.getLayer(id))
        map.setLayoutProperty(id, "visibility",
                              layerOn.get(l.key) ? "visible" : "none");
  drawLegend();
}

function swatchHtml(l) {
  if (l.swatch === "dot-frp")
    return ["#ffb14a", "#f2762b", "#c22e12"]
      .map((c) => '<span class="sw dot" style="background:' + c + '"></span>')
      .join("");
  if (l.swatch === "class")
    return ["#1b6ec2", "#1baf7a", "#8a7a3a"]
      .map((c) => '<span class="sw box" style="background:' + c + '"></span>')
      .join("");
  if (l.swatch === "ring")
    return '<span class="sw ring"></span>';
  return '<span class="sw box" style="background:' + l.swatch + '"></span>';
}

/* The legend lists what is switched on, and nothing else: a legend entry for a
   hidden layer is a legend that does not describe the map. */
function drawLegend() {
  const el = $("legend");
  if (!el) return;
  const rows = LAYERS.filter((l) => layerOn.get(l.key)).map((l) =>
    '<li>' + swatchHtml(l) + esc(l.label) +
    (l.note ? ' <span class="muted">' + esc(l.note) + "</span>" : "") +
    "</li>");
  el.innerHTML = rows.length
    ? "<ul>" + rows.join("") + "</ul>"
    : '<p class="muted">No data layers switched on.</p>';
}

function buildLayerSwitch() {
  const el = $("layers");
  if (!el) return;
  el.innerHTML = LAYERS.map((l) =>
    '<label><input type="checkbox" data-layer="' + l.key + '"' +
    (l.on ? " checked" : "") + "> " + esc(l.label) + "</label>").join("");
  el.querySelectorAll("input[data-layer]").forEach((box) => {
    box.addEventListener("change", () => {
      layerOn.set(box.dataset.layer, box.checked);
      applyVisibility();
    });
  });
  drawLegend();
}
buildLayerSwitch();

map.on("load", async () => {
  const fetches = [
    ["desa", "data/biak_desa.geojson",
     "District boundaries (biak_desa.geojson) failed to load — desa " +
     "boundaries are not drawn."],
    ["hotspots", "data/hotspots_latest.geojson",
     "Hotspot data (hotspots_latest.geojson) failed to load — the map shows " +
     "boundaries only."],
    ["recurrentRaw", "data/recurrent_sites.json",
     "Recurrent sites (recurrent_sites.json) failed to load — the " +
     "recurrent-location layer is unavailable."],
    ["burned", "data/burned_areas.geojson",
     "Burn polygons (burned_areas.geojson) failed to load — the mapped " +
     "burn layer is unavailable, which is not a statement that nothing " +
     "burned."],
    ["labels", "data/labels.geojson",
     "Interpretation boxes (labels.geojson) failed to load — that layer is " +
     "unavailable."],
  ];
  await Promise.all(fetches.map(async ([key, url, errText]) => {
    try {
      const json = await loadJSON(url);
      if (key === "recurrentRaw") {
        // recurrent_sites.json is not GeoJSON: build the site features here
        localData.recurrent = {
          type: "FeatureCollection",
          features: json.sites.map((s) => ({
            type: "Feature",
            geometry: { type: "Point",
                        coordinates: [s.centroid_lon, s.centroid_lat] },
            properties: { days: s.distinct_days,
                          first: s.first_date, last: s.last_date },
          })),
        };
      } else {
        localData[key] = json;
      }
    } catch (e) {
      dataError(key, errText + " " + e.message);
    }
  }));
  addLocalLayers();
});

/* Basemap upgrade: applied only if the style really loads; setStyle
   replaces everything, so the local layers are re-added afterwards. There
   is no single reliable event for "new style fully loaded" (styledata can
   fire before isStyleLoaded() turns true), so reapply runs on styledata
   AND on a bounded timer, stopping as soon as the local sources exist. */
(async () => {
  const reapply = () => {
    if (!map.isStyleLoaded() || !localData.desa) return;
    addLocalLayers();
    if (LOCAL_SOURCES.every((s) => map.getSource(s))) {
      clearInterval(reapplyTimer);
      map.off("styledata", reapply);
    }
  };
  const reapplyTimer = setInterval(reapply, 400);
  try {
    const r = await fetch(BASEMAP_STYLE_URL);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const style = await r.json();
    map.on("styledata", reapply);
    map.setStyle(style);
    reapply();
    setTimeout(() => clearInterval(reapplyTimer), 120000);
  } catch (e) {
    clearInterval(reapplyTimer);
    dataError("basemap", "Basemap (OpenFreeMap) unavailable — showing local " +
      "data on a plain background. " + e.message);
  }
})();
