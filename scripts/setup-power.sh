#!/usr/bin/env bash
# Configures power saving for battery operation.
# Run as root (sudo scripts/setup-power.sh).
set -euo pipefail

# ── CPU governor: conservative ────────────────────────────
# Clocks down on idle, ramps up on load. Better than ondemand
# for battery because it doesn't spike as aggressively.
echo "Setting CPU governor to conservative..."
apt-get install -y cpufrequtils -q
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
    echo conservative > "${cpu}/cpufreq/scaling_governor" 2>/dev/null || true
done

# Persist across reboots
cat > /etc/default/cpufrequtils << 'EOF'
GOVERNOR="conservative"
EOF

# ── SSD power management ──────────────────────────────────
# APM level 128: moderate — spins down after idle but not
# aggressively (avoids excessive load-cycle wear).
# Detect the SSD block device (assumes single external drive).
SSD_DEV=$(lsblk -dpno NAME,TRAN | awk '$2=="usb" || $2=="nvme" {print $1}' | head -1)
if [[ -n "$SSD_DEV" ]]; then
    echo "Setting SSD APM on ${SSD_DEV}..."
    hdparm -B 128 "$SSD_DEV"
    # Persist via udev rule
    SERIAL=$(udevadm info --query=property --name="$SSD_DEV" | grep ID_SERIAL= | cut -d= -f2)
    cat > /etc/udev/rules.d/60-ssd-power.rules << EOF
ACTION=="add", SUBSYSTEM=="block", ENV{ID_SERIAL}=="${SERIAL}", \
    RUN+="/sbin/hdparm -B 128 /dev/%k"
EOF
fi

echo "Power management configured."
