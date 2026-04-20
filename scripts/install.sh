#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="/data"

echo "=== Cyberdeck install ==="

# ── System packages ──────────────────────────────────────
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    kiwix-tools \
    hdparm \
    cpufrequtils \
    chromium-browser \
    fonts-noto \
    python3.14 \
    python3.14-venv

# ── mbtileserver (arm64 binary from GitHub releases) ─────
MBTILES_VERSION="0.10.0"
MBTILES_BINARY="/usr/local/bin/mbtileserver"
if [[ ! -f "$MBTILES_BINARY" ]]; then
    echo "Installing mbtileserver ${MBTILES_VERSION}..."
    curl -fsSL \
        "https://github.com/developmentseed/mbtileserver/releases/download/v${MBTILES_VERSION}/mbtileserver_linux_arm64" \
        -o "$MBTILES_BINARY"
    sudo chmod +x "$MBTILES_BINARY"
fi

# ── uv ───────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# ── Python venv ──────────────────────────────────────────
echo "Creating Python venv..."
cd "$REPO_DIR"
uv venv
uv pip install -e .

# ── Data directories ─────────────────────────────────────
echo "Creating data directories at ${DATA_DIR}..."
sudo mkdir -p \
    "${DATA_DIR}/zim" \
    "${DATA_DIR}/maps" \
    "${DATA_DIR}/downloads" \
    "${DATA_DIR}/packages"
sudo chown -R pi:pi "${DATA_DIR}"

# Seed registry if missing
if [[ ! -f "${DATA_DIR}/packages/registry.json" ]]; then
    cp "${REPO_DIR}/data/packages/registry.json" "${DATA_DIR}/packages/registry.json"
fi

# Seed empty kiwix library if missing
if [[ ! -f "${DATA_DIR}/zim/library.xml" ]]; then
    cat > "${DATA_DIR}/zim/library.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8" ?>
<library version="1.0">
</library>
XML
fi

# ── systemd services ─────────────────────────────────────
echo "Installing systemd services..."
sudo cp "${REPO_DIR}/systemd/"*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cyberdeck.service kiwix.service mbtileserver.service
sudo systemctl start kiwix.service mbtileserver.service cyberdeck.service

echo "=== Done. Check: sudo systemctl status cyberdeck ==="
