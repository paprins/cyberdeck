# Cyberdeck Design Spec
**Date:** 2026-04-20  
**Status:** Draft — awaiting implementation plan

---

## 1. Overview

A portable offline knowledge terminal built on Raspberry Pi 5 (4GB RAM). Primary use case: emergency / SHTF (Shit Hits The Fan) preparedness — providing reliable access to critical knowledge (medical, maps, survival, food) when the internet is unavailable. Secondary use case: day-to-day reference for the owner and family.

**Core principles:**
- Clarity under stress — hierarchy must be instantly readable under duress
- Tool, not toy — earns trust through precision and restraint
- Touch-first, never tiny — minimum large touch targets for all primary actions
- Power awareness — every design and implementation decision considers battery life
- Family-legible — non-technical household members navigate confidently without instruction

---

## 2. Hardware

| Component | Spec |
|-----------|------|
| SBC | Raspberry Pi 5, 4GB RAM |
| Display | Raspberry Pi Display 2, 1280×720, capacitive touch |
| Storage | 1TB SSD (NVMe via HAT) |
| Input | Touchscreen (primary) + optional keyboard |
| Power | Battery pack (capacity 3x3500 mAh); solar expansion planned |
| OS | Raspberry Pi OS Lite 64-bit (headless base) |

**Future hardware expansions (design must not block these):**
- GPS module
- LoRa radio module
- SDR / ham radio
- Solar charge controller integration
- WiFi hotspot (requires USB WiFi dongle alongside built-in adapter)

---

## 3. System Architecture

**Approach: FastAPI portal + Kiwix-serve sidecar**

Three processes managed by systemd, all started on boot:

```
┌─────────────────────────────────────────────┐
│  Chromium (--start-fullscreen)               │
│  localhost:8000                              │
└────────────────┬────────────────────────────┘
                 │ HTTP
┌────────────────▼────────────────────────────┐
│  FastAPI Portal App          port 8000       │
│  • Home portal (bento UI)                   │
│  • Unified search aggregator                │
│  • Package / update manager                 │
│  • Reverse proxy → Kiwix + tile server      │
│  • Power management endpoints               │
│  • Subprocess lifecycle (start/stop/reload) │
└──────────┬──────────────────┬───────────────┘
           │                  │
┌──────────▼──────┐  ┌────────▼────────────┐
│  Kiwix-serve    │  │  mbtileserver       │
│  port 8080      │  │  port 8081          │
│  ZIM files      │  │  .mbtiles files     │
│  (Wikipedia,    │  │  (OpenStreetMap     │
│   medical,      │  │   regional/world)   │
│   survival…)    │  └─────────────────────┘
└─────────────────┘
           │
┌──────────▼──────────────────────────────────┐
│  1TB SSD                                    │
│  /data/zim/         ZIM content packs       │
│  /data/maps/        .mbtiles map files      │
│  /data/downloads/   partial + staged files  │
│  /data/packages/    registry.json           │
└─────────────────────────────────────────────┘
```

### 3.1 Process management

All three services run as independent systemd units and restart on reboot. FastAPI does not spawn them as subprocesses — systemd owns their lifecycle. After a package install, FastAPI signals Kiwix-serve to reload its ZIM library via its HTTP management API (or SIGHUP); mbtileserver detects new `.mbtiles` files on its own at startup.

### 3.2 Kiosk display

Chromium launches on boot with:
```
chromium-browser --start-fullscreen --app=http://localhost:8000
  --disable-gpu-compositing --disable-smooth-scrolling
  --noerrdialogs --disable-infobars
```

`--start-fullscreen` (not `--kiosk`) is deliberate: it provides a full-screen experience while allowing the address bar (Ctrl+L / F6) and new tabs (Ctrl+T). This enables the Internet tile to open live web access for trusted family users. `--kiosk` would lock the device to a single URL with no escape, which is appropriate for public kiosks but too restrictive here.

---

## 4. User Interface

### 4.1 Design language

| Token | Value |
|-------|-------|
| Background | `oklch(12% 0.008 110)` — dark olive-black |
| Tile surface | `oklch(19% 0.012 110)` |
| Center tile | `oklch(22% 0.016 110)` — elevated |
| Border radius | 20px |
| Grid gap | 10px |
| Display font | B612 (Airbus avionics — optimized for critical readability) |
| Body font | Atkinson Hyperlegible (maximum legibility under stress) |
| Theme | Dark — low-light emergency use, battery conservation |

**Accent colors per module category:**

| Module | Color |
|--------|-------|
| Medical | `oklch(66% 0.15 28)` — warm amber-red |
| Maps | `oklch(60% 0.12 148)` — earth green |
| Survival | `oklch(66% 0.13 52)` — burnt orange |
| Food & Plants | `oklch(62% 0.11 128)` — olive green |
| Encyclopedia | `oklch(64% 0.10 238)` — steel blue |
| Packages | `oklch(56% 0.07 200)` — cool teal |
| Internet | `oklch(68% 0.13 258)` — electric blue |

### 4.2 Home portal — dynamic bento layout

The home portal is a CSS Grid bento box that **reflows dynamically based on the number of active modules**. The layout is not static.

**Layout rules:**
1. There is always a **dominant center card** (2×2 large tile) — occupied by the highest-priority active module. Priority order: Maps → Medical → first active module alphabetically. If no modules are active, the center shows the empty CTA.
2. The center card is always visually elevated (larger icon, larger type, slightly brighter tile surface)
3. Remaining active module tiles fill surrounding slots using the vocabulary: **square** (1×1), **wide** (2×1 or 3×1), **portrait** (1×2)
4. System tiles (Packages, Internet) are always anchored as a bottom strip
5. Internet tile is only shown when network connectivity is detected
6. The grid always forms a **perfect rectangle** — no orphaned cells, no gaps

**Layout presets by module count:**

| Active modules | Grid | Center position | Layout |
|----------------|------|-----------------|--------|
| 0 | 4×2 | — (empty CTA) | Full-width empty state + system strip |
| 1 | 3×3 | cols 2-3, rows 1-2 | Module as center; Medical/system around it |
| 2 | 3×3 | cols 2-3, rows 1-2 | 1 portrait left + center 2×2 + system strip |
| 3–4 | 4×3 | cols 2-3, rows 1-2 | Modules fill top + sides + center 2×2 + system strip |
| 5 | 4×4 | cols 2-3, rows 2-3 | Wide top + portrait sides + center 2×2 + system strip |
| 6+ | 4×5 or scroll | cols 2-3, rows 2-3 | Additional rows above/below center |

**Tile size assignment algorithm (5-module example):**
```
grid-template-areas:
  "medical  medical  survival  food"
  "encyclo  center   center    food"
  "encyclo  center   center    inet"
  "pkg      pkg      pkg       inet";
```
Medical → wide (2×1), Survival → square (1×1), Food → portrait (1×2),
Encyclopedia → portrait (1×2), Maps (center) → large (2×2),
Packages → wide (3×1), Internet → portrait (1×2, spans system rows).

### 4.3 Global search bar

Persistent search bar below the top chrome, always visible. Searches across all active knowledge bases simultaneously. Keyboard shortcut: Ctrl+K. On the RPi Display 2, tapping the bar invokes the on-screen keyboard (configured system-wide via squeekboard or matchbox-keyboard).

### 4.4 Internet tile

Visible only when network is detected (FastAPI pings a local DNS or checks interface state). Clicking navigates Chromium to a blank page where the address bar becomes accessible. A pulsing green dot indicates live connectivity.

### 4.5 Top chrome

Fixed header strip showing:
- Wordmark: `⬡ CYBERDECK`
- Active module count
- WiFi status (connected / offline)
- Battery percentage + visual battery bar

---

## 5. Knowledge Base System

### 5.1 Content formats

| Format | Used for | Tool |
|--------|----------|------|
| ZIM | Wikipedia subset, medical, survival, food | Kiwix-serve |
| MBTiles | OpenStreetMap vector/raster tiles | mbtileserver |

### 5.2 Curated ZIM packs (initial set)

| Pack ID | Content | Approx. size |
|---------|---------|--------------|
| `wikipedia-curated` | Wikipedia for Schools or custom subset | ~3GB |
| `medical-wikimed` | WikiMed Medical Encyclopedia | ~0.8GB |
| `survival-wikihow` | WikiHow survival/how-to subset | ~1GB |
| `food-plants` | Wild edibles, nutrition, food preservation | ~0.5GB |
| `maps-world` | OpenStreetMap world MBTiles (low zoom) | ~10–80GB |
| `maps-regional` | OpenStreetMap regional (high zoom) | varies |

All ZIM packs are sourced from the [Kiwix library](https://library.kiwix.org/) or custom-packaged. Map tiles are sourced from OpenMapTiles or similar.

---

## 6. Package & Update System

### 6.1 registry.json

Single source of truth for configuration and module state. Lives at `/data/packages/registry.json`.

```json
{
  "update_server": "https://updates.example.com/cyberdeck/manifest.json",
  "modules": []
}
```

After first update check, `modules` is populated from the remote manifest:

```json
{
  "update_server": "https://updates.example.com/cyberdeck/manifest.json",
  "modules": [
    {
      "id": "wikipedia-curated",
      "display_name": "Wikipedia (Curated)",
      "category": "encyclopedia",
      "description": "...",
      "latest_version": "2024-11",
      "size_gb": 3.1,
      "checksum": "sha256:abc123...",
      "installed_version": null,
      "installed_checksum": null,
      "active": false
    }
  ]
}
```

`active: true` means the module tile appears in the home portal bento grid.

### 6.2 Update flow

1. **Check for updates** — FastAPI fetches the remote manifest from `update_server`, merges new/updated entries into `modules`, sets `installed_version: null` for new packs. No internet required to browse already-fetched module list.
2. **Select modules** — user opens Packages tile, sees available modules as bento cards (same design language), selects which to download and activate.
3. **Download** — HTTP request with `Range` header for resumable downloads. Partial file stored as `<id>.zim.partial` in `/data/downloads/`. Progress reported via a FastAPI SSE endpoint to the UI.
4. **Verify** — on completion, SHA256 of downloaded file checked against `checksum` in registry.
5. **Install** — file moved to `/data/zim/` or `/data/maps/`, `installed_version` + `installed_checksum` updated in registry. `active` remains `false` until the user explicitly activates the module.
6. **Activate** — user toggles `active: true` in the Package manager UI. FastAPI updates registry, signals Kiwix-serve to reload, pushes an SSE event to the portal; bento grid reflows to include the new tile.
7. **Deactivate** — user can toggle `active: false` to hide a module tile without deleting its content.

### 6.3 Package manager UI

The Packages tile opens a full-screen view using the same bento grid design language. Each available module is presented as a bento card showing: name, category, size, version, install status, and a download/update button. Layout adapts to number of available modules using the same dynamic bento algorithm.

---

## 7. Power Management

| Mechanism | Implementation |
|-----------|----------------|
| CPU governor | `conservative` via `cpufrequtils` — clocks down on idle |
| Display backlight | FastAPI `/system/brightness` writes to `/sys/class/backlight/*/brightness`; JS idle timer auto-dims after 2 minutes |
| Chromium GPU | `--disable-gpu-compositing --disable-smooth-scrolling` reduce VideoCore load |
| SSD APM | `hdparm -B 128` — moderate power saving without aggressive spin-down wear |
| No animations | UI uses no CSS transitions that would sustain GPU compositing |
| Service priority | All three services run with `nice 10` to yield CPU to foreground interaction |

---

## 8. Storage Layout

```
/data/
  zim/                 # Active ZIM content packs
  maps/                # Active .mbtiles map files
  downloads/           # In-progress and staged downloads
    <id>.zim.partial   # Resumable download state
  packages/
    registry.json      # Module registry + update server config

Approximate allocation (1TB SSD):
  OS + application     ~10 GB
  Initial content      ~10 GB
  Maps (regional)      ~50–200 GB
  Maps (world)         ~80 GB
  Downloads staging    ~100 GB
  Reserved / headroom  ~600 GB
```

---

## 9. Future Expansion Hooks

The architecture is designed so these additions require no changes to the core portal or package system:

| Expansion | Integration point |
|-----------|-------------------|
| **GPS** | New FastAPI endpoint `/system/gps` serves NMEA data; Maps tile gains a "current location" feature |
| **LoRa** | New FastAPI service bridges LoRa UART to a WebSocket; new Portal tile `LoRa Comms` |
| **SDR / Radio** | New FastAPI service wraps rtl_fm or similar; new Portal tile `Radio` |
| **Solar** | Battery status in chrome reads from solar controller via I²C/serial |
| **WiFi Hotspot** | USB WiFi dongle; hostapd + dnsmasq config; family devices connect and access portal via LAN |

Each expansion follows the same pattern: a systemd service + FastAPI endpoint + a new module tile in the bento grid.

---

## 10. Not In Scope (v1)

- WiFi hotspot (designed for, not built in v1)
- GPS integration
- LoRa / Radio
- Multi-user accounts or access control
- Custom ZIM pack creation tooling
- Mobile app companion
