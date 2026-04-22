# Package System — Plan 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full package manager: update-check, resumable downloads, install/uninstall, activate/deactivate, and a `/packages` screen — plus a chrome simplification across all pages.

**Architecture:** Download state is derived purely from the filesystem (`.part` file = in-progress or interrupted; final file in `/data/zim/` or `/data/maps/` = installed). An in-memory `_active_tasks` dict tracks running asyncio tasks. Kiwix integration uses `kiwix-manage` + SIGHUP; mbtileserver needs only SIGHUP. The `/packages` page is server-rendered Jinja2; Alpine.js handles per-row download polling and reactive action buttons without full page reloads.

**Tech Stack:** Python 3.14, FastAPI, httpx, asyncio, subprocess, Jinja2, Alpine.js, TailwindCSS v4 (compiled via `tailwindcss` Homebrew CLI)

---

## File map

| File | Action | Purpose |
|------|--------|---------|
| `app/templates/base.html` | Modify | Remove modules count, updates badge, wifi text |
| `app/routers/home.py` | Modify | Drop unused template context vars |
| `app/models/registry.py` | Modify | Add `download_url: Optional[str] = None` to `Module` |
| `app/services/packages.py` | Create | Download manager, status detection, install/uninstall/activate/deactivate, kiwix integration |
| `app/routers/packages.py` | Create | All `/packages` and `/api/packages/*` routes |
| `app/templates/packages.html` | Create | Packages screen (extends base.html) |
| `app/main.py` | Modify | Include packages router |
| `app/static/css/app.css` | Recompile | Pick up new Tailwind classes from packages.html |
| `tests/test_packages.py` | Create | Service unit tests + HTTP endpoint tests |
| `tests/test_home.py` | Modify | Add chrome simplification regression tests |

---

## Task 1: Chrome simplification

Removes the modules count, updates badge, and wifi text from `base.html` (affects all pages). Also cleans up the home router to stop passing the now-unused template variables.

**Files:**
- Modify: `tests/test_home.py`
- Modify: `app/templates/base.html`
- Modify: `app/routers/home.py`

- [ ] **Step 1: Add failing regression tests**

Append to `tests/test_home.py`:

```python
async def test_chrome_has_no_modules_label(client):
    r = await client.get("/")
    assert "Modules" not in r.text


async def test_chrome_wifi_no_text(client):
    r = await client.get("/")
    assert ">connected<" not in r.text
    assert ">offline<" not in r.text


async def test_chrome_has_no_updates_badge(client):
    r = await client.get("/")
    assert "bg-tile-survival" not in r.text
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_home.py::test_chrome_has_no_modules_label tests/test_home.py::test_chrome_wifi_no_text tests/test_home.py::test_chrome_has_no_updates_badge -v
```

Expected: `FAILED` — all three assertions fail because the current chrome contains these elements.

- [ ] **Step 3: Replace `app/templates/base.html`**

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
  <!-- Top chrome -->
  <header class="flex items-center justify-between px-5 h-[50px] flex-shrink-0"
          style="background: oklch(11% 0.005 90); border-bottom: 1px solid oklch(35% 0.06 75);">
    <span class="font-display font-bold text-[16px] tracking-[0.18em] text-amber">⬡ CYBERDECK</span>
    <div class="flex items-center gap-7">

      <!-- WiFi status — dot only -->
      <div class="flex items-center gap-[7px]">
        <span class="text-[11px] tracking-[0.12em] uppercase text-text-lo">Net</span>
        <span class="w-2 h-2 rounded-full"
              :class="wifi_connected ? 'bg-tile-maps' : 'bg-text-lo'"></span>
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

- [ ] **Step 4: Update `app/routers/home.py` to drop unused context variables**

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
            "battery_pct": status.battery_pct,
            "wifi_connected": status.wifi_connected,
        })

    return router
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
uv run pytest tests/test_home.py -v
```

Expected: all tests pass including the three new ones.

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/templates/base.html app/routers/home.py tests/test_home.py
git commit -m "feat: simplify chrome — dot-only wifi, remove modules count and update badge"
```

---

## Task 2: Add `download_url` to Module model

**Files:**
- Modify: `app/models/registry.py`
- Modify: `tests/test_registry.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_registry.py`:

```python
def test_module_download_url_defaults_to_none():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
    )
    assert m.download_url is None


def test_module_download_url_round_trips():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
        download_url="https://example.com/wikimed.zim",
    )
    data = m.model_dump_json()
    m2 = Module.model_validate_json(data)
    assert m2.download_url == "https://example.com/wikimed.zim"
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_registry.py::test_module_download_url_defaults_to_none tests/test_registry.py::test_module_download_url_round_trips -v
```

Expected: `FAILED` — `Module` has no `download_url` field.

- [ ] **Step 3: Add `download_url` to `app/models/registry.py`**

Add one line to `Module` after `installed_checksum`:

```python
class Module(BaseModel):
    id: str
    display_name: str
    category: str
    description: str
    latest_version: str
    size_gb: float
    checksum: str
    installed_version: Optional[str] = None
    installed_checksum: Optional[str] = None
    download_url: Optional[str] = None
    active: bool = False

    @computed_field
    @property
    def is_installed(self) -> bool:
        return self.installed_version is not None

    @computed_field
    @property
    def has_update(self) -> bool:
        if not self.is_installed:
            return False
        return self.latest_version != self.installed_version
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_registry.py -v
```

Expected: all tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add app/models/registry.py tests/test_registry.py
git commit -m "feat: add download_url field to Module model"
```

---

## Task 3: Packages service — status detection and storage

Creates `app/services/packages.py` with the pure filesystem-query functions. No asyncio, no subprocess in this task.

**Files:**
- Create: `app/services/packages.py`
- Create: `tests/test_packages.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_packages.py`:

```python
from __future__ import annotations
import asyncio
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
import httpx

from app.config import Settings
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry
import app.services.packages as pkg_service


# ── helpers ───────────────────────────────────────────────────────────────────

def _mod(**overrides) -> Module:
    defaults = dict(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="Medical reference",
        latest_version="2024-10",
        size_gb=1.0,
        checksum="sha256:abc",
        download_url="https://example.com/wikimed.zim",
    )
    defaults.update(overrides)
    return Module(**defaults)


def _seed(tmp_settings, modules=None):
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=modules or [],
    )
    tmp_settings.registry_path.write_text(reg.model_dump_json())


@pytest.fixture(autouse=True)
def clear_active_tasks():
    pkg_service._active_tasks.clear()
    yield
    pkg_service._active_tasks.clear()


# ── get_download_status ───────────────────────────────────────────────────────

def test_get_download_status_not_installed(tmp_settings):
    m = _mod()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "not_installed"
    assert result["bytes_downloaded"] == 0
    assert result["pct"] == 0


def test_get_download_status_interrupted(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "interrupted"
    assert result["bytes_downloaded"] == 500


def test_get_download_status_downloading(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 200)
    pkg_service._active_tasks["medical-wikimed"] = object()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "downloading"
    assert result["bytes_downloaded"] == 200


def test_get_download_status_installed(tmp_settings):
    m = _mod()
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "installed"
    assert result["pct"] == 100


def test_get_download_status_maps_uses_mbtiles(tmp_settings):
    m = _mod(id="maps-world", category="maps")
    mbt = tmp_settings.maps_dir / "maps-world.mbtiles"
    mbt.parent.mkdir(parents=True, exist_ok=True)
    mbt.write_bytes(b"tiles")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "installed"


# ── get_storage_info ──────────────────────────────────────────────────────────

def test_get_storage_info_returns_used_and_free(tmp_settings):
    result = pkg_service.get_storage_info(tmp_settings)
    assert "used_bytes" in result
    assert "free_bytes" in result
    assert result["used_bytes"] > 0
    assert result["free_bytes"] > 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: `ImportError: cannot import name 'get_download_status' from 'app.services.packages'`

- [ ] **Step 3: Create `app/services/packages.py` with status and storage functions**

```python
from __future__ import annotations
import asyncio
import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

import httpx

from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry, save_registry, merge_remote_manifest

log = logging.getLogger(__name__)

_active_tasks: dict[str, asyncio.Task] = {}


# ── Path helpers ──────────────────────────────────────────────────────────────

def _final_path(module: Module, settings: Settings) -> Path:
    if module.category == "maps":
        return settings.maps_dir / f"{module.id}.mbtiles"
    return settings.zim_dir / f"{module.id}.zim"


def _part_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.part"


# ── Status and storage ────────────────────────────────────────────────────────

def get_download_status(module: Module, settings: Settings) -> dict:
    total_bytes = int(module.size_gb * 1024 ** 3)
    part = _part_path(module, settings)
    final = _final_path(module, settings)

    if final.exists():
        return {
            "status": "installed",
            "bytes_downloaded": total_bytes,
            "total_bytes": total_bytes,
            "pct": 100,
        }

    bytes_downloaded = part.stat().st_size if part.exists() else 0
    pct = int(bytes_downloaded * 100 / total_bytes) if total_bytes > 0 else 0

    if module.id in _active_tasks:
        return {
            "status": "downloading",
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": pct,
        }

    if part.exists():
        return {
            "status": "interrupted",
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": pct,
        }

    return {
        "status": "not_installed",
        "bytes_downloaded": 0,
        "total_bytes": total_bytes,
        "pct": 0,
    }


def get_storage_info(settings: Settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    return {"used_bytes": usage.used, "free_bytes": usage.free}
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: add packages service — status detection and storage info"
```

---

## Task 4: Packages service — uninstall, activate, deactivate

Adds the registry-mutation functions to `app/services/packages.py`. Subprocess calls to kiwix-manage and pkill are mocked in tests.

**Files:**
- Modify: `app/services/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_packages.py`:

```python
# ── uninstall_module ──────────────────────────────────────────────────────────

async def test_uninstall_deletes_final_file(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not zim.exists()


async def test_uninstall_deletes_part_file_if_present(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"partial")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not part.exists()


async def test_uninstall_clears_registry_fields(tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    await pkg_service.uninstall_module(m, tmp_settings)
    reg = load_registry(tmp_settings)
    updated = reg.modules[0]
    assert updated.installed_version is None
    assert updated.installed_checksum is None
    assert updated.active is False


# ── activate / deactivate ─────────────────────────────────────────────────────

async def test_activate_sets_active_true(tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=False)
    _seed(tmp_settings, [m])
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)
    await pkg_service.activate_module(m, tmp_settings)
    assert load_registry(tmp_settings).modules[0].active is True


async def test_deactivate_sets_active_false(tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    monkeypatch.setattr(pkg_service, "_kiwix_remove", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)
    await pkg_service.deactivate_module(m, tmp_settings)
    assert load_registry(tmp_settings).modules[0].active is False
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_packages.py -k "uninstall or activate or deactivate" -v
```

Expected: `AttributeError` — these functions don't exist yet.

- [ ] **Step 3: Add functions to `app/services/packages.py`**

Append after `get_storage_info`:

```python
# ── Install / uninstall / activate / deactivate ───────────────────────────────

async def uninstall_module(module: Module, settings: Settings) -> None:
    await cancel_download(module.id)
    part = _part_path(module, settings)
    final = _final_path(module, settings)
    if part.exists():
        part.unlink()
    if final.exists():
        final.unlink()
    if module.category != "maps":
        _kiwix_remove(module, settings)
    _signal_service(module)
    registry = load_registry(settings)
    for m in registry.modules:
        if m.id == module.id:
            m.installed_version = None
            m.installed_checksum = None
            m.active = False
            break
    save_registry(settings, registry)


async def activate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, True)
    if module.category != "maps":
        _kiwix_add(module, settings)
    _signal_service(module)


async def deactivate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, False)
    if module.category != "maps":
        _kiwix_remove(module, settings)
    _signal_service(module)


# ── Kiwix and service signals ─────────────────────────────────────────────────

def _kiwix_add(module: Module, settings: Settings) -> None:
    library_xml = settings.zim_dir / "library.xml"
    zim_path = settings.zim_dir / f"{module.id}.zim"
    if not library_xml.exists() or not zim_path.exists():
        return
    _run(["kiwix-manage", str(library_xml), "add", str(zim_path)])
    _run(["pkill", "-HUP", "kiwix-serve"])


def _kiwix_remove(module: Module, settings: Settings) -> None:
    library_xml = settings.zim_dir / "library.xml"
    if not library_xml.exists():
        return
    _run(["kiwix-manage", str(library_xml), "delete", module.id])
    _run(["pkill", "-HUP", "kiwix-serve"])


def _signal_service(module: Module) -> None:
    if module.category == "maps":
        _run(["pkill", "-HUP", "mbtileserver"])


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=False, capture_output=True)
    except FileNotFoundError:
        pass


# ── cancel_download (needed by uninstall) ─────────────────────────────────────

async def cancel_download(module_id: str) -> None:
    task = _active_tasks.get(module_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _active_tasks.pop(module_id, None)
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: add packages service — uninstall, activate, deactivate"
```

---

## Task 5: Packages service — start_download and check_for_updates

Adds the async download task and manifest-fetch function.

**Files:**
- Modify: `app/services/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_packages.py`:

```python
# ── start_download ────────────────────────────────────────────────────────────

async def test_start_download_raises_if_already_active(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["other-module"] = object()
    with pytest.raises(RuntimeError, match="already active"):
        await pkg_service.start_download(m, tmp_settings)


async def test_start_download_raises_if_no_url(tmp_settings):
    m = _mod(download_url=None)
    _seed(tmp_settings, [m])
    with pytest.raises(ValueError, match="no download_url"):
        await pkg_service.start_download(m, tmp_settings)


# ── check_for_updates ─────────────────────────────────────────────────────────

async def test_check_for_updates_merges_manifest(tmp_settings, monkeypatch):
    _seed(tmp_settings)
    manifest = [
        {
            "id": "medical-wikimed",
            "display_name": "WikiMed",
            "category": "medical",
            "description": "Medical",
            "latest_version": "2024-10",
            "size_gb": 0.8,
            "checksum": "sha256:abc",
            "download_url": "https://example.com/wikimed.zim",
        }
    ]

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return manifest

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, timeout=None): return _Resp()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _FakeClient)
    count = await pkg_service.check_for_updates(tmp_settings)
    assert count == 1
    assert len(load_registry(tmp_settings).modules) == 1


async def test_check_for_updates_raises_on_network_error(tmp_settings, monkeypatch):
    _seed(tmp_settings)

    class _ErrorClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, timeout=None):
            raise httpx.RequestError("connection refused")

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _ErrorClient)
    with pytest.raises(httpx.RequestError):
        await pkg_service.check_for_updates(tmp_settings)
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_packages.py -k "start_download or check_for_updates" -v
```

Expected: `AttributeError` — functions not yet defined.

- [ ] **Step 3: Append `start_download` and `check_for_updates` to `app/services/packages.py`**

Append after `cancel_download`:

```python
async def start_download(module: Module, settings: Settings) -> None:
    if _active_tasks:
        raise RuntimeError("A download is already active")
    if not module.download_url:
        raise ValueError(f"Module {module.id} has no download_url")
    task = asyncio.create_task(_download_task(module, settings))
    _active_tasks[module.id] = task


async def check_for_updates(settings: Settings) -> int:
    registry = load_registry(settings)
    async with httpx.AsyncClient() as client:
        r = await client.get(registry.update_server, timeout=10.0)
        r.raise_for_status()
        remote_modules = r.json()
    before_ids = {m.id for m in load_registry(settings).modules}
    before_versions = {m.id: m.latest_version for m in load_registry(settings).modules}
    merge_remote_manifest(settings, remote_modules)
    after = load_registry(settings).modules
    return sum(
        1 for m in after
        if m.id not in before_ids or m.latest_version != before_versions.get(m.id)
    )


async def _download_task(module: Module, settings: Settings) -> None:
    part = _part_path(module, settings)
    part.parent.mkdir(parents=True, exist_ok=True)
    offset = part.stat().st_size if part.exists() else 0
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}
            async with client.stream(
                "GET", module.download_url, headers=headers, timeout=30.0
            ) as r:
                r.raise_for_status()
                with part.open("ab") as f:
                    async for chunk in r.aiter_bytes(65536):
                        f.write(chunk)

        sha = hashlib.sha256()
        with part.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        digest = f"sha256:{sha.hexdigest()}"
        if digest != module.checksum:
            raise ValueError(f"Checksum mismatch: expected {module.checksum}, got {digest}")

        final = _final_path(module, settings)
        final.parent.mkdir(parents=True, exist_ok=True)
        part.rename(final)

        registry = load_registry(settings)
        for m in registry.modules:
            if m.id == module.id:
                m.installed_version = module.latest_version
                m.installed_checksum = module.checksum
                m.active = True
                break
        save_registry(settings, registry)

        if module.category != "maps":
            _kiwix_add(module, settings)
        _signal_service(module)

    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Download failed for %s", module.id)
    finally:
        _active_tasks.pop(module.id, None)
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: add packages service — start_download, cancel_download, check_for_updates"
```

---

## Task 6: Packages router, template, and main.py wiring

Adds the full `/packages` screen. Tests cover all API endpoints and the HTML page.

**Files:**
- Create: `app/routers/packages.py`
- Create: `app/templates/packages.html`
- Modify: `app/main.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Add failing HTTP tests**

Append to `tests/test_packages.py`:

```python
# ── HTTP fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── GET /packages ─────────────────────────────────────────────────────────────

async def test_packages_page_returns_200(client):
    r = await client.get("/packages")
    assert r.status_code == 200


async def test_packages_page_returns_html(client):
    r = await client.get("/packages")
    assert "text/html" in r.headers["content-type"]


async def test_packages_page_shows_installed_module(client, tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    r = await client.get("/packages")
    assert "WikiMed" in r.text


async def test_packages_page_shows_available_module(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    r = await client.get("/packages")
    assert "WikiMed" in r.text


async def test_packages_page_shows_updates_section_when_update_exists(client, tmp_settings):
    m = _mod(
        installed_version="2024-09",
        installed_checksum="sha256:old",
        latest_version="2024-10",
        active=True,
    )
    _seed(tmp_settings, [m])
    r = await client.get("/packages")
    assert "Updates available" in r.text


# ── POST /api/packages/check-updates ─────────────────────────────────────────

async def test_check_updates_returns_502_on_network_error(client, tmp_settings, monkeypatch):
    _seed(tmp_settings)
    import app.routers.packages as pkg_router

    async def _fail(settings):
        raise httpx.RequestError("down")

    monkeypatch.setattr(pkg_router, "check_for_updates", _fail)
    r = await client.post("/api/packages/check-updates")
    assert r.status_code == 502


# ── GET /api/packages/{id}/status ────────────────────────────────────────────

async def test_status_returns_404_for_unknown_module(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/api/packages/nonexistent/status")
    assert r.status_code == 404


async def test_status_returns_not_installed(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    r = await client.get("/api/packages/medical-wikimed/status")
    assert r.status_code == 200
    assert r.json()["status"] == "not_installed"


# ── POST /api/packages/{id}/install ──────────────────────────────────────────

async def test_install_returns_404_for_unknown_module(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/install")
    assert r.status_code == 404


async def test_install_returns_409_when_download_active(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["other"] = object()
    r = await client.post("/api/packages/medical-wikimed/install")
    assert r.status_code == 409


# ── POST /api/packages/{id}/cancel ───────────────────────────────────────────

async def test_cancel_returns_404_when_not_downloading(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/medical-wikimed/cancel")
    assert r.status_code == 404


# ── POST /api/packages/{id}/uninstall ────────────────────────────────────────

async def test_uninstall_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc")
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "uninstall_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/uninstall")
    assert r.status_code == 204


async def test_uninstall_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/uninstall")
    assert r.status_code == 404


# ── POST /api/packages/{id}/activate ─────────────────────────────────────────

async def test_activate_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=False)
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "activate_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/activate")
    assert r.status_code == 204


# ── POST /api/packages/{id}/deactivate ───────────────────────────────────────

async def test_deactivate_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "deactivate_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/deactivate")
    assert r.status_code == 204
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_packages.py -k "packages_page or check_updates or status or install or cancel or uninstall or activate or deactivate" -v
```

Expected: all `FAILED` with 404 — `/packages` route and `/api/packages/*` don't exist yet.

- [ ] **Step 3: Create `app/routers/packages.py`**

```python
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import httpx

from app.config import Settings
from app.services.packages import (
    _active_tasks,
    activate_module,
    cancel_download,
    check_for_updates,
    deactivate_module,
    get_download_status,
    get_storage_info,
    start_download,
    uninstall_module,
)
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/packages", response_class=HTMLResponse)
    async def packages_page(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        storage = get_storage_info(cfg)
        all_statuses = {m.id: get_download_status(m, cfg) for m in registry.modules}

        updates = [m for m in registry.modules if m.has_update]
        installed = [
            m for m in registry.modules
            if (m.is_installed and not m.has_update)
            or (not m.is_installed and all_statuses[m.id]["status"] in ("downloading", "interrupted"))
        ]
        available = [
            m for m in registry.modules
            if not m.is_installed
            and not m.has_update
            and all_statuses[m.id]["status"] == "not_installed"
        ]

        return templates.TemplateResponse(request, "packages.html", {
            "updates": updates,
            "installed": installed,
            "available": available,
            "module_statuses": all_statuses,
            "storage": storage,
            "has_active_download": bool(_active_tasks),
            "battery_pct": status.battery_pct,
            "wifi_connected": status.wifi_connected,
        })

    @router.post("/api/packages/check-updates")
    async def check_updates_endpoint():
        try:
            count = await check_for_updates(cfg)
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return {"updated": count}

    @router.get("/api/packages/{module_id}/status")
    async def module_status(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return get_download_status(module, cfg)

    @router.post("/api/packages/{module_id}/install")
    async def install(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            await start_download(module, cfg)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return Response(status_code=202)

    @router.post("/api/packages/{module_id}/cancel")
    async def cancel(module_id: str):
        if module_id not in _active_tasks:
            return JSONResponse({"error": "not downloading"}, status_code=404)
        await cancel_download(module_id)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/uninstall")
    async def uninstall(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await uninstall_module(module, cfg)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/activate")
    async def activate(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await activate_module(module, cfg)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/deactivate")
    async def deactivate(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await deactivate_module(module, cfg)
        return Response(status_code=204)

    return router
```

- [ ] **Step 4: Create `app/templates/packages.html`**

```html
{% extends "base.html" %}

{% block content %}
{% set icons = {
  'medical': '🏥', 'maps': '🗺️', 'survival': '🪓', 'food': '🌿',
  'encyclopedia': '📖', 'packages': '📦', 'internet': '🌐',
} %}

<!-- Page header + check-updates button -->
<div
  class="flex-shrink-0 border-b border-border"
  x-data="{ checking: false, checkError: '' }"
>
  <div class="px-4 py-3 flex items-center justify-between">
    <span class="font-display font-bold text-[13px] uppercase tracking-[0.14em] text-text-hi">📦 Packages</span>
    <button
      class="font-display text-[10px] uppercase tracking-[0.08em] text-amber border border-amber-ghost px-3 py-[5px] rounded-[5px]"
      :disabled="checking"
      :class="checking ? 'opacity-50' : ''"
      @click="
        checking = true; checkError = '';
        fetch('/api/packages/check-updates', {method: 'POST'})
          .then(r => { if (r.ok) location.reload(); else { checkError = 'Update check failed'; } })
          .catch(() => { checkError = 'Network error'; })
          .finally(() => { checking = false; setTimeout(() => checkError = '', 3000); })
      "
    >
      <span x-show="!checking">↻ Check for updates</span>
      <span x-show="checking" x-cloak>Checking…</span>
    </button>
  </div>
  <div x-show="checkError" x-cloak class="px-4 pb-2">
    <span x-text="checkError" class="font-body text-[11px] text-tile-medical"></span>
  </div>
</div>

<!-- Storage bar -->
<div class="px-4 py-2 flex items-center gap-3 flex-shrink-0 border-b border-border">
  <span class="font-display text-[10px] uppercase tracking-[0.1em] text-text-lo whitespace-nowrap">Storage</span>
  <div class="flex-1 h-[5px] bg-elevated rounded-full overflow-hidden">
    <div class="h-full bg-tile-maps rounded-full"
         style="width: {{ [(storage.used_bytes / (storage.used_bytes + storage.free_bytes) * 100) | int, 100] | min }}%"></div>
  </div>
  <span class="font-body text-[10px] text-text-lo whitespace-nowrap">
    {{ "%.0f"|format(storage.used_bytes / 1e9) }} GB used · {{ "%.0f"|format(storage.free_bytes / 1e9) }} GB free
  </span>
</div>

<!-- Scrollable module list -->
<div class="flex-1 overflow-y-auto px-4 pb-4">

  <!-- ── Updates section ─────────────────────────────────────────── -->
  {% if updates %}
  <div class="flex items-center gap-2 pt-3 pb-[6px] font-display text-[10px] uppercase tracking-[0.12em] font-bold text-amber">
    ▸ Updates available
    <span class="text-[9px] px-[6px] py-[1px] rounded-[10px] bg-amber-ghost text-amber">{{ updates | length }}</span>
  </div>
  {% for m in updates %}
  {% set s = module_statuses[m.id] %}
  <div class="flex items-center gap-[10px] px-3 py-[10px] rounded-lg mb-1 border"
       style="background: oklch(13% 0.015 75); border-color: oklch(25% 0.04 75);"
       x-data="{
         async act(url) {
           await fetch(url, {method: 'POST'});
           location.reload();
         }
       }">
    <span class="text-[20px] w-7 text-center flex-shrink-0">{{ icons.get(m.category, '▪') }}</span>
    <div class="flex-1 min-w-0">
      <div class="font-display font-bold text-[13px] text-text-hi truncate">{{ m.display_name }}</div>
      <div class="font-body text-[10px] text-text-lo mt-[2px]">{{ "%.1f"|format(m.size_gb) }} GB · installed {{ m.installed_version }}</div>
    </div>
    <span class="font-body text-[10px] text-amber whitespace-nowrap">→ {{ m.latest_version }}</span>
    <div class="flex gap-[6px] flex-shrink-0">
      <button @click="act('/api/packages/{{ m.id }}/install')"
              class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-amber border-amber-mid bg-amber-ghost">
        Update
      </button>
      <button @click="act('/api/packages/{{ m.id }}/uninstall')"
              class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-tile-medical border-tile-medical/40">
        Remove
      </button>
    </div>
  </div>
  {% endfor %}
  {% endif %}

  <!-- ── Installed section ───────────────────────────────────────── -->
  {% if installed %}
  <div class="flex items-center gap-2 pt-3 pb-[6px] font-display text-[10px] uppercase tracking-[0.12em] font-bold text-tile-maps">
    ▸ Installed
    <span class="text-[9px] px-[6px] py-[1px] rounded-[10px] bg-elevated text-text-lo">{{ installed | length }}</span>
  </div>
  {% for m in installed %}
  {% set s = module_statuses[m.id] %}
  <div
    class="flex items-center gap-[10px] px-3 py-[10px] rounded-lg mb-1 bg-surface"
    x-data="{
      status: '{{ s.status }}',
      pct: {{ s.pct }},
      bytes_dl: {{ s.bytes_downloaded }},
      total: {{ s.total_bytes }},
      _poll: null,
      init() {
        if (this.status === 'downloading')
          this._poll = setInterval(() => this.refresh(), 1000);
      },
      async refresh() {
        const r = await fetch('/api/packages/{{ m.id }}/status');
        const d = await r.json();
        this.status = d.status;
        this.pct = d.pct;
        this.bytes_dl = d.bytes_downloaded;
        if (this.status !== 'downloading') {
          clearInterval(this._poll);
          location.reload();
        }
      },
      async act(url) {
        await fetch(url, {method: 'POST'});
        location.reload();
      }
    }"
  >
    <span class="text-[20px] w-7 text-center flex-shrink-0">{{ icons.get(m.category, '▪') }}</span>

    <!-- Downloading -->
    <div class="flex-1 min-w-0" x-show="status === 'downloading'">
      <div class="font-display font-bold text-[13px] text-text-hi truncate">{{ m.display_name }}</div>
      <div class="h-[5px] bg-elevated rounded-full mt-[5px] overflow-hidden">
        <div class="h-full bg-amber rounded-full" :style="'width:' + pct + '%'"></div>
      </div>
      <div class="font-body text-[10px] text-text-lo mt-[3px]"
           x-text="(bytes_dl/1e9).toFixed(1) + ' GB of ' + (total/1e9).toFixed(1) + ' GB · ' + pct + '%'"></div>
    </div>

    <!-- Interrupted -->
    <div class="flex-1 min-w-0" x-show="status === 'interrupted'" x-cloak>
      <div class="font-display font-bold text-[13px] text-text-hi truncate">{{ m.display_name }}</div>
      <div class="font-body text-[10px] text-tile-survival mt-[2px]"
           x-text="'⚠ Interrupted · ' + (bytes_dl/1e9).toFixed(1) + ' GB of ' + (total/1e9).toFixed(1) + ' GB'"></div>
    </div>

    <!-- Installed -->
    <div class="flex-1 min-w-0" x-show="status === 'installed'" x-cloak>
      <div class="font-display font-bold text-[13px] text-text-hi truncate">{{ m.display_name }}</div>
      <div class="font-body text-[10px] text-text-lo mt-[2px]">{{ "%.1f"|format(m.size_gb) }} GB · {{ m.installed_version }}</div>
    </div>

    <!-- Actions -->
    <div class="flex gap-[6px] flex-shrink-0">
      <template x-if="status === 'downloading'">
        <button @click="act('/api/packages/{{ m.id }}/cancel')"
                class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-text-lo border-border">
          Cancel
        </button>
      </template>
      <template x-if="status === 'interrupted'">
        <div class="flex gap-[6px]">
          <button @click="act('/api/packages/{{ m.id }}/install')"
                  class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-tile-survival border-tile-survival/40">
            Resume
          </button>
          <button @click="act('/api/packages/{{ m.id }}/uninstall')"
                  class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-tile-medical border-tile-medical/40">
            Remove
          </button>
        </div>
      </template>
      <template x-if="status === 'installed'">
        <div class="flex gap-[6px]">
          {% if m.active %}
          <button @click="act('/api/packages/{{ m.id }}/deactivate')"
                  class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-tile-maps border-tile-maps/40">
            Active
          </button>
          {% else %}
          <button @click="act('/api/packages/{{ m.id }}/activate')"
                  class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-text-lo border-border">
            Activate
          </button>
          {% endif %}
          <button @click="act('/api/packages/{{ m.id }}/uninstall')"
                  class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-tile-medical border-tile-medical/40">
            Remove
          </button>
        </div>
      </template>
    </div>
  </div>
  {% endfor %}
  {% endif %}

  <!-- ── Available section ───────────────────────────────────────── -->
  {% if available %}
  <div class="flex items-center gap-2 pt-3 pb-[6px] font-display text-[10px] uppercase tracking-[0.12em] font-bold text-text-lo">
    ▸ Available
    <span class="text-[9px] px-[6px] py-[1px] rounded-[10px] bg-elevated text-text-lo">{{ available | length }}</span>
  </div>
  {% for m in available %}
  <div class="flex items-center gap-[10px] px-3 py-[10px] rounded-lg mb-1 border border-dashed border-border">
    <span class="text-[20px] w-7 text-center flex-shrink-0 opacity-50">{{ icons.get(m.category, '▪') }}</span>
    <div class="flex-1 min-w-0">
      <div class="font-display font-bold text-[13px] text-text-lo truncate">{{ m.display_name }}</div>
      <div class="font-body text-[10px] text-text-lo mt-[2px]">{{ "%.1f"|format(m.size_gb) }} GB</div>
    </div>
    <button
      onclick="fetch('/api/packages/{{ m.id }}/install', {method:'POST'}).then(()=>location.reload())"
      class="font-display text-[10px] font-bold px-2 py-[3px] rounded border text-text-mid border-border flex-shrink-0"
      {% if has_active_download %}disabled style="opacity:.4;cursor:not-allowed"{% endif %}
    >Install</button>
  </div>
  {% endfor %}
  {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 5: Wire packages router into `app/main.py`**

Add after the search router include in `create_app`:

```python
    from app.routers import search as search_router
    app.include_router(search_router.make_router(cfg))

    from app.routers import packages as packages_router
    app.include_router(packages_router.make_router(cfg))
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
        yield

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    from app.routers import system as system_router
    app.include_router(system_router.make_router(cfg))

    from app.routers import home as home_router
    app.include_router(home_router.make_router(cfg))

    from app.routers import search as search_router
    app.include_router(search_router.make_router(cfg))

    from app.routers import packages as packages_router
    app.include_router(packages_router.make_router(cfg))

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

- [ ] **Step 6: Run new tests — expect all pass**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass with no warnings.

- [ ] **Step 8: Commit**

```bash
git add app/routers/packages.py app/templates/packages.html app/main.py tests/test_packages.py
git commit -m "feat: add packages router, template, and /packages screen"
```

---

## Task 7: Tailwind recompile and smoke test

**Files:**
- Modify: `app/static/css/app.css` (recompile)

- [ ] **Step 1: Recompile Tailwind with all new template classes**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

Expected: `app/static/css/app.css` updated (larger than before, new utility classes from `packages.html`).

- [ ] **Step 2: Start dev server and verify in browser**

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`. Verify:
- Chrome shows only `⬡ CYBERDECK` · `Net [dot]` · `Bat [pct]` — no modules count, no update badge, no wifi text
- Dot is green if wifi connected, grey if not

Open `http://localhost:8000/packages`. Verify:
- Page renders with `📦 Packages` header and `↻ Check for updates` button
- Storage bar is visible
- Empty state (no modules) shows nothing except empty sections

- [ ] **Step 3: Seed modules and verify packages screen states**

In a second terminal:

```bash
python3 - << 'EOF'
import json
from pathlib import Path

reg = {
  "update_server": "https://updates.example.com/cyberdeck/manifest.json",
  "modules": [
    {
      "id": "medical-wikimed", "display_name": "WikiMed Medical", "category": "medical",
      "description": "Offline medical encyclopedia",
      "latest_version": "2024-10", "size_gb": 0.8, "checksum": "sha256:abc",
      "installed_version": "2024-10", "installed_checksum": "sha256:abc",
      "download_url": "https://example.com/wikimed.zim", "active": True
    },
    {
      "id": "maps-world", "display_name": "OpenStreetMap World", "category": "maps",
      "description": "Offline OSM",
      "latest_version": "2024-01", "size_gb": 9.2, "checksum": "sha256:xyz",
      "installed_version": None, "installed_checksum": None,
      "download_url": "https://example.com/maps.mbtiles", "active": False
    },
    {
      "id": "survival-wikihow", "display_name": "WikiHow Survival", "category": "survival",
      "description": "Offline survival guide",
      "latest_version": "2024-11", "size_gb": 1.4, "checksum": "sha256:new",
      "installed_version": "2024-09", "installed_checksum": "sha256:old",
      "download_url": "https://example.com/survival.zim", "active": True
    }
  ]
}
Path("/data/packages").mkdir(parents=True, exist_ok=True)
Path("/data/packages/registry.json").write_text(json.dumps(reg, indent=2))
print("Seeded.")
EOF
```

Reload `http://localhost:8000/packages`. Verify:
- "Updates available (1)" section appears in amber with WikiHow showing `→ 2024-11`
- "Installed (1)" section shows WikiMed with green "Active" badge and "Remove" button
- "Available (1)" section shows OpenStreetMap with "Install" button
- Clicking "Active" on WikiMed calls `POST /api/packages/medical-wikimed/deactivate` and reloads

- [ ] **Step 4: Verify home portal still works**

Open `http://localhost:8000`. Verify:
- Bento grid renders correctly
- Chrome shows only Net dot + Bat — no modules count or badge

- [ ] **Step 5: Final Tailwind recompile to ensure no drift**

```bash
tailwindcss -i app/static/css/input.css -o app/static/css/app.css --minify
```

- [ ] **Step 6: Commit**

```bash
git add app/static/css/app.css
git commit -m "chore: recompile Tailwind with packages screen class set"
```

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `GET /packages` HTML page | Task 6 |
| `POST /api/packages/check-updates` | Task 6 |
| `GET /api/packages/{id}/status` | Task 6 |
| `POST /api/packages/{id}/install` (start/resume) | Task 6 |
| `POST /api/packages/{id}/cancel` | Task 6 |
| `POST /api/packages/{id}/uninstall` | Task 6 |
| `POST /api/packages/{id}/activate` | Task 6 |
| `POST /api/packages/{id}/deactivate` | Task 6 |
| Chrome simplification — all pages | Task 1 |
| `download_url` on Module | Task 2 |
| Filesystem state (`.part`, final file) | Task 3 |
| Storage bar | Task 6 (template) |
| One download at a time (409) | Task 6 |
| Resumable downloads (Range header) | Task 5 |
| SHA-256 checksum verification | Task 5 |
| Kiwix library.xml management | Task 4 |
| mbtileserver SIGHUP | Task 4 |
| Updates section (amber, sorted first) | Task 6 (template) |
| Per-row Alpine polling during download | Task 6 (template) |
| Disable Install buttons during active download | Task 6 (template) |

**Placeholder scan:** No TBDs or incomplete sections found.

**Type consistency:**
- `get_download_status(module, settings) -> dict` defined Task 3, called Task 6 router ✓
- `get_storage_info(settings) -> dict` defined Task 3, called Task 6 router; `storage.used_bytes` / `storage.free_bytes` used in template ✓
- `start_download(module, settings)` defined Task 5, called in router Task 6 ✓
- `cancel_download(module_id)` defined Task 4, called in router Task 6 ✓
- `uninstall_module(module, settings)` defined Task 4, called in router Task 6 ✓
- `activate_module(module, settings)` defined Task 4, called in router Task 6 ✓
- `deactivate_module(module, settings)` defined Task 4, called in router Task 6 ✓
- `check_for_updates(settings) -> int` defined Task 5, called in router Task 6; monkeypatched by name `check_for_updates` in test ✓
- `_active_tasks` dict imported by name in router Task 6; cleared in `autouse` fixture ✓
- `module_statuses[m.id]` — template accesses `.status`, `.pct`, `.bytes_downloaded`, `.total_bytes` — all returned by `get_download_status` ✓
- `storage.used_bytes` / `storage.free_bytes` — returned by `get_storage_info`, accessed in template ✓
- `_kiwix_add`, `_kiwix_remove`, `_signal_service` — monkeypatched in Task 4 tests by those exact names ✓
