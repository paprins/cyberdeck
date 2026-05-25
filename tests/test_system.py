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
    assert "is_online" in data
    assert "connectivity" in data
    assert "updates_available" in data
    assert "uptime_s" in data
    assert "notifications" in data


async def test_system_endpoint_notifications_shape(client):
    r = await client.get("/api/system")
    n = r.json()["notifications"]
    for key in (
        "check_for_updates", "connectivity_check", "wifi_connected", "package_updates",
        "downloads", "services", "firmware_update_available",
        "upgrade_phase", "upgrade_target_version",
        "connectivity_check_auto_disabled_at", "connectivity_grace_minutes",
    ):
        assert key in n
    assert isinstance(n["package_updates"], list)
    assert isinstance(n["downloads"], dict)
    assert isinstance(n["services"], list)


async def test_check_for_updates_patch_persists(client, tmp_settings):
    from app.services.notifications import effective_check_for_updates
    assert effective_check_for_updates(tmp_settings) is True
    r = await client.post(
        "/api/settings/check-for-updates", json={"enabled": False},
    )
    assert r.status_code == 204
    assert effective_check_for_updates(tmp_settings) is False


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


# ── read_loadavg ──────────────────────────────────────────────────────────────

def test_read_loadavg_parses_first_two(tmp_path):
    p = tmp_path / "loadavg"
    p.write_text("0.42 0.35 0.28 1/123 4567\n")
    assert sys_svc.read_loadavg(_path=p) == (0.42, 0.35)


def test_read_loadavg_returns_none_when_missing(tmp_path):
    assert sys_svc.read_loadavg(_path=tmp_path / "nope") is None


def test_read_loadavg_returns_none_when_malformed(tmp_path):
    p = tmp_path / "loadavg"
    p.write_text("nonsense\n")
    assert sys_svc.read_loadavg(_path=p) is None


# ── read_meminfo ──────────────────────────────────────────────────────────────

def test_read_meminfo_parses_total_and_available(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("MemTotal:        7945000 kB\nMemFree:         123 kB\nMemAvailable:    6500000 kB\n")
    assert sys_svc.read_meminfo(_path=p) == (7945000, 6500000)


def test_read_meminfo_returns_none_when_missing(tmp_path):
    assert sys_svc.read_meminfo(_path=tmp_path / "nope") is None


def test_read_meminfo_returns_none_when_keys_absent(tmp_path):
    p = tmp_path / "meminfo"
    p.write_text("SomethingElse: 1 kB\n")
    assert sys_svc.read_meminfo(_path=p) is None


# ── read_temp_c ───────────────────────────────────────────────────────────────

def test_read_temp_c_converts_millidegrees(tmp_path):
    zone = tmp_path / "thermal_zone0"
    zone.mkdir()
    (zone / "temp").write_text("45123\n")
    assert sys_svc.read_temp_c(_root=tmp_path) == 45.123


def test_read_temp_c_returns_none_when_no_zone(tmp_path):
    assert sys_svc.read_temp_c(_root=tmp_path) is None


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


# ── Power: service ────────────────────────────────────────────────────────────

async def test_restart_services_invokes_both_units(monkeypatch):
    calls: list[tuple[str, ...]] = []

    async def fake(*args, timeout=30.0):
        calls.append(args)

    monkeypatch.setattr(sys_svc, "_systemctl", fake)
    await sys_svc.restart_services()
    assert calls == [("restart", "kiwix.service"), ("restart", "mbtileserver.service")]


async def test_reboot_uses_no_block(monkeypatch):
    calls: list[tuple[str, ...]] = []

    async def fake(*args, timeout=30.0):
        calls.append(args)

    monkeypatch.setattr(sys_svc, "_systemctl", fake)
    await sys_svc.reboot()
    assert calls == [("--no-block", "reboot")]


async def test_poweroff_uses_no_block(monkeypatch):
    calls: list[tuple[str, ...]] = []

    async def fake(*args, timeout=30.0):
        calls.append(args)

    monkeypatch.setattr(sys_svc, "_systemctl", fake)
    await sys_svc.poweroff()
    assert calls == [("--no-block", "poweroff")]


async def test_systemctl_raises_unsupported_when_sudo_missing(monkeypatch):
    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError("sudo")

    monkeypatch.setattr(sys_svc.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(sys_svc.SystemCommandError) as exc_info:
        await sys_svc._systemctl("restart", "kiwix.service")
    assert exc_info.value.unsupported is True


async def test_systemctl_marks_password_error_as_unsupported(monkeypatch):
    class FakeProc:
        returncode = 1

        async def communicate(self):
            return b"", b"sudo: a password is required"

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(sys_svc.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(sys_svc.SystemCommandError) as exc_info:
        await sys_svc._systemctl("restart", "kiwix.service")
    assert exc_info.value.unsupported is True


async def test_systemctl_other_failure_is_general_error(monkeypatch):
    class FakeProc:
        returncode = 5

        async def communicate(self):
            return b"", b"Failed to restart kiwix.service: Unit not found."

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(sys_svc.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(sys_svc.SystemCommandError) as exc_info:
        await sys_svc._systemctl("restart", "kiwix.service")
    assert exc_info.value.unsupported is False
    assert "Unit not found" in str(exc_info.value)


# ── Power: HTTP endpoints ─────────────────────────────────────────────────────

async def test_post_restart_services_returns_204(client, monkeypatch):
    async def ok(): return None
    monkeypatch.setattr(sys_svc, "restart_services", ok)
    r = await client.post("/api/system/restart-services")
    assert r.status_code == 204


async def test_post_reboot_returns_202(client, monkeypatch):
    async def ok(): return None
    monkeypatch.setattr(sys_svc, "reboot", ok)
    r = await client.post("/api/system/reboot")
    assert r.status_code == 202


async def test_post_shutdown_returns_202(client, monkeypatch):
    async def ok(): return None
    monkeypatch.setattr(sys_svc, "poweroff", ok)
    r = await client.post("/api/system/shutdown")
    assert r.status_code == 202


async def test_post_reboot_returns_503_when_unsupported(client, monkeypatch):
    async def boom():
        raise sys_svc.SystemCommandError("sudo not available", unsupported=True)
    monkeypatch.setattr(sys_svc, "reboot", boom)
    r = await client.post("/api/system/reboot")
    assert r.status_code == 503
    assert "sudo" in r.json()["detail"]


async def test_post_restart_services_returns_500_on_error(client, monkeypatch):
    async def boom():
        raise sys_svc.SystemCommandError("Unit not found.")
    monkeypatch.setattr(sys_svc, "restart_services", boom)
    r = await client.post("/api/system/restart-services")
    assert r.status_code == 500
    assert "Unit not found" in r.json()["detail"]
