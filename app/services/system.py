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
    supply_dir = Path("/sys/class/power_supply")
    if not supply_dir.exists():
        return False
    paths = sorted(supply_dir.glob("*/status"), key=lambda p: (not p.parent.name.startswith("BAT"), p))
    for path in paths:
        try:
            return path.read_text().strip().lower() == "charging"
        except OSError:
            pass
    return False


def _wifi_connected() -> bool:
    net_dir = Path("/sys/class/net")
    if not net_dir.exists():
        return False
    for iface_dir in net_dir.iterdir():
        name = iface_dir.name
        if not (name.startswith("wlan") or name.startswith("wlp")):
            continue
        try:
            state = (iface_dir / "operstate").read_text().strip()
            if state == "up":
                return True
        except OSError:
            pass
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


_BACKLIGHT_ROOT = Path("/sys/class/backlight")


def read_brightness(_root: Path = _BACKLIGHT_ROOT) -> int | None:
    for brightness_path in _root.glob("*/brightness"):
        try:
            raw = int(brightness_path.read_text().strip())
            max_raw = int((brightness_path.parent / "max_brightness").read_text().strip())
            if max_raw == 0:
                return None
            return min(100, round(raw * 100 / max_raw))
        except (OSError, ValueError):
            pass
    return None


def write_brightness(pct: int, _root: Path = _BACKLIGHT_ROOT) -> None:
    pct = max(0, min(100, pct))
    for max_path in _root.glob("*/max_brightness"):
        try:
            max_raw = int(max_path.read_text().strip())
            raw = round(pct * max_raw / 100)
            (max_path.parent / "brightness").write_text(str(raw))
            return
        except OSError:
            pass
