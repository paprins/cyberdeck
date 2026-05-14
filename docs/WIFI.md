Step 1: Verify current state

  nmcli device status
  iw dev

  Step 2: Create the virtual AP interface

  iw dev wlan0 interface add uap0 type __ap

  Step 3: Create the hotspot connection

  nmcli connection add \
    type wifi \
    ifname uap0 \
    con-name "cyberdeck-two" \
    ssid "cyberdeck-two" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel 6 \
    ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "yourpassword" \
    autoconnect yes

  ipv4.method shared sets up NAT so AP clients share the Pi's WiFi uplink.

  Step 4: Bring it up

  nmcli connection up cyberdeck-two

  Step 5: Make uap0 persist across reboots

  iw interface add doesn't survive reboots, and it must run before NetworkManager tries to activate the connection. Create a systemd service:

  cat > /etc/systemd/system/uap0.service << EOF
  [Unit]
  Description=Create uap0 virtual WiFi AP interface
  Before=NetworkManager.service
  After=sys-subsystem-net-devices-wlan0.device

  [Service]
  Type=oneshot
  RemainAfterExit=yes
  ExecStart=/sbin/iw dev wlan0 interface add uap0 type __ap
  ExecStop=/sbin/iw dev uap0 del

  [Install]
  WantedBy=multi-user.target
  EOF

  systemctl enable uap0
  systemctl start uap0

  Verify

  nmcli connection show cyberdeck-two
  iw dev uap0 info

  You should see type AP in the iw output and clients will be assigned addresses in the 10.42.0.0/24 range by default (NetworkManager's shared mode
  uses dnsmasq under the hood).

  ---
  Notes:
  - Channel 6 is a safe default; if your uplink AP is also on 2.4 GHz, pick a non-overlapping channel (1, 6, or 11).
  - If you want 5 GHz instead: replace band bg channel 6 with band a channel 36 (check local regulations).
  - If you want an open AP (no password), omit the wifi-sec.* lines entirely.