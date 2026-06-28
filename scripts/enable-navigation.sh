#!/usr/bin/env bash
set -euo pipefail
# Enable offline turn-by-turn navigation for an existing map region.
#
# A region needs two datasets: the display tiles (data/maps/<map-id>.mbtiles,
# handled by regenerate-mbtiles.sh) and routing tiles for the Valhalla engine.
# This script prepares the routing tiles, registers them against the map region,
# stages them as the active extract, and (re)starts the engine.
#
# Two ways to supply the routing tiles:
#   --routing-tar PATH   use a prebuilt Valhalla tar  (RECOMMENDED on a Pi)
#   --pbf-url URL        download an OSM extract and BUILD the tar here
#
# Building is RAM-heavy (>=4-8 GB) and slow. Do NOT build on a Raspberry Pi —
# build on a workstation and copy the tar over, then run this with --routing-tar.

IMAGE="ghcr.io/nilsnolde/docker-valhalla/valhalla:latest"

usage() {
    cat <<EOF
Usage: $(basename "$0") --map-id ID (--routing-tar PATH | --pbf-url URL) [options]

Enable navigation for the map region <map-id> (data/maps/<map-id>.mbtiles).

Required:
  --map-id ID            Existing mbtiles map region id.

Routing tiles (exactly one):
  --routing-tar PATH     Use an already-built Valhalla tar (recommended on a Pi).
  --pbf-url URL          Download this OSM .osm.pbf and build the tar locally.

Options:
  --routing-id ID        Routing module id      (default: <map-id>-routing)
  --name NAME            Display name            (default: "<map-id> Routing")
  --data-dir DIR         Data directory          (default: \${CYBERDECK_DATA_DIR:-data})
  --force-build          Allow building on an ARM/Pi host (not recommended).
  --keep-pbf             Keep the downloaded .osm.pbf after building.
  -h, --help

Examples:
  # On a Pi, install a tar you built elsewhere:
  $(basename "$0") --map-id netherlands-260525 --routing-tar ~/netherlands-routing.tar

  # On a workstation, build from a Geofabrik extract:
  $(basename "$0") --map-id netherlands-260525 \\
      --pbf-url https://download.geofabrik.de/europe/netherlands-latest.osm.pbf
EOF
}

# ── args ────────────────────────────────────────────────────────────────────
MAP_ID="" ROUTING_TAR="" PBF_URL="" ROUTING_ID="" NAME=""
DATA_DIR="${CYBERDECK_DATA_DIR:-data}" FORCE_BUILD="" KEEP_PBF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --map-id)      MAP_ID="$2"; shift 2 ;;
        --routing-tar) ROUTING_TAR="$2"; shift 2 ;;
        --pbf-url)     PBF_URL="$2"; shift 2 ;;
        --routing-id)  ROUTING_ID="$2"; shift 2 ;;
        --name)        NAME="$2"; shift 2 ;;
        --data-dir)    DATA_DIR="$2"; shift 2 ;;
        --force-build) FORCE_BUILD="1"; shift ;;
        --keep-pbf)    KEEP_PBF="1"; shift ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

[[ -n "$MAP_ID" ]] || { echo "ERROR: --map-id is required" >&2; usage >&2; exit 1; }
if [[ -n "$ROUTING_TAR" && -n "$PBF_URL" ]] || [[ -z "$ROUTING_TAR" && -z "$PBF_URL" ]]; then
    echo "ERROR: supply exactly one of --routing-tar or --pbf-url" >&2; exit 1
fi

ROUTING_ID="${ROUTING_ID:-${MAP_ID}-routing}"
NAME="${NAME:-${MAP_ID} Routing}"

# Resolve repo root (this script lives in scripts/) so `uv run` finds the app.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Make DATA_DIR absolute so docker volume mounts and python agree.
mkdir -p "$DATA_DIR/maps" "$DATA_DIR/routing"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
ROUTING_DIR="$DATA_DIR/routing"
DEST_TAR="$ROUTING_DIR/${ROUTING_ID}.tar"

echo "==> region:      $MAP_ID"
echo "==> routing id:  $ROUTING_ID"
echo "==> data dir:    $DATA_DIR"

# Warn if the display map isn't present — routing without it is not viewable.
if [[ ! -f "$DATA_DIR/maps/${MAP_ID}.mbtiles" ]]; then
    echo "WARNING: $DATA_DIR/maps/${MAP_ID}.mbtiles not found." >&2
    echo "         Routing will be registered but the map region must exist for" >&2
    echo "         the NAVIGATE panel to appear. (See regenerate-mbtiles.sh.)" >&2
fi

# ── 1. obtain the routing tar ────────────────────────────────────────────────
if [[ -n "$ROUTING_TAR" ]]; then
    [[ -f "$ROUTING_TAR" ]] || { echo "ERROR: $ROUTING_TAR not found" >&2; exit 1; }
    SRC_ABS="$(cd "$(dirname "$ROUTING_TAR")" && pwd)/$(basename "$ROUTING_TAR")"
    if [[ "$SRC_ABS" == "$DEST_TAR" ]]; then
        echo "==> tar already in place: $DEST_TAR"
    else
        echo "==> installing prebuilt tar: $ROUTING_TAR"
        cp -f "$ROUTING_TAR" "$DEST_TAR"
    fi
else
    command -v docker >/dev/null || { echo "ERROR: docker is required to build" >&2; exit 1; }

    ARCH="$(uname -m)"
    if [[ "$ARCH" == aarch64 || "$ARCH" == arm64 || "$ARCH" == armv7l ]] && [[ -z "$FORCE_BUILD" ]]; then
        echo "ERROR: building tiles on an ARM/Pi host is not recommended (RAM-heavy)." >&2
        echo "       Build on a workstation and copy the tar, then re-run with" >&2
        echo "       --routing-tar <path>. Use --force-build to override." >&2
        exit 1
    fi

    PBF="$ROUTING_DIR/source.osm.pbf"
    echo "==> downloading $PBF_URL"
    curl -fL --retry 3 -o "$PBF" "$PBF_URL"

    # Verify against Geofabrik's published md5 when available (truncated
    # downloads are the #1 cause of 'PBF error: unexpected EOF').
    if EXPECTED="$(curl -fsS "${PBF_URL}.md5" 2>/dev/null | awk '{print $1}')"; then
        if command -v md5sum >/dev/null; then ACTUAL="$(md5sum "$PBF" | awk '{print $1}')";
        else ACTUAL="$(md5 -q "$PBF")"; fi
        if [[ "$EXPECTED" != "$ACTUAL" ]]; then
            echo "ERROR: md5 mismatch (expected $EXPECTED, got $ACTUAL). Re-download." >&2
            exit 1
        fi
        echo "==> md5 verified"
    else
        echo "WARNING: no published .md5 to verify against; continuing." >&2
    fi

    echo "==> building Valhalla tiles (15-30 min, needs several GB RAM)..."
    # Clear any stale build state, keep the .pbf.
    rm -rf "$ROUTING_DIR/valhalla_tiles" "$ROUTING_DIR/valhalla_tiles.tar" \
           "$ROUTING_DIR/valhalla.json" "$ROUTING_DIR/file_hashes.txt" \
           "$ROUTING_DIR/duplicateways.txt"
    docker run --rm -v "$ROUTING_DIR:/custom_files" \
        -e use_tiles_ignore_pbf=False -e force_rebuild=True \
        -e build_tar=True -e serve_tiles=False "$IMAGE"

    [[ -f "$ROUTING_DIR/valhalla_tiles.tar" ]] || { echo "ERROR: build produced no tar" >&2; exit 1; }
    mv -f "$ROUTING_DIR/valhalla_tiles.tar" "$DEST_TAR"

    # Clean build by-products (the symlink + serve config are managed by the app).
    rm -rf "$ROUTING_DIR/valhalla_tiles" "$ROUTING_DIR/valhalla.json" \
           "$ROUTING_DIR/file_hashes.txt" "$ROUTING_DIR/duplicateways.txt"
    [[ -n "$KEEP_PBF" ]] || rm -f "$PBF"
fi

TAR_GB="$(du -m "$DEST_TAR" | awk '{printf "%.1f", $1/1024}')"
echo "==> routing tar ready: $DEST_TAR (${TAR_GB} GB)"

# ── 2. register the routing module + stage the active extract ─────────────────
echo "==> registering routing module and staging active extract"
CYBERDECK_DATA_DIR="$DATA_DIR" \
ROUTING_ID="$ROUTING_ID" MAP_ID="$MAP_ID" NAME="$NAME" SIZE_GB="$TAR_GB" \
uv run python - <<'PY'
import os
from pathlib import Path
from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry, save_registry
from app.services.packages import reconcile_active_routing

s = Settings(data_dir=Path(os.environ["CYBERDECK_DATA_DIR"]))
rid, mid = os.environ["ROUTING_ID"], os.environ["MAP_ID"]
reg = load_registry(s)
reg.modules = [m for m in reg.modules if m.id != rid]
reg.modules.append(Module(
    id=rid,
    display_name=os.environ["NAME"],
    category="navigation",
    description=f"Valhalla routing tiles for {mid}.",
    latest_version="1",
    size_gb=float(os.environ["SIZE_GB"]),
    kind="routing",
    checksum="sha256:local",
    routing_for=mid,
    installed_version="1",
    active=True,
))
save_registry(s, reg)
reconcile_active_routing(s)   # stages valhalla_tiles.tar symlink + restarts engine
print(f"registered {rid} -> serves {mid}")
PY

# ── 3. ensure the engine is up ───────────────────────────────────────────────
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 \
   && [[ -f "$REPO_ROOT/docker-compose.yml" ]]; then
    echo "==> starting companion services (docker compose)"
    docker compose up -d mbtileserver valhalla || true
elif command -v systemctl >/dev/null && systemctl list-unit-files | grep -q '^valhalla'; then
    echo "==> restarting valhalla (systemd)"
    sudo systemctl restart valhalla || true
else
    echo "NOTE: start the Valhalla service yourself (it must serve" >&2
    echo "      $ROUTING_DIR/valhalla_tiles.tar on the configured valhalla port)." >&2
fi

cat <<EOF

Done. Navigation is enabled for '$MAP_ID'.
Open /map/$MAP_ID, click the directions icon, set A and B, choose a mode, NAVIGATE.

Quick check:
  curl -s http://127.0.0.1:8082/status
EOF
