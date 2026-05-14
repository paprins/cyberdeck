#!/usr/bin/env bash
set -euo pipefail
# Detached health watcher spawned by upgrade.sh before the service restart.
# Polls /health for 30s; rolls back symlink + restarts on failure.
#
# Usage: watch_health.sh <new_version> <old_version>

NEW_VERSION="${1:?new version required}"
OLD_VERSION="${2:-}"

INSTALL_ROOT="/opt/cyberdeck"
STATE_FILE="${INSTALL_ROOT}/upgrade/state.json"
HEALTH_URL="http://127.0.0.1:8000/health"
WRITE_STATE="${INSTALL_ROOT}/current/scripts/_write_state.py"

_state() { python3 "${WRITE_STATE}" "$1" "${2:-}" "$NEW_VERSION" "$OLD_VERSION" "$STATE_FILE"; }

_state "health_checking" "polling /health"
DEADLINE=$(($(date +%s) + 30))
while (( $(date +%s) < DEADLINE )); do
    sleep 2
    if curl -sf --max-time 3 "${HEALTH_URL}" | grep -q '"ok"'; then
        _state "success" "v${NEW_VERSION} healthy"
        if [[ -x "${INSTALL_ROOT}/current/.venv/bin/python" ]]; then
            "${INSTALL_ROOT}/current/.venv/bin/python" -c \
                "from app.services.upgrade import cleanup_old_versions; cleanup_old_versions()" \
                || true
        fi
        exit 0
    fi
done

if [[ -z "${OLD_VERSION}" ]]; then
    _state "failed" "health check timeout, no previous version to roll back to"
    exit 1
fi

ROLLBACK_DIR="${INSTALL_ROOT}/v${OLD_VERSION}"
if [[ ! -d "${ROLLBACK_DIR}" ]]; then
    _state "failed" "rollback target ${ROLLBACK_DIR} missing"
    exit 1
fi

ln -sfn "${ROLLBACK_DIR}" "${INSTALL_ROOT}/current.tmp"
mv -Tf "${INSTALL_ROOT}/current.tmp" "${INSTALL_ROOT}/current"
sudo /bin/systemctl restart cyberdeck.service

sleep 10
if curl -sf --max-time 3 "${HEALTH_URL}" | grep -q '"ok"'; then
    _state "rolled_back" "rolled back to v${OLD_VERSION}"
    exit 0
fi
_state "failed" "rollback restart also failed; manual recovery required"
exit 1
