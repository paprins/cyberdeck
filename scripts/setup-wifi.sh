#!/usr/bin/env bash
set -euo pipefail

# Creates a WiFi access point named after the device hostname.
# Idempotent: safe to run multiple times.

[[ $EUID -eq 0 ]] || { echo "Error: run as root" >&2; exit 1; }

AP_SSID=$(hostname)
AP_PASSWORD="${WIFI_PASSWORD:-${AP_SSID}}"
CON_NAME="${AP_SSID}"
AP_IFACE="uap0"
STA_IFACE="wlan0"
SERVICE="/etc/systemd/system/uap0.service"

echo "=== WiFi access point: ${AP_SSID} ==="

# ── 1. Virtual AP interface ───────────────────────────────────────────────────
if iw dev "${AP_IFACE}" info &>/dev/null; then
    echo "[1] Interface ${AP_IFACE} already exists — skip"
else
    echo "[1] Creating virtual AP interface ${AP_IFACE}..."
    iw dev "${STA_IFACE}" interface add "${AP_IFACE}" type __ap
fi

# ── 2. NetworkManager connection ──────────────────────────────────────────────
if nmcli connection show "${CON_NAME}" &>/dev/null; then
    echo "[2] NM connection '${CON_NAME}' already exists — skip"
else
    echo "[2] Creating NM connection '${CON_NAME}'..."
    nmcli connection add \
        type wifi \
        ifname "${AP_IFACE}" \
        con-name "${CON_NAME}" \
        ssid "${CON_NAME}" \
        802-11-wireless.mode ap \
        802-11-wireless.band bg \
        802-11-wireless.channel 6 \
        ipv4.method shared \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "${AP_PASSWORD}" \
        autoconnect yes
fi

# ── 3. Activate connection ────────────────────────────────────────────────────
# Check actual AP mode on the interface, not just NM "active" status — the
# connection can be "active" in NM's view while the interface is in managed mode.
if iw dev "${AP_IFACE}" info 2>/dev/null | grep -q "type AP"; then
    echo "[3] Interface ${AP_IFACE} is in AP mode — skip"
else
    echo "[3] Activating connection '${CON_NAME}'..."
    nmcli connection up "${CON_NAME}"
fi

# ── 4. Systemd service for uap0 persistence across reboots ───────────────────
# Always write the service file so changes take effect on re-runs.
# Run After NetworkManager (not Before) so nmcli is available for explicit
# activation — autoconnect on a virtual interface is unreliable at boot.
echo "[4] Installing/updating systemd service uap0..."
cat > "${SERVICE}" << EOF
[Unit]
Description=Create uap0 virtual WiFi AP interface
Requires=sys-subsystem-net-devices-${STA_IFACE}.device
After=sys-subsystem-net-devices-${STA_IFACE}.device NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/iw dev ${STA_IFACE} interface add ${AP_IFACE} type __ap
ExecStartPost=/usr/bin/nmcli connection up ${CON_NAME}
ExecStop=/usr/bin/nmcli connection down ${CON_NAME}
ExecStop=/sbin/iw dev ${AP_IFACE} del

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable uap0

# ── 5. Start service ──────────────────────────────────────────────────────────
if systemctl is-active --quiet uap0; then
    echo "[5] Service uap0 already active — skip"
else
    echo "[5] Starting service uap0..."
    systemctl start uap0
fi

echo ""
echo "Done. Access point '${AP_SSID}' is live."
echo "  Password : ${AP_PASSWORD}"
iw dev "${AP_IFACE}" info
