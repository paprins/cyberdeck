#!/usr/bin/env bash
# Fail-safe by design: we don't use `set -e` so a missing file or stopped
# service never aborts the rest of the cleanup. Errors from individual steps
# are tolerated; running this script twice is safe.
set -uo pipefail

usage() {
    cat <<EOF
Usage: $(basename "$0") [--yes] [--purge]

Remove a Cyberdeck install from this machine. Idempotent: safe to re-run.

Flags:
  -y, --yes     Skip confirmation prompt.
  --purge       ALSO remove /data (ZIM files, maps, registry),
                /opt/pyenv, and /usr/local/bin/mbtileserver.

By default, /data and shared tooling (pyenv, mbtileserver) are PRESERVED so
content downloads survive a reinstall. APT-installed system packages are
never removed.
EOF
}

ASSUME_YES=""
PURGE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)  ASSUME_YES=1; shift ;;
        --purge)   PURGE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ $EUID -eq 0 ]]; then
    echo "Error: run as a regular user (e.g. 'pi'), not root." >&2; exit 1
fi

INSTALL_ROOT="/opt/cyberdeck"
DATA_DIR="/data"
PYENV_ROOT="/opt/pyenv"
MBTILES_BINARY="/usr/local/bin/mbtileserver"
SERVICES=(cyberdeck.service kiwix.service mbtileserver.service)

echo "=== Cyberdeck uninstall ==="
echo "→ Remove: systemd units, ${INSTALL_ROOT}, /etc/cyberdeck, sudoers, polkit, profile.d"
if [[ -n "$PURGE" ]]; then
    echo "→ Also remove (--purge): ${DATA_DIR}, ${PYENV_ROOT}, ${MBTILES_BINARY}"
fi
echo

if [[ -z "$ASSUME_YES" ]]; then
    read -r -p "Proceed? [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

# Helper: report a step but never abort on failure.
step() { echo "→ $*"; }

# ── Stop and disable systemd units ───────────────────────
for svc in "${SERVICES[@]}"; do
    if systemctl list-unit-files "$svc" >/dev/null 2>&1; then
        step "Stopping ${svc}"
        sudo systemctl stop "$svc" 2>/dev/null || true
        sudo systemctl disable "$svc" 2>/dev/null || true
    fi
done

# ── Remove unit files ────────────────────────────────────
for svc in "${SERVICES[@]}"; do
    if [[ -e "/etc/systemd/system/${svc}" ]]; then
        step "Removing /etc/systemd/system/${svc}"
        sudo rm -f "/etc/systemd/system/${svc}"
    fi
done
sudo systemctl daemon-reload 2>/dev/null || true
sudo systemctl reset-failed 2>/dev/null || true

# ── /opt/cyberdeck (versioned installs + 'current' + 'upgrade') ──
if [[ -e "${INSTALL_ROOT}" ]]; then
    step "Removing ${INSTALL_ROOT}"
    sudo rm -rf "${INSTALL_ROOT}"
fi

# ── Release pubkey ───────────────────────────────────────
if [[ -e /etc/cyberdeck ]]; then
    step "Removing /etc/cyberdeck"
    sudo rm -rf /etc/cyberdeck
fi

# ── Sudoers fragment ─────────────────────────────────────
if [[ -e /etc/sudoers.d/cyberdeck-upgrade ]]; then
    step "Removing /etc/sudoers.d/cyberdeck-upgrade"
    sudo rm -f /etc/sudoers.d/cyberdeck-upgrade
fi

# ── Polkit rule ──────────────────────────────────────────
if [[ -e /etc/polkit-1/rules.d/50-cyberdeck-nm.rules ]]; then
    step "Removing /etc/polkit-1/rules.d/50-cyberdeck-nm.rules"
    sudo rm -f /etc/polkit-1/rules.d/50-cyberdeck-nm.rules
fi

# ── profile.d pyenv shim ─────────────────────────────────
if [[ -e /etc/profile.d/pyenv.sh ]]; then
    step "Removing /etc/profile.d/pyenv.sh"
    sudo rm -f /etc/profile.d/pyenv.sh
fi

# ── --purge: data dir, pyenv, mbtileserver binary ───────
if [[ -n "$PURGE" ]]; then
    if [[ -e "${DATA_DIR}" ]]; then
        step "Removing ${DATA_DIR} (--purge)"
        sudo rm -rf "${DATA_DIR}"
    fi
    if [[ -e "${PYENV_ROOT}" ]]; then
        step "Removing ${PYENV_ROOT} (--purge)"
        sudo rm -rf "${PYENV_ROOT}"
    fi
    if [[ -e "${MBTILES_BINARY}" ]]; then
        step "Removing ${MBTILES_BINARY} (--purge)"
        sudo rm -f "${MBTILES_BINARY}"
    fi
fi

echo
echo "=== Done. ==="
if [[ -z "$PURGE" ]]; then
    echo "Preserved: ${DATA_DIR}, ${PYENV_ROOT}, ${MBTILES_BINARY}"
    echo "Pass --purge to remove these as well."
fi
echo "APT packages (kiwix-tools, minisign, build deps, chromium...) were NOT removed."
echo "User group membership (netdev) was NOT changed."
