#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") (--kiosk | --headless) [--version X.Y.Z | --local]

Install the Cyberdeck stack on this machine.

Modes:
  --kiosk           Install with Chromium for the touchscreen UI.
  --headless        Install server only (no browser).
  --version X.Y.Z   Install a specific release (downloaded from GitHub).
  --local           Install from the local repo source (skips signature check).
                    Only available when run from a cloned repo.

Without --version or --local, installs the latest GitHub release.

Defaults to paprins/cyberdeck. Override with CYBERDECK_REPO=owner/repo for forks.
EOF
}

if [[ $# -eq 0 ]]; then usage >&2; exit 1; fi

INSTALL_KIOSK=""
VERSION=""
LOCAL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kiosk)    INSTALL_KIOSK=1; shift ;;
        --headless) INSTALL_KIOSK=0; shift ;;
        --version)  VERSION="${2#v}"; shift 2 ;;
        --local)    LOCAL=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ -z "$INSTALL_KIOSK" ]]; then
    echo "Error: must specify --kiosk or --headless" >&2; usage >&2; exit 1
fi
if [[ $EUID -eq 0 ]]; then
    echo "Error: run as a regular user (e.g. 'pi'), not root." >&2; exit 1
fi
if [[ -n "$LOCAL" && -n "$VERSION" ]]; then
    echo "Error: --local and --version are mutually exclusive" >&2; exit 1
fi

DATA_DIR="/data"
INSTALL_ROOT="/opt/cyberdeck"

# ── Detect run mode: file in clone, or piped via curl ────
REPO_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]:-}" ]] \
   && [[ -f "$(dirname "${BASH_SOURCE[0]}")/../pyproject.toml" ]]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

if [[ -n "$LOCAL" && -z "$REPO_DIR" ]]; then
    echo "Error: --local requires running from a cloned repo, not via curl|bash" >&2
    exit 1
fi

# ── Determine GitHub repo (for release downloads) ────────
# Defaults to paprins/cyberdeck; override via CYBERDECK_REPO env var if forking,
# or auto-detect from the origin remote when run from a clone.
if [[ -z "$LOCAL" ]]; then
    GITHUB_REPO="${CYBERDECK_REPO:-}"
    if [[ -z "$GITHUB_REPO" && -n "$REPO_DIR" ]]; then
        GH_URL="$(git -C "${REPO_DIR}" config --get remote.origin.url 2>/dev/null || true)"
        GITHUB_REPO="$(echo "$GH_URL" | sed -E 's|^(git@github.com:|https://github.com/)([^/]+/[^/.]+)(\.git)?$|\2|')"
        [[ "$GITHUB_REPO" == "$GH_URL" ]] && GITHUB_REPO=""
    fi
    GITHUB_REPO="${GITHUB_REPO:-paprins/cyberdeck}"
fi

# ── Resolve version ──────────────────────────────────────
if [[ -n "$LOCAL" ]]; then
    VERSION="$(grep -E '^version = ' "${REPO_DIR}/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')"
elif [[ -z "$VERSION" ]]; then
    # curl needs to be installed before we can call it; pull from system or apt-bootstrap
    if ! command -v curl >/dev/null 2>&1; then
        sudo apt-get update -q && sudo apt-get install -y curl
    fi
    echo "Querying latest release from ${GITHUB_REPO}..."
    LATEST_TAG="$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" \
        | grep -m1 '"tag_name"' | sed 's/.*"\(v[^"]*\)".*/\1/')"
    if [[ -z "$LATEST_TAG" ]]; then
        echo "Error: could not determine latest release" >&2; exit 1
    fi
    VERSION="${LATEST_TAG#v}"
fi
[[ -z "$VERSION" ]] && { echo "Error: empty version" >&2; exit 1; }
TARGET_DIR="${INSTALL_ROOT}/v${VERSION}"

echo "=== Cyberdeck install ==="
echo "→ Mode:    $([[ "$INSTALL_KIOSK" == "1" ]] && echo kiosk || echo headless)"
echo "→ Source:  $([[ -n "$LOCAL" ]] && echo "local repo (${REPO_DIR})" || echo "github release (${GITHUB_REPO})")"
echo "→ Version: ${VERSION}"
echo "→ Target:  ${TARGET_DIR}"

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

# ── /opt/cyberdeck install root ──────────────────────────
echo "Preparing ${INSTALL_ROOT}..."
sudo mkdir -p "${INSTALL_ROOT}"
sudo chown "${USER}:$(id -gn)" "${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}/upgrade"

# ── Populate ${TARGET_DIR} ───────────────────────────────
WORK_TMP="$(mktemp -d)"
trap 'rm -rf "$WORK_TMP"' EXIT

if [[ -n "$LOCAL" ]]; then
    echo "Syncing local source to ${TARGET_DIR}..."
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
    PUBKEY="${REPO_DIR}/release.pub"
else
    # Source the trusted public key. Locally if a clone is available, else
    # over HTTPS from the same repo we are fetching the release from.
    PUBKEY="${WORK_TMP}/release.pub"
    if [[ -n "$REPO_DIR" && -f "${REPO_DIR}/release.pub" ]]; then
        cp "${REPO_DIR}/release.pub" "$PUBKEY"
    else
        echo "Downloading release.pub..."
        curl -fsSL "https://raw.githubusercontent.com/${GITHUB_REPO}/main/release.pub" -o "$PUBKEY"
    fi

    TARBALL="${WORK_TMP}/cyberdeck-v${VERSION}.tar.gz"
    SIG="${TARBALL}.minisig"
    BASE_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}"
    echo "Downloading cyberdeck-v${VERSION}.tar.gz..."
    curl -fL --progress-bar -o "$TARBALL" "${BASE_URL}/cyberdeck-v${VERSION}.tar.gz"
    curl -fL --progress-bar -o "$SIG"     "${BASE_URL}/cyberdeck-v${VERSION}.tar.gz.minisig"

    echo "Verifying signature..."
    MINISIGN_OUT="$(minisign -V -p "$PUBKEY" -m "$TARBALL" -x "$SIG" 2>/dev/null)" \
        || { echo "Error: signature verification failed" >&2; exit 1; }
    EXPECTED_TC="Trusted comment: cyberdeck release v${VERSION}"
    if ! grep -qxF "${EXPECTED_TC}" <<< "${MINISIGN_OUT}"; then
        echo "Error: trusted comment does not match v${VERSION}" >&2; exit 1
    fi

    echo "Extracting to ${TARGET_DIR}..."
    rm -rf "${TARGET_DIR}"
    mkdir -p "${TARGET_DIR}"
    tar -xzf "$TARBALL" -C "${TARGET_DIR}" --strip-components=1
fi

# ── pyenv + Python (.python-version sourced from TARGET_DIR) ──
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

PYTHON_VERSION="$(cat "${TARGET_DIR}/.python-version")"
if ! pyenv versions --bare | grep -qx "${PYTHON_VERSION}"; then
    echo "Installing Python ${PYTHON_VERSION} via pyenv (a few minutes on a Pi 5)..."
    sudo env PYENV_ROOT="${PYENV_ROOT}" PATH="${PYENV_ROOT}/bin:${PATH}" \
        pyenv install "${PYTHON_VERSION}"
fi
PYBIN="${PYENV_ROOT}/versions/${PYTHON_VERSION}/bin/python"

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

WHEEL_DIR="${TARGET_DIR}/dist/wheels"
PIP="${TARGET_DIR}/.venv/bin/pip"
if [[ -d "${WHEEL_DIR}" ]]; then
    echo "Installing dependencies from bundled wheels..."
    "${PIP}" install --no-index --find-links "${WHEEL_DIR}" "${TARGET_DIR}"
else
    echo "Installing dependencies from PyPI..."
    "${PIP}" install --upgrade pip
    "${PIP}" install -e "${TARGET_DIR}"
fi

# ── Activate this version via symlink ────────────────────
echo "Setting current → v${VERSION}..."
ln -sfn "${TARGET_DIR}" "${INSTALL_ROOT}/current.tmp"
mv -Tf "${INSTALL_ROOT}/current.tmp" "${INSTALL_ROOT}/current"

# ── Public signing key ───────────────────────────────────
echo "Installing release public key..."
sudo mkdir -p /etc/cyberdeck
sudo install -m 0644 "$PUBKEY" /etc/cyberdeck/release.pub

# ── Data directories ─────────────────────────────────────
echo "Creating data directories at ${DATA_DIR}..."
sudo mkdir -p \
    "${DATA_DIR}/zim" \
    "${DATA_DIR}/maps" \
    "${DATA_DIR}/downloads" \
    "${DATA_DIR}/packages"
sudo chown -R "${USER}:$(id -gn)" "${DATA_DIR}"

if [[ ! -f "${DATA_DIR}/packages/registry.json" && -f "${TARGET_DIR}/data/packages/registry.json" ]]; then
    cp "${TARGET_DIR}/data/packages/registry.json" "${DATA_DIR}/packages/registry.json"
fi

if [[ ! -d "${DATA_DIR}/static" && -d "${TARGET_DIR}/data/static" ]]; then
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
trap 'rm -f "$TMP_SUDOERS"; rm -rf "$WORK_TMP"' EXIT
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
