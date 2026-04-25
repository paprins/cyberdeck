# Power Management — Plan 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a brightness control API (`GET`/`POST /api/system/brightness`) and a JS idle auto-dim (2 min → 10%, restore on activity) to the existing system service, router, and base template.

**Architecture:** Two new functions in `app/services/system.py` read/write `/sys/class/backlight/*/brightness` with an injectable root for testability. Two new routes in `app/routers/system.py` expose them. The idle timer lives in `base.html`'s Alpine.js `x-data` — fetching the restore level on page load, dimming after 120 s of inactivity, restoring on any window event. No-op on dev machines (no backlight device).

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, Alpine.js, Jinja2

---

## File map

| File | Action | Purpose |
|------|--------|---------|
| `app/services/system.py` | Modify | Add `read_brightness`, `write_brightness` |
| `app/routers/system.py` | Modify | Add `GET /api/system/brightness`, `POST /api/system/brightness` |
| `app/templates/base.html` | Modify | Add idle timer to Alpine.js `x-data` / `x-init` |
| `tests/test_system.py` | Modify | Append service + router brightness tests |

---

## Task 1: Brightness service functions

Adds `read_brightness` and `write_brightness` to `app/services/system.py`. Both accept an injectable `_root` parameter (default `/sys/class/backlight`) so tests can point at `tmp_path` without any mocking.

**Files:**
- Modify: `app/services/system.py`
- Modify: `tests/test_system.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_system.py`:

```python
import app.services.system as sys_svc


# ── read_brightness ───────────────────────────────────────────────────────────

def test_read_brightness_returns_scaled_pct(tmp_path):
    dev = tmp_path / "rpi_backlight"
    dev.mkdir()
    (dev / "brightness").write_text("128")
    (dev / "max_brightness").write_text("255")
    assert sys_svc.read_brightness(_root=tmp_path) == 50


def test_read_brightness_full_on(tmp_path):
    dev = tmp_path / "rpi_backlight"
    dev.mkdir()
    (dev / "brightness").write_text("255")
    (dev / "max_brightness").write_text("255")
    assert sys_svc.read_brightness(_root=tmp_path) == 100


def test_read_brightness_returns_none_when_no_device(tmp_path):
    assert sys_svc.read_brightness(_root=tmp_path) is None


# ── write_brightness ──────────────────────────────────────────────────────────

def test_write_brightness_scales_and_writes(tmp_path):
    dev = tmp_path / "rpi_backlight"
    dev.mkdir()
    (dev / "max_brightness").write_text("255")
    (dev / "brightness").write_text("0")
    sys_svc.write_brightness(50, _root=tmp_path)
    assert int((dev / "brightness").read_text()) == 128


def test_write_brightness_clamps_above_100(tmp_path):
    dev = tmp_path / "rpi_backlight"
    dev.mkdir()
    (dev / "max_brightness").write_text("255")
    (dev / "brightness").write_text("0")
    sys_svc.write_brightness(150, _root=tmp_path)
    assert int((dev / "brightness").read_text()) == 255


def test_write_brightness_noop_when_no_device(tmp_path):
    sys_svc.write_brightness(50, _root=tmp_path)  # must not raise
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_system.py -k "brightness" -v
```

Expected: `AttributeError: module 'app.services.system' has no attribute 'read_brightness'`

- [ ] **Step 3: Add functions to `app/services/system.py`**

Append after `_uptime_s`:

```python
_BACKLIGHT_ROOT = Path("/sys/class/backlight")


def read_brightness(_root: Path = _BACKLIGHT_ROOT) -> int | None:
    for brightness_path in _root.glob("*/brightness"):
        try:
            raw = int(brightness_path.read_text().strip())
            max_raw = int((brightness_path.parent / "max_brightness").read_text().strip())
            if max_raw == 0:
                return None
            return min(100, round(raw * 100 / max_raw))
        except (OSError, ValueError):
            pass
    return None


def write_brightness(pct: int, _root: Path = _BACKLIGHT_ROOT) -> None:
    pct = max(0, min(100, pct))
    for max_path in _root.glob("*/max_brightness"):
        try:
            max_raw = int(max_path.read_text().strip())
            raw = round(pct * max_raw / 100)
            (max_path.parent / "brightness").write_text(str(raw))
            return
        except OSError:
            pass
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_system.py -k "brightness" -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/system.py tests/test_system.py
git commit -m "feat: add read_brightness and write_brightness to system service"
```

---

## Task 2: Brightness API routes

Adds `GET /api/system/brightness` and `POST /api/system/brightness` to `app/routers/system.py`. Uses a Pydantic model for input validation — out-of-range values produce a 422 automatically.

**Files:**
- Modify: `app/routers/system.py`
- Modify: `tests/test_system.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_system.py`:

```python
# ── GET /api/system/brightness ────────────────────────────────────────────────

async def test_get_brightness_returns_pct(client, monkeypatch):
    monkeypatch.setattr(sys_svc, "read_brightness", lambda: 80)
    r = await client.get("/api/system/brightness")
    assert r.status_code == 200
    assert r.json() == {"brightness_pct": 80}


async def test_get_brightness_returns_null_when_no_device(client, monkeypatch):
    monkeypatch.setattr(sys_svc, "read_brightness", lambda: None)
    r = await client.get("/api/system/brightness")
    assert r.status_code == 200
    assert r.json() == {"brightness_pct": None}


# ── POST /api/system/brightness ───────────────────────────────────────────────

async def test_post_brightness_returns_204(client, monkeypatch):
    calls = []
    monkeypatch.setattr(sys_svc, "write_brightness", lambda pct: calls.append(pct))
    r = await client.post("/api/system/brightness", json={"level": 50})
    assert r.status_code == 204
    assert calls == [50]


async def test_post_brightness_rejects_out_of_range(client):
    r = await client.post("/api/system/brightness", json={"level": 150})
    assert r.status_code == 422


async def test_post_brightness_rejects_negative(client):
    r = await client.post("/api/system/brightness", json={"level": -1})
    assert r.status_code == 422
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_system.py -k "get_brightness or post_brightness" -v
```

Expected: `FAILED` — routes don't exist, 404s.

- [ ] **Step 3: Replace `app/routers/system.py`**

```python
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.config import Settings
import app.services.system as sys_svc
from app.services.system import read_system_status


class BrightnessRequest(BaseModel):
    level: int = Field(..., ge=0, le=100)


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/system")
    async def system_status():
        status = read_system_status(cfg)
        return {
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
        }

    @router.get("/api/system/brightness")
    async def get_brightness():
        return {"brightness_pct": sys_svc.read_brightness()}

    @router.post("/api/system/brightness", status_code=204)
    async def set_brightness(body: BrightnessRequest):
        sys_svc.write_brightness(body.level)
        return Response(status_code=204)

    return router
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_system.py -v
```

Expected: all tests pass including the 5 new ones.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/routers/system.py tests/test_system.py
git commit -m "feat: add GET/POST /api/system/brightness endpoints"
```

---

## Task 3: JS idle timer in base.html

Adds idle detection to `base.html`'s Alpine.js component. On page load it fetches the current brightness as the restore level. A 30-second interval fires `_setBrightness(10)` once two minutes of inactivity pass. Any window event restores brightness and resets the timer.

No automated tests — verified manually by running the dev server.

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Replace the `x-data` and `x-init` on `<body>` in `app/templates/base.html`**

Replace:

```html
<body
  class="bg-bg text-text-hi font-display h-full overflow-hidden flex"
  x-data="{
    battery_pct: {{ battery_pct | tojson }},
    wifi_connected: {{ wifi_connected | tojson }},
    async poll() {
      try {
        const r = await fetch('/api/system');
        const d = await r.json();
        this.battery_pct = d.battery_pct;
        this.wifi_connected = d.wifi_connected;
      } catch(e) {}
    }
  }"
  x-init="setInterval(() => poll(), 10000)"
  @keydown.ctrl.k.window.prevent="document.getElementById('search') && document.getElementById('search').focus()"
>
```

With:

```html
<body
  class="bg-bg text-text-hi font-display h-full overflow-hidden flex"
  x-data="{
    battery_pct: {{ battery_pct | tojson }},
    wifi_connected: {{ wifi_connected | tojson }},
    lastActivity: Date.now(),
    dimmed: false,
    restorePct: null,
    async poll() {
      try {
        const r = await fetch('/api/system');
        const d = await r.json();
        this.battery_pct = d.battery_pct;
        this.wifi_connected = d.wifi_connected;
      } catch(e) {}
    },
    async initBrightness() {
      try {
        const r = await fetch('/api/system/brightness');
        const d = await r.json();
        this.restorePct = d.brightness_pct;
      } catch(e) {}
    },
    async _setBrightness(pct) {
      try {
        await fetch('/api/system/brightness', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({level: pct})
        });
      } catch(e) {}
    },
    _onActivity() {
      this.lastActivity = Date.now();
      if (this.dimmed) {
        this.dimmed = false;
        this._setBrightness(this.restorePct ?? 100);
      }
    }
  }"
  x-init="
    initBrightness();
    setInterval(() => poll(), 10000);
    setInterval(() => {
      if (!dimmed && Date.now() - lastActivity > 120000) {
        dimmed = true;
        _setBrightness(10);
      }
    }, 30000);
    ['mousemove', 'keydown', 'click', 'touchstart'].forEach(e =>
      window.addEventListener(e, () => _onActivity(), {passive: true})
    );
  "
  @keydown.ctrl.k.window.prevent="document.getElementById('search') && document.getElementById('search').focus()"
>
```

- [ ] **Step 2: Run the dev server and verify**

```bash
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`. Open browser DevTools → Network tab. Verify:
- On page load, a `GET /api/system/brightness` request fires and returns `{"brightness_pct": null}` (no backlight on dev machine).
- No JS console errors.

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat: add idle auto-dim — 2 min inactivity dims to 10%, restores on activity"
```

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `read_brightness() -> int \| None` | Task 1 |
| `write_brightness(pct: int) -> None` | Task 1 |
| No-op / None when no backlight device | Task 1 |
| `GET /api/system/brightness` | Task 2 |
| `POST /api/system/brightness` body `{"level": N}` | Task 2 |
| 204 on POST | Task 2 |
| 422 on out-of-range level | Task 2 |
| Fetch restore level on page load | Task 3 |
| Dim to 10% after 2 min idle | Task 3 |
| Restore on mousemove / keydown / click / touchstart | Task 3 |
| `restorePct ?? 100` fallback when no device | Task 3 |

**Placeholder scan:** No TBDs or incomplete sections.

**Type consistency:**
- `read_brightness(_root)` defined Task 1, monkeypatched as `lambda: 80` in Task 2 tests — signature compatible ✓
- `write_brightness(pct, _root)` defined Task 1, monkeypatched as `lambda pct: calls.append(pct)` in Task 2 tests — compatible ✓
- `sys_svc.read_brightness` / `sys_svc.write_brightness` imported via module in router — matches monkeypatch target ✓
- `BrightnessRequest.level` validated `ge=0, le=100` — matches 422 tests ✓
- `_setBrightness(10)` and `_setBrightness(this.restorePct ?? 100)` — body `{level: pct}` matches `BrightnessRequest.level` ✓
