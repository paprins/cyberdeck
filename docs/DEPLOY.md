# Deploying cyberdeck to a Raspberry Pi

End-to-end guide for getting the app from this repo onto a Pi and running on boot.

## What runs on the Pi

Three `systemd`-managed services on `localhost`:

| Service       | Port | Unit file                          |
| ------------- | ---- | ---------------------------------- |
| FastAPI (UI)  | 8000 | `systemd/cyberdeck.service`        |
| kiwix-serve   | 8080 | `systemd/kiwix.service`            |
| mbtileserver  | 8081 | `systemd/mbtileserver.service`     |

Data lives under `/data` (`/data/zim`, `/data/maps`, `/data/downloads`, `/data/packages`).
The app itself is installed at `/home/pi/cyberdeck` as a uv-managed venv.

Optional extras:

- **WiFi access point** — `scripts/setup-wifi.sh` (creates a `uap0` virtual AP, see [WIFI.md](WIFI.md))
- **Chromium kiosk** — `scripts/setup-chromium.sh` (skip on a headless Pi)
- **Power tuning** — `scripts/setup-power.sh` (CPU governor + SSD APM)

## Prerequisites

- Raspberry Pi 4 or 5, arm64 (the install pulls the `linux_arm64` mbtileserver binary)
- Raspberry Pi OS Bookworm or newer, 64-bit
- A user named `pi` (the systemd units run as `pi` and expect the repo at `/home/pi/cyberdeck`).
  If you use a different user, edit the `User=`, `Group=`, and `WorkingDirectory=` lines in
  the three unit files before installing.
- Internet access on the Pi during install (one-time, to fetch apt packages, uv, and the
  mbtileserver binary). After install the device is offline-only.

## Packaging

There's no build artifact — the app installs from source with `uv pip install -e .`.
Pick whichever distribution method fits how the Pi will reach the code:

### Option A: git clone on the Pi (simplest, needs internet)

```bash
ssh pi@<pi>
git clone <repo-url> ~/cyberdeck
cd ~/cyberdeck
```

### Option B: tarball over SSH (works without git on the Pi)

From your dev machine:

```bash
git archive --format=tar.gz --prefix=cyberdeck/ HEAD -o cyberdeck.tar.gz
scp cyberdeck.tar.gz pi@<pi>:~
ssh pi@<pi> 'tar xzf ~/cyberdeck.tar.gz && rm ~/cyberdeck.tar.gz'
```

Using `git archive` (not `tar`) guarantees a clean tree — no `.venv`, no untracked
junk, no local data files. The `--prefix` puts everything under `cyberdeck/` so it
extracts to `/home/pi/cyberdeck`.

### Option C: USB stick (fully air-gapped Pi)

Copy the tarball from Option B to a USB stick, plug it into the Pi, and extract.
You'll still need internet *once* to run `install.sh` (apt + uv + mbtileserver
download). If even that's not available, pre-stage those dependencies — out of
scope here.

## Install

From the repo on the Pi:

```bash
cd ~/cyberdeck
./scripts/install.sh
```

This is idempotent — re-running is safe. It will:

1. Install apt packages (`kiwix-tools`, `chromium-browser`, `python3.14`, etc.)
2. Download the mbtileserver arm64 binary to `/usr/local/bin/`
3. Install `uv` if missing
4. Create the venv and install the app (`uv pip install -e .`)
5. Create `/data/{zim,maps,downloads,packages}` owned by `pi:pi`
6. Seed `registry.json` and an empty `library.xml` if absent
7. Install the three systemd units, enable, and start them

When it finishes, the UI is reachable on `http://<pi>:8000`.

### Headless WiFi AP (recommended for a headless Pi)

The install script does **not** configure WiFi — run separately:

```bash
sudo ./scripts/setup-wifi.sh
```

The AP SSID defaults to the Pi's hostname and the password to the same string.
Override the password with `WIFI_PASSWORD=...`. Connect a phone/laptop to the AP,
then visit `http://<pi-hostname>.local:8000` or `http://10.42.0.1:8000`.

See [WIFI.md](WIFI.md) for the underlying configuration.

### Kiosk mode (skip if headless)

```bash
./scripts/setup-chromium.sh   # run as the pi user, not root
sudo reboot
```

### Power tuning (optional)

```bash
sudo ./scripts/setup-power.sh
```

## Verify

```bash
systemctl status cyberdeck kiwix mbtileserver
curl -s http://localhost:8000/ -o /dev/null -w '%{http_code}\n'   # expect 200
curl -s http://localhost:8080/ -o /dev/null -w '%{http_code}\n'   # kiwix
curl -s http://localhost:8081/services -o /dev/null -w '%{http_code}\n'   # mbtileserver
```

Tail logs if anything is unhappy:

```bash
journalctl -u cyberdeck -f
```

## Updates

```bash
ssh pi@<pi>
cd ~/cyberdeck
git pull                       # or re-extract a fresh tarball
uv pip install -e .            # pick up new dependencies
sudo systemctl restart cyberdeck
```

Only restart `kiwix` or `mbtileserver` if their unit files changed (rare —
their config is in `/data`, not in the repo). If the unit files themselves
changed, re-run `./scripts/install.sh` to reinstall them.

## Uninstall

```bash
sudo systemctl disable --now cyberdeck kiwix mbtileserver
sudo rm /etc/systemd/system/{cyberdeck,kiwix,mbtileserver}.service
sudo systemctl daemon-reload
rm -rf ~/cyberdeck
# Leave /data alone unless you really want to wipe downloaded content.
```

If you ran `setup-wifi.sh`, also:

```bash
sudo systemctl disable --now uap0
sudo rm /etc/systemd/system/uap0.service
sudo nmcli connection delete "$(hostname)"
```
