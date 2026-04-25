# Power Management — Design Spec

**Goal:** Implement the remaining software piece of spec §7 — a brightness control API and an idle-based auto-dim in the browser. All other §7 items (CPU governor, SSD APM, Chromium GPU flags, service priority) are already implemented in `scripts/setup-power.sh`, `scripts/setup-chromium.sh`, and `systemd/cyberdeck.service`.

---

## Scope

| Item | Status |
|------|--------|
| CPU governor (`conservative`) | Done — `scripts/setup-power.sh` |
| SSD APM (`hdparm -B 128`) | Done — `scripts/setup-power.sh` |
| Chromium GPU flags | Done — `scripts/setup-chromium.sh` |
| Service priority (`Nice=10`) | Done — `systemd/cyberdeck.service` |
| No CSS animations | Done — design convention |
| **Brightness API** | **This spec** |
| **JS idle auto-dim** | **This spec** |
| Manual brightness UI | Deferred — will be added when sidebar is redesigned |

---

## Architecture

### `app/services/system.py` — two new functions

**`read_brightness() -> int | None`**

Globs `/sys/class/backlight/*/brightness` and the sibling `max_brightness` file. Returns a 0–100 integer (rounded). Returns `None` if no backlight device exists — this is the expected result on dev machines and must not raise.

**`write_brightness(pct: int) -> None`**

Reads `max_brightness` for the same device, scales `pct` (clamped 0–100) to the raw integer range, and writes it to `brightness`. No-op if no backlight device exists. Errors writing to the sysfs file are logged and swallowed — a brightness failure must not crash the app.

Both functions target the first device found under `/sys/class/backlight/`. On the Pi this is typically `rpi_backlight`.

---

### `app/routers/system.py` — two new routes

**`GET /api/system/brightness`**

Returns `{"brightness_pct": 80}`. `brightness_pct` is `int | None` — `null` when no backlight device is present.

**`POST /api/system/brightness`**

Request body: `{"level": 50}` — an integer 0–100.
Response: 204 No Content.
Validation: FastAPI/Pydantic rejects out-of-range values with 422.

---

### `app/templates/base.html` — idle timer

Added to the existing Alpine.js `x-data` on `<body>`:

```
lastActivity: Date.now(),
dimmed: false,
restorePct: null,
```

On `x-init`:
1. Fetch `GET /api/system/brightness` and store result as `restorePct`.
2. Start a `setInterval` every 30 seconds that checks `Date.now() - lastActivity > 120_000`. If idle and not already dimmed: POST `{"level": 10}`, set `dimmed = true`.

Activity listeners on `window` for `mousemove`, `keydown`, `click`, `touchstart`:
- Always update `lastActivity = Date.now()`.
- If `dimmed`: POST `{"level": restorePct ?? 100}`, set `dimmed = false`.

`restorePct` is captured once at page load. If `GET /api/system/brightness` returns `null` (no backlight device), the idle timer still runs but the POST calls are effectively no-ops on the server.

---

## Error handling

| Scenario | Behaviour |
|----------|-----------|
| No backlight device (dev machine) | `read_brightness` returns `null`; `write_brightness` is no-op |
| sysfs write permission denied | Logged, swallowed — app continues |
| `GET /api/system/brightness` fails in JS | `restorePct` stays `null`; restore POSTs `{"level": 100}` |
| `POST /api/system/brightness` fails in JS | Silently ignored — UI state may drift; corrected on next page load |

---

## Testing

### `tests/test_system.py` — new tests appended

**Service layer** — uses `tmp_path` to create fake sysfs files:
- `test_read_brightness_returns_scaled_pct` — write `brightness=128`, `max_brightness=255`, mock glob to point at `tmp_path`, assert returns `50`.
- `test_read_brightness_returns_none_when_no_device` — no files in `tmp_path`, assert returns `None`.
- `test_write_brightness_scales_and_writes` — write `max_brightness=255`, call `write_brightness(50, ...)`, assert `brightness` file contains `127` (or `128`).
- `test_write_brightness_noop_when_no_device` — no files, call must not raise.

**Router layer** — monkeypatches service functions:
- `test_get_brightness_returns_pct` — mock `read_brightness` → `80`, GET returns `{"brightness_pct": 80}`.
- `test_get_brightness_returns_null_when_none` — mock returns `None`, GET returns `{"brightness_pct": null}`.
- `test_post_brightness_returns_204` — POST `{"level": 50}`, assert 204, assert `write_brightness` called with `50`.
- `test_post_brightness_rejects_out_of_range` — POST `{"level": 150}`, assert 422.

---

## File map

| File | Action |
|------|--------|
| `app/services/system.py` | Add `read_brightness`, `write_brightness` |
| `app/routers/system.py` | Add `GET /api/system/brightness`, `POST /api/system/brightness` |
| `app/templates/base.html` | Add idle timer to Alpine.js `x-data` |
| `tests/test_system.py` | Append new service + router tests |

---

## Self-review

**Placeholder scan:** No TBDs or incomplete sections.

**Internal consistency:**
- `restorePct ?? 100` in JS handles the `null` case from no-backlight devices — restore will POST 100 rather than crash.
- `write_brightness` clamps input before scaling — consistent with the 422 on the router (belt-and-suspenders).
- Fake sysfs pattern in tests mirrors how `read_brightness` service function globs the real path — no mocking needed, just `tmp_path` files.

**Scope check:** Two service functions, two routes, one JS change. Fits a single plan.

**Ambiguity check:**
- "First device found" — alphabetical glob order. On Pi there is only one. Acceptable.
- Dim level is fixed at 10% (not configurable). Explicit choice.
- `setInterval` at 30s granularity means dim triggers 2:00–2:30 after last activity. Acceptable.
