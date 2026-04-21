from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from app.config import Settings
from app.services.registry import load_registry


@dataclass
class SystemStatus:
    battery_pct: int | None
    battery_charging: bool
    wifi_connected: bool
    updates_available: int
    uptime_s: int | None


def read_system_status(settings: Settings) -> SystemStatus:
    return SystemStatus(
        battery_pct=_battery_pct(),
        battery_charging=_battery_charging(),
        wifi_connected=_wifi_connected(),
        updates_available=_updates_available(settings),
        uptime_s=_uptime_s(),
    )


def _battery_pct() -> int | None:
    for path in Path("/sys/class/power_supply").glob("*/capacity"):
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            pass
    return None


def _battery_charging() -> bool:
    for path in Path("/sys/class/power_supply").glob("*/status"):
        try:
            return path.read_text().strip().lower() == "charging"
        except OSError:
            pass
    return False


def _wifi_connected() -> bool:
    try:
        content = Path("/proc/net/wireless").read_text()
        data_lines = [l for l in content.splitlines()[2:] if l.strip()]
        return len(data_lines) > 0
    except OSError:
        return False


def _updates_available(settings: Settings) -> int:
    try:
        registry = load_registry(settings)
        return len([m for m in registry.modules if m.has_update])
    except Exception:
        return 0


def _uptime_s() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None
