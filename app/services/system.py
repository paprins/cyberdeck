from __future__ import annotations
import asyncio
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
        uptime_s=read_uptime_s(),
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


def read_uptime_s() -> int | None:
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


_BACKLIGHT_ROOT = Path("/sys/class/backlight")
_LOADAVG_PATH = Path("/proc/loadavg")
_MEMINFO_PATH = Path("/proc/meminfo")
_THERMAL_ROOT = Path("/sys/class/thermal")


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
        except (OSError, ValueError):
            pass


def read_loadavg(_path: Path = _LOADAVG_PATH) -> tuple[float, float] | None:
    """1-minute and 5-minute load averages from /proc/loadavg.

    Single sysfs read — preferred over /proc/stat which would require two
    samples to compute a CPU rate.
    """
    try:
        parts = _path.read_text().split()
        return float(parts[0]), float(parts[1])
    except (OSError, ValueError, IndexError):
        return None


def read_meminfo(_path: Path = _MEMINFO_PATH) -> tuple[int, int] | None:
    """(MemTotal, MemAvailable) in kB from /proc/meminfo."""
    try:
        total: int | None = None
        avail: int | None = None
        for line in _path.read_text().splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
            if total is not None and avail is not None:
                return total, avail
    except (OSError, ValueError, IndexError):
        pass
    return None


def read_temp_c(_root: Path = _THERMAL_ROOT) -> float | None:
    """CPU temperature in °C from the first readable thermal zone."""
    for temp_path in sorted(_root.glob("thermal_zone*/temp")):
        try:
            return int(temp_path.read_text().strip()) / 1000.0
        except (OSError, ValueError):
            pass
    return None


# ── Power management ──────────────────────────────────────────────────────────

class SystemCommandError(RuntimeError):
    """A privileged system command failed.

    `unsupported=True` means the environment can't run it (no sudo, no
    systemctl, or no matching NOPASSWD grant) — the router maps this to 503.
    """
    def __init__(self, message: str = "", *, unsupported: bool = False) -> None:
        super().__init__(message)
        self.unsupported = unsupported


_DEV_MODE_SIGNALS = (
    "command not found",
    "no such file or directory",
    "password is required",
    "may not run sudo",
    "not in the sudoers",
)


async def _systemctl(*args: str, timeout: float = 30.0) -> None:
    """Run `sudo -n /bin/systemctl <args>`. Module-level so tests can monkeypatch."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "/bin/systemctl", *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise SystemCommandError("sudo not available", unsupported=True) from e
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise SystemCommandError(f"systemctl {' '.join(args)} timed out") from e
    if proc.returncode == 0:
        return
    err = stderr.decode(errors="replace").strip() or f"systemctl exit {proc.returncode}"
    lower = err.lower()
    unsupported = any(sig in lower for sig in _DEV_MODE_SIGNALS)
    raise SystemCommandError(err, unsupported=unsupported)


async def restart_services() -> None:
    """Restart kiwix and mbtileserver. Stops at first failure."""
    await _systemctl("restart", "kiwix.service")
    await _systemctl("restart", "mbtileserver.service")


async def reboot() -> None:
    """Schedule a system reboot. Returns immediately via --no-block."""
    await _systemctl("--no-block", "reboot", timeout=5.0)


async def poweroff() -> None:
    """Schedule a system poweroff. Returns immediately via --no-block."""
    await _systemctl("--no-block", "poweroff", timeout=5.0)
