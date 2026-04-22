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
