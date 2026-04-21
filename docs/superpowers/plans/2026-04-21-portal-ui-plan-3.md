# Portal UI — Plan 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tiles interactive links to Kiwix/mbtileserver, wire the search bar to a backend aggregation endpoint, and add a working CTA link to the empty state.

**Architecture:** Tile URLs are computed in the home router after `compute_layout()` using `dataclasses.replace`, stored in `TileLayout.url`, and rendered as `<a>` tags in the tile macro. Search is a new `GET /api/search?q=` endpoint backed by `app/services/search.py` which fans out async HTTP requests to Kiwix's suggest API; the frontend sends debounced queries and renders a results dropdown using Alpine.js nested `x-data`. No new dependencies — `httpx` is already in the project.

**Tech Stack:** Python 3.14, FastAPI, httpx (already installed), Jinja2 templates, Alpine.js, TailwindCSS v4 (compiled via `tailwindcss` Homebrew CLI)

---

## File map

| File | Action | Purpose |
|------|--------|---------|
| `app/services/bento.py` | Modify | Add `url: str = ""` field to `TileLayout` |
| `app/routers/home.py` | Modify | Add `_tile_url()`, compute URLs for all tiles after layout |
| `app/templates/macros/tile.html` | Modify | Render `<a>` tag when `tile.url` is set, `<div>` otherwise |
| `app/templates/home.html` | Modify | CTA link + enabled search input + Alpine.js + results dropdown |
| `app/services/search.py` | Create | `kiwix_suggestions()` + `search_modules()` — async Kiwix suggest client |
| `app/routers/search.py` | Create | `GET /api/search?q=<query>` endpoint |
| `app/main.py` | Modify | Include search router |
| `tests/test_search.py` | Create | Unit tests for search service + HTTP tests for endpoint |

---

## Task 1: Tile URLs — make tiles clickable links

**Files:**
- Modify: `app/services/bento.py`
- Modify: `app/routers/home.py`
- Modify: `app/templates/macros/tile.html`
- Modify: `tests/test_home.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_home.py` (append after existing tests):

```python
async def test_maps_tile_has_mbtiles_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OSM", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8081/' in r.text


async def test_medical_tile_has_kiwix_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8080/medical-wikimed/' in r.text


async def test_packages_tile_has_packages_url(client):
    r = await client.get("/")
    assert 'href="/packages"' in r.text
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_home.py::test_maps_tile_has_mbtiles_url tests/test_home.py::test_medical_tile_has_kiwix_url tests/test_home.py::test_packages_tile_has_packages_url -v
```

Expected: `FAILED` — tiles render as `<div>` with no `href`.

- [ ] **Step 3: Add `url` field to `TileLayout` in `app/services/bento.py`**

Change the `TileLayout` dataclass (line 13–16):

```python
@dataclass
class TileLayout:
    module: Module
    grid_area: str
    size: str  # "center" | "regular"
    url: str = ""
```

- [ ] **Step 4: Add URL computation to `app/routers/home.py`**

Replace the full file:

```python
from __future__ import annotations
from dataclasses import replace as dc_replace
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import Settings
from app.models.registry import Module
from app.services.bento import BentoLayout, TileLayout, compute_layout
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _tile_url(module: Module, cfg: Settings) -> str:
    if module.category == "maps":
        return f"http://localhost:{cfg.mbtiles_port}/"
    if module.category == "packages":
        return "/packages"
    if module.category == "internet":
        return "https://duckduckgo.com"
    return f"http://localhost:{cfg.kiwix_port}/{module.id}/"


def _with_urls(layout: BentoLayout, cfg: Settings) -> BentoLayout:
    return dc_replace(
        layout,
        tiles=[dc_replace(t, url=_tile_url(t.module, cfg)) for t in layout.tiles],
        system_tiles=[dc_replace(t, url=_tile_url(t.module, cfg)) for t in layout.system_tiles],
    )


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        active_modules = [m for m in registry.modules if m.active]
        layout = _with_urls(compute_layout(active_modules, wifi_connected=status.wifi_connected), cfg)
        return templates.TemplateResponse(request, "home.html", {
            "layout": layout,
            "active_count": len(active_modules),
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
        })

    return router
```

- [ ] **Step 5: Update `app/templates/macros/tile.html` to render `<a>` when url is set**

Replace the full file:

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
{%- set tag = 'a' if tile.url else 'div' -%}
<{{ tag }}
  {% if tile.url %}href="{{ tile.url }}"{% endif %}
  class="{{ bg }} rounded-tile border border-border flex flex-col items-center justify-center text-center gap-[6px] relative overflow-hidden p-4{% if tile.url %} cursor-pointer hover:bg-border transition-none{% endif %}"
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
</{{ tag }}>
{% endmacro %}
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
uv run pytest tests/test_home.py -v
```

Expected: all 10 tests pass (7 existing + 3 new).

- [ ] **Step 7: Run full suite to check no regressions**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/services/bento.py app/routers/home.py \
        app/templates/macros/tile.html tests/test_home.py
git commit -m "feat: make tiles clickable links to Kiwix and mbtileserver"
```

---

## Task 2: Empty state CTA link

**Files:**
- Modify: `app/templates/home.html`
- Modify: `tests/test_home.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_home.py`:

```python
async def test_empty_state_cta_links_to_packages(client):
    r = await client.get("/")
    assert "No modules active" in r.text
    assert 'href="/packages"' in r.text
```

- [ ] **Step 2: Run — expect failure**

```bash
uv run pytest tests/test_home.py::test_empty_state_cta_links_to_packages -v
```

Expected: `FAILED` — the CTA text has no `href`.

- [ ] **Step 3: Update empty state in `app/templates/home.html`**

Replace the empty-state block only (lines 18–29):

Old:
```html
  {% if layout.empty %}
  <div class="w-full h-full flex items-center justify-center">
    <div class="text-center">
      <div class="text-[48px] mb-4">📦</div>
      <div class="font-display font-bold text-[22px] uppercase tracking-[0.05em] text-text-mid mb-2">No modules active</div>
      <div class="font-body text-[14px] text-text-lo">Open Packages to install content</div>
    </div>
  </div>
```

New:
```html
  {% if layout.empty %}
  <div class="w-full h-full flex items-center justify-center">
    <div class="text-center">
      <div class="text-[48px] mb-4">📦</div>
      <div class="font-display font-bold text-[22px] uppercase tracking-[0.05em] text-text-mid mb-2">No modules active</div>
      <a href="/packages" class="font-body text-[14px] text-tile-packages hover:text-text-hi underline underline-offset-2">Open Packages to install content</a>
    </div>
  </div>
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/test_home.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/templates/home.html tests/test_home.py
git commit -m "feat: link empty state CTA to /packages"
```

---

## Task 3: Search API — Kiwix suggest aggregation

**Files:**
- Create: `app/services/search.py`
- Create: `app/routers/search.py`
- Modify: `app/main.py`
- Create: `tests/test_search.py`

Kiwix exposes a JSON suggest endpoint:
`GET http://localhost:{kiwix_port}/suggest?content={module_id}&term={query}&count=3`
Response: a JSON array of title strings, e.g. `["First Aid", "Wound Care"]`.

The `/api/search` endpoint fans out async requests to Kiwix for each non-map active module and returns aggregated `{title, module, url}` objects. Maps are excluded (no text content). If Kiwix isn't running (dev/test), the `RequestError` is caught and that module contributes no results.

- [ ] **Step 1: Write failing tests**

Create `tests/test_search.py`:

```python
from __future__ import annotations
import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry
from app.services.search import search_modules, kiwix_suggestions


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mod(id: str, category: str, active: bool = True) -> Module:
    return Module(
        id=id, display_name=id.replace("-", " ").title(), category=category,
        description=f"{id} description", latest_version="2024-01",
        size_gb=1.0, checksum="sha256:abc", active=active,
    )


class _MockClient:
    """Minimal stand-in for httpx.AsyncClient — returns preset JSON by URL fragment."""
    def __init__(self, responses: dict[str, list]):
        self._responses = responses  # {url_fragment: [titles]}

    async def get(self, url: str, timeout: float = 2.0):
        for fragment, data in self._responses.items():
            if fragment in url:
                return _MockResponse(data, 200)
        return _MockResponse([], 404)


class _MockResponse:
    def __init__(self, data, status_code: int):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class _ErrorClient:
    async def get(self, url: str, timeout: float = 2.0):
        raise httpx.RequestError("connection refused")


# ── kiwix_suggestions unit tests ─────────────────────────────────────────────

async def test_kiwix_suggestions_returns_titles():
    mod = _mod("medical-wikimed", "medical")
    client = _MockClient({"medical-wikimed": ["First Aid", "Wound Care"]})
    titles = await kiwix_suggestions("first", mod, 8080, client)
    assert titles == ["First Aid", "Wound Care"]


async def test_kiwix_suggestions_returns_empty_on_404():
    mod = _mod("medical-wikimed", "medical")
    client = _MockClient({})  # no match → 404
    titles = await kiwix_suggestions("first", mod, 8080, client)
    assert titles == []


async def test_kiwix_suggestions_returns_empty_on_request_error():
    mod = _mod("medical-wikimed", "medical")
    titles = await kiwix_suggestions("first", mod, 8080, _ErrorClient())
    assert titles == []


# ── search_modules unit tests ─────────────────────────────────────────────────

async def test_search_modules_returns_results():
    modules = [_mod("medical-wikimed", "medical")]
    client = _MockClient({"medical-wikimed": ["First Aid", "Bandaging"]})
    results = await search_modules("first", modules, 8080, client)
    assert len(results) == 2
    assert results[0]["title"] == "First Aid"
    assert results[0]["module"] == "Medical-Wikimed"
    assert "medical-wikimed" in results[0]["url"]


async def test_search_modules_excludes_maps():
    modules = [_mod("maps-world", "maps")]
    results = await search_modules("world", modules, 8080, _MockClient({}))
    assert results == []


async def test_search_modules_excludes_packages():
    modules = [_mod("_packages", "packages")]
    results = await search_modules("pkg", modules, 8080, _MockClient({}))
    assert results == []


async def test_search_modules_excludes_internet():
    modules = [_mod("_internet", "internet")]
    results = await search_modules("web", modules, 8080, _MockClient({}))
    assert results == []


async def test_search_modules_returns_empty_when_no_active():
    results = await search_modules("test", [], 8080, _MockClient({}))
    assert results == []


async def test_search_modules_handles_kiwix_down():
    modules = [_mod("medical-wikimed", "medical")]
    results = await search_modules("first", modules, 8080, _ErrorClient())
    assert results == []


async def test_search_modules_result_url_contains_query():
    modules = [_mod("medical-wikimed", "medical")]
    client = _MockClient({"medical-wikimed": ["First Aid"]})
    results = await search_modules("first", modules, 8080, client)
    assert "first" in results[0]["url"]


async def test_search_modules_aggregates_multiple_modules():
    modules = [
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
    ]
    client = _MockClient({
        "medical-wikimed": ["CPR"],
        "survival-wikihow": ["Fire Starting"],
    })
    results = await search_modules("s", modules, 8080, client)
    modules_in_results = {r["module"] for r in results}
    assert len(modules_in_results) == 2


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_search_endpoint_missing_q_returns_422(client):
    r = await client.get("/api/search")
    assert r.status_code == 422


async def test_search_endpoint_short_q_returns_422(client):
    r = await client.get("/api/search?q=a")
    assert r.status_code == 422


async def test_search_endpoint_returns_200_with_valid_q(client):
    # Kiwix not running in tests → graceful empty list
    r = await client.get("/api/search?q=test")
    assert r.status_code == 200


async def test_search_endpoint_returns_list(client):
    r = await client.get("/api/search?q=test")
    assert isinstance(r.json(), list)


async def test_search_endpoint_result_shape(client, tmp_settings, monkeypatch):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)

    import app.routers.search as search_router_module
    async def _fake_search(query, active_modules, kiwix_port, http_client):
        return [{"title": "First Aid", "module": "Medical", "url": "http://localhost:8080/search?content=medical-wikimed&pattern=first"}]
    monkeypatch.setattr(search_router_module, "search_modules", _fake_search)

    r = await client.get("/api/search?q=first")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert "title" in data[0]
    assert "module" in data[0]
    assert "url" in data[0]
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_search.py -v
```

Expected: `ImportError` — `app.services.search` doesn't exist yet.

- [ ] **Step 3: Create `app/services/search.py`**

```python
from __future__ import annotations
import httpx
from app.models.registry import Module

_EXCLUDE_CATEGORIES = {"maps", "packages", "internet"}


async def kiwix_suggestions(
    query: str,
    module: Module,
    kiwix_port: int,
    client: httpx.AsyncClient,
    count: int = 3,
) -> list[str]:
    url = f"http://localhost:{kiwix_port}/suggest?content={module.id}&term={query}&count={count}"
    try:
        r = await client.get(url, timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except httpx.RequestError:
        pass
    return []


async def search_modules(
    query: str,
    active_modules: list[Module],
    kiwix_port: int,
    client: httpx.AsyncClient,
) -> list[dict]:
    results = []
    searchable = [m for m in active_modules if m.category not in _EXCLUDE_CATEGORIES]
    for module in searchable:
        titles = await kiwix_suggestions(query, module, kiwix_port, client)
        search_url = f"http://localhost:{kiwix_port}/search?content={module.id}&pattern={query}"
        for title in titles:
            results.append({
                "title": title,
                "module": module.display_name,
                "url": search_url,
            })
    return results
```

- [ ] **Step 4: Create `app/routers/search.py`**

```python
from __future__ import annotations
import httpx
from fastapi import APIRouter, Query, Request
from app.config import Settings
from app.services.registry import load_registry
from app.services.search import search_modules


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/search")
    async def search(request: Request, q: str = Query(..., min_length=2)):
        registry = load_registry(cfg)
        active = [m for m in registry.modules if m.active]
        async with httpx.AsyncClient() as client:
            return await search_modules(q, active, cfg.kiwix_port, client)

    return router
```

- [ ] **Step 5: Wire into `app/main.py`**

Add search router include after the existing router includes:

Old block in `create_app`:
```python
    from app.routers import system as system_router
    app.include_router(system_router.make_router(cfg))

    from app.routers import home as home_router
    app.include_router(home_router.make_router(cfg))
```

New:
```python
    from app.routers import system as system_router
    app.include_router(system_router.make_router(cfg))

    from app.routers import home as home_router
    app.include_router(home_router.make_router(cfg))

    from app.routers import search as search_router
    app.include_router(search_router.make_router(cfg))
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
uv run pytest tests/test_search.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/services/search.py app/routers/search.py app/main.py \
        tests/test_search.py
git commit -m "feat: add /api/search endpoint with Kiwix suggest aggregation"
```

---

## Task 4: Search frontend — enable input and results dropdown

**Files:**
- Modify: `app/templates/home.html`
- Modify: `app/static/css/app.css` (recompile)

No new Python tests — the frontend behaviour is Alpine.js only. The earlier `test_home.py` tests keep passing as the search input markup changes.

- [ ] **Step 1: Replace the search bar section in `app/templates/home.html`**

Replace the search bar block (lines 1–18 in `home.html`, the `<!-- Search bar -->` section through the closing `</div>`) with:

```html
<!-- Search bar -->
<div
  class="px-[10px] pt-2 flex-shrink-0 relative"
  x-data="{
    searchQuery: '',
    searchResults: [],
    searchOpen: false,
    async search() {
      if (this.searchQuery.length < 2) { this.searchResults = []; this.searchOpen = false; return; }
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(this.searchQuery));
        this.searchResults = await r.json();
        this.searchOpen = this.searchResults.length > 0;
      } catch(e) { this.searchResults = []; }
    }
  }"
>
  <div class="flex items-center gap-[10px] bg-surface border border-border rounded-lg px-4 py-[10px]">
    <span class="text-text-lo text-[14px]">⌕</span>
    <input
      id="search"
      type="text"
      x-model="searchQuery"
      @input.debounce.300ms="search()"
      @keydown.escape="searchResults = []; searchOpen = false"
      placeholder="Search knowledge bases…"
      class="flex-1 bg-transparent font-display text-[14px] text-text-lo placeholder-text-lo outline-none tracking-[0.02em]"
      autocomplete="off"
    >
    <span class="text-[11px] text-text-lo tracking-[0.08em] bg-[oklch(22%_0.006_90)] border border-border px-2 py-[2px] rounded">Ctrl+K</span>
  </div>

  <!-- Results dropdown -->
  <div
    x-show="searchOpen && searchResults.length > 0"
    x-cloak
    class="absolute left-[10px] right-[10px] mt-[2px] bg-surface border border-border rounded-lg overflow-hidden z-10"
  >
    <template x-for="result in searchResults" :key="result.title + result.module">
      <a
        :href="result.url"
        class="flex items-center gap-3 px-4 py-[10px] border-b border-border last:border-b-0 hover:bg-elevated"
        @click="searchOpen = false; searchQuery = ''"
      >
        <span class="text-text-lo text-[11px] tracking-[0.06em] uppercase font-display min-w-[80px]" x-text="result.module"></span>
        <span class="text-text-hi text-[14px] font-body truncate" x-text="result.title"></span>
      </a>
    </template>
  </div>
</div>
```

The full updated `app/templates/home.html`:

```html
{% extends "base.html" %}
{% from "macros/tile.html" import render_tile %}

{% block content %}
<!-- Search bar -->
<div
  class="px-[10px] pt-2 flex-shrink-0 relative"
  x-data="{
    searchQuery: '',
    searchResults: [],
    searchOpen: false,
    async search() {
      if (this.searchQuery.length < 2) { this.searchResults = []; this.searchOpen = false; return; }
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(this.searchQuery));
        this.searchResults = await r.json();
        this.searchOpen = this.searchResults.length > 0;
      } catch(e) { this.searchResults = []; }
    }
  }"
>
  <div class="flex items-center gap-[10px] bg-surface border border-border rounded-lg px-4 py-[10px]">
    <span class="text-text-lo text-[14px]">⌕</span>
    <input
      id="search"
      type="text"
      x-model="searchQuery"
      @input.debounce.300ms="search()"
      @keydown.escape="searchResults = []; searchOpen = false"
      placeholder="Search knowledge bases…"
      class="flex-1 bg-transparent font-display text-[14px] text-text-lo placeholder-text-lo outline-none tracking-[0.02em]"
      autocomplete="off"
    >
    <span class="text-[11px] text-text-lo tracking-[0.08em] bg-[oklch(22%_0.006_90)] border border-border px-2 py-[2px] rounded">Ctrl+K</span>
  </div>

  <!-- Results dropdown -->
  <div
    x-show="searchOpen && searchResults.length > 0"
    x-cloak
    class="absolute left-[10px] right-[10px] mt-[2px] bg-surface border border-border rounded-lg overflow-hidden z-10"
  >
    <template x-for="result in searchResults" :key="result.title + result.module">
      <a
        :href="result.url"
        class="flex items-center gap-3 px-4 py-[10px] border-b border-border last:border-b-0 hover:bg-elevated"
        @click="searchOpen = false; searchQuery = ''"
      >
        <span class="text-text-lo text-[11px] tracking-[0.06em] uppercase font-display min-w-[80px]" x-text="result.module"></span>
        <span class="text-text-hi text-[14px] font-body truncate" x-text="result.title"></span>
      </a>
    </template>
  </div>
</div>

<!-- Bento grid -->
<div class="flex-1 p-[10px] min-h-0">
  {% if layout.empty %}
  <div class="w-full h-full flex items-center justify-center">
    <div class="text-center">
      <div class="text-[48px] mb-4">📦</div>
      <div class="font-display font-bold text-[22px] uppercase tracking-[0.05em] text-text-mid mb-2">No modules active</div>
      <a href="/packages" class="font-body text-[14px] text-tile-packages hover:text-text-hi underline underline-offset-2">Open Packages to install content</a>
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

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass (no new tests for this task — frontend behaviour is verified manually in Step 3).

- [ ] **Step 3: Recompile Tailwind**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

Expected: `app/static/css/app.css` updated.

- [ ] **Step 4: Start dev server and verify manually**

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`. Verify:
- Tiles render with accent bars and text (same as Plan 2)
- Maps tile is a clickable link (cursor changes on hover)
- Packages system tile is a clickable link
- Empty state (no modules) shows "Open Packages to install content" as a teal underlined link
- Search bar is now enabled — can type into it
- Ctrl+K focuses the search input
- Typing 2+ characters triggers a fetch to `/api/search` (visible in browser devtools Network tab) — returns `[]` since Kiwix isn't running; dropdown stays hidden

- [ ] **Step 5: Commit**

```bash
git add app/templates/home.html app/static/css/app.css
git commit -m "feat: enable search input with Alpine.js dropdown"
```

---

## Self-review

**Spec coverage:**

| Spec §9 item | Task |
|---|---|
| Module tile interactivity — linking to Kiwix/mbtileserver | Task 1 |
| Empty state CTA actions | Task 2 |
| Search functionality — backend search aggregation | Task 3 |
| Search frontend wiring | Task 4 |

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `TileLayout.url: str = ""` added in Task 1 step 3; used in tile macro step 5 as `tile.url` ✓
- `_with_urls(layout, cfg)` returns `BentoLayout`; assigned to `layout` in home route ✓
- `kiwix_suggestions(query, module, kiwix_port, client)` defined in search service; called in `search_modules` with same signature ✓
- `search_modules(query, active_modules, kiwix_port, client)` imported in `app/routers/search.py`; monkeypatched in test as `app.routers.search.search_modules` ✓
- `make_router(cfg)` pattern used for all three routers; consistent with existing `system.py` and `home.py` ✓
