from __future__ import annotations
import json
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from app.main import create_app
import app.services.upgrade as upgrade_svc
from app.config import Settings
from app.models.upgrade import (
    InstallRequest,
    Release,
    UpgradeAlreadyRunningError,
    UpgradeChannel,
    UpgradeDowngradeError,
    UpgradeNetworkError,
    UpgradeStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def cfg(tmp_path):
    s = Settings(data_dir=tmp_path / "data", install_root=tmp_path / "install")
    s.install_root.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
def app(tmp_settings, monkeypatch, tmp_path):
    install_root = tmp_path / "install"
    install_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(tmp_settings, "install_root", install_root, raising=False)
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c




# ── _parse_version ────────────────────────────────────────────────────────────


def test_parse_version_strips_v():
    assert upgrade_svc._parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_handles_plain():
    assert upgrade_svc._parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_sorts_correctly():
    versions = ["v1.10.0", "v1.2.0", "v1.2.9", "v2.0.0"]
    assert sorted(versions, key=upgrade_svc._parse_version) == ["v1.2.0", "v1.2.9", "v1.10.0", "v2.0.0"]


# ── current_version / list_installed_versions ─────────────────────────────────


def test_current_version_returns_none_without_symlink(cfg):
    assert upgrade_svc.current_version(cfg) is None


def test_current_version_resolves_symlink(cfg):
    target = cfg.install_root / "v1.2.3"
    target.mkdir()
    (cfg.install_root / "current").symlink_to(target)
    assert upgrade_svc.current_version(cfg) == "1.2.3"


def test_list_installed_versions_sorted_desc(cfg):
    (cfg.install_root / "v1.0.0").mkdir()
    (cfg.install_root / "v1.2.0").mkdir()
    (cfg.install_root / "v1.10.0").mkdir()
    (cfg.install_root / "not-a-version").mkdir()
    assert upgrade_svc.list_installed_versions(cfg) == ["1.10.0", "1.2.0", "1.0.0"]


# ── State read/write ──────────────────────────────────────────────────────────


def test_read_status_returns_idle_when_no_file(cfg):
    s = upgrade_svc.read_status(cfg)
    assert s.phase == "idle"


def test_write_then_read_status_roundtrips(cfg):
    upgrade_svc._write_status(cfg, UpgradeStatus(phase="downloading", target_version="1.2.3"))
    s = upgrade_svc.read_status(cfg)
    assert s.phase == "downloading"
    assert s.target_version == "1.2.3"


def test_read_status_returns_idle_on_bad_file(cfg):
    cfg.upgrade_dir.mkdir(parents=True, exist_ok=True)
    cfg.upgrade_state_path.write_text("not json")
    s = upgrade_svc.read_status(cfg)
    assert s.phase == "idle"


# ── _file_uri_to_path ─────────────────────────────────────────────────────────


def test_file_uri_decodes_spaces():
    p = Path("/media/My Drive/cyberdeck-v1.0.0.tar.gz")
    assert upgrade_svc._file_uri_to_path(p.as_uri()) == p


def test_file_uri_decodes_unicode():
    p = Path("/media/Café/file.tar.gz")
    assert upgrade_svc._file_uri_to_path(p.as_uri()) == p


# ── scan_usb ──────────────────────────────────────────────────────────────────


def test_scan_usb_finds_tarball_and_sig(cfg, monkeypatch, tmp_path):
    fake_mount = tmp_path / "usb0"
    fake_mount.mkdir()
    tar = fake_mount / "cyberdeck-v2.0.0.tar.gz"
    sig = fake_mount / "cyberdeck-v2.0.0.tar.gz.minisig"
    tar.write_bytes(b"fake")
    sig.write_bytes(b"sig")
    monkeypatch.setattr(upgrade_svc, "_USB_ROOTS", (tmp_path,))
    releases = upgrade_svc.scan_usb(cfg)
    assert len(releases) == 1
    assert releases[0].version == "2.0.0"
    assert releases[0].channel == UpgradeChannel.OFFLINE


def test_scan_usb_skips_when_sig_missing(cfg, monkeypatch, tmp_path):
    fake_mount = tmp_path / "usb0"
    fake_mount.mkdir()
    (fake_mount / "cyberdeck-v2.0.0.tar.gz").write_bytes(b"fake")
    monkeypatch.setattr(upgrade_svc, "_USB_ROOTS", (tmp_path,))
    assert upgrade_svc.scan_usb(cfg) == []


def test_scan_usb_filters_older_than_current(cfg, monkeypatch, tmp_path):
    target = cfg.install_root / "v3.0.0"
    target.mkdir()
    (cfg.install_root / "current").symlink_to(target)

    fake_mount = tmp_path / "usb0"
    fake_mount.mkdir()
    (fake_mount / "cyberdeck-v2.0.0.tar.gz").write_bytes(b"x")
    (fake_mount / "cyberdeck-v2.0.0.tar.gz.minisig").write_bytes(b"x")
    monkeypatch.setattr(upgrade_svc, "_USB_ROOTS", (tmp_path,))
    assert upgrade_svc.scan_usb(cfg) == []


# ── check_online ──────────────────────────────────────────────────────────────


async def test_check_online_returns_empty_without_repo(cfg):
    cfg.github_repo = ""
    assert await upgrade_svc.check_online(cfg) == []


async def test_check_online_raises_on_network_error(cfg, monkeypatch):
    cfg.github_repo = "x/y"

    class _BoomClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            import httpx
            raise httpx.RequestError("boom")

    monkeypatch.setattr("app.services.upgrade.httpx.AsyncClient", _BoomClient)
    with pytest.raises(UpgradeNetworkError):
        await upgrade_svc.check_online(cfg)


# ── start_upgrade ─────────────────────────────────────────────────────────────


async def test_start_upgrade_blocks_when_active(cfg):
    upgrade_svc._write_status(cfg, UpgradeStatus(phase="downloading"))
    with pytest.raises(UpgradeAlreadyRunningError):
        await upgrade_svc.start_upgrade(cfg, InstallRequest(
            version="2.0.0", channel=UpgradeChannel.ONLINE,
            tarball_url="http://x", signature_url="http://y",
        ))


async def test_start_upgrade_blocks_when_package_download_active(cfg, monkeypatch):
    from app.services import packages as pkg_svc
    monkeypatch.setitem(pkg_svc._active_tasks, "fake", "task")  # type: ignore
    try:
        with pytest.raises(UpgradeAlreadyRunningError):
            await upgrade_svc.start_upgrade(cfg, InstallRequest(
                version="2.0.0", channel=UpgradeChannel.ONLINE,
                tarball_url="http://x", signature_url="http://y",
            ))
    finally:
        pkg_svc._active_tasks.pop("fake", None)


async def test_start_upgrade_marks_failed_when_spawn_fails(cfg, monkeypatch):
    # Simulate a non-executable upgrade.sh — Popen raises PermissionError.
    current = cfg.install_root / "v0.0.4"
    current.mkdir()
    (current / "scripts").mkdir()
    (current / "scripts" / "upgrade.sh").write_text("#!/bin/sh\n")  # not chmod +x
    (cfg.install_root / "current").symlink_to(current)

    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(current / "scripts" / "upgrade.sh"))
    monkeypatch.setattr(upgrade_svc, "_popen", boom)

    # Stub the download so we exercise only the spawn path.
    async def fake_dl(*a, **k): return None
    monkeypatch.setattr(upgrade_svc, "_download", fake_dl)

    from app.models.upgrade import UpgradeError
    with pytest.raises(UpgradeError):
        await upgrade_svc.start_upgrade(cfg, InstallRequest(
            version="0.0.5", channel=UpgradeChannel.ONLINE,
            tarball_url="http://x/t.tar.gz", signature_url="http://x/t.tar.gz.minisig",
        ))

    # State must be 'failed', not stuck on 'downloading' — otherwise retries are blocked.
    status = upgrade_svc.read_status(cfg)
    assert status.phase == "failed"
    assert "spawn_failed" in (status.message or "")


async def test_start_upgrade_blocks_downgrade(cfg):
    target = cfg.install_root / "v3.0.0"
    target.mkdir()
    (cfg.install_root / "current").symlink_to(target)
    with pytest.raises(UpgradeDowngradeError):
        await upgrade_svc.start_upgrade(cfg, InstallRequest(
            version="2.0.0", channel=UpgradeChannel.ONLINE,
            tarball_url="http://x", signature_url="http://y",
        ))


# ── cancel ────────────────────────────────────────────────────────────────────


def test_cancel_resets_failed_state(cfg):
    upgrade_svc._write_status(cfg, UpgradeStatus(phase="failed", message="boom"))
    upgrade_svc.cancel(cfg)
    assert upgrade_svc.read_status(cfg).phase == "idle"


def test_cancel_raises_on_active_phase(cfg):
    upgrade_svc._write_status(cfg, UpgradeStatus(phase="downloading"))
    with pytest.raises(UpgradeAlreadyRunningError):
        upgrade_svc.cancel(cfg)


# ── cleanup_old_versions ──────────────────────────────────────────────────────


def test_cleanup_removes_oldest_keeps_n(cfg):
    for v in ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"]:
        (cfg.install_root / f"v{v}").mkdir()
    target = cfg.install_root / "v1.4.0"
    (cfg.install_root / "current").symlink_to(target)
    removed = upgrade_svc.cleanup_old_versions(cfg, keep=2)
    # keep=2 + active = 3 total kept; 5 - 3 = 2 removed
    assert set(removed) == {"1.0.0", "1.1.0"}
    assert (cfg.install_root / "v1.4.0").exists()
    assert (cfg.install_root / "v1.3.0").exists()
    assert (cfg.install_root / "v1.2.0").exists()
    assert not (cfg.install_root / "v1.0.0").exists()


def test_cleanup_never_removes_active(cfg):
    (cfg.install_root / "v1.0.0").mkdir()
    (cfg.install_root / "v2.0.0").mkdir()
    target = cfg.install_root / "v1.0.0"
    (cfg.install_root / "current").symlink_to(target)
    removed = upgrade_svc.cleanup_old_versions(cfg, keep=1)
    # active 1.0.0 is kept; keep=1 means v2.0.0 also; nothing removed
    assert removed == []
    assert (cfg.install_root / "v1.0.0").exists()
    assert (cfg.install_root / "v2.0.0").exists()


# ── Router endpoints ──────────────────────────────────────────────────────────


async def test_get_status_returns_200(client):
    r = await client.get("/api/upgrade/status")
    assert r.status_code == 200
    assert r.json()["phase"] == "idle"


async def test_check_returns_200_with_releases(client, monkeypatch):
    async def fake_check(cfg):
        return {
            "current_version": "1.0.0",
            "releases": [Release(version="1.2.0", channel=UpgradeChannel.ONLINE,
                                 tarball_url="http://x", signature_url="http://y")],
            "online_error": None,
        }
    monkeypatch.setattr(upgrade_svc, "check_for_updates", fake_check)
    r = await client.post("/api/upgrade/check")
    assert r.status_code == 200
    body = r.json()
    assert body["current_version"] == "1.0.0"
    assert len(body["releases"]) == 1


async def test_install_returns_202(client, monkeypatch):
    async def fake_start(cfg, req): return None
    monkeypatch.setattr(upgrade_svc, "start_upgrade", fake_start)
    r = await client.post("/api/upgrade/install", json={
        "version": "2.0.0", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 202


async def test_install_returns_409_when_active(client, monkeypatch):
    async def fake_start(cfg, req):
        raise UpgradeAlreadyRunningError("busy")
    monkeypatch.setattr(upgrade_svc, "start_upgrade", fake_start)
    r = await client.post("/api/upgrade/install", json={
        "version": "2.0.0", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 409


async def test_install_returns_409_on_downgrade(client, monkeypatch):
    async def fake_start(cfg, req):
        raise UpgradeDowngradeError("older")
    monkeypatch.setattr(upgrade_svc, "start_upgrade", fake_start)
    r = await client.post("/api/upgrade/install", json={
        "version": "0.0.1", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 409


async def test_install_returns_502_on_network_error(client, monkeypatch):
    async def fake_start(cfg, req):
        raise UpgradeNetworkError("no internet")
    monkeypatch.setattr(upgrade_svc, "start_upgrade", fake_start)
    r = await client.post("/api/upgrade/install", json={
        "version": "2.0.0", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 502


async def test_install_rejects_missing_fields(client):
    r = await client.post("/api/upgrade/install", json={"version": "2.0.0"})
    assert r.status_code == 422


async def test_install_rejects_malformed_version(client):
    r = await client.post("/api/upgrade/install", json={
        "version": "../../etc/passwd", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 422


async def test_install_rejects_version_with_letters(client):
    r = await client.post("/api/upgrade/install", json={
        "version": "1.2.3-beta", "channel": "online",
        "tarball_url": "http://x", "signature_url": "http://y",
    })
    assert r.status_code == 422


async def test_cancel_returns_204(client, monkeypatch):
    def fake_cancel(cfg): return None
    monkeypatch.setattr(upgrade_svc, "cancel", fake_cancel)
    r = await client.post("/api/upgrade/cancel")
    assert r.status_code == 204


async def test_cancel_returns_409_when_active(client, monkeypatch):
    def fake_cancel(cfg):
        raise UpgradeAlreadyRunningError("nope")
    monkeypatch.setattr(upgrade_svc, "cancel", fake_cancel)
    r = await client.post("/api/upgrade/cancel")
    assert r.status_code == 409


# ── /health endpoint extension ────────────────────────────────────────────────


async def test_health_includes_version(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
