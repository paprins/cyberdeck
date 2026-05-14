#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "Error: run as a regular user (e.g. 'pi'), not root. The script uses sudo internally where needed." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="/data"

echo "=== Cyberdeck install ==="

# ── System packages ──────────────────────────────────────
# Includes pyenv's suggested build environment for compiling CPython from source.
# See https://github.com/pyenv/pyenv/wiki#suggested-build-environment
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    kiwix-tools \
    hdparm \
    cpufrequtils \
    chromium-browser \
    fonts-noto \
    git \
    curl \
    make \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    libffi-dev \
    liblzma-dev \
    tk-dev \
    xz-utils

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

# ── pyenv (system-wide at /opt/pyenv) ────────────────────
# Installed root-owned so every user gets read+exec, and managed via sudo.
export PYENV_ROOT="/opt/pyenv"
export PATH="${PYENV_ROOT}/bin:${PATH}"
if [[ ! -d "${PYENV_ROOT}" ]]; then
    echo "Installing pyenv to ${PYENV_ROOT}..."
    sudo git clone --depth 1 https://github.com/pyenv/pyenv.git "${PYENV_ROOT}"
fi

# Shell init for all users (login shells source /etc/profile.d/*.sh).
if [[ ! -f /etc/profile.d/pyenv.sh ]]; then
    echo "Installing /etc/profile.d/pyenv.sh..."
    sudo tee /etc/profile.d/pyenv.sh > /dev/null << 'EOF'
export PYENV_ROOT="/opt/pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - bash)"
EOF
    sudo chmod 0644 /etc/profile.d/pyenv.sh
fi
eval "$(pyenv init - bash)"

# ── Python (version from .python-version) ────────────────
cd "$REPO_DIR"
PYTHON_VERSION="$(cat .python-version)"
if ! pyenv versions --bare | grep -qx "${PYTHON_VERSION}"; then
    echo "Installing Python ${PYTHON_VERSION} via pyenv (builds from source — 15–30 min on a Pi)..."
    # sudo strips env by default; preserve PYENV_ROOT and PATH so pyenv writes to /opt.
    sudo env PYENV_ROOT="${PYENV_ROOT}" PATH="${PYENV_ROOT}/bin:${PATH}" \
        pyenv install "${PYTHON_VERSION}"
fi
PYBIN="${PYENV_ROOT}/versions/${PYTHON_VERSION}/bin/python"

# ── Project venv ─────────────────────────────────────────
# Recreate .venv if its Python doesn't match .python-version.
if [[ -d .venv ]]; then
    VENV_PYVER="$(.venv/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo "")"
    if [[ "${VENV_PYVER}" != "${PYTHON_VERSION}" ]]; then
        echo "Recreating .venv (was '${VENV_PYVER}', want '${PYTHON_VERSION}')..."
        rm -rf .venv
    fi
fi
if [[ ! -d .venv ]]; then
    echo "Creating .venv with Python ${PYTHON_VERSION}..."
    "${PYBIN}" -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

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
