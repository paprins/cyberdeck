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
INSTALL_ROOT="/opt/cyberdeck"

VERSION="$(grep -E '^version = ' "${REPO_DIR}/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')"
if [[ -z "$VERSION" ]]; then
    echo "Error: could not read version from pyproject.toml" >&2
    exit 1
fi
TARGET_DIR="${INSTALL_ROOT}/v${VERSION}"

echo "=== Cyberdeck install ==="
echo "→ Mode: $([[ "$INSTALL_KIOSK" == "1" ]] && echo kiosk || echo headless)"
echo "→ Version: ${VERSION}"
echo "→ Target: ${TARGET_DIR}"

# ── System packages ──────────────────────────────────────
echo "Installing system packages..."
sudo apt-get update -q
PACKAGES=(
    kiwix-tools
    hdparm
    linux-cpupower
    git
    curl
    unzip
    rsync
    minisign
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
export PYENV_ROOT="/opt/pyenv"
export PATH="${PYENV_ROOT}/bin:${PATH}"
if [[ ! -d "${PYENV_ROOT}" ]]; then
    echo "Installing pyenv to ${PYENV_ROOT}..."
    sudo git clone --depth 1 https://github.com/pyenv/pyenv.git "${PYENV_ROOT}"
fi

echo "Installing /etc/profile.d/pyenv.sh..."
sudo tee /etc/profile.d/pyenv.sh > /dev/null << 'EOF'
export PYENV_ROOT="/opt/pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init - --no-rehash bash)"
EOF
sudo chmod 0644 /etc/profile.d/pyenv.sh

# ── Python (version from .python-version) ────────────────
PYTHON_VERSION="$(cat "${REPO_DIR}/.python-version")"
if ! pyenv versions --bare | grep -qx "${PYTHON_VERSION}"; then
    echo "Installing Python ${PYTHON_VERSION} via pyenv (a few minutes on a Pi 5)..."
    sudo env PYENV_ROOT="${PYENV_ROOT}" PATH="${PYENV_ROOT}/bin:${PATH}" \
        pyenv install "${PYTHON_VERSION}"
fi
PYBIN="${PYENV_ROOT}/versions/${PYTHON_VERSION}/bin/python"

# ── /opt/cyberdeck install root ──────────────────────────
echo "Preparing ${INSTALL_ROOT}..."
sudo mkdir -p "${INSTALL_ROOT}"
sudo chown "${USER}:$(id -gn)" "${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}/upgrade"

# ── Sync source into versioned directory ─────────────────
echo "Syncing source to ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='tests/' \
    --exclude='dist/' \
    --exclude='build/' \
    --exclude='cyberdeck.tar.gz' \
    "${REPO_DIR}/" "${TARGET_DIR}/"

# ── Project venv inside versioned dir ────────────────────
if [[ -d "${TARGET_DIR}/.venv" ]]; then
    VENV_PYVER="$("${TARGET_DIR}/.venv/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo "")"
    if [[ "${VENV_PYVER}" != "${PYTHON_VERSION}" ]]; then
        echo "Recreating .venv (was '${VENV_PYVER}', want '${PYTHON_VERSION}')..."
        rm -rf "${TARGET_DIR}/.venv"
    fi
fi
if [[ ! -d "${TARGET_DIR}/.venv" ]]; then
    echo "Creating .venv with Python ${PYTHON_VERSION}..."
    "${PYBIN}" -m venv "${TARGET_DIR}/.venv"
fi
"${TARGET_DIR}/.venv/bin/pip" install --upgrade pip
"${TARGET_DIR}/.venv/bin/pip" install -e "${TARGET_DIR}"

# ── Activate this version via symlink ────────────────────
echo "Setting current → v${VERSION}..."
ln -sfn "${TARGET_DIR}" "${INSTALL_ROOT}/current.tmp"
mv -Tf "${INSTALL_ROOT}/current.tmp" "${INSTALL_ROOT}/current"

# ── Public signing key ───────────────────────────────────
echo "Installing release public key..."
sudo mkdir -p /etc/cyberdeck
sudo install -m 0644 "${REPO_DIR}/release.pub" /etc/cyberdeck/release.pub

# ── Data directories ─────────────────────────────────────
echo "Creating data directories at ${DATA_DIR}..."
sudo mkdir -p \
    "${DATA_DIR}/zim" \
    "${DATA_DIR}/maps" \
    "${DATA_DIR}/downloads" \
    "${DATA_DIR}/packages"
sudo chown -R "${USER}:$(id -gn)" "${DATA_DIR}"

if [[ ! -f "${DATA_DIR}/packages/registry.json" ]]; then
    cp "${TARGET_DIR}/data/packages/registry.json" "${DATA_DIR}/packages/registry.json"
fi

if [[ ! -d "${DATA_DIR}/static" ]]; then
    cp -r "${TARGET_DIR}/data/static" "${DATA_DIR}/static"
fi

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
for svc in "${TARGET_DIR}/systemd/"*.service; do
    name="$(basename "$svc")"
    sed -e "s|^User=pi$|User=${SVC_USER}|" \
        -e "s|^Group=pi$|Group=${SVC_GROUP}|" \
        "$svc" | sudo tee "/etc/systemd/system/${name}" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable cyberdeck.service kiwix.service mbtileserver.service

# ── Sudoers for upgrade-driven service restart ───────────
echo "Installing sudoers rule for upgrade restart..."
TMP_SUDOERS="$(mktemp)"
trap 'rm -f "$TMP_SUDOERS"' EXIT
sed "s|^pi |${USER} |" "${TARGET_DIR}/sudoers/cyberdeck-upgrade" > "$TMP_SUDOERS"
sudo visudo -cf "$TMP_SUDOERS" > /dev/null
sudo install -m 0440 "$TMP_SUDOERS" /etc/sudoers.d/cyberdeck-upgrade

# ── polkit rule for wifi management ──────────────────────
echo "Installing polkit rule for wifi management..."
sudo install -m 0644 \
    "${TARGET_DIR}/polkit/50-cyberdeck-nm.rules" \
    /etc/polkit-1/rules.d/50-cyberdeck-nm.rules

if ! id -nG "${USER}" | tr ' ' '\n' | grep -qx netdev; then
    echo "Adding ${USER} to netdev group..."
    sudo usermod -aG netdev "${USER}"
fi

# ── Start / restart services ─────────────────────────────
sudo systemctl restart kiwix.service mbtileserver.service cyberdeck.service

echo "=== Done. v${VERSION} active at ${TARGET_DIR}. Check: sudo systemctl status cyberdeck ==="
