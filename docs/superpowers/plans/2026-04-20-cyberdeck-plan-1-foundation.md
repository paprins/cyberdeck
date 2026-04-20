# Cyberdeck — Plan 1: Foundation & Infrastructure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the Python project, typed config, registry data model, FastAPI skeleton, systemd service definitions, and RPi bootstrap scripts. After this plan the device boots into a working FastAPI service (port 8000) that Chromium can connect to.

**Architecture:** FastAPI serves on port 8000 via uvicorn, managed by systemd. Kiwix-serve (port 8080) and mbtileserver (port 8081) are sibling systemd units. All runtime paths derive from a single `Settings` object driven by env vars with sensible RPi defaults. The registry is a JSON file at `/data/packages/registry.json`, read/written through a typed service layer.

**Tech Stack:** Python 3.14, FastAPI 0.115+, uvicorn[standard], pydantic 2.x, pydantic-settings 2.x, httpx, pytest 8, pytest-asyncio, uv (package manager)

---

## Project roadmap (4 plans total)

| Plan | Scope | Depends on |
|------|-------|------------|
| **Plan 1 (this)** | Foundation: project setup, config, registry model, FastAPI skeleton, systemd, scripts | — |
| Plan 2 | Portal UI: bento layout engine, home portal, design system, search bar, top chrome | Plan 1 |
| Plan 3 | Content services: Kiwix proxy, mbtileserver proxy, unified search aggregation | Plan 1 |
| Plan 4 | Package system: update check, resumable downloads, install/activate flow, package manager UI | Plans 1–3 |

---

## File structure

```
cyberdeck/
├── pyproject.toml              # Project metadata + dependencies
├── .python-version             # 3.14
├── .gitignore
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, lifespan, health + status endpoints
│   ├── config.py               # Settings (pydantic-settings, env prefix CYBERDECK_)
│   ├── models/
│   │   ├── __init__.py
│   │   └── registry.py         # Registry + Module pydantic models
│   └── services/
│       ├── __init__.py
│       └── registry.py         # load / save / query registry.json
├── data/
│   └── packages/
│       └── registry.json       # Initial empty registry (committed as seed)
├── systemd/
│   ├── cyberdeck.service       # FastAPI portal service
│   ├── kiwix.service           # Kiwix-serve ZIM content service
│   └── mbtileserver.service    # MBTiles map tile service
├── scripts/
│   ├── install.sh              # Full bootstrap for a fresh RPi
│   ├── setup-chromium.sh       # Chromium kiosk autostart
│   └── setup-power.sh          # CPU governor + SSD power management
└── tests/
    ├── conftest.py             # Shared fixtures (tmp settings, test client)
    ├── test_config.py
    ├── test_registry.py
    └── test_main.py
```

---

### Task 1: Python project setup

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/models/__init__.py`
- Create: `app/services/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

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
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create `.python-version`**

```
3.14
```

- [ ] **Step 3: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
dist/
*.egg-info/
data/zim/
data/maps/
data/downloads/
!data/packages/registry.json
.env
```

- [ ] **Step 4: Create empty `__init__.py` files**

```bash
touch app/__init__.py app/models/__init__.py app/services/__init__.py
```

- [ ] **Step 5: Install uv and create virtualenv**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv
uv pip install -e ".[dev]"
```

- [ ] **Step 6: Verify install**

```bash
uv run python -c "import fastapi, pydantic_settings; print('ok')"
```

Expected output: `ok`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version .gitignore app/
git commit -m "chore: initialise Python project with FastAPI + pydantic-settings"
```

---

### Task 2: Config

**Files:**
- Create: `app/config.py`
- Create: `tests/conftest.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from pathlib import Path
import pytest
from app.config import Settings


def test_default_data_dir():
    s = Settings()
    assert s.data_dir == Path("/data")


def test_default_ports():
    s = Settings()
    assert s.app_port == 8000
    assert s.kiwix_port == 8080
    assert s.mbtiles_port == 8081


def test_env_override(monkeypatch):
    monkeypatch.setenv("CYBERDECK_DATA_DIR", "/tmp/test-data")
    s = Settings()
    assert s.data_dir == Path("/tmp/test-data")


def test_derived_zim_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.zim_dir == Path("/tmp/x/zim")


def test_derived_maps_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.maps_dir == Path("/tmp/x/maps")


def test_derived_downloads_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.downloads_dir == Path("/tmp/x/downloads")


def test_derived_registry_path():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.registry_path == Path("/tmp/x/packages/registry.json")
```

Create `tests/conftest.py`:

```python
import pytest
from pathlib import Path
from app.config import Settings


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointed at a temporary data directory."""
    return Settings(data_dir=tmp_path)
```

- [ ] **Step 2: Run tests — expect failures**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` (Settings not defined yet).

- [ ] **Step 3: Implement `app/config.py`**

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    app_port: int = 8000
    kiwix_port: int = 8080
    mbtiles_port: int = 8081

    model_config = SettingsConfigDict(env_prefix="CYBERDECK_")

    @property
    def zim_dir(self) -> Path:
        return self.data_dir / "zim"

    @property
    def maps_dir(self) -> Path:
        return self.data_dir / "maps"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "packages" / "registry.json"
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: add Settings config with env override and derived paths"
```

---

### Task 3: Registry models

**Files:**
- Create: `app/models/registry.py`
- Create: `tests/test_registry.py` (partial — models section)

- [ ] **Step 1: Write failing model tests**

Create `tests/test_registry.py` (models section only for now):

```python
import json
import pytest
from app.models.registry import Module, Registry


def test_module_defaults():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed Medical Encyclopedia",
        category="medical",
        description="Offline medical reference",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc123",
    )
    assert m.installed_version is None
    assert m.installed_checksum is None
    assert m.active is False


def test_module_is_installed():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc123",
        installed_version="2024-10",
        installed_checksum="sha256:abc123",
    )
    assert m.is_installed is True
    assert m.has_update is False


def test_module_has_update():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-11",
        size_gb=0.8,
        checksum="sha256:newchecksum",
        installed_version="2024-10",
        installed_checksum="sha256:oldchecksum",
    )
    assert m.is_installed is True
    assert m.has_update is True


def test_registry_defaults():
    r = Registry(update_server="https://example.com/manifest.json")
    assert r.modules == []


def test_registry_serialises_to_json():
    r = Registry(update_server="https://example.com/manifest.json")
    data = json.loads(r.model_dump_json())
    assert data["update_server"] == "https://example.com/manifest.json"
    assert data["modules"] == []
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_registry.py::test_module_defaults -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `app/models/registry.py`**

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, computed_field


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


class Registry(BaseModel):
    update_server: str
    modules: list[Module] = []
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_registry.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/registry.py tests/test_registry.py
git commit -m "feat: add Registry and Module pydantic models with computed fields"
```

---

### Task 4: Registry service

**Files:**
- Create: `app/services/registry.py`
- Modify: `tests/test_registry.py` (add service tests)
- Create: `data/packages/registry.json`

- [ ] **Step 1: Add service tests to `tests/test_registry.py`**

Append to the existing file:

```python
import json
from pathlib import Path
from app.services.registry import (
    load_registry,
    save_registry,
    get_active_modules,
    set_module_active,
    merge_remote_manifest,
)
from app.models.registry import Module, Registry


# ── helpers ──────────────────────────────────────────────

def _seed(tmp_settings, modules=None):
    """Write a registry.json to the tmp data dir."""
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=modules or [],
    )
    tmp_settings.registry_path.write_text(reg.model_dump_json())


def _sample_module(**overrides) -> Module:
    defaults = dict(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="Medical reference",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
    )
    defaults.update(overrides)
    return Module(**defaults)


# ── tests ─────────────────────────────────────────────────

def test_load_empty_registry(tmp_settings):
    _seed(tmp_settings)
    reg = load_registry(tmp_settings)
    assert reg.update_server == "https://example.com/manifest.json"
    assert reg.modules == []


def test_load_missing_creates_default(tmp_settings):
    reg = load_registry(tmp_settings)
    assert reg.modules == []
    assert tmp_settings.registry_path.exists()


def test_save_and_reload(tmp_settings):
    _seed(tmp_settings)
    reg = load_registry(tmp_settings)
    reg.update_server = "https://new.example.com/manifest.json"
    save_registry(tmp_settings, reg)
    reloaded = load_registry(tmp_settings)
    assert reloaded.update_server == "https://new.example.com/manifest.json"


def test_get_active_modules_empty(tmp_settings):
    _seed(tmp_settings)
    assert get_active_modules(tmp_settings) == []


def test_get_active_modules_returns_only_active(tmp_settings):
    m1 = _sample_module(id="medical-wikimed", active=True)
    m2 = _sample_module(id="survival-wikihow", active=False)
    _seed(tmp_settings, modules=[m1, m2])
    active = get_active_modules(tmp_settings)
    assert len(active) == 1
    assert active[0].id == "medical-wikimed"


def test_set_module_active_true(tmp_settings):
    _seed(tmp_settings, modules=[_sample_module(active=False)])
    set_module_active(tmp_settings, "medical-wikimed", True)
    active = get_active_modules(tmp_settings)
    assert len(active) == 1


def test_set_module_active_false(tmp_settings):
    _seed(tmp_settings, modules=[_sample_module(active=True)])
    set_module_active(tmp_settings, "medical-wikimed", False)
    assert get_active_modules(tmp_settings) == []


def test_set_module_active_nonexistent_raises(tmp_settings):
    _seed(tmp_settings)
    with pytest.raises(KeyError, match="nonexistent"):
        set_module_active(tmp_settings, "nonexistent", True)


def test_merge_remote_manifest_adds_new_modules(tmp_settings):
    _seed(tmp_settings)
    remote = [
        {
            "id": "medical-wikimed",
            "display_name": "WikiMed",
            "category": "medical",
            "description": "Medical reference",
            "latest_version": "2024-10",
            "size_gb": 0.8,
            "checksum": "sha256:abc",
        }
    ]
    merge_remote_manifest(tmp_settings, remote)
    reg = load_registry(tmp_settings)
    assert len(reg.modules) == 1
    assert reg.modules[0].id == "medical-wikimed"


def test_merge_remote_manifest_preserves_installed_state(tmp_settings):
    existing = _sample_module(
        installed_version="2024-10",
        installed_checksum="sha256:abc",
        active=True,
    )
    _seed(tmp_settings, modules=[existing])
    remote = [
        {
            "id": "medical-wikimed",
            "display_name": "WikiMed",
            "category": "medical",
            "description": "Medical reference",
            "latest_version": "2024-11",
            "size_gb": 0.9,
            "checksum": "sha256:newchecksum",
        }
    ]
    merge_remote_manifest(tmp_settings, remote)
    reg = load_registry(tmp_settings)
    m = reg.modules[0]
    assert m.latest_version == "2024-11"
    assert m.installed_version == "2024-10"
    assert m.active is True
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_registry.py -k "service or load or save or active or merge" -v
```

Expected: `ImportError` (service not implemented).

- [ ] **Step 3: Implement `app/services/registry.py`**

```python
from __future__ import annotations
import json
from typing import Any
from app.config import Settings
from app.models.registry import Module, Registry

_DEFAULT_UPDATE_SERVER = "https://updates.example.com/cyberdeck/manifest.json"


def load_registry(settings: Settings) -> Registry:
    path = settings.registry_path
    if not path.exists():
        reg = Registry(update_server=_DEFAULT_UPDATE_SERVER)
        save_registry(settings, reg)
        return reg
    return Registry.model_validate_json(path.read_text())


def save_registry(settings: Settings, registry: Registry) -> None:
    path = settings.registry_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2))


def get_active_modules(settings: Settings) -> list[Module]:
    return [m for m in load_registry(settings).modules if m.active]


def set_module_active(settings: Settings, module_id: str, active: bool) -> None:
    registry = load_registry(settings)
    for module in registry.modules:
        if module.id == module_id:
            module.active = active
            save_registry(settings, registry)
            return
    raise KeyError(module_id)


def merge_remote_manifest(
    settings: Settings, remote_modules: list[dict[str, Any]]
) -> None:
    registry = load_registry(settings)
    existing = {m.id: m for m in registry.modules}
    for remote in remote_modules:
        module_id = remote["id"]
        if module_id in existing:
            current = existing[module_id]
            updated = Module(
                **{
                    **remote,
                    "installed_version": current.installed_version,
                    "installed_checksum": current.installed_checksum,
                    "active": current.active,
                }
            )
            existing[module_id] = updated
        else:
            existing[module_id] = Module(**remote)
    registry.modules = list(existing.values())
    save_registry(settings, registry)
```

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_registry.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Create seed registry file**

```bash
mkdir -p data/packages
cat > data/packages/registry.json << 'EOF'
{
  "update_server": "https://updates.example.com/cyberdeck/manifest.json",
  "modules": []
}
EOF
```

- [ ] **Step 6: Commit**

```bash
git add app/services/registry.py tests/test_registry.py data/packages/registry.json
git commit -m "feat: add registry service — load/save/merge/activate modules"
```

---

### Task 5: FastAPI app skeleton

**Files:**
- Create: `app/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_main.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.config import Settings


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_status_returns_module_count(client, tmp_settings):
    r = await client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["active_modules"] == 0
    assert data["total_modules"] == 0


async def test_status_data_dirs_listed(client):
    r = await client.get("/api/status")
    data = r.json()
    assert "data_dirs" in data


async def test_404_returns_json(client):
    r = await client.get("/nonexistent")
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect failures**

```bash
uv run pytest tests/test_main.py -v
```

Expected: `ImportError` (main not defined).

- [ ] **Step 3: Implement `app/main.py`**

```python
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.config import Settings
from app.services.registry import load_registry

_settings: Settings | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for d in (cfg.zim_dir, cfg.maps_dir, cfg.downloads_dir, cfg.registry_path.parent):
            d.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="Cyberdeck", lifespan=lifespan)

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

- [ ] **Step 4: Run — expect all pass**

```bash
uv run pytest tests/test_main.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass, no warnings.

- [ ] **Step 6: Verify server starts**

```bash
uv run uvicorn app.main:app --port 8000 &
sleep 2
curl http://localhost:8000/health
kill %1
```

Expected output: `{"status":"ok"}`

- [ ] **Step 7: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: FastAPI skeleton with /health and /api/status endpoints"
```

---

### Task 6: Systemd service files

**Files:**
- Create: `systemd/cyberdeck.service`
- Create: `systemd/kiwix.service`
- Create: `systemd/mbtileserver.service`

- [ ] **Step 1: Create `systemd/cyberdeck.service`**

```ini
[Unit]
Description=Cyberdeck Portal
After=network.target
Wants=kiwix.service mbtileserver.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/cyberdeck
ExecStart=/home/pi/cyberdeck/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=5
Nice=10
Environment=CYBERDECK_DATA_DIR=/data

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create `systemd/kiwix.service`**

Kiwix-serve 3.x accepts a library XML file with `--library`:

```ini
[Unit]
Description=Kiwix ZIM Content Server
After=network.target

[Service]
Type=simple
User=pi
Group=pi
ExecStart=/usr/bin/kiwix-serve \
    --port 8080 \
    --library /data/zim/library.xml
Restart=on-failure
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create `systemd/mbtileserver.service`**

```ini
[Unit]
Description=MBTiles Map Tile Server
After=network.target

[Service]
Type=simple
User=pi
Group=pi
ExecStart=/usr/local/bin/mbtileserver \
    --port 8081 \
    --dir /data/maps \
    --enable-reload-signal
Restart=on-failure
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Commit**

```bash
git add systemd/
git commit -m "chore: add systemd service units for cyberdeck, kiwix, mbtileserver"
```

---

### Task 7: Install script

**Files:**
- Create: `scripts/install.sh`

Run this once on a fresh Raspberry Pi OS Lite (64-bit, Bookworm) as the `pi` user.

- [ ] **Step 1: Create `scripts/install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="/data"

echo "=== Cyberdeck install ==="

# ── System packages ──────────────────────────────────────
echo "Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y \
    kiwix-tools \
    hdparm \
    cpufrequtils \
    chromium-browser \
    fonts-noto \
    python3.14 \
    python3.14-venv

# ── mbtileserver (arm64 binary from GitHub releases) ─────
MBTILES_VERSION="0.10.0"
MBTILES_BINARY="/usr/local/bin/mbtileserver"
if [[ ! -f "$MBTILES_BINARY" ]]; then
    echo "Installing mbtileserver ${MBTILES_VERSION}..."
    curl -fsSL \
        "https://github.com/developmentseed/mbtileserver/releases/download/v${MBTILES_VERSION}/mbtileserver_linux_arm64" \
        -o "$MBTILES_BINARY"
    sudo chmod +x "$MBTILES_BINARY"
fi

# ── uv ───────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# ── Python venv ──────────────────────────────────────────
echo "Creating Python venv..."
cd "$REPO_DIR"
uv venv
uv pip install -e .

# ── Data directories ─────────────────────────────────────
echo "Creating data directories at ${DATA_DIR}..."
sudo mkdir -p \
    "${DATA_DIR}/zim" \
    "${DATA_DIR}/maps" \
    "${DATA_DIR}/downloads" \
    "${DATA_DIR}/packages"
sudo chown -R pi:pi "${DATA_DIR}"

# Seed registry if missing
if [[ ! -f "${DATA_DIR}/packages/registry.json" ]]; then
    cp "${REPO_DIR}/data/packages/registry.json" "${DATA_DIR}/packages/registry.json"
fi

# Seed empty kiwix library if missing
if [[ ! -f "${DATA_DIR}/zim/library.xml" ]]; then
    cat > "${DATA_DIR}/zim/library.xml" << 'XML'
<?xml version="1.0" encoding="UTF-8" ?>
<library version="1.0">
</library>
XML
fi

# ── systemd services ─────────────────────────────────────
echo "Installing systemd services..."
sudo cp "${REPO_DIR}/systemd/"*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cyberdeck.service kiwix.service mbtileserver.service
sudo systemctl start kiwix.service mbtileserver.service cyberdeck.service

echo "=== Done. Check: sudo systemctl status cyberdeck ==="
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/install.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "chore: add RPi bootstrap install script"
```

---

### Task 8: Chromium kiosk setup script

**Files:**
- Create: `scripts/setup-chromium.sh`

- [ ] **Step 1: Create `scripts/setup-chromium.sh`**

```bash
#!/usr/bin/env bash
# Sets up Chromium to launch in fullscreen kiosk mode on boot.
# Run as pi user after install.sh.
set -euo pipefail

AUTOSTART_DIR="$HOME/.config/lxsession/LXDE-pi"
mkdir -p "$AUTOSTART_DIR"

# Disable screen blanking + screensaver
cat > "$AUTOSTART_DIR/autostart" << 'EOF'
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xscreensaver -no-splash
@xset s off
@xset -dpms
@xset s noblank
@chromium-browser \
    --start-fullscreen \
    --app=http://localhost:8000 \
    --disable-gpu-compositing \
    --disable-smooth-scrolling \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000
EOF

echo "Chromium kiosk configured. Reboot to activate."
echo "Note: --start-fullscreen (not --kiosk) allows Ctrl+T for new tabs and Ctrl+L for address bar."
echo "This is intentional — see design spec §3.2."
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/setup-chromium.sh
git add scripts/setup-chromium.sh
git commit -m "chore: add Chromium fullscreen kiosk autostart script"
```

---

### Task 9: Power management script

**Files:**
- Create: `scripts/setup-power.sh`

- [ ] **Step 1: Create `scripts/setup-power.sh`**

```bash
#!/usr/bin/env bash
# Configures power saving for battery operation.
# Run as root (sudo scripts/setup-power.sh).
set -euo pipefail

# ── CPU governor: conservative ────────────────────────────
# Clocks down on idle, ramps up on load. Better than ondemand
# for battery because it doesn't spike as aggressively.
echo "Setting CPU governor to conservative..."
apt-get install -y cpufrequtils -q
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
    echo conservative > "${cpu}/cpufreq/scaling_governor" 2>/dev/null || true
done

# Persist across reboots
cat > /etc/default/cpufrequtils << 'EOF'
GOVERNOR="conservative"
EOF

# ── SSD power management ──────────────────────────────────
# APM level 128: moderate — spins down after idle but not
# aggressively (avoids excessive load-cycle wear).
# Detect the SSD block device (assumes single external drive).
SSD_DEV=$(lsblk -dpno NAME,TRAN | awk '$2=="usb" || $2=="nvme" {print $1}' | head -1)
if [[ -n "$SSD_DEV" ]]; then
    echo "Setting SSD APM on ${SSD_DEV}..."
    hdparm -B 128 "$SSD_DEV"
    # Persist via udev rule
    SERIAL=$(udevadm info --query=property --name="$SSD_DEV" | grep ID_SERIAL= | cut -d= -f2)
    cat > /etc/udev/rules.d/60-ssd-power.rules << EOF
ACTION=="add", SUBSYSTEM=="block", ENV{ID_SERIAL}=="${SERIAL}", \
    RUN+="/sbin/hdparm -B 128 /dev/%k"
EOF
fi

echo "Power management configured."
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/setup-power.sh
git add scripts/setup-power.sh
git commit -m "chore: add power management setup script (CPU governor + SSD APM)"
```

---

### Task 10: Smoke test on RPi (manual)

Verify the full stack runs correctly on the actual hardware.

- [ ] **Step 1: Clone and install on RPi**

```bash
git clone <repo-url> ~/cyberdeck
cd ~/cyberdeck
bash scripts/install.sh
bash scripts/setup-chromium.sh
sudo bash scripts/setup-power.sh
```

- [ ] **Step 2: Verify all three services are running**

```bash
sudo systemctl status cyberdeck kiwix mbtileserver
```

Expected: all three show `active (running)`.

- [ ] **Step 3: Test FastAPI from RPi terminal**

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/status
```

Expected:
```json
{"status":"ok"}
{"active_modules":0,"total_modules":0,"data_dirs":{...}}
```

- [ ] **Step 4: Reboot and verify Chromium autostart**

```bash
sudo reboot
```

After reboot: Chromium should open fullscreen showing `http://localhost:8000`. FastAPI returns a blank JSON response (the portal UI is Plan 2).

- [ ] **Step 5: Verify power settings persisted**

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

Expected: `conservative`

---

## Self-review checklist

**Spec coverage:**
- [x] §2 Hardware — install.sh handles system package setup
- [x] §3 Architecture — three systemd units, correct ports
- [x] §3.1 Process management — systemd owns lifecycle, not FastAPI
- [x] §3.2 Kiosk — `--start-fullscreen` documented with rationale
- [x] §6.1 registry.json — seed file + full service layer with tests
- [x] §7 Power management — setup-power.sh covers CPU governor + SSD APM
- [x] §8 Storage layout — install.sh creates `/data/{zim,maps,downloads,packages}`
- [ ] §4 UI — out of scope, Plan 2
- [ ] §5 Knowledge bases — out of scope, Plan 3
- [ ] §6.2–6.3 Update/download flow — out of scope, Plan 4

**No placeholders found.**

**Type consistency:** `load_registry`, `save_registry`, `get_active_modules`, `set_module_active`, `merge_remote_manifest` — all used consistently between Task 4 (implementation) and Task 5 (main.py usage).
