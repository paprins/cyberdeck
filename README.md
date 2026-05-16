# cyberdeck

An offline-first information portal for a Raspberry Pi 5. Serves a curated set
of content modules (Kiwix ZIM files, OpenStreetMap tiles, etc.) over a local
WiFi access point, plus a touchscreen UI for managing content, connectivity,
and firmware updates.

## Install

On a fresh Raspberry Pi 5 (Debian Trixie / Raspberry Pi OS, arm64), one of:

### One-line install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/paprins/cyberdeck/main/scripts/install.sh | bash -s -- --headless
```

The installer fetches the latest release's tarball + minisign signature from
GitHub, verifies it against the public key at `release.pub` on `main`, then
extracts to `/opt/cyberdeck/v<version>/`. No git clone, no source on disk.

If you've forked the repo, override with `CYBERDECK_REPO=<owner>/cyberdeck`
before `bash`.

### From a clone (for developers)

```bash
git clone https://github.com/paprins/cyberdeck.git ~/cyberdeck
~/cyberdeck/scripts/install.sh --headless           # installs latest release
~/cyberdeck/scripts/install.sh --headless --local   # installs from local source
```

### Modes and flags

```text
scripts/install.sh (--kiosk | --headless) [--version X.Y.Z | --local]
```

| Flag | Meaning |
|---|---|
| `--kiosk` | Install with Chromium for the touchscreen UI. |
| `--headless` | Install server only (no browser). |
| `--version X.Y.Z` | Install a specific tagged release. |
| `--local` | Install from the current local repo source (dev mode; no signature check). |

Without `--version` or `--local`, the installer fetches the **latest GitHub
release**, verifies its minisign signature against the bundled public key
(`release.pub` in the repo), and extracts to `/opt/cyberdeck/v<version>/`.

## What the installer does

- Installs system packages (kiwix-tools, mbtileserver, Python build deps).
- Provisions Python via pyenv at `/opt/pyenv` (system-wide).
- Downloads + verifies the signed release tarball (or syncs from local repo with `--local`).
- Extracts to `/opt/cyberdeck/v<version>/` and builds a venv there.
- Atomically swaps `/opt/cyberdeck/current` to the new version.
- Installs the release public key to `/etc/cyberdeck/release.pub`.
- Installs systemd units (`cyberdeck`, `kiwix`, `mbtileserver`) and starts them.
- Drops a sudoers fragment so the running service can `systemctl restart` itself for upgrades.
- Drops a polkit rule so the service can manage WiFi via NetworkManager.

Persistent state lives under `/data/` (registry, downloaded content, static
assets) and survives upgrades and reinstalls.

## After install

Browse to `http://<pi>:8000` or, on the Pi itself, `http://localhost:8000`.

- **Settings → Packages**: download/activate content modules (ZIM, mbtiles).
- **Settings → System → Firmware**: check for new releases (online via GitHub
  or offline via USB stick containing a `cyberdeck-v*.tar.gz` + `.minisig`),
  install with one click. Health check + automatic rollback on failure.

## Upgrades

After first install, you never need to run `install.sh` again. The settings
page's **Firmware** row handles upgrades through the same signed-tarball
mechanism — over the internet via the GitHub Releases API, or offline via a
USB drive carrying the release files.

## Cutting a release (maintainers)

```bash
# Bump pyproject.toml version, then:
git tag v0.1.2
git push origin v0.1.2
```

The `release` workflow builds an arm64 tarball with bundled wheels, signs it
with minisign (using the `MINISIGN_RELEASE_KEY` repository secret), and
publishes it as a GitHub release. Devices on older versions will see it
within 10 seconds of clicking "CHECK" on the Firmware settings row.

## Development

```bash
uv sync --extra dev
uv run pytest
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000
```

See `AGENTS.md` for project conventions.
