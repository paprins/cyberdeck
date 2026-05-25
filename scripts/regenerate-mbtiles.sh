#!/usr/bin/env bash
set -euo pipefail
# Regenerate a Netherlands mbtiles file with bounds that include the
# Wadden Islands and surrounding sea (the existing extract clipped them off).
#
# Uses a locally-built `tilemaker` docker image (the ghcr.io/systemed
# upstream does not ship ARM64). Build it once on this machine with:
#   git clone https://github.com/systemed/tilemaker && cd tilemaker
#   docker build -t tilemaker .
#
# Outputs to data/maps/netherlands-<YYMMDD>.mbtiles, leaving the original
# untouched. Update data/packages/registry.json afterwards if you want the
# new file to show up in the UI.
#
# Usage:
#   scripts/regenerate-mbtiles.sh                   # download source + run
#   scripts/regenerate-mbtiles.sh --pbf <path>      # use a local PBF (host path under repo)
#   scripts/regenerate-mbtiles.sh --bbox W,S,E,N    # override clip box
#   scripts/regenerate-mbtiles.sh --fresh-pbf       # force re-download (use if you hit parse errors)
#   scripts/regenerate-mbtiles.sh --image <name>    # override docker image name (default: tilemaker)
#
# Requires:  docker, curl

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="${REPO_ROOT}/data/cache/tilemaker"
OUT_DIR="${REPO_ROOT}/data/maps"
DATE_TAG="$(date +%y%m%d)"
OUT_PATH="${OUT_DIR}/netherlands-${DATE_TAG}.mbtiles"
TM_IMAGE="tilemaker"  # local build; upstream ghcr.io/systemed/tilemaker has no ARM64

# Default bbox covers mainland NL + all five Wadden Islands + a small sea
# buffer to the north and the German border in the east. Lon W, Lat S, Lon E,
# Lat N. The previous extract topped out at ~53.4°N which cropped Ameland and
# Schiermonnikoog; 53.7°N gives ~25 km of headroom.
BBOX="3.0,50.7,7.3,53.7"
PBF=""
FRESH_PBF=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pbf)        PBF="$2"; shift 2 ;;
        --bbox)       BBOX="$2"; shift 2 ;;
        --image)      TM_IMAGE="$2"; shift 2 ;;
        --fresh-pbf)  FRESH_PBF=1; shift ;;
        -h|--help)
            sed -n '/^# Regenerate/,/^$/p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }

mkdir -p "${CACHE_DIR}" "${OUT_DIR}"

# Source OSM data. GeoFabrik's Netherlands extract already includes the
# offshore region (Wadden + EEZ); no special handling needed beyond a
# generous bbox.
if [[ -z "${PBF}" ]]; then
    PBF="${CACHE_DIR}/netherlands-latest.osm.pbf"
    if [[ ${FRESH_PBF} -eq 1 && -f "${PBF}" ]]; then
        echo "→ --fresh-pbf: removing cached PBF"
        rm -f "${PBF}"
    fi
    if [[ ! -f "${PBF}" ]]; then
        echo "→ downloading netherlands-latest.osm.pbf from GeoFabrik (~500 MB)"
        curl -fL --progress-bar -o "${PBF}.tmp" \
            "https://download.geofabrik.de/europe/netherlands-latest.osm.pbf"
        mv "${PBF}.tmp" "${PBF}"
    else
        echo "→ using cached PBF: ${PBF}"
    fi
fi

# Tilemaker config (OpenMapTiles schema). Pulled from master so the schema
# matches the master tag we build from.
CONFIG_JSON="${CACHE_DIR}/config-openmaptiles.json"
CONFIG_LUA="${CACHE_DIR}/process-openmaptiles.lua"
TM_BASE="https://raw.githubusercontent.com/systemed/tilemaker/master/resources"
for f in config-openmaptiles.json process-openmaptiles.lua; do
    if [[ ! -f "${CACHE_DIR}/${f}" ]]; then
        echo "→ fetching ${f}"
        curl -fL -o "${CACHE_DIR}/${f}" "${TM_BASE}/${f}"
    fi
done

# OSM water polygons. The config references coastline/water_polygons.shp;
# without it tilemaker has no global sea outline and the North Sea renders
# as background at low zoom (only inland lakes from OSM are drawn). The zip
# is ~700 MB compressed, ~2 GB extracted — cached once, reused forever.
COASTLINE_SHP="${CACHE_DIR}/coastline/water_polygons.shp"
if [[ ! -f "${COASTLINE_SHP}" ]]; then
    ZIP="${CACHE_DIR}/water-polygons-split-4326.zip"
    if [[ ! -f "${ZIP}" ]]; then
        echo "→ downloading water-polygons-split-4326.zip from osmdata.openstreetmap.de (~700 MB)"
        curl -fL --progress-bar -o "${ZIP}.tmp" \
            "https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip"
        mv "${ZIP}.tmp" "${ZIP}"
    fi
    command -v unzip >/dev/null || { echo "unzip not found" >&2; exit 1; }
    echo "→ extracting water polygons to coastline/"
    mkdir -p "${CACHE_DIR}/coastline"
    unzip -jq "${ZIP}" -d "${CACHE_DIR}/coastline"
fi

# All paths inside the container must live under /data (where we mount the
# repo root). Strip the host prefix so the same script works on macOS Docker
# Desktop AND on Linux without relying on auto-mounted /Users.
to_container() { printf '/data/%s' "${1#${REPO_ROOT}/}"; }

C_PBF=$(to_container "${PBF}")
C_OUT=$(to_container "${OUT_PATH}")
C_CONFIG_JSON=$(to_container "${CONFIG_JSON}")
C_CONFIG_LUA=$(to_container "${CONFIG_LUA}")
C_CACHE_DIR=$(to_container "${CACHE_DIR}")

echo "→ running tilemaker"
echo "  image:  ${TM_IMAGE}"
echo "  input:  ${PBF}"
echo "  output: ${OUT_PATH}"
echo "  bbox:   ${BBOX}"
echo "  coast:  ${COASTLINE_SHP}"

# Working dir set to the cache dir so the config's relative path
# `coastline/water_polygons.shp` resolves to our extracted shapefile.
docker run --rm \
    -v "${REPO_ROOT}:/data" \
    -w "${C_CACHE_DIR}" \
    "${TM_IMAGE}" \
    --input "${C_PBF}" \
    --output "${C_OUT}" \
    --bbox "${BBOX}" \
    --config "${C_CONFIG_JSON}" \
    --process "${C_CONFIG_LUA}"

echo
echo "✓ wrote ${OUT_PATH}"
echo
echo "next steps:"
echo "  1. update data/packages/registry.json: change the active mbtiles"
echo "     module to point at netherlands-${DATE_TAG}"
echo "  2. restart mbtileserver (docker compose restart mbtileserver)"
echo "  3. reload the map viewer in the browser"
