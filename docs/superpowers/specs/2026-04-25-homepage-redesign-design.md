# Homepage Redesign — Design Spec
**Date:** 2026-04-25
**Status:** Approved

## Overview

Replace the bento-box homepage with a survivalist/military card grid that is a 100% visual match to `mockup/code.html`, implementing the design system in `mockup/DESIGN.md`.

---

## 1. Assets

### Fonts (self-hosted, offline-first)
Download as `.woff2` to `/app/static/fonts/`:
- **Space Grotesk** — weights 300, 400, 500, 600, 700 (headline + labels)
- **Inter** — weights 400, 500, 600, 700 (body)

### Images
Download 7 category images from mockup URLs to `/app/static/images/categories/`:
- `medical.jpg`
- `food.jpg`
- `energy.jpg`
- `mechanic.jpg`
- `gardening.jpg`
- `shelter.jpg`
- `animal_care.jpg`

### Icon font
Material Symbols Outlined loaded via Google Fonts CDN (graceful degradation on offline).

---

## 2. Color Palette & CSS

Replace all existing CSS tokens in `app/static/css/input.css` with the mockup palette:

| Token | Value |
|---|---|
| surface | #131313 |
| surface-dim | #131313 |
| surface-container-lowest | #0e0e0e |
| surface-container-low | #1b1b1b |
| surface-container | #1f1f1f |
| surface-container-high | #2a2a2a |
| surface-container-highest | #353535 |
| surface-variant | #353535 |
| surface-bright | #393939 |
| background | #131313 |
| primary | #ffb693 |
| primary-container | #ff6b00 |
| on-primary | #561f00 |
| on-primary-container | #572000 |
| on-primary-fixed | #351000 |
| primary-fixed | #ffdbcc |
| primary-fixed-dim | #ffb693 |
| secondary | #d3beeb |
| secondary-container | #524267 |
| on-secondary | #38294d |
| on-secondary-container | #c4b0dd |
| tertiary | #9ccaff |
| tertiary-container | #059eff |
| on-tertiary | #003257 |
| on-tertiary-container | #003357 |
| outline | #a98a7d |
| outline-variant | #5a4136 |
| on-surface | #e2e2e2 |
| on-surface-variant | #e2bfb0 |
| on-background | #e2e2e2 |
| inverse-surface | #e2e2e2 |
| inverse-on-surface | #303030 |
| error | #ffb4ab |
| error-container | #93000a |
| on-error | #690005 |
| on-error-container | #ffdad6 |

Font families:
- `font-headline`: Space Grotesk
- `font-body`: Inter
- `font-label`: Space Grotesk

Border radius: `0px` everywhere (including `lg`, `xl`). `full` stays `9999px`.

Scrollbar: 4px wide, `#0e0e0e` track, `#ff6b00` thumb.

---

## 3. Header (`base.html`)

Full replacement of the current minimal topbar.

**Left side:**
- Orange square (`bg-primary-container`) with `radar` Material Symbol icon
- Title block: `SURVIVAL_DASHBOARD` in Space Grotesk bold, `#ff6b00`, uppercase; subtitle `SECURE_ACCESS // SECTOR_G14` in 8px Space Grotesk, `primary/60` opacity, letter-spaced
- Inline search input: `surface-container-lowest` background, `QUERY_DATABASE...` placeholder, `search` icon

**Right side:**
- Language dropdown: `ENG_US` label, `language` icon, `surface-container-highest` bg
- Icons: `settings`, `battery_charging_full`, `signal_cellular_connected_no_internet_4_bar` (error color for offline)
- `SHUTDOWN` button: red border, `power_settings_new` icon, `error` text color

**Preserved JS (Alpine.js):**
- Battery percentage polling (`/api/system`)
- WiFi status polling
- Auto-dim brightness on 2 min inactivity (`/api/system/brightness`)
- Activity listeners (mousemove, keydown, click, touchstart)
- Ctrl+K search focus

---

## 4. Homepage (`home.html`)

### Structure
```
<main>
  <div class="flex-1 grid grid-cols-4 grid-rows-2 gap-4">
    <!-- 7 module cards + 1 IMPORT_MODULE card -->
  </div>
  <div class="system-log-footer">
    <!-- CORE_PROCESS_LOG strip -->
  </div>
</main>
```

### Module Card
Each active module renders as a card:

```
<a href="{url}">
  <div class="top-half image">
    <img grayscale, brightness-75, hover removes grayscale>
    <badge absolute top-right>  <!-- category-specific -->
  </div>
  <div class="bottom-half info">
    <h4>MODULE_NAME</h4>
    <icon>material symbol</icon>
    <p>description</p>
    <footer>
      <span>{size_gb}_GB</span>
      <span>VIEW →</span>
    </footer>
  </div>
</a>
```

Hover state: `bg-surface-container-high`, `border-b-2 border-primary`, image un-grays.

### IMPORT_MODULE card (always last)
Dashed border, `add_box` icon, `IMPORT_MODULE` label, links to `/packages`.

### System Log Footer
Fixed strip below the grid:
- Header: `CORE_PROCESS_LOG` + `TIME_UTC: HH:MM:SS` (live via Alpine.js)
- 3–4 static log lines showing checksum verification, encryption status, sync pending, voltage warning
- Last line pulses (`animate-pulse`) for the warning

### Category → UI mapping

| Category | Badge text | Badge bg | Icon |
|---|---|---|---|
| medical | CRITICAL | error-container | medication |
| food | RESOURCE | secondary-container | inventory |
| energy | GRID_OFF | tertiary-container | bolt |
| mechanic | — | — | build |
| gardening | — | — | potted_plant |
| shelter | — | — | foundation |
| animal_care | — | — | pets |

---

## 5. Backend (`home.py`)

- Remove `BentoLayout` / `compute_layout` import
- Pass `modules` (flat list of active `Module` objects with `.url` attached) to template
- Keep `battery_pct` and `wifi_connected` context vars
- Delete `app/services/bento.py` (no longer used)

URL logic (unchanged):
- maps → `http://localhost:{mbtiles_port}/`
- packages → `/packages`
- internet → `https://duckduckgo.com`
- all others → `http://localhost:{kiwix_port}/{module.id}/`

---

## 6. Category System

Replace all existing category values with the 7 mockup categories:
- `medical`, `food`, `energy`, `mechanic`, `gardening`, `shelter`, `animal_care`

Update `tile.html` macro (or inline into `home.html`) to use the new category→icon/badge/image mapping.

Old categories (`maps`, `survival`, `encyclopedia`, `internet`, `packages`) are retired. The `packages` and `internet` system entries remain as the IMPORT_MODULE card and (if wifi) a card, but are not styled as category modules.

---

## 7. What Is NOT Changing

- `/packages` route and template
- `/api/search` endpoint and search functionality (search input moves to header)
- `/api/system` and `/api/system/brightness` endpoints
- Alpine.js version and CDN source
- Test suite
- Registry model and registry service
