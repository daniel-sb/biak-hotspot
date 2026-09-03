"""Export burn targets as waypoints for Google Maps and any GPS app.

    python src/export_waypoints.py --from=-1.1624014,136.0626332
                                   [--priority kuat] [--max 40]

Note the "=" in --from. A southern latitude starts with a minus sign, and
without the equals sign argparse reads it as another option and stops.

Writes into fieldwork/:
    waypoints_<priority>.csv    import into Google My Maps
    waypoints_<priority>.kml    import into Google My Maps or Google Earth
    waypoints_<priority>.gpx    OsmAnd, Locus, Garmin, anything that speaks GPX
    waypoints_<priority>.html   one tap-to-navigate link per target

and prints the nearest targets with distance and bearing from where you are.

Distances here are straight lines. Biak's roads are not, and the interior has
few of them, so a target 4 km away across the karst can be an hour's drive
round the coast. Read the numbers as an ordering, never as a travel time.
"""

from __future__ import annotations

import argparse
import csv
import html
import math
import sqlite3
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPKG = ROOT / "fieldwork" / "biak_ground_truth.gpkg"
EARTH_R = 6371008.8

COMPASS = ("U", "TL", "T", "TG", "S", "BD", "B", "BL")


def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def read_targets(priorities):
    con = sqlite3.connect(GPKG)
    marks = ",".join("?" for _ in priorities)
    rows = con.execute(
        "SELECT target_id, prioritas, n_deteksi, n_satelit, n_hari, frp_maks,"
        " tgl_awal, tgl_akhir, desa, distrik, geom FROM target_bakar"
        " WHERE prioritas IN ({})".format(marks), tuple(priorities)).fetchall()
    con.close()
    out = []
    for r in rows:
        lon, lat = struct.unpack("<BIdd", r[-1][8:])[2:]
        out.append({
            "target_id": r[0], "prioritas": r[1], "n_deteksi": r[2],
            "n_satelit": r[3], "n_hari": r[4], "frp_maks": r[5],
            "tgl_awal": r[6], "tgl_akhir": r[7], "desa": r[8] or "-",
            "distrik": r[9] or "-", "lat": lat, "lon": lon,
        })
    return out


def group_by_desa(targets):
    """One trip serves one desa, so the desa is the unit of planning.

    Ranking 74 targets by distance alone reads as a route but is not one: it
    interleaves desa, so following it means entering Sambawofuar, leaving for
    Yendidori, and coming back. Grouped, the shape of the work appears - the
    eight nearest desa hold 45 of the 74 strong targets, and Anjareuw alone
    holds ten.

    Groups are ordered by their nearest member, so the closest desa is still
    first; only the interleaving is gone.
    """
    buckets = {}
    for t in targets:
        buckets.setdefault((t["distrik"], t["desa"]), []).append(t)

    groups = []
    for (distrik, desa), rows in buckets.items():
        rows.sort(key=lambda t: (t["km"] if t["km"] == t["km"] else 0,
                                 -t["n_deteksi"]))
        kms = [t["km"] for t in rows if t["km"] == t["km"]]
        groups.append({
            "distrik": distrik, "desa": desa, "targets": rows,
            "n_deteksi": sum(t["n_deteksi"] for t in rows),
            "km_min": min(kms) if kms else float("nan"),
            "km_max": max(kms) if kms else float("nan"),
        })
    groups.sort(key=lambda g: (g["km_min"] if g["km_min"] == g["km_min"]
                               else -g["n_deteksi"], g["desa"]))
    return groups


def describe(t):
    return ("{prioritas} - {n_deteksi} deteksi, {n_satelit} satelit, "
            "{n_hari} hari, FRP maks {frp_maks} MW. {tgl_awal} s/d {tgl_akhir}. "
            "Desa {desa}, {distrik}.").format(**t)


def write_csv(path, targets):
    # Google My Maps reads a plain CSV and asks which columns are the
    # coordinates. Keep latitude and longitude in separate columns; a single
    # "lat,lon" cell is the usual way this import goes wrong.
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["nama", "latitude", "longitude", "prioritas", "desa",
                    "distrik", "n_deteksi", "keterangan"])
        for t in targets:
            w.writerow([t["target_id"], "{:.6f}".format(t["lat"]),
                        "{:.6f}".format(t["lon"]), t["prioritas"], t["desa"],
                        t["distrik"], t["n_deteksi"], describe(t)])


def write_kml(path, groups, title):
    """Folders by DISTRIK, not desa. Google My Maps turns each KML folder
    into a layer and allows ten of them; there are thirty desa here and only
    six distrik, so folding by desa would silently lose two thirds of the
    map. The desa is still on every placemark."""
    by_distrik = {}
    for g in groups:
        by_distrik.setdefault(g["distrik"], []).append(g)

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             "<name>{}</name>".format(html.escape(title))]
    for distrik, gs in by_distrik.items():
        n = sum(len(g["targets"]) for g in gs)
        parts.append("<Folder><name>{} ({} target)</name>".format(
            html.escape(distrik), n))
        for g in gs:
            for t in g["targets"]:
                parts.append(
                    "<Placemark><name>{} - {}</name><description>{}"
                    "</description><Point><coordinates>{:.6f},{:.6f},0"
                    "</coordinates></Point></Placemark>".format(
                        html.escape(t["target_id"]), html.escape(g["desa"]),
                        html.escape(describe(t)),
                        t["lon"], t["lat"]))   # KML is lon,lat - not lat,lon
        parts.append("</Folder>")
    parts.append("</Document></kml>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_gpx(path, targets, title):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="biak-hotspot" '
             'xmlns="http://www.topografix.com/GPX/1/1">',
             "<metadata><name>{}</name></metadata>".format(
                 html.escape(title))]
    for t in targets:
        parts.append(
            '<wpt lat="{:.6f}" lon="{:.6f}"><name>{}</name>'
            "<desc>{}</desc></wpt>".format(
                t["lat"], t["lon"], html.escape(t["target_id"]),
                html.escape(describe(t))))
    parts.append("</gpx>")
    path.write_text("\n".join(parts), encoding="utf-8")


def maps_url(t):
    return ("https://www.google.com/maps/search/?api=1&query="
            "{:.6f},{:.6f}".format(t["lat"], t["lon"]))


def route_url(origin, stops):
    """A Google Maps directions URL. It accepts nine intermediate stops, so
    a desa with more targets than that gets a route to the first ten and the
    rest are walked from there."""
    if not origin or len(stops) < 1:
        return ""
    stops = stops[:10]
    url = ("https://www.google.com/maps/dir/?api=1&origin={:.6f},{:.6f}"
           "&destination={:.6f},{:.6f}&travelmode=driving".format(
               origin[0], origin[1], stops[-1]["lat"], stops[-1]["lon"]))
    if len(stops) > 1:
        url += "&waypoints=" + "|".join(
            "{:.6f},{:.6f}".format(s["lat"], s["lon"]) for s in stops[:-1])
    return url


def write_html(path, groups, origin, title):
    total = sum(len(g["targets"]) for g in groups)
    body, seen = [], 0
    for g in groups:
        seen += len(g["targets"])
        span = ("{:.1f} km".format(g["km_min"])
                if g["km_min"] == g["km_min"] else "")
        if g["km_min"] == g["km_min"] and g["km_max"] > g["km_min"] + 0.05:
            span = "{:.1f}-{:.1f} km".format(g["km_min"], g["km_max"])
        rows = "".join(
            "<tr><td><b>{}</b></td><td>{} deteksi</td><td>{}</td>"
            "<td><a href='{}'>peta</a></td></tr>".format(
                html.escape(t["target_id"]), t["n_deteksi"],
                "-" if t["km"] != t["km"] else
                "{:.1f} km {}".format(t["km"], t["arah"]), maps_url(t))
            for t in g["targets"])
        route = route_url(origin, g["targets"])
        body.append(
            "<section><h3>{desa} <small>{distrik} &middot; {n} target "
            "&middot; {span} &middot; kumulatif {seen}/{total}</small></h3>"
            "{route}<table>{rows}</table></section>".format(
                desa=html.escape(g["desa"]),
                distrik=html.escape(g["distrik"]), n=len(g["targets"]),
                span=span, seen=seen, total=total, rows=rows,
                route=("<p><a href='{}'>Rute ke desa ini</a></p>".format(route)
                       if route else "")))
    return path.write_text(
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>{t}</title><style>body{{font:15px system-ui;margin:12px;"
        "max-width:760px}}h3{{margin:22px 0 4px;border-bottom:2px solid #111;"
        "padding-bottom:3px}}h3 small{{font-weight:400;color:#666;"
        "font-size:13px;display:block;border:0}}"
        "table{{border-collapse:collapse;width:100%}}"
        "td{{border-bottom:1px solid #ddd;padding:7px 5px}}"
        "a{{display:inline-block;padding:6px 10px;background:#111;color:#fff;"
        "border-radius:5px;text-decoration:none}}</style>"
        "<h2>{t}</h2><p style='color:#666'>{total} target dalam {ng} desa, "
        "diurutkan menurut desa terdekat. Jarak garis lurus, bukan jarak "
        "jalan.</p>{body}".format(
            t=html.escape(title), total=total, ng=len(groups),
            body="".join(body)),
        encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="origin", default=None,
                    help="posisi sekarang, 'lat,lon'. Pakai --from=-1.16,136.06 "
                         "(dengan tanda sama dengan) untuk lintang selatan")
    ap.add_argument("--priority", default="kuat",
                    help="kuat, sedang, or 'kuat,sedang'")
    ap.add_argument("--max", type=int, default=0, help="0 = semua")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "fieldwork")
    args = ap.parse_args()

    if not GPKG.exists():
        raise SystemExit("{} missing - run src/fieldwork_gpkg.py".format(GPKG))
    prios = [p.strip() for p in args.priority.split(",") if p.strip()]
    targets = read_targets(prios)
    if not targets:
        raise SystemExit("no targets with prioritas in {}".format(prios))

    origin = None
    if args.origin:
        # Accept the comma-decimal form phones copy out, e.g. -1,1624 136,0626
        raw = args.origin.replace(" ", "")
        try:
            lat, lon = (float(v) for v in raw.split(","))
        except ValueError:
            raise SystemExit(
                "--from wants 'lat,lon' with dots for decimals, got "
                "{!r}".format(args.origin))
        origin = (lat, lon)
        for t in targets:
            t["km"] = haversine(lat, lon, t["lat"], t["lon"]) / 1000
            b = bearing(lat, lon, t["lat"], t["lon"])
            t["arah"] = COMPASS[int((b + 22.5) % 360 // 45)]
        targets.sort(key=lambda t: t["km"])
    else:
        for t in targets:
            t["km"], t["arah"] = float("nan"), "-"
        targets.sort(key=lambda t: (-t["n_deteksi"], t["target_id"]))

    if args.max:
        targets = targets[:args.max]

    groups = group_by_desa(targets)

    tag = "-".join(prios)
    title = "Target bakar {} - Biak, Agustus 2026".format(tag)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / "waypoints_{}".format(tag)
    write_csv(stem.with_suffix(".csv"), targets)
    write_kml(stem.with_suffix(".kml"), groups, title)
    write_gpx(stem.with_suffix(".gpx"), targets, title)
    write_html(stem.with_suffix(".html"), groups, origin, title)

    print("{} target dalam {} desa, {} distrik. prioritas {}".format(
        len(targets), len(groups),
        len({g["distrik"] for g in groups}), prios))
    if origin:
        print("dari {:.6f}, {:.6f} - desa terdekat lebih dulu\n".format(*origin))

    seen = 0
    for g in groups:
        seen += len(g["targets"])
        span = ("{:.1f}".format(g["km_min"]) if g["km_min"] == g["km_min"]
                else "-")
        if g["km_min"] == g["km_min"] and g["km_max"] > g["km_min"] + 0.05:
            span += "-{:.1f}".format(g["km_max"])
        print("  {:<12} {:<16} {:>2} target  {:>10} km  {:>3} deteksi"
              "   kumulatif {}/{}".format(
                  g["distrik"][:12], g["desa"][:16], len(g["targets"]),
                  span, g["n_deteksi"], seen, len(targets)))
        for t in g["targets"]:
            print("      {:<7} {:>4} det  {:>5} {:<4} {:.6f},{:.6f}".format(
                t["target_id"], t["n_deteksi"],
                "-" if t["km"] != t["km"] else "{:.1f}".format(t["km"]),
                t["arah"], t["lat"], t["lon"]))

    for ext in ("csv", "kml", "gpx", "html"):
        print("wrote {}".format(stem.with_suffix("." + ext)))


if __name__ == "__main__":
    raise SystemExit(main())
