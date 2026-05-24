#!/usr/bin/env bash
set -euo pipefail
# Apply a verified upgrade: verify → extract → build venv → migrate → swap → restart.
# Called by the Python service via Popen in a detached subprocess.
#
# Usage: upgrade.sh <tarball> <sigfile> <version>

TARBALL="${1:?tarball path required}"
SIG="${2:?sig path required}"
NEW_VERSION="${3:?version required}"

INSTALL_ROOT="/opt/cyberdeck"
PUBKEY="/etc/cyberdeck/release.pub"
TARGET_DIR="${INSTALL_ROOT}/v${NEW_VERSION}"
STATE_FILE="${INSTALL_ROOT}/upgrade/state.json"
CURRENT_SYM="${INSTALL_ROOT}/current"
WRITE_STATE="${INSTALL_ROOT}/current/scripts/_write_state.py"

OLD_VERSION=""
if [[ -L "${CURRENT_SYM}" ]]; then
    OLD_VERSION="$(basename "$(readlink -f "${CURRENT_SYM}")" | sed 's/^v//')"
fi

_state() { python3 "${WRITE_STATE}" "$1" "${2:-}" "$NEW_VERSION" "$OLD_VERSION" "$STATE_FILE"; }

_fail() {
    _state "failed" "$1"
    rm -rf "${TARGET_DIR}"
    exit 1
}

# 1. Verify signature + trusted-comment version
_state "verifying" "checking signature"
if ! [[ "${NEW_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    _fail "invalid_version_format"
fi
MINISIGN_OUT="$(minisign -V -p "${PUBKEY}" -m "${TARBALL}" -x "${SIG}" 2>/dev/null)" \
    || _fail "signature_invalid"
EXPECTED_TC="Trusted comment: cyberdeck release v${NEW_VERSION}"
if ! grep -qxF "${EXPECTED_TC}" <<< "${MINISIGN_OUT}"; then
    _fail "version_mismatch_in_signature"
fi

# 2. Extract
_state "extracting" "unpacking tarball"
mkdir -p "${TARGET_DIR}"
tar -xzf "${TARBALL}" -C "${TARGET_DIR}" --strip-components=1 || _fail "extract_failed"
chmod +x "${TARGET_DIR}"/scripts/*.sh 2>/dev/null || true

# 3. Build venv with bundled wheels
_state "building_venv" "creating virtualenv"
PYBIN="$(command -v python3)"
if [[ ! -x "${PYBIN}" ]]; then
    _fail "no_python"
fi
"${PYBIN}" -m venv "${TARGET_DIR}/.venv" || _fail "venv_create_failed"

WHEEL_DIR="${TARGET_DIR}/dist/wheels"
PIP="${TARGET_DIR}/.venv/bin/pip"
if [[ -d "${WHEEL_DIR}" ]]; then
    # Install the prebuilt wheel by name (avoids PEP 517 build → no hatchling needed offline)
    "${PIP}" install --no-index --find-links "${WHEEL_DIR}" \
        "cyberdeck==${NEW_VERSION}" || _fail "pip_install_offline_failed"
else
    "${PIP}" install -e "${TARGET_DIR}" || _fail "pip_install_failed"
fi

# 4. Run migrations whose version is strictly OLD < V <= NEW
_state "migrating" "running migrations"
PY="${TARGET_DIR}/.venv/bin/python"
shopt -s nullglob
for migration in "${TARGET_DIR}/migrations/"v*.py; do
    fname="$(basename "${migration}")"
    mig_ver="${fname#v}"
    mig_ver="${mig_ver%.py}"
    # Skip if mig_ver <= OLD_VERSION (strict greater-than required)
    if [[ -n "${OLD_VERSION}" ]]; then
        if [[ "${mig_ver}" == "${OLD_VERSION}" ]]; then continue; fi
        if printf '%s\n%s\n' "${mig_ver}" "${OLD_VERSION}" | sort -VC; then continue; fi
    fi
    # Skip if mig_ver > NEW_VERSION
    if ! printf '%s\n%s\n' "${mig_ver}" "${NEW_VERSION}" | sort -VC; then continue; fi
    if ! "${PY}" "${migration}"; then
        _fail "migration_failed: ${fname}"
    fi
done

# 5. Atomic symlink swap (must precede watcher spawn so swap phase is observable)
_state "swapping" "activating new version"
ln -sfn "${TARGET_DIR}" "${INSTALL_ROOT}/current.tmp"
mv -Tf "${INSTALL_ROOT}/current.tmp" "${CURRENT_SYM}"

# 6. Spawn detached health watcher BEFORE restart (it owns post-restart phases)
_state "restarting" "starting service"
WATCH="${TARGET_DIR}/scripts/watch_health.sh"
if [[ -x "${WATCH}" ]]; then
    nohup "${WATCH}" "${NEW_VERSION}" "${OLD_VERSION}" \
        > "${INSTALL_ROOT}/upgrade/watch.log" 2>&1 < /dev/null &
    disown || true
fi

# 7. Restart service (NOPASSWD via sudoers)
sudo /bin/systemctl restart cyberdeck.service
