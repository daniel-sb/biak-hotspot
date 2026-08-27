#!/bin/sh
# Derive a desa/kelurahan boundary GeoJSON from the national BIG administrative
# geodatabase. The source .gdb is 340 MB, manually downloaded, and gitignored;
# only the small extracts are tracked.
#
# Source: BIG RBI 1:10K administrative boundaries (desa/kelurahan), 2023-09-28
#   https://geoservices.big.go.id/portal/home/item.html?id=d1457b6bcf79413e90981e1e564665e9  # pragma: allowlist secret
#
# Requires ogr2ogr. It ships with QGIS; on Windows it is typically at
#   /c/Program Files/QGIS <version>/bin/ogr2ogr.exe
#
# Default extract, the Biak AOI (306 desa, 24 distrik):
#   sh scripts/extract_boundary.sh
#
# Any other regency, by exact WADMKK value:
#   WHERE="WADMKK = 'Yahukimo'" OUT=data/boundaries/yahukimo_desa.geojson #       sh scripts/extract_boundary.sh
#
# Find the exact name first - do not guess the spelling:
#   ogrinfo -dialect SQLITE -sql #     "SELECT DISTINCT WADMPR, WADMKK FROM ADMINISTRASI_AR_DESAKEL WHERE WADMKK LIKE '%partial%'" #     data/RBI10K_ADMINISTRASI_DESA_20230928.gdb
set -e

GDB="${GDB:-data/RBI10K_ADMINISTRASI_DESA_20230928.gdb}"
OUT="${OUT:-data/boundaries/biak_desa.geojson}"
WHERE="${WHERE:-WADMKK IN ('Biak Numfor','Supiori')}"
OGR2OGR="${OGR2OGR:-ogr2ogr}"

[ -d "$GDB" ] || { echo "Source geodatabase not found: $GDB"; exit 1; }
mkdir -p "$(dirname "$OUT")"

# Filter by attribute, never clip by bounding box: a bbox clip would cut desa
# polygons at the box edge and silently truncate the regency.
# -dim XY drops the EGM2008 vertical component; RFC7946 forces lon,lat order.
"$OGR2OGR" -f GeoJSON "$OUT" "$GDB" ADMINISTRASI_AR_DESAKEL     -where "$WHERE"     -select WADMKD,WADMKC,WADMKK,WADMPR,KDEBPS,KDCBPS,LUASWH     -dim XY -t_srs EPSG:4326     -lco RFC7946=YES -lco COORDINATE_PRECISION=6

echo "Wrote $OUT  (where: $WHERE)"
