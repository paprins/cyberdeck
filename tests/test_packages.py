from __future__ import annotations
import asyncio
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
import httpx

from app.config import Settings
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import load_registry, save_registry
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


def test_get_download_status_checksum_mismatch(tmp_settings):
    m = _mod(checksum="sha256:expected")
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 1000)
    mismatch.write_text("sha256:actual")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "checksum_mismatch"
    assert result["actual_checksum"] == "sha256:actual"
    assert result["expected_checksum"] == "sha256:expected"
    assert result["pct"] == 100


def test_get_download_status_interrupted_without_mismatch_file(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    # No .mismatch file — should still be interrupted, not checksum_mismatch
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "interrupted"


# ── get_storage_info ──────────────────────────────────────────────────────────

def test_get_storage_info_returns_used_and_free(tmp_settings):
    result = pkg_service.get_storage_info(tmp_settings)
    assert "used_bytes" in result
    assert "free_bytes" in result
    assert result["used_bytes"] > 0
    assert result["free_bytes"] > 0


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


async def test_accept_checksum_mismatch_installs_file(tmp_settings, monkeypatch):
    m = _mod(checksum="sha256:expected")
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"file content")
    mismatch_file.write_text("sha256:actual")
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.accept_checksum_mismatch(m, tmp_settings)

    final = tmp_settings.zim_dir / "medical-wikimed.zim"
    assert final.exists(), "file must be moved to final path"
    assert not part.exists(), ".part must be gone"
    assert not mismatch_file.exists(), ".mismatch must be gone"
    reg = load_registry(tmp_settings)
    mod = reg.modules[0]
    assert mod.installed_checksum == "sha256:actual"
    assert mod.installed_version == "2024-10"
    assert mod.active is True


async def test_accept_checksum_mismatch_raises_if_no_mismatch_pending(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    with pytest.raises(RuntimeError):
        await pkg_service.accept_checksum_mismatch(m, tmp_settings)


async def test_discard_checksum_mismatch_deletes_files(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actual")

    await pkg_service.discard_checksum_mismatch(m, tmp_settings)

    assert not part.exists()
    assert not mismatch_file.exists()


async def test_uninstall_clears_mismatch_file(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actual")

    await pkg_service.uninstall_module(m, tmp_settings)

    assert not part.exists()
    assert not mismatch_file.exists()


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


async def test_download_writes_mismatch_file_on_checksum_failure(tmp_settings, monkeypatch):
    m = _mod(checksum="sha256:expectedbutnotthis")
    _seed(tmp_settings, [m])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    fake_bytes = b"fake file content"

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url, headers=None, timeout=None):
            return _Stream()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.start_download(m, tmp_settings)
    task = pkg_service._active_tasks["medical-wikimed"]
    await task

    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    assert part.exists(), ".part file must be kept on mismatch"
    assert mismatch.exists(), ".mismatch file must be written"
    import hashlib
    expected_digest = "sha256:" + hashlib.sha256(fake_bytes).hexdigest()
    assert mismatch.read_text().strip() == expected_digest


async def test_download_does_not_write_mismatch_on_correct_checksum(tmp_settings, monkeypatch):
    fake_bytes = b"correct content"
    import hashlib
    correct_checksum = "sha256:" + hashlib.sha256(fake_bytes).hexdigest()
    m = _mod(checksum=correct_checksum)
    _seed(tmp_settings, [m])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url, headers=None, timeout=None):
            return _Stream()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.start_download(m, tmp_settings)
    task = pkg_service._active_tasks.get("medical-wikimed")
    if task:
        await task

    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    assert not mismatch.exists(), ".mismatch must not exist on successful download"


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
    assert "UPDATES_AVAILABLE" in r.text


# ── POST /api/packages/check-updates ─────────────────────────────────────────

async def test_check_updates_returns_502_on_network_error(client, tmp_settings, monkeypatch):
    _seed(tmp_settings)
    import app.routers.packages as pkg_router

    async def _fail(settings):
        raise httpx.RequestError("down")

    monkeypatch.setattr(pkg_router, "check_for_updates", _fail)
    r = await client.post("/api/packages/check-updates")
    assert r.status_code == 502


# ── GET /api/packages/active-download ────────────────────────────────────────

async def test_active_download_returns_null_when_idle(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/api/packages/active-download")
    assert r.status_code == 200
    assert r.json()["module_id"] is None


async def test_active_download_returns_module_id_when_active(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["medical-wikimed"] = object()
    r = await client.get("/api/packages/active-download")
    assert r.status_code == 200
    assert r.json()["module_id"] == "medical-wikimed"


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
