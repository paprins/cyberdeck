from __future__ import annotations
import pytest

from app.models.registry import Module, Registry
from app.services import notifications as notif
from app.services.registry import save_registry


@pytest.fixture(autouse=True)
def _reset_caches():
    """Module-level caches leak between tests; reset before each."""
    notif._firmware_cache.available_version = None
    notif._firmware_cache.checked_at = None
    notif._firmware_cache.in_flight = False
    notif._services_cache.services = []
    yield


# ── preferences overlay ───────────────────────────────────────────────────────

def test_effective_check_for_updates_defaults_to_settings_value(tmp_settings):
    assert notif.effective_check_for_updates(tmp_settings) is True


def test_effective_check_for_updates_uses_preferences_override(tmp_settings):
    notif.save_preference(tmp_settings, "check_for_updates", False)
    assert notif.effective_check_for_updates(tmp_settings) is False


def test_save_preference_writes_json_atomically(tmp_settings):
    notif.save_preference(tmp_settings, "check_for_updates", False)
    assert tmp_settings.preferences_path.exists()
    notif.save_preference(tmp_settings, "another_key", 42)
    prefs = notif.load_preferences(tmp_settings)
    assert prefs == {"check_for_updates": False, "another_key": 42}


# ── snapshot ──────────────────────────────────────────────────────────────────

def _registry_with(*modules: Module) -> Registry:
    return Registry( modules=list(modules))


def test_snapshot_no_modules(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.package_updates == []
    assert snap.downloads == {}
    assert snap.firmware_update_available is None
    assert snap.services == []
    assert snap.upgrade_phase == "idle"


def test_snapshot_lists_package_updates(tmp_settings):
    save_registry(tmp_settings, _registry_with(
        Module(
            id="medical-wikimed", display_name="Medical", category="medical",
            description="WikiMed", latest_version="2024-02", size_gb=0.8,
            checksum="sha256:new",
            installed_version="2024-01", installed_checksum="sha256:old",
            active=True,
        ),
        Module(
            id="maps-eu", display_name="Maps EU", category="maps",
            description="Maps", latest_version="2024-01", size_gb=5,
            checksum="sha256:abc",
            installed_version="2024-01", installed_checksum="sha256:abc",
            active=True,
        ),
    ))
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert len(snap.package_updates) == 1
    assert snap.package_updates[0]["id"] == "medical-wikimed"
    assert snap.package_updates[0]["latest_version"] == "2024-02"


def test_snapshot_firmware_gated_off_when_offline(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    notif._firmware_cache.available_version = "1.2.3"
    snap = notif.build_snapshot(tmp_settings, wifi_connected=False)
    assert snap.firmware_update_available is None


def test_snapshot_firmware_gated_off_when_disabled(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    notif.save_preference(tmp_settings, "check_for_updates", False)
    notif._firmware_cache.available_version = "1.2.3"
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.firmware_update_available is None


def test_snapshot_firmware_visible_when_eligible(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    notif._firmware_cache.available_version = "1.2.3"
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.firmware_update_available == "1.2.3"


def test_snapshot_services_from_cache(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    notif._services_cache.services = [
        {"name": "kiwix", "state": "ok"},
        {"name": "mbtileserver", "state": "down"},
    ]
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.services == [
        {"name": "kiwix", "state": "ok"},
        {"name": "mbtileserver", "state": "down"},
    ]


def test_snapshot_check_for_updates_flag_propagates(tmp_settings):
    save_registry(tmp_settings, _registry_with())
    snap = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap.check_for_updates is True
    notif.save_preference(tmp_settings, "check_for_updates", False)
    snap2 = notif.build_snapshot(tmp_settings, wifi_connected=True)
    assert snap2.check_for_updates is False


# ── firmware refresh scheduling ───────────────────────────────────────────────

def test_schedule_skipped_when_offline(tmp_settings, monkeypatch):
    called = False
    async def fake(_cfg):
        nonlocal called
        called = True
    monkeypatch.setattr(notif, "maybe_refresh_firmware", fake)
    notif.schedule_firmware_refresh_if_eligible(tmp_settings, wifi_connected=False)
    assert called is False


def test_schedule_skipped_when_disabled(tmp_settings, monkeypatch):
    notif.save_preference(tmp_settings, "check_for_updates", False)
    called = False
    async def fake(_cfg):
        nonlocal called
        called = True
    monkeypatch.setattr(notif, "maybe_refresh_firmware", fake)
    notif.schedule_firmware_refresh_if_eligible(tmp_settings, wifi_connected=True)
    assert called is False


async def test_schedule_creates_task_when_eligible(tmp_settings, monkeypatch):
    notif._firmware_cache.checked_at = None  # stale
    fired = []
    async def fake(cfg):
        fired.append(cfg)
    monkeypatch.setattr(notif, "maybe_refresh_firmware", fake)
    notif.schedule_firmware_refresh_if_eligible(tmp_settings, wifi_connected=True)
    # Give the task one event-loop tick to run.
    import asyncio
    await asyncio.sleep(0)
    assert fired == [tmp_settings]
