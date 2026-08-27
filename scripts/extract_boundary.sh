#!/bin/sh
# Derive data/boundaries/biak_desa.geojson from the national BIG administrative
# geodatabase. The source .gdb is 340 MB, manually downloaded, and gitignored;
# only the 1.2 MB extract is tracked.
#
# Source: BIG RBI 1:10K administrative boundaries (desa/kelurahan), 2023-09-28
#   https://geoservices.big.go.id/portal/home/item.html?id=d1457b6bcf79413e90981e1e564665e9  # pragma: allowlist secret
#
# Requires ogr2ogr. It ships with QGIS; on Windows it is typically at
#   /c/Program Files/QGIS <version>/bin/ogr2ogr.exe
# Override with OGR2OGR=/path/to/ogr2ogr sh scripts/extract_boundary.sh
set -e

GDB="${GDB:-data/RBI10K_ADMINISTRASI_DESA_20230928.gdb}"
OUT="${OUT:-data/boundaries/biak_desa.geojson}"
OGR2OGR="${OGR2OGR:-ogr2ogr}"

[ -d "$GDB" ] || { echo "Source geodatabase not found: $GDB"; exit 1; }
mkdir -p "$(dirname "$OUT")"

# Filter by attribute, never clip by bounding box: a bbox clip would cut desa
# polygons at the box edge and silently truncate the two regencies.
# -dim XY drops the EGM2008 vertical component; RFC7946 forces lon,lat order.
"$OGR2OGR" -f GeoJSON "$OUT" "$GDB" ADMINISTRASI_AR_DESAKEL \
    -where "WADMKK IN ('Biak Numfor','Supiori')" \
    -select WADMKD,WADMKC,WADMKK,WADMPR,KDEBPS,KDCBPS,LUASWH \
    -dim XY -t_srs EPSG:4326 \
    -lco RFC7946=YES -lco COORDINATE_PRECISION=6 -nln biak_desa

echo "Wrote $OUT"
echo "Expected: 306 desa (Biak Numfor 268, Supiori 38) across 24 distrik."
