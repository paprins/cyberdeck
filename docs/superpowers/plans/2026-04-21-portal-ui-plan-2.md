# Portal UI — Plan 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the home portal screen — dynamic bento grid of active modules, system status chrome, and search bar — served by FastAPI via Jinja2 templates with TailwindCSS and Alpine.js.

**Architecture:** Approach A — server-side bento layout algorithm in Python produces `grid-template-areas` strings consumed by Jinja2 templates; Alpine.js handles only live chrome polling (battery/wifi/updates every 10s) and Ctrl+K search focus. Tailwind compiled once at dev time and committed; RPi never runs Tailwind or Node.

**Tech Stack:** Python 3.14, FastAPI 0.115+, Jinja2 (via `python-multipart` + `jinja2`), TailwindCSS standalone via `pytailwindcss`, Alpine.js 3.x (vendored), B612 + Atkinson Hyperlegible (self-hosted woff2)

---

## File map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Modify | Add `jinja2`, `python-multipart`; dev: `pytailwindcss` |
| `app/main.py` | Modify | Mount `/static`, include `home` + `system` routers |
| `app/routers/__init__.py` | Create | Empty package marker |
| `app/routers/home.py` | Create | `GET /` — render home portal |
| `app/routers/system.py` | Create | `GET /api/system` — live system status |
| `app/services/bento.py` | Create | Pure layout algorithm: modules → grid areas |
| `app/services/system.py` | Create | Read battery/wifi/uptime from `/sys`/`/proc` |
| `app/templates/base.html` | Create | HTML shell: fonts, Tailwind, Alpine.js, top chrome |
| `app/templates/home.html` | Create | Bento grid + search bar (extends base) |
| `app/templates/macros/tile.html` | Create | Jinja2 macro: renders one tile |
| `app/static/css/input.css` | Create | Tailwind input (base + components + utilities) |
| `app/static/css/app.css` | Create | Compiled Tailwind output (committed) |
| `app/static/js/alpine.min.js` | Create | Vendored Alpine.js 3.14.1 |
| `app/static/fonts/*.woff2` | Create | B612 Regular/Bold, Atkinson Hyperlegible Regular/Bold |
| `tailwind.config.js` | Create | Design token extensions |
| `tests/test_bento.py` | Create | Unit tests for bento layout algorithm |
| `tests/test_system.py` | Create | HTTP tests for `/api/system` |
| `tests/test_home.py` | Create | HTTP tests for `GET /` |

---

## Task 1: Project setup — deps, dirs, assets

**Files:**
- Modify: `pyproject.toml`
- Create: `app/routers/__init__.py`
- Create: `app/static/css/input.css`
- Create: `tailwind.config.js`
- Create: `app/static/js/alpine.min.js` (download)
- Create: `app/static/fonts/*.woff2` (download)

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

```toml
[project]
name = "cyberdeck"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "httpx>=0.27",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "pytailwindcss>=0.3.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["app"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Install updated deps**

```bash
uv sync --extra dev
```

Expected: resolves without error, `jinja2` and `pytailwindcss` appear in `.venv`.

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p app/routers app/templates/macros app/static/css app/static/js app/static/fonts
touch app/routers/__init__.py
```

- [ ] **Step 4: Download Alpine.js (vendored)**

```bash
curl -sL "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js" \
  -o app/static/js/alpine.min.js
```

Expected: `app/static/js/alpine.min.js` exists and is ~44KB.

- [ ] **Step 5: Download fonts via Google Fonts API**

```bash
python3 << 'EOF'
import urllib.request, re
from pathlib import Path

Path("app/static/fonts").mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

def dl_family(api_name: str, dest_names: list[str]):
    url = f"https://fonts.googleapis.com/css2?family={api_name}:wght@400;700&display=swap"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    css = urllib.request.urlopen(req).read().decode()
    urls = re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", css)
    for woff2_url, dest in zip(urls, dest_names):
        print(f"  {dest}")
        urllib.request.urlretrieve(woff2_url, f"app/static/fonts/{dest}")

print("Downloading B612...")
dl_family("B612", ["B612-Regular.woff2", "B612-Bold.woff2"])
print("Downloading Atkinson Hyperlegible...")
dl_family("Atkinson+Hyperlegible", [
    "AtkinsonHyperlegible-Regular.woff2",
    "AtkinsonHyperlegible-Bold.woff2",
])
print("Done.")
EOF
```

Expected: four `.woff2` files in `app/static/fonts/`, each 20–80KB.

- [ ] **Step 6: Create Tailwind input CSS**

Create `app/static/css/input.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  @font-face {
    font-family: 'B612';
    src: url('/static/fonts/B612-Regular.woff2') format('woff2');
    font-weight: 400;
    font-style: normal;
  }
  @font-face {
    font-family: 'B612';
    src: url('/static/fonts/B612-Bold.woff2') format('woff2');
    font-weight: 700;
    font-style: normal;
  }
  @font-face {
    font-family: 'Atkinson Hyperlegible';
    src: url('/static/fonts/AtkinsonHyperlegible-Regular.woff2') format('woff2');
    font-weight: 400;
    font-style: normal;
  }
  @font-face {
    font-family: 'Atkinson Hyperlegible';
    src: url('/static/fonts/AtkinsonHyperlegible-Bold.woff2') format('woff2');
    font-weight: 700;
    font-style: normal;
  }
}
```

- [ ] **Step 7: Create `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/templates/**/*.html"],
  corePlugins: {
    animation: false,
    transitionProperty: false,
    transitionDuration: false,
    transitionTimingFunction: false,
    transitionDelay: false,
  },
  theme: {
    extend: {
      colors: {
        bg:       'oklch(9% 0.005 90)',
        surface:  'oklch(15% 0.007 90)',
        elevated: 'oklch(20% 0.010 90)',
        border:   'oklch(30% 0.008 90)',
        amber: {
          DEFAULT: 'oklch(80% 0.15 75)',
          mid:     'oklch(68% 0.10 75)',
          ghost:   'oklch(35% 0.06 75)',
        },
        text: {
          hi:  'oklch(92% 0.006 90)',
          mid: 'oklch(66% 0.006 90)',
          lo:  'oklch(48% 0.005 90)',
        },
        tile: {
          medical:      'oklch(68% 0.25 25)',
          maps:         'oklch(72% 0.22 145)',
          survival:     'oklch(76% 0.18 58)',
          food:         'oklch(74% 0.19 118)',
          encyclopedia: 'oklch(70% 0.18 232)',
          packages:     'oklch(65% 0.14 195)',
          internet:     'oklch(72% 0.20 260)',
        },
      },
      fontFamily: {
        display: ['B612', 'monospace'],
        body:    ['Atkinson Hyperlegible', 'sans-serif'],
      },
      borderRadius: {
        tile: '16px',
      },
    },
  },
}
```

- [ ] **Step 8: Compile Tailwind (initial — templates don't exist yet so output is minimal)**

```bash
uv run tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

Expected: `app/static/css/app.css` created. Will be recompiled in Task 4 once templates exist.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock app/routers/__init__.py \
        app/static/ tailwind.config.js
git commit -m "chore: add frontend deps, static assets, Tailwind config"
```

---

## Task 2: Bento layout service

**Files:**
- Create: `app/services/bento.py`
- Create: `tests/test_bento.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bento.py`:

```python
from __future__ import annotations
import pytest
from app.models.registry import Module
from app.services.bento import compute_layout, BentoLayout, TileLayout


def _mod(id: str, category: str, active: bool = True) -> Module:
    return Module(
        id=id,
        display_name=id.replace("-", " ").title(),
        category=category,
        description=f"{id} description",
        latest_version="2024-01",
        size_gb=1.0,
        checksum="sha256:abc",
        active=active,
    )


# ── empty state ──────────────────────────────────────────────────────────────

def test_empty_layout_when_no_active_modules():
    layout = compute_layout([], wifi_connected=False)
    assert layout.empty is True
    assert layout.tiles == []


def test_empty_layout_packages_tile_always_present():
    layout = compute_layout([], wifi_connected=False)
    assert any(t.grid_area == "pkg" for t in layout.system_tiles)


def test_empty_layout_no_internet_tile_when_no_wifi():
    layout = compute_layout([], wifi_connected=False)
    assert not any(t.grid_area == "inet" for t in layout.system_tiles)


def test_empty_layout_internet_tile_when_wifi():
    layout = compute_layout([], wifi_connected=True)
    assert any(t.grid_area == "inet" for t in layout.system_tiles)


# ── center tile priority ──────────────────────────────────────────────────────

def test_maps_module_gets_center():
    modules = [_mod("maps-world", "maps"), _mod("medical-wikimed", "medical")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.category == "maps"


def test_medical_gets_center_when_no_maps():
    modules = [_mod("medical-wikimed", "medical"), _mod("survival-wikihow", "survival")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.category == "medical"


def test_first_alphabetically_gets_center_when_no_maps_or_medical():
    modules = [_mod("survival-wikihow", "survival"), _mod("food-plants", "food")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.id == "food-plants"


# ── center tile size ──────────────────────────────────────────────────────────

def test_center_tile_has_size_center():
    modules = [_mod("maps-world", "maps")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.size == "center"


# ── layout presets ────────────────────────────────────────────────────────────

def test_one_module_grid_is_3x3():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert layout.columns == 3
    assert layout.rows == 3


def test_two_modules_grid_is_3x3():
    modules = [_mod("maps-world", "maps"), _mod("medical-wikimed", "medical")]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 3
    assert layout.rows == 3


def test_three_modules_grid_is_4x3():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 3


def test_four_modules_grid_is_4x3():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
        _mod("food-plants", "food"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 3


def test_five_modules_grid_is_4x4():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
        _mod("food-plants", "food"),
        _mod("wikipedia-curated", "encyclopedia"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 4


def test_six_plus_modules_grid_is_4x5():
    modules = [_mod(f"mod-{i}", "encyclopedia") for i in range(6)]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 5


# ── grid_template_areas format ────────────────────────────────────────────────

def test_grid_template_areas_contains_center():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert "center" in layout.grid_template_areas


def test_grid_template_areas_contains_pkg():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert "pkg" in layout.grid_template_areas


def test_grid_template_areas_is_quoted_rows():
    """Each row must be a quoted string, rows separated by newlines."""
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    rows = layout.grid_template_areas.strip().splitlines()
    assert len(rows) == layout.rows
    for row in rows:
        assert row.strip().startswith("'") and row.strip().endswith("'")
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_bento.py -v
```

Expected: `ImportError: cannot import name 'compute_layout' from 'app.services.bento'`

- [ ] **Step 3: Implement `app/services/bento.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from app.models.registry import Module

_PRIORITY: dict[str, int] = {"maps": 0, "medical": 1}


def _sort_key(m: Module) -> tuple[int, str]:
    return (_PRIORITY.get(m.category, 99), m.id)


@dataclass
class TileLayout:
    module: Module
    grid_area: str
    size: str  # "center" | "regular"


@dataclass
class BentoLayout:
    tiles: list[TileLayout]
    system_tiles: list[TileLayout]
    grid_template_areas: str
    columns: int
    rows: int
    empty: bool


# Each preset: (areas_no_wifi, areas_wifi, slot_names, columns, rows)
# areas: one quoted string per row, separated by "\n"
# slot_names: grid-area names for non-center content modules, in fill order
_PRESETS: dict[int, tuple[str, str, list[str], int, int]] = {
    0: (
        "'empty empty empty empty'\n'pkg   pkg   pkg   pkg  '",
        "'empty empty empty inet '\n'pkg   pkg   pkg   inet '",
        [], 4, 2,
    ),
    1: (
        "'.    center center'\n'.    center center'\n'pkg  pkg    pkg  '",
        "'.    center center'\n'.    center center'\n'pkg  pkg    inet '",
        [], 3, 3,
    ),
    2: (
        "'slot1 center center'\n'slot1 center center'\n'pkg   pkg    pkg  '",
        "'slot1 center center'\n'slot1 center center'\n'pkg   pkg    inet '",
        ["slot1"], 3, 3,
    ),
    3: (
        "'slot1 center center slot2'\n'slot3 center center slot2'\n'pkg   pkg    pkg    pkg  '",
        "'slot1 center center slot2'\n'slot3 center center slot2'\n'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3"], 4, 3,
    ),
    4: (
        "'slot1 center center slot2'\n'slot3 center center slot4'\n'pkg   pkg    pkg    pkg  '",
        "'slot1 center center slot2'\n'slot3 center center slot4'\n'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3", "slot4"], 4, 3,
    ),
    5: (
        "'slot1 slot1  slot2  slot3'\n'slot4 center center slot3'\n'slot4 center center slot5'\n'pkg   pkg    pkg    slot5'",
        "'slot1 slot1  slot2  slot3'\n'slot4 center center slot3'\n'slot4 center center inet '\n'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3", "slot4", "slot5"], 4, 4,
    ),
}
# 6+ uses same shape as 5 but with an extra row of slots above
_PRESET_6PLUS: tuple[str, str, list[str], int, int] = (
    "'slot6 slot6  slot7  slot8'\n'slot1 slot1  slot2  slot3'\n'slot4 center center slot3'\n'slot4 center center slot5'\n'pkg   pkg    pkg    slot5'",
    "'slot6 slot6  slot7  slot8'\n'slot1 slot1  slot2  slot3'\n'slot4 center center slot3'\n'slot4 center center inet '\n'pkg   pkg    pkg    inet '",
    ["slot1", "slot2", "slot3", "slot4", "slot5", "slot6", "slot7", "slot8"], 4, 5,
)

_PACKAGES_MODULE = Module(
    id="_packages",
    display_name="Packages",
    category="packages",
    description="Manage content modules",
    latest_version="",
    size_gb=0,
    checksum="",
)
_INTERNET_MODULE = Module(
    id="_internet",
    display_name="Internet",
    category="internet",
    description="Live web access",
    latest_version="",
    size_gb=0,
    checksum="",
)


def compute_layout(modules: list[Module], wifi_connected: bool) -> BentoLayout:
    active = sorted(modules, key=_sort_key)
    n = len(active)

    if n >= 6:
        areas_no_wifi, areas_wifi, slot_names, columns, rows = _PRESET_6PLUS
    else:
        areas_no_wifi, areas_wifi, slot_names, columns, rows = _PRESETS[n]

    areas = areas_wifi if wifi_connected else areas_no_wifi

    # Assign content tiles
    tiles: list[TileLayout] = []
    if active:
        tiles.append(TileLayout(module=active[0], grid_area="center", size="center"))
        for module, slot in zip(active[1:], slot_names):
            tiles.append(TileLayout(module=module, grid_area=slot, size="regular"))

    # System tiles
    system_tiles = [TileLayout(module=_PACKAGES_MODULE, grid_area="pkg", size="regular")]
    if wifi_connected:
        system_tiles.append(TileLayout(module=_INTERNET_MODULE, grid_area="inet", size="regular"))

    return BentoLayout(
        tiles=tiles,
        system_tiles=system_tiles,
        grid_template_areas=areas,
        columns=columns,
        rows=rows,
        empty=len(active) == 0,
    )
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/test_bento.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/bento.py tests/test_bento.py
git commit -m "feat: add bento layout service with preset grid algorithm"
```

---

## Task 3: System status service and endpoint

**Files:**
- Create: `app/services/system.py`
- Create: `app/routers/system.py`
- Create: `tests/test_system.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_system.py`:

```python
from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_system_endpoint_returns_200(client):
    r = await client.get("/api/system")
    assert r.status_code == 200


async def test_system_endpoint_returns_all_keys(client):
    r = await client.get("/api/system")
    data = r.json()
    assert "battery_pct" in data
    assert "battery_charging" in data
    assert "wifi_connected" in data
    assert "updates_available" in data
    assert "uptime_s" in data


async def test_system_battery_pct_is_int_or_none(client):
    r = await client.get("/api/system")
    val = r.json()["battery_pct"]
    assert val is None or isinstance(val, int)


async def test_system_battery_charging_is_bool(client):
    r = await client.get("/api/system")
    assert isinstance(r.json()["battery_charging"], bool)


async def test_system_wifi_connected_is_bool(client):
    r = await client.get("/api/system")
    assert isinstance(r.json()["wifi_connected"], bool)


async def test_system_updates_available_is_int(client):
    r = await client.get("/api/system")
    assert isinstance(r.json()["updates_available"], int)


async def test_system_updates_available_counts_modules_with_updates(client, tmp_settings):
    from app.services.registry import save_registry
    from app.models.registry import Registry, Module
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OSM", latest_version="2024-02", size_gb=10,
                checksum="sha256:new",
                installed_version="2024-01", installed_checksum="sha256:old",
                active=True,
            ),
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01", size_gb=0.8,
                checksum="sha256:abc",
                installed_version="2024-01", installed_checksum="sha256:abc",
                active=True,
            ),
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/api/system")
    assert r.json()["updates_available"] == 1


async def test_system_uptime_is_int_or_none(client):
    r = await client.get("/api/system")
    val = r.json()["uptime_s"]
    assert val is None or isinstance(val, int)
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_system.py -v
```

Expected: `404` responses — `/api/system` does not exist yet.

- [ ] **Step 3: Implement `app/services/system.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from app.config import Settings
from app.services.registry import load_registry


@dataclass
class SystemStatus:
    battery_pct: int | None
    battery_charging: bool
    wifi_connected: bool
    updates_available: int
    uptime_s: int | None


def read_system_status(settings: Settings) -> SystemStatus:
    return SystemStatus(
        battery_pct=_battery_pct(),
        battery_charging=_battery_charging(),
        wifi_connected=_wifi_connected(),
        updates_available=_updates_available(settings),
        uptime_s=_uptime_s(),
    )


def _battery_pct() -> int | None:
    for path in Path("/sys/class/power_supply").glob("*/capacity"):
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            pass
    return None


def _battery_charging() -> bool:
    for path in Path("/sys/class/power_supply").glob("*/status"):
        try:
            return path.read_text().strip().lower() == "charging"
        except OSError:
            pass
    return False


def _wifi_connected() -> bool:
    try:
        content = Path("/proc/net/wireless").read_text()
        data_lines = [l for l in content.splitlines()[2:] if l.strip()]
        return len(data_lines) > 0
    except OSError:
        return False


def _updates_available(settings: Settings) -> int:
    try:
        registry = load_registry(settings)
        return len([m for m in registry.modules if m.has_update])
    except Exception:
        return 0


def _uptime_s() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None
```

- [ ] **Step 4: Implement `app/routers/system.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/system")
async def system_status(request: Request):
    from app.services.system import read_system_status
    status = read_system_status(request.app.state.settings)
    return {
        "battery_pct": status.battery_pct,
        "battery_charging": status.battery_charging,
        "wifi_connected": status.wifi_connected,
        "updates_available": status.updates_available,
        "uptime_s": status.uptime_s,
    }
```

- [ ] **Step 5: Wire router and settings into `app/main.py`**

Replace `app/main.py` entirely:

```python
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.config import Settings
from app.services.registry import load_registry

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for d in (cfg.zim_dir, cfg.maps_dir, cfg.downloads_dir, cfg.registry_path.parent):
            d.mkdir(parents=True, exist_ok=True)
        app.state.settings = cfg
        app.state.template_dir = _TEMPLATE_DIR
        yield

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    from app.routers import system as system_router
    app.include_router(system_router.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/status")
    async def status():
        registry = load_registry(cfg)
        active = [m for m in registry.modules if m.active]
        return {
            "active_modules": len(active),
            "total_modules": len(registry.modules),
            "data_dirs": {
                "zim": str(cfg.zim_dir),
                "maps": str(cfg.maps_dir),
                "downloads": str(cfg.downloads_dir),
            },
        }

    @app.exception_handler(404)
    async def not_found(request, exc):
        return JSONResponse({"error": "not found"}, status_code=404)

    return app


app = create_app()
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
uv run pytest tests/test_system.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 7: Run full suite to check no regressions**

```bash
uv run pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add app/services/system.py app/routers/system.py app/main.py \
        tests/test_system.py
git commit -m "feat: add system status service and /api/system endpoint"
```

---

## Task 4: Templates

**Files:**
- Create: `app/templates/macros/tile.html`
- Create: `app/templates/base.html`
- Create: `app/templates/home.html`

No tests in this task — templates are tested end-to-end in Task 5. Recompile Tailwind after writing all three files so the CSS includes all utility classes.

- [ ] **Step 1: Create `app/templates/macros/tile.html`**

```html
{% macro render_tile(tile, is_center=False) %}
{%- set ICONS = {
  'medical':      '🏥',
  'maps':         '🗺️',
  'survival':     '🪓',
  'food':         '🌿',
  'encyclopedia': '📖',
  'packages':     '📦',
  'internet':     '🌐',
} -%}
{%- set ACCENT_BG = {
  'medical':      'bg-tile-medical',
  'maps':         'bg-tile-maps',
  'survival':     'bg-tile-survival',
  'food':         'bg-tile-food',
  'encyclopedia': 'bg-tile-encyclopedia',
  'packages':     'bg-tile-packages',
  'internet':     'bg-tile-internet',
} -%}
{%- set ACCENT_TEXT = {
  'medical':      'text-tile-medical',
  'maps':         'text-tile-maps',
  'survival':     'text-tile-survival',
  'food':         'text-tile-food',
  'encyclopedia': 'text-tile-encyclopedia',
  'packages':     'text-tile-packages',
  'internet':     'text-tile-internet',
} -%}
{%- set bg = 'bg-elevated' if is_center else 'bg-surface' -%}
{%- set icon_size = 'text-[52px]' if is_center else 'text-[30px]' -%}
{%- set name_size = 'text-[30px]' if is_center else 'text-[18px]' -%}
{%- set sub_size  = 'text-[14px]' if is_center else 'text-[12px]' -%}
{%- set cat = tile.module.category -%}
<div
  class="{{ bg }} rounded-tile border border-border flex flex-col items-center justify-center text-center gap-[6px] relative overflow-hidden p-4"
  style="grid-area: {{ tile.grid_area }}"
>
  <div class="absolute top-0 left-0 right-0 h-[3px] rounded-t-tile {{ ACCENT_BG.get(cat, 'bg-text-lo') }}"></div>
  <div class="{{ icon_size }} leading-none">{{ ICONS.get(cat, '▪') }}</div>
  <div class="font-display font-bold uppercase tracking-[0.05em] {{ name_size }} leading-tight {{ ACCENT_TEXT.get(cat, 'text-text-hi') }}">
    {{ tile.module.display_name }}
  </div>
  <div class="font-body {{ sub_size }} text-text-mid leading-snug max-w-[90%]">
    {{ tile.module.description }}
  </div>
</div>
{% endmacro %}
```

- [ ] **Step 2: Create `app/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=1280, initial-scale=1">
  <title>Cyberdeck</title>
  <link rel="stylesheet" href="/static/css/app.css">
  <script defer src="/static/js/alpine.min.js"></script>
</head>
<body
  class="bg-bg text-text-hi font-display h-full overflow-hidden flex flex-col"
  style="background-image: radial-gradient(circle, oklch(19% 0.006 90) 1px, transparent 1px); background-size: 28px 28px;"
  x-data="{
    battery_pct: {{ battery_pct | tojson }},
    battery_charging: {{ battery_charging | tojson }},
    wifi_connected: {{ wifi_connected | tojson }},
    updates_available: {{ updates_available | tojson }},
    uptime_s: {{ uptime_s | tojson }},
    async poll() {
      try {
        const r = await fetch('/api/system');
        const d = await r.json();
        this.battery_pct = d.battery_pct;
        this.battery_charging = d.battery_charging;
        this.wifi_connected = d.wifi_connected;
        this.updates_available = d.updates_available;
        this.uptime_s = d.uptime_s;
      } catch(e) {}
    }
  }"
  x-init="setInterval(() => poll(), 10000)"
  @keydown.ctrl.k.window.prevent="document.getElementById('search').focus()"
>
  <!-- Top chrome -->
  <header class="flex items-center justify-between px-5 h-[50px] flex-shrink-0"
          style="background: oklch(11% 0.005 90); border-bottom: 1px solid oklch(35% 0.06 75);">
    <span class="font-display font-bold text-[16px] tracking-[0.18em] text-amber">⬡ CYBERDECK</span>
    <div class="flex items-center gap-7">

      <!-- Modules count + update badge -->
      <div class="flex items-center gap-[7px]">
        <span class="text-[11px] tracking-[0.12em] uppercase text-text-lo">Modules</span>
        <span class="font-bold text-[13px] text-text-hi">{{ active_count }} active</span>
        <span
          x-show="updates_available > 0"
          x-text="updates_available"
          class="inline-flex items-center justify-center min-w-[20px] h-5 px-[5px] rounded-[10px] bg-tile-survival text-[11px] font-bold leading-none"
          style="color: oklch(10% 0.005 90);"
        >{{ updates_available }}</span>
      </div>

      <!-- WiFi status -->
      <div class="flex items-center gap-[7px]">
        <span class="text-[11px] tracking-[0.12em] uppercase text-text-lo">Net</span>
        <span class="w-2 h-2 rounded-full"
              :class="wifi_connected ? 'bg-tile-maps' : 'bg-text-lo'"></span>
        <span class="font-bold text-[13px] text-text-hi"
              x-text="wifi_connected ? 'connected' : 'offline'">{{ 'connected' if wifi_connected else 'offline' }}</span>
      </div>

      <!-- Battery -->
      <div class="flex items-center gap-[7px]">
        <span class="text-[11px] tracking-[0.12em] uppercase text-text-lo">Bat</span>
        <span class="font-bold text-[13px] text-text-hi"
              x-text="battery_pct !== null ? battery_pct + '%' : '—'">{{ (battery_pct ~ '%') if battery_pct is not none else '—' }}</span>
      </div>

    </div>
  </header>

  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: Create `app/templates/home.html`**

```html
{% extends "base.html" %}
{% from "macros/tile.html" import render_tile %}

{% block content %}
<!-- Search bar -->
<div class="px-[10px] pt-2 flex-shrink-0">
  <div class="flex items-center gap-[10px] bg-surface border border-border rounded-lg px-4 py-[10px]">
    <span class="text-text-lo text-[14px]">⌕</span>
    <input
      id="search"
      type="text"
      placeholder="Search knowledge bases…"
      class="flex-1 bg-transparent font-display text-[14px] text-text-lo placeholder-text-lo outline-none tracking-[0.02em]"
      disabled
    >
    <span class="text-[11px] text-text-lo tracking-[0.08em] bg-[oklch(22%_0.006_90)] border border-border px-2 py-[2px] rounded">Ctrl+K</span>
  </div>
</div>

<!-- Bento grid -->
<div class="flex-1 p-[10px] min-h-0">
  {% if layout.empty %}
  <div class="w-full h-full flex items-center justify-center">
    <div class="text-center">
      <div class="text-[48px] mb-4">📦</div>
      <div class="font-display font-bold text-[22px] uppercase tracking-[0.05em] text-text-mid mb-2">No modules active</div>
      <div class="font-body text-[14px] text-text-lo">Open Packages to install content</div>
    </div>
  </div>
  {% else %}
  <div
    class="grid w-full h-full gap-[10px]"
    style="
      grid-template-areas: {{ layout.grid_template_areas }};
      grid-template-columns: repeat({{ layout.columns }}, 1fr);
      grid-template-rows: repeat({{ layout.rows }}, 1fr);
    "
  >
    {% for tile in layout.tiles %}
      {{ render_tile(tile, is_center=(tile.grid_area == 'center')) }}
    {% endfor %}
    {% for tile in layout.system_tiles %}
      {{ render_tile(tile, is_center=False) }}
    {% endfor %}
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Recompile Tailwind now that templates exist**

```bash
uv run tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

Expected: `app/static/css/app.css` is larger now (contains all utility classes used in templates).

- [ ] **Step 5: Commit**

```bash
git add app/templates/ app/static/css/app.css
git commit -m "feat: add Jinja2 templates — base, home, tile macro"
```

---

## Task 5: Home portal route

**Files:**
- Create: `app/routers/home.py`
- Create: `tests/test_home.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_home.py`:

```python
from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_home_returns_200(client):
    r = await client.get("/")
    assert r.status_code == 200


async def test_home_returns_html(client):
    r = await client.get("/")
    assert "text/html" in r.headers["content-type"]


async def test_home_renders_wordmark(client):
    r = await client.get("/")
    assert "CYBERDECK" in r.text


async def test_home_shows_active_module_name(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OpenStreetMap offline", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Maps" in r.text


async def test_home_shows_empty_state_when_no_active_modules(client):
    r = await client.get("/")
    assert "No modules active" in r.text


async def test_home_packages_tile_always_rendered(client):
    r = await client.get("/")
    assert "Packages" in r.text


async def test_home_active_count_in_chrome(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OSM", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            ),
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:def", active=True,
            ),
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "2 active" in r.text
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_home.py -v
```

Expected: `404` — `GET /` not yet defined.

- [ ] **Step 3: Implement `app/routers/home.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.bento import compute_layout
from app.services.registry import load_registry
from app.services.system import read_system_status

router = APIRouter()


def _get_templates(request: Request) -> Jinja2Templates:
    return Jinja2Templates(directory=request.app.state.template_dir)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    cfg = request.app.state.settings
    registry = load_registry(cfg)
    status = read_system_status(cfg)

    active_modules = [m for m in registry.modules if m.active]
    layout = compute_layout(active_modules, wifi_connected=status.wifi_connected)

    templates = _get_templates(request)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "layout": layout,
            "active_count": len(active_modules),
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
        },
    )
```

- [ ] **Step 4: Include home router in `app/main.py`**

Add after the system router include (one line change):

```python
    from app.routers import system as system_router
    app.include_router(system_router.router)

    from app.routers import home as home_router   # ← add this
    app.include_router(home_router.router)         # ← add this
```

The full updated `create_app` function in `app/main.py`:

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for d in (cfg.zim_dir, cfg.maps_dir, cfg.downloads_dir, cfg.registry_path.parent):
            d.mkdir(parents=True, exist_ok=True)
        app.state.settings = cfg
        app.state.template_dir = _TEMPLATE_DIR
        yield

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    from app.routers import system as system_router
    app.include_router(system_router.router)

    from app.routers import home as home_router
    app.include_router(home_router.router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/status")
    async def status():
        registry = load_registry(cfg)
        active = [m for m in registry.modules if m.active]
        return {
            "active_modules": len(active),
            "total_modules": len(registry.modules),
            "data_dirs": {
                "zim": str(cfg.zim_dir),
                "maps": str(cfg.maps_dir),
                "downloads": str(cfg.downloads_dir),
            },
        }

    @app.exception_handler(404)
    async def not_found(request, exc):
        return JSONResponse({"error": "not found"}, status_code=404)

    return app
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
uv run pytest tests/test_home.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass (26 from Plan 1 + new tests from Plan 2).

- [ ] **Step 7: Commit**

```bash
git add app/routers/home.py app/main.py tests/test_home.py
git commit -m "feat: add home portal route — bento grid server-side render"
```

---

## Task 6: Smoke test and final Tailwind compile

**Files:**
- Modify: `app/static/css/app.css` (recompile)

- [ ] **Step 1: Run full test suite one final time**

```bash
uv run pytest -v
```

Expected: all tests pass with no warnings.

- [ ] **Step 2: Start dev server and verify in browser**

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` in a browser. Verify:
- Dark background with dot-grid visible
- `⬡ CYBERDECK` in amber in the chrome
- `0 active` module count (empty registry)
- "No modules active" empty state with Packages tile
- Search bar renders with `Ctrl+K` label
- Ctrl+K focuses the search input

- [ ] **Step 3: Seed a test module and reload**

In a second terminal:

```bash
python3 - << 'EOF'
import json
from pathlib import Path

reg = {
  "update_server": "https://updates.example.com/cyberdeck/manifest.json",
  "modules": [
    {
      "id": "maps-world", "display_name": "Maps", "category": "maps",
      "description": "OpenStreetMap — fully offline",
      "latest_version": "2024-01", "size_gb": 10.0, "checksum": "sha256:abc",
      "installed_version": None, "installed_checksum": None, "active": True
    },
    {
      "id": "medical-wikimed", "display_name": "Medical", "category": "medical",
      "description": "WikiMed offline encyclopedia",
      "latest_version": "2024-01", "size_gb": 0.8, "checksum": "sha256:def",
      "installed_version": None, "installed_checksum": None, "active": True
    }
  ]
}
Path("/data/packages/registry.json").write_text(json.dumps(reg, indent=2))
print("Seeded.")
EOF
```

Reload `http://localhost:8000`. Verify:
- Bento grid renders with Maps as the dominant center tile (phosphor green accent)
- Medical tile renders with red accent
- Chrome shows `2 active`
- Packages system tile visible in bottom strip

- [ ] **Step 4: Final Tailwind recompile with all templates**

```bash
uv run tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

- [ ] **Step 5: Commit**

```bash
git add app/static/css/app.css
git commit -m "chore: recompile Tailwind with full template class set"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §2 Tech stack: Jinja2, Tailwind, Alpine.js, fonts | Task 1 |
| §3 File structure | Tasks 1–5 |
| §4 Design system: color tokens, typography, dot-grid | Tasks 1, 4 |
| §5 Bento layout algorithm | Task 2 |
| §6 Components: base, home, tile macro | Task 4 |
| §6 Top chrome: wordmark, modules, wifi, battery, update badge | Task 4 |
| §6 Search bar: Ctrl+K, non-functional | Task 4 |
| §7 `GET /` home portal route | Task 5 |
| §7 `GET /api/system` | Task 3 |
| §8 test_bento.py | Task 2 |
| §8 test_system.py | Task 3 |
| §8 test_home.py | Task 5 |

**No placeholders found.**

**Type consistency:**
- `TileLayout.module: Module` — defined Task 2, used in Task 4 tile macro ✓
- `BentoLayout.grid_template_areas: str` — defined Task 2, used in Task 4 home.html ✓
- `BentoLayout.tiles` / `system_tiles` — defined Task 2, iterated in Task 4 home.html ✓
- `SystemStatus` fields — defined Task 3, consumed in Task 5 home router ✓
- `request.app.state.settings` — set in lifespan Task 3, read in Tasks 3 & 5 ✓
- `request.app.state.template_dir` — set in lifespan Task 3, read in Task 5 ✓
