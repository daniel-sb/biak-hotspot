# Task 07b — the page did not render

Task 07's structure, data files and wording are accepted. The page itself did not work. I loaded
it in a browser during review; that is the check task 07 was missing and it should have been in
the task file. Read `AGENTS.md` first, then PLAN.md sections 8 and 9.

---

## Already fixed in review, listed so you do not undo them

**The page threw on load.** Three call sites used `maplibre.` where the global is `maplibregl.`
(`NavigationControl` and two `Popup`s). The first threw `ReferenceError` and killed the entire
script, so the map was blank and both the brief and evening panels sat on "Loading..." forever.
All 70 tests passed throughout, because every one of them matches strings in the source.

**22 double-encoded characters and a byte-order mark.** Every em-dash in `docs/index.html`
rendered as a stray sequence, from a cp1252/UTF-8 round trip. Nothing in a terminal shows this.

Both now have regression tests, and both were verified to fail when the fault is reintroduced.

## 1. The map renders nothing, and cannot tell you why

After the crash fix the map is still empty — no basemap, no desa boundaries, no hotspots — on a
fresh tab, with no console error. `tiles.openfreemap.org/styles/liberty` and the unpkg script both
return 200 from the shell, so the cause is not simply an unreachable host.

The structural fault is visible in the source regardless of what blocked it here:

```
map.on("load", async () => {   ... every data layer lives in here ... });
```

and there is no `map.on("error", ...)` anywhere in the file.

Two consequences, both of which will happen on a Biak mobile connection:

- **A remote basemap failure takes the local data down with it.** `load` does not fire until the
  style resolves, so `biak_desa.geojson` and `hotspots_latest.geojson` — both served from the same
  origin as the page — never get added.
- **The failure is silent.** Task 07 required the page to degrade honestly and said a blank map is
  not an empty island. A blank map with no message is exactly that.

Required:

- Add a `map.on("error", ...)` handler that surfaces style and tile failures in the page's existing
  error-banner mechanism, naming what failed.
- **Add the local GeoJSON layers on a path that does not depend on the remote style resolving.**
  If the basemap cannot load, the island outline and the hotspots must still draw, with a banner
  saying the basemap is unavailable. The data is local; it should never be hostage to a CDN.
- Diagnose why the style did not render here and report what you find. If it turns out to be
  environmental rather than a page fault, say so plainly — but the two changes above are required
  either way.

## 2. The Markdown converter mangles the brief

Visible in the rendered page:

```
VIIRS_SNPP_NRT        renders as   VIIRS SNPP NRT   (italicised, underscores eaten)
hotspots_latest.geojson  renders as   hotspotslatest.geojson
...ending 2026-08-27.    renders as   ...ending 2026-08-27._
```

Underscores are being treated as emphasis inside identifiers. Every satellite source name and
every filename in every brief is affected, and these are the strings a reader most needs to be
exact.

Fix: do not treat `_` as an emphasis marker at all. The briefs use `*` for emphasis; underscore
emphasis buys nothing and breaks every identifier in the corpus.

## 3. The tables are misaligned

In the rendered "Satellite sources" and "Detections by district" tables, cells land in the wrong
columns — values drift right across rows, and one row's "observed, no detections" sits under the
wrong heading. The brief's substance is tables, so this is not cosmetic.

Check the separator-row handling and cells that are empty or contain a lone `-`.

## 4. Add a real render check

The source-level tests cannot catch any of the above, and should not be extended to try — string
matching will never find a runtime crash.

Add one check that actually loads the page. **Do not add a browser dependency.** The cheapest
honest option is to parse and execute nothing, but assert the things that only break at runtime
by structural inspection instead:

- every identifier used with `new X.` or `X.Map(` resolves to a name the loaded script defines
- every `getElementById` target exists in the document's own markup
- every `fetch("...")` path in the page exists on disk under `docs/`

That catches this class of fault without a headless browser. If you can see a materially better
approach within the no-new-dependency rule, propose it in your report rather than adding one.

## The checks

1. Reintroducing `maplibre.` fails a test. (Already true — keep it.)
2. Reintroducing a double-encoded character fails a test. (Already true — keep it.)
3. Every `fetch()` path in the page exists under `docs/`.
4. Every `getElementById` target exists in the markup.
5. `_` inside an identifier survives the Markdown conversion unchanged.
6. A table row with an empty cell and a row with a lone `-` both land in the right columns.
7. The existing 72 tests still pass.

## Out of scope

Restyling, new panels, precipitation, AQI, the evening Parquet as a layer. No new dependencies,
and no headless-browser package.

## Before you finish

Name every decision this task did not specify, per AGENTS.md. And say plainly whether you loaded
the page yourself; if you could not, say that instead of implying it.
