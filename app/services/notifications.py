from __future__ import annotations
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import Settings
from app.services.diagnostics import _probe
from app.services.packages import _active_tasks, _pending, _mismatch_path
from app.services.registry import load_registry
from app.services.upgrade import check_online, read_status

log = logging.getLogger(__name__)


_FIRMWARE_TTL_S = 3600.0
_SERVICES_PROBE_INTERVAL_S = 30.0


# ── In-memory caches (single event loop, no lock needed) ──────────────────────

@dataclass
class _FirmwareCache:
    available_version: str | None = None
    checked_at: float | None = None
    in_flight: bool = False


@dataclass
class _ServicesCache:
    services: list[dict] = field(default_factory=list)


_firmware_cache = _FirmwareCache()
_services_cache = _ServicesCache()


# ── Preferences (runtime overrides for env-default Settings) ──────────────────

def load_preferences(cfg: Settings) -> dict:
    """Read the JSON preferences sidecar. Returns {} if absent or unreadable."""
    try:
        return json.loads(cfg.preferences_path.read_text())
    except (OSError, ValueError):
        return {}


def save_preference(cfg: Settings, key: str, value: object) -> None:
    """Merge a single key into the preferences sidecar atomically."""
    prefs = load_preferences(cfg)
    prefs[key] = value
    cfg.preferences_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg.preferences_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(prefs))
    tmp.replace(cfg.preferences_path)


def effective_check_for_updates(cfg: Settings) -> bool:
    """Preference overlay on top of the env-backed default."""
    prefs = load_preferences(cfg)
    if "check_for_updates" in prefs:
        return bool(prefs["check_for_updates"])
    return cfg.check_for_updates


# ── Snapshot ──────────────────────────────────────────────────────────────────

Severity = Literal["info", "success", "warning", "error"]


@dataclass
class NotificationsSnapshot:
    check_for_updates: bool
    wifi_connected: bool
    package_updates: list[dict]  # [{id, display_name, latest_version}]
    downloads: dict[str, dict]   # id -> {status, pct, display_name}
    services: list[dict]         # [{name, state}]
    firmware_update_available: str | None  # version or None
    upgrade_phase: str
    upgrade_target_version: str | None


def _build_downloads_map(cfg: Settings) -> dict[str, dict]:
    """Snapshot any module that has user-visible download state.

    Drives both the "download complete/failed" toasts and cross-page progress.
    Restricted to in-flight, queued, or terminal-after-failure states — installed
    modules are NOT included (they would fire a spurious success toast on every
    page load). The watcher uses transitions, not absolute state.
    """
    registry = load_registry(cfg)
    out: dict[str, dict] = {}
    for m in registry.modules:
        status = None
        if m.id in _active_tasks:
            status = "downloading"
        elif m.id in _pending:
            status = "queued"
        elif _mismatch_path(m, cfg).exists():
            status = "checksum_mismatch"
        if status:
            out[m.id] = {"status": status, "display_name": m.display_name}
    return out


def build_snapshot(cfg: Settings, wifi_connected: bool) -> NotificationsSnapshot:
    """Assemble the toast-relevant view of system state.

    Pure in-memory reads only — no HTTP, no subprocesses, no slow I/O. Safe to
    call on every /api/system poll without latency cost. Service health is read
    from _services_cache (refreshed by services_probe_loop, not here).
    """
    cfu = effective_check_for_updates(cfg)
    upgrade = read_status(cfg)

    if cfu and wifi_connected:
        firmware_version = _firmware_cache.available_version
    else:
        firmware_version = None

    registry = load_registry(cfg)
    package_updates = [
        {
            "id": m.id,
            "display_name": m.display_name,
            "latest_version": m.latest_version,
        }
        for m in registry.modules
        if m.has_update
    ]

    return NotificationsSnapshot(
        check_for_updates=cfu,
        wifi_connected=wifi_connected,
        package_updates=package_updates,
        downloads=_build_downloads_map(cfg),
        services=list(_services_cache.services),
        firmware_update_available=firmware_version,
        upgrade_phase=upgrade.phase,
        upgrade_target_version=upgrade.target_version,
    )


# ── Opportunistic firmware refresh ────────────────────────────────────────────

def _firmware_cache_is_stale() -> bool:
    if _firmware_cache.checked_at is None:
        return True
    return (time.monotonic() - _firmware_cache.checked_at) > _FIRMWARE_TTL_S


async def maybe_refresh_firmware(cfg: Settings) -> None:
    """Fetch latest release tag and update the cache.

    Fire-and-forget: scheduled via asyncio.create_task from request handlers.
    Self-gates on in-flight to avoid concurrent refreshes; the handler should
    pre-check effective_check_for_updates and wifi state to avoid even
    scheduling this when ineligible.
    """
    if _firmware_cache.in_flight:
        return
    _firmware_cache.in_flight = True
    try:
        releases = await check_online(cfg)
        _firmware_cache.available_version = releases[0].version if releases else None
        _firmware_cache.checked_at = time.monotonic()
    except Exception:
        log.exception("firmware update check failed")
        _firmware_cache.checked_at = time.monotonic()
    finally:
        _firmware_cache.in_flight = False


def schedule_firmware_refresh_if_eligible(cfg: Settings, wifi_connected: bool) -> None:
    """Hook called by /api/system handler. Schedules a background refresh only
    when the cache is stale AND online AND the user opted in."""
    if not wifi_connected:
        return
    if not effective_check_for_updates(cfg):
        return
    if not _firmware_cache_is_stale():
        return
    asyncio.create_task(maybe_refresh_firmware(cfg))


# ── Services probe loop (lifespan task) ───────────────────────────────────────

async def services_probe_loop(cfg: Settings) -> None:
    """Refresh _services_cache every 30s. Cancelled cleanly on shutdown."""
    while True:
        try:
            async with httpx.AsyncClient() as client:
                kiwix, mbtiles = await asyncio.gather(
                    _probe("kiwix", cfg.kiwix_port, client),
                    _probe("mbtileserver", cfg.mbtiles_port, client),
                )
            _services_cache.services = [
                {"name": kiwix.name, "state": kiwix.state},
                {"name": mbtiles.name, "state": mbtiles.state},
            ]
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("services probe failed")
        await asyncio.sleep(_SERVICES_PROBE_INTERVAL_S)
