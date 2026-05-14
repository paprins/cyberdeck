#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") (--kiosk | --headless)

Install the Cyberdeck stack on this machine.

Modes:
  --kiosk     Install with Chromium for the touchscreen UI.
  --headless  Install server only (no browser).

You must pass exactly one of --kiosk or --headless.
EOF
}

if [[ $# -eq 0 ]]; then
    usage >&2
    exit 1
fi

INSTALL_KIOSK=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kiosk)    INSTALL_KIOSK=1 ;;
        --headless) INSTALL_KIOSK=0 ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
    shift
done

if [[ -z "$INSTALL_KIOSK" ]]; then
    echo "Error: must specify --kiosk or --headless" >&2
    usage >&2
    exit 1
fi

if [[ $EUID -eq 0 ]]; then
    echo "Error: run as a regular user (e.g. 'pi'), not root. The script uses sudo internally where needed." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="/data"

echo "=== Cyberdeck install ==="
if [[ "$INSTALL_KIOSK" == "1" ]]; then
    echo "→ Mode: kiosk"
else
    echo "→ Mode: headless"
fi

# ── System packages ──────────────────────────────────────
# Includes pyenv's suggested build environment for compiling CPython from source.
# See https://github.com/pyenv/pyenv/wiki#suggested-build-environment
echo "Installing system packages..."
sudo apt-get update -q
PACKAGES=(
    kiwix-tools
    hdparm
    linux-cpupower
    git
    curl
    unzip
    make
    build-essential
    libssl-dev
    zlib1g-dev
    libbz2-dev
    libreadline-dev
    libsqlite3-dev
    libncursesw5-dev
    libffi-dev
    liblzma-dev
    tk-dev
    xz-utils
)
if [[ "$INSTALL_KIOSK" == "1" ]]; then
    PACKAGES+=(chromium fonts-noto)
fi
sudo apt-get install -y "${PACKAGES[@]}"

# ── mbtileserver (arm64 binary from GitHub releases) ─────
MBTILES_VERSION="0.11.0"
MBTILES_BINARY="/usr/local/bin/mbtileserver"
if [[ ! -f "$MBTILES_BINARY" ]]; then
    echo "Installing mbtileserver ${MBTILES_VERSION}..."
    MBTILES_TMP="$(mktemp -d)"
    curl -fsSL \
        "https://github.com/consbio/mbtileserver/releases/download/v${MBTILES_VERSION}/mbtileserver_v${MBTILES_VERSION}_linux_arm64.zip" \
        -o "${MBTILES_TMP}/mbtileserver.zip"
    unzip -q "${MBTILES_TMP}/mbtileserver.zip" -d "${MBTILES_TMP}"
    sudo install -m 0755 "${MBTILES_TMP}/mbtileserver_v${MBTILES_VERSION}_linux_arm64" "$MBTILES_BINARY"
    rm -rf "${MBTILES_TMP}"
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
# --no-rehash because /opt/pyenv/shims is root-owned; rehash is done by sudo
# during installs, so users don't need to write to shims at login.
echo "Installing /etc/profile.d/pyenv.sh..."
sudo tee /etc/profile.d/pyenv.sh > /dev/null << 'EOF'
export PYENV_ROOT="/opt/pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - --no-rehash bash)"
EOF
sudo chmod 0644 /etc/profile.d/pyenv.sh

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
sudo chown -R "${USER}:$(id -gn)" "${DATA_DIR}"

# Seed registry if missing
if [[ ! -f "${DATA_DIR}/packages/registry.json" ]]; then
    cp "${REPO_DIR}/data/packages/registry.json" "${DATA_DIR}/packages/registry.json"
fi

# Seed static assets if missing
if [[ ! -d "${DATA_DIR}/static" ]]; then
    cp -r "${REPO_DIR}/data/static" "${DATA_DIR}/static"
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
SVC_USER="${USER}"
SVC_GROUP="$(id -gn)"
for svc in "${REPO_DIR}/systemd/"*.service; do
    name="$(basename "$svc")"
    sed -e "s|^User=pi$|User=${SVC_USER}|" \
        -e "s|^Group=pi$|Group=${SVC_GROUP}|" \
        -e "s|/home/pi/cyberdeck|${REPO_DIR}|g" \
        "$svc" | sudo tee "/etc/systemd/system/${name}" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable cyberdeck.service kiwix.service mbtileserver.service
sudo systemctl start kiwix.service mbtileserver.service cyberdeck.service

# ── polkit rule for wifi management ──────────────────────
# Lets the cyberdeck service (running as $USER) drive NetworkManager via nmcli
# without an interactive auth prompt.
echo "Installing polkit rule for wifi management..."
sudo install -m 0644 \
    "${REPO_DIR}/polkit/50-cyberdeck-nm.rules" \
    /etc/polkit-1/rules.d/50-cyberdeck-nm.rules

if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx netdev; then
    echo "Adding ${USER} to netdev group..."
    sudo usermod -aG netdev "${USER}"
    echo "  (group change takes effect on next login or service restart)"
fi

# Restart cyberdeck so the new netdev supplementary group is in its credentials.
sudo systemctl restart cyberdeck.service

echo "=== Done. Check: sudo systemctl status cyberdeck ==="
