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

/* Biak island proper: the extent of its ten districts plus a margin, the same
   box scripts/render_biak_poster.py frames its plates with. The project AOI
   is far wider — it reaches Supiori, Numfor and the Padaido islands, and a
   handful of desa 300 km to the north-west — and opening on the whole of it
   put the island the page is about in the middle third of the frame. */
const BIAK_BOUNDS = [[135.70, -1.34], [136.42, -0.69]];

const map = new maplibregl.Map({
  container: "map",
  style: FALLBACK_STYLE,
  bounds: BIAK_BOUNDS,
  fitBoundsOptions: { padding: 16 },
  attributionControl: { compact: false },
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }),
               "top-right");
map.addControl(new maplibregl.FullscreenControl(), "top-right");
map.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }),
               "top-right");
map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }),
               "bottom-left");

/* The panel is open on a desktop, where it costs a corner of a wide map, and
   shut on a phone, where 17 rem of panel over a 360 px map is the whole map.
   A <details> cannot be opened by media query, so it is done once here. */
(() => {
  const panel = document.getElementById("mappanel");
  if (panel && window.matchMedia("(max-width: 48rem)").matches)
    panel.open = false;
})();

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
                    burned: null, labels: null, survey: null };

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
   so it never covers the data regardless of which layers are switched on.
   The Sentinel-2 scene is in this list too, so a background mosaic never
   lands on top of the scene the reader asked for. */
function firstVectorLayer() {
  for (const id of ["burned-fill", "labels-fill", "desa-lines", "hotspots",
                    "survey-dot"])
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

/* ---------- Sentinel-2 scenes ----------
   data/imagery.json lists one WebP per event, band combination and date,
   already warped to WGS84, so each one is an ordinary MapLibre image source
   pinned to its own corner quad. These are the scenes the labelling project
   drew its boxes over (data/labels/biak_labels.qgz), republished at about
   3 m per pixel instead of the 1 m the archive holds. */
const SCENE_ID = "s2-scene";
let scenes = null;               // the manifest, once it loads
let sceneDates = [];             // the dates available for the current choice
let sceneOn = false;


function sceneMatches() {
  if (!scenes) return [];
  const ev = $("scene-event").value;
  const kind = $("scene-kind").value;
  return scenes.tiles
    .filter((t) => t.event === ev && t.kind === kind)
    .sort((a, b) => a.date.localeCompare(b.date));
}

function sceneCurrent() {
  const matches = sceneMatches();
  if (!matches.length) return null;
  const i = Math.min(matches.length - 1,
                     Math.max(0, Number($("scene-date").value)));
  return matches[i];
}

function addScene() {
  if (map.getLayer(SCENE_ID)) map.removeLayer(SCENE_ID);
  if (map.getSource(SCENE_ID)) map.removeSource(SCENE_ID);
  if (!sceneOn) return;
  const tile = sceneCurrent();
  if (!tile) return;
  const [w, s, e, n] = tile.bounds;
  map.addSource(SCENE_ID, {
    type: "image",
    url: tile.file,
    coordinates: [[w, n], [e, n], [e, s], [w, s]],
  });
  map.addLayer({ id: SCENE_ID, type: "raster", source: SCENE_ID,
                 paint: { "raster-opacity": 1, "raster-fade-duration": 0 } },
               firstVectorLayer());
}

function drawSceneUI() {
  const matches = sceneMatches();
  sceneDates = matches.map((t) => t.date);
  const slider = $("scene-date");
  slider.max = String(Math.max(0, matches.length - 1));
  if (Number(slider.value) > Number(slider.max)) slider.value = slider.max;
  const tile = sceneCurrent();
  $("scene-date-label").textContent = tile
    ? tile.date + "  (" + (Number(slider.value) + 1) + " of " + matches.length + ")"
    : "no scene for this choice";
  const note = $("scene-note");
  if (!tile) {
    note.textContent = "";
    return;
  }
  note.textContent = tile.label + ", " + tile.desa + " (" + tile.event + "), " +
    tile.date + ". " + tile.note + " " + scenes.source;
}

function refreshScene() {
  drawSceneUI();
  addScene();
}

function initSceneUI() {
  const evSel = $("scene-event");
  evSel.innerHTML = scenes.events
    .map((e) => '<option value="' + esc(e.event) + '">' + esc(e.desa) +
                " (" + esc(e.event) + ")</option>").join("");
  const kinds = [];
  for (const t of scenes.tiles)
    if (!kinds.some((k) => k.kind === t.kind))
      kinds.push({ kind: t.kind, label: t.label });
  $("scene-kind").innerHTML = kinds
    .map((k) => '<option value="' + esc(k.kind) + '">' + esc(k.label) +
                "</option>").join("");
  // A range input clamps its value against its max, so max has to be set
  // before value or the series silently starts on the oldest date.
  const slider = $("scene-date");
  slider.max = String(Math.max(0, sceneMatches().length - 1));
  slider.value = slider.max;        // the look furthest after the fires
  $("scene-event").addEventListener("input", refreshScene);
  $("scene-kind").addEventListener("input", refreshScene);
  $("scene-date").addEventListener("input", refreshScene);
  $("scene-on").addEventListener("change", (e) => {
    sceneOn = e.target.checked;
    addScene();
    if (sceneOn) zoomToScene();
  });
  $("scene-zoom").addEventListener("click", zoomToScene);
  drawSceneUI();
}

function zoomToScene() {
  const tile = sceneCurrent();
  if (!tile) return;
  const [w, s, e, n] = tile.bounds;
  map.fitBounds([[w, s], [e, n]], { padding: 24, duration: 600 });
}

function addLocalLayers() {
  addImagery();
  addScene();
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
  /* Survey plots: the three places a surveyor stood on 2026-09-03 and
     photographed the ground. The 361 planned targets in the same GeoPackage
     are not published — nobody ever visited them, and a dot labelled "burn
     target" beside somebody's garden is a claim this project cannot make. */
  if (localData.survey) {
    if (!map.getSource("survey"))
      map.addSource("survey", { type: "geojson", data: localData.survey });
    if (!map.getLayer("survey-halo"))
      map.addLayer({
        id: "survey-halo", type: "circle", source: "survey",
        paint: { "circle-radius": 11, "circle-color": "#ffffff",
                 "circle-opacity": 0.55 },
      });
    if (!map.getLayer("survey-dot"))
      map.addLayer({
        id: "survey-dot", type: "circle", source: "survey",
        paint: { "circle-radius": 6, "circle-color": "#a3341f",
                 "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
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

/* ---------- identify ----------
   One click handler, not one per layer. Where layers overlap - and a burn
   polygon overlaps nearly everything else on this map - a handler per layer
   opens one popup per layer, stacked on each other, and the reader has to
   dismiss three records to read the one they clicked. The order below is how
   specific the layer is: a plot somebody stood on beats a box somebody
   interpreted, which beats a polygon covering half a square kilometre. */

function hotspotPopup(p) {
  const distrik = p.distrik ? p.distrik : "outside mapped desa (offshore/water)";
  return "<strong>" + esc(p.acq_date) + "</strong> - " +
    esc((p.datetime_wit || "").slice(11, 16)) + " WIT<br>" +
    "Satellite: " + esc(p.satellite) + "<br>" +
    "Confidence: " + esc(p.confidence) + " (raw instrument code)<br>" +
    "FRP: " + esc(p.frp) + " MW<br>" +
    "Distrik: " + esc(distrik);
}

function recurrentPopup(p) {
  return "<strong>Recurrent location</strong><br>" +
    "Hotspots on " + esc(p.days) + " distinct days, " +
    esc(p.first) + " to " + esc(p.last) +
    ".<br><em>Recurrent location</em> describes how often hotspots have " +
    "appeared here. It does not say what is here.";
}

function burnedPopup(p) {
  return "<strong>Mapped burn polygon</strong><br>" +
    "Event: " + esc(p.event_id) + "<br>" +
    "dNBR+ threshold: " + esc(p.threshold) +
    "<br><em>A change like a burn is not proof of burning, and says nothing " +
    "about why. Per-event areas and their caveats are on the results page." +
    "</em>";
}

function labelPopup(p) {
  return "<strong>Interpretation box " + esc(p.sample_id) + "</strong><br>" +
    "Read as: " + esc(p["class"]) + " (interpreter confidence " +
    esc(p.confidence) + ")<br>" +
    "Event: " + esc(p.event_id) + " \u00b7 stratum: " + esc(p.sampling) +
    "<br><em>One interpreter's reading of 1 m imagery for this 60 m sample " +
    "box. No second interpreter checked it, so agreement between " +
    "interpreters was never measured. It is evidence about the product, not " +
    "a statement about this land or anyone on it.</em>";
}

/* The only layer on the map whose evidence is a person standing on the
   ground, so the popup leads with the photograph. GeoJSON properties survive
   MapLibre as strings, so the photo list arrives JSON-encoded. */
function surveyPopup(p) {
  let photos = [];
  try {
    photos = typeof p.photos === "string"
      ? JSON.parse(p.photos) : (p.photos || []);
  } catch (err) {
    photos = [];
  }
  const shots = photos.map((s) =>
    '<img class="popup-photo" loading="lazy" src="' + esc(s.file) +
    '" alt="Ground photograph looking ' + esc(s.arah) + ' from plot ' +
    esc(p.plot_id) + '">' +
    '<span class="muted">Looking ' + esc(s.arah) +
    (s.keterangan ? " - " + esc(s.keterangan) : "") + "</span>").join("");
  return "<strong>Field plot " + esc(p.plot_id) + "</strong><br>" + shots +
    "<br>Read on the ground as: " + esc(p.kelas) + " (" +
    esc(p.tingkat_yakin) + ")<br>" +
    "Evidence: " + esc(p.bukti) + "<br>" +
    "Visited " + esc(p.waktu) + " WIT, GNSS accuracy " +
    esc(p.akurasi_m) + " m<br>" +
    (p.catatan ? "Note: " + esc(p.catatan) + "<br>" : "") +
    "<em>One of three plots visited on 2026-09-03. Three plots cannot " +
    "validate a map of the island; they say what the ground looked like at " +
    "three points, eleven days after the detections stopped.</em>";
}

const IDENTIFY = [
  { layer: "survey-dot", html: surveyPopup },
  { layer: "labels-fill", html: labelPopup },
  { layer: "recurrent-ring", html: recurrentPopup },
  { layer: "hotspots", html: hotspotPopup },
  { layer: "burned-fill", html: burnedPopup },
];

const identifiable = () =>
  IDENTIFY.map((i) => i.layer).filter((id) => map.getLayer(id));

/* Registered once, on the map rather than on a layer, so they keep working
   after the basemap upgrade replaces every layer the page added. */
map.on("click", (e) => {
  for (const entry of IDENTIFY) {
    if (!map.getLayer(entry.layer)) continue;
    const hits = map.queryRenderedFeatures(e.point, {
      layers: [entry.layer] });
    if (!hits.length) continue;
    new maplibregl.Popup({ maxWidth: "320px" })
      .setLngLat(e.lngLat)
      .setHTML(entry.html(hits[0].properties))
      .addTo(map);
    return;
  }
});

map.on("mousemove", (e) => {
  const layers = identifiable();
  const over = layers.length > 0 &&
    map.queryRenderedFeatures(e.point, { layers }).length > 0;
  map.getCanvas().style.cursor = over ? "pointer" : "";
});

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
  { key: "survey", label: "Field plots, with photographs", on: true,
    ids: ["survey-halo", "survey-dot"], swatch: "pin",
    note: "3 plots visited 2026-09-03" },
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
  if (l.swatch === "pin")
    return '<span class="sw pin"></span>';
  return '<span class="sw box" style="background:' + l.swatch + '"></span>';
}

/* The legend lists what is switched on, and nothing else: a legend entry for a
   hidden layer is a legend that does not describe the map. */
function drawLegend() {
  const el = $("legend");
  if (!el) return;
  const rows = LAYERS.filter((l) => layerOn.get(l.key)).map((l) =>
    "<li>" + swatchHtml(l) + "<span>" + esc(l.label) +
    (l.note ? ' <span class="muted">— ' + esc(l.note) + "</span>" : "") +
    "</span></li>");
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
    ["survey", "data/survey.geojson",
     "Field plots (survey.geojson) failed to load — the ground photographs " +
     "are unavailable."],
    ["scenes", "data/imagery.json",
     "The Sentinel-2 scene index (imagery.json) failed to load — no scene " +
     "can be draped on the map."],
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
      } else if (key === "scenes") {
        scenes = json;
      } else {
        localData[key] = json;
      }
    } catch (e) {
      dataError(key, errText + " " + e.message);
    }
  }));
  if (scenes) initSceneUI();
  addLocalLayers();
});

/* Basemap upgrade: applied only if the style really loads. setStyle replaces
   everything the page added, so the local layers have to be rebuilt after it,
   and there is no single reliable event for "the new style is fully loaded"
   (styledata can fire before isStyleLoaded() turns true). reapply therefore
   runs on styledata AND on a bounded timer.

   It used to stop as soon as every local source existed, which was a race it
   lost intermittently: the fetches in map.on("load") can finish BEFORE the
   basemap fetch returns, in which case addLocalLayers() has already built all
   six sources, the stop condition is true on the next tick, the listener is
   removed - and then setStyle arrives and wipes the lot with nothing left
   watching. The condition cannot be "the layers exist now", because the whole
   point is that they are about to stop existing. So reapply is registered
   before anything can replace the style, and keeps running for the bounded
   window regardless; addLocalLayers() is idempotent, so a tick that finds
   everything in place costs a dozen getLayer() calls. */
(() => {
  const reapply = () => {
    if (!map.isStyleLoaded() || !localData.desa) return;
    addLocalLayers();
  };
  const reapplyTimer = setInterval(reapply, 400);
  map.on("styledata", reapply);
  const stop = () => {
    clearInterval(reapplyTimer);
    map.off("styledata", reapply);
  };
  (async () => {
    try {
      const r = await fetch(BASEMAP_STYLE_URL);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const style = await r.json();
      map.setStyle(style);
      reapply();
      // Long enough to outlast the style swap and the tiles behind it on a
      // slow connection; the timer is a no-op once the layers are back.
      setTimeout(stop, 120000);
    } catch (e) {
      stop();
      dataError("basemap", "Basemap (OpenFreeMap) unavailable — showing " +
        "local data on a plain background. " + e.message);
    }
  })();
})();
