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
