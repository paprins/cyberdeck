#!/usr/bin/env bash
# Sets up Chromium to launch in fullscreen kiosk mode on boot.
# Run as pi user after install.sh.
set -euo pipefail

AUTOSTART_DIR="$HOME/.config/lxsession/LXDE-pi"
mkdir -p "$AUTOSTART_DIR"

# Disable screen blanking + screensaver
cat > "$AUTOSTART_DIR/autostart" << 'EOF'
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xscreensaver -no-splash
@xset s off
@xset -dpms
@xset s noblank
@chromium-browser \
    --start-fullscreen \
    --app=http://localhost:8000 \
    --disable-gpu-compositing \
    --disable-smooth-scrolling \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000
EOF

echo "Chromium kiosk configured. Reboot to activate."
echo "Note: --start-fullscreen (not --kiosk) allows Ctrl+T for new tabs and Ctrl+L for address bar."
echo "This is intentional — see design spec §3.2."
