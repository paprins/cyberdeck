# Portal UI Design Spec — Plan 2

**Date:** 2026-04-21
**Status:** Approved — ready for implementation plan
**Depends on:** Plan 1 (Foundation)

---

## 1. Overview

Plan 2 builds the home portal: the screen Chromium shows on boot. It renders the dynamic bento grid of active content modules, the top chrome (system status), and a search bar. No module interactivity is wired in Plan 2 — tiles are visual-only; linking to Kiwix/maps is Plan 3.

---

## 2. Tech Stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Templates | Jinja2 via FastAPI | Server-side render; `Jinja2Templates` from `fastapi.templating` |
| CSS | TailwindCSS standalone CLI | Compiled to `app/static/css/app.css`; committed to repo — RPi never runs Tailwind |
| JS | Alpine.js (vendored) | Pinned version at `app/static/js/alpine.min.js`; no CDN calls |
| Fonts | Self-hosted woff2 | B612 + Atkinson Hyperlegible in `app/static/fonts/` |

Tailwind's `animation` and `transitionProperty` core plugins are **disabled** — no GPU-sustaining CSS transitions per the power-awareness principle.

---

## 3. File Structure

New additions to the project:

```
app/
  routers/
    __init__.py
    home.py          # GET / → renders home portal
    system.py        # GET /api/system → battery, wifi, updates
  templates/
    base.html        # HTML shell: Tailwind, Alpine.js, top chrome
    home.html        # Bento grid + search bar (extends base.html)
    macros/
      tile.html      # Jinja2 macro: renders one module tile
  static/
    css/
      app.css        # Tailwind compiled output (committed)
    js/
      alpine.min.js  # Vendored Alpine.js
    fonts/
      B612-Regular.woff2
      B612-Bold.woff2
      AtkinsonHyperlegible-Regular.woff2
      AtkinsonHyperlegible-Bold.woff2
  services/
    bento.py         # Pure function: active modules → grid-area assignments
tailwind.config.js
tests/
  test_bento.py
  test_home.py
  test_system.py
```

`app/main.py` gains two additions: mount `app/static` as `/static` and include the two new routers. Existing `/health` and `/api/status` are untouched.

---

## 4. Design System

### 4.1 Color tokens

```js
// tailwind.config.js — theme.extend
colors: {
  bg:       'oklch(9%  0.005 90)',   // page background
  surface:  'oklch(15% 0.007 90)',   // tile surface
  elevated: 'oklch(20% 0.010 90)',   // center tile (Maps)
  border:   'oklch(30% 0.008 90)',   // tile borders

  amber: {
    DEFAULT: 'oklch(80% 0.15 75)',   // wordmark, primary chrome
    mid:     'oklch(68% 0.10 75)',   // battery shell, secondary chrome
    ghost:   'oklch(35% 0.06 75)',   // chrome bottom border
  },

  text: {
    hi:  'oklch(92% 0.006 90)',      // tile names, chrome values
    mid: 'oklch(66% 0.006 90)',      // tile subtitles
    lo:  'oklch(48% 0.005 90)',      // chrome labels, search placeholder
  },

  tile: {
    medical:      'oklch(68% 0.25 25)',   // hot red — blood, urgency
    maps:         'oklch(72% 0.22 145)',  // phosphor green — radar, terrain
    survival:     'oklch(76% 0.18 58)',   // amber-orange — fire
    food:         'oklch(74% 0.19 118)',  // acid green — growth
    encyclopedia: 'oklch(70% 0.18 232)', // cobalt blue — data
    packages:     'oklch(65% 0.14 195)', // teal — system
    internet:     'oklch(72% 0.20 260)', // electric blue — signal
  },
},
```

### 4.2 Typography

```js
fontFamily: {
  display: ['B612', 'monospace'],
  body:    ['Atkinson Hyperlegible', 'sans-serif'],
},
```

- **B612** — tile names, wordmark, all UI labels (avionics-grade legibility)
- **Atkinson Hyperlegible** — tile subtitles, longer descriptive text

### 4.3 Spacing & shape

```js
borderRadius: { tile: '16px' },
```

Background: dot-grid texture via `radial-gradient` (static CSS, no animation) — `oklch(19% 0.006 90)` 1px dots on 28px grid. Circuit-board reference.

---

## 5. Bento Layout Algorithm

`app/services/bento.py` — pure function, no I/O.

```python
@dataclass
class TileLayout:
    module: Module
    grid_area: str   # CSS grid-area name
    size: str        # "large" | "wide" | "portrait" | "square"

@dataclass
class BentoLayout:
    tiles: list[TileLayout]         # content module tiles
    system_tiles: list[TileLayout]  # packages + internet
    grid_template_areas: str        # CSS grid-template-areas string
    columns: int
    rows: int
    empty: bool                     # True when no active modules
```

`compute_layout(modules: list[Module], wifi_connected: bool) -> BentoLayout`:

1. **Priority-sort** active modules: Maps first → Medical → rest alphabetically
2. **Select preset** by active module count (0 / 1 / 2 / 3–4 / 5 / 6+) — hard-coded `grid-template-areas` string constants
3. **Assign slots** — center module gets the 2×2 `"center"` area; remaining fill named slots in priority order
4. **System strip** — Packages tile always present; Internet tile only when `wifi_connected=True`

Layout presets (from design spec §4.2):

| Active modules | Grid | Center |
|----------------|------|--------|
| 0 | 4×2 | — empty CTA |
| 1 | 3×3 | cols 2–3, rows 1–2 |
| 2 | 3×3 | cols 2–3, rows 1–2 |
| 3–4 | 4×3 | cols 2–3, rows 1–2 |
| 5 | 4×4 | cols 2–3, rows 2–3 |
| 6+ | 4×5 | cols 2–3, rows 2–3 |

---

## 6. Component Breakdown

### `base.html`
HTML shell. Loads Tailwind CSS, Alpine.js, self-hosted fonts. Renders top chrome. Defines Alpine.js `x-data` on `<body>`:

```js
{
  battery_pct: null,
  battery_charging: false,
  wifi_connected: false,
  updates_available: 0,
  uptime_s: null
}
```

Polls `GET /api/system` every 10 seconds via `fetch()` to refresh chrome indicators. Defines `Ctrl+K` keydown handler that focuses the search input.

### `home.html`
Extends `base.html`. Receives `layout: BentoLayout` from the router. Renders CSS Grid with `grid-template-areas` from `layout.grid_template_areas`. Iterates `layout.tiles` and `layout.system_tiles` via the `tile` macro. Renders search bar below the chrome.

### `macros/tile.html`
Jinja2 macro `render_tile(tile: TileLayout)`. Renders a single tile as a centered vertical stack:

```
[ icon  ]    — 30px emoji/SVG; 52px for center tile
[ TITLE ]    — bold uppercase, category accent color; 18px / 30px center
[ subtitle ] — 12px text-mid; 14px center
```

Top 3px accent bar using `::before` pseudo-element in category color. Non-interactive in Plan 2 — rendered as `<div>`, no `<a>` tag.

### Top chrome (inside `base.html`)

```
⬡ CYBERDECK          MODULES  5 active [2]   NET ● connected   BAT ▓▓▓▓░ 78%
```

- **Wordmark**: B612 bold, amber, 16px, letter-spacing 0.18em
- **Modules**: label (text-lo) + value (text-hi bold) + update badge (amber-orange pill, hidden when 0)
- **Net**: label + colored dot (maps-green when connected) + value
- **Bat**: label + battery bar graphic + percentage value
- All values update live via Alpine.js polling

### Search bar

Full-width below chrome. Styled input, always visible. Displays `⌕ Search knowledge bases… [Ctrl+K]`. `Ctrl+K` focuses it via Alpine.js. Non-functional in Plan 2 — no backend wired yet (Plan 3).

---

## 7. New API Routes

### `GET /`
Reads registry via `load_registry(settings)`, reads wifi state via the same system-reading function used by `/api/system` (no HTTP self-call), calls `compute_layout(active_modules, wifi_connected)`, renders `home.html` with `layout` context. Returns `text/html`.

### `GET /api/system`
Returns live system state. Alpine.js polls every 10s.

```json
{
  "battery_pct": 78,
  "battery_charging": false,
  "wifi_connected": true,
  "updates_available": 2,
  "uptime_s": 43200
}
```

**Data sources (RPi):**
- `battery_pct` / `battery_charging` — `/sys/class/power_supply/*/capacity` and `status`
- `wifi_connected` — checks network interface state
- `updates_available` — `len([m for m in registry.modules if m.has_update])`
- `uptime_s` — `/proc/uptime`

**Dev fallback (non-RPi):** all values return `null` / `false` / `0` gracefully — no crash.

---

## 8. Testing

### `test_bento.py` — pure unit tests
- Layout preset for each module count bucket (0, 1, 2, 3, 4, 5, 6)
- Center tile is always highest-priority module (Maps > Medical > alphabetical)
- Internet tile absent when `wifi_connected=False`
- Packages system tile always present
- Empty layout (`empty=True`) when no active modules

### `test_home.py` — HTTP via `AsyncClient` + `tmp_settings`
- `GET /` returns 200 `text/html`
- Active module names appear in response body
- Empty state rendered when registry has no active modules

### `test_system.py` — HTTP via `AsyncClient`
- `GET /api/system` returns 200 with correct JSON shape
- All keys present: `battery_pct`, `battery_charging`, `wifi_connected`, `updates_available`, `uptime_s`
- Values are `int | bool | None` (dev-mode fallback works off-RPi)

---

## 9. Out of Scope for Plan 2

- Module tile interactivity (linking to Kiwix/mbtileserver) — Plan 3
- Search functionality (backend search aggregation) — Plan 3
- Empty state CTA actions — Plan 3
- Package manager UI — Plan 4
