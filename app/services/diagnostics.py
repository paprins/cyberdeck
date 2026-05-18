from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from app.config import Settings
from app.services.packages import get_storage_info
from app.services.registry import load_registry
from app.services.system import (
    _wifi_connected,
    read_brightness,
    read_loadavg,
    read_meminfo,
    read_temp_c,
    read_uptime_s,
)
from app.services.upgrade import current_version
from app.services.wifi import _nmcli, _split_terse


@dataclass
class ServiceHealth:
    name: str
    url: str
    state: Literal["ok", "down"]
    status_code: int | None
    latency_ms: int | None


@dataclass
class Diagnostics:
    uptime_s: int | None
    brightness_pct: int | None
    storage_used_bytes: int
    storage_free_bytes: int
    storage_total_bytes: int
    updates_available: int
    firmware_version: str | None
    active_modules: int
    total_modules: int
    loadavg_1m: float | None
    loadavg_5m: float | None
    mem_total_kb: int | None
    mem_available_kb: int | None
    temp_c: float | None
    services: list[ServiceHealth] = field(default_factory=list)
    # ── Connectivity ──
    wifi_state: str = "UNKNOWN"
    wifi_ssid: str | None = None
    wifi_signal_pct: int | None = None
    wifi_channel: int | None = None
    lan_state: str = "UNKNOWN"
    lan_iface: str | None = None
    lan_ip: str | None = None
    wan_state: str = "UNKNOWN"
    wan_target: str | None = None
    wan_latency_ms: int | None = None
    wan_checked_at: float | None = None


async def _read_wifi_info() -> dict:
    """Parse `nmcli device wifi` for the in-use row. State is ASSOCIATED when
    that row exists, SCANNING when wlan interface is up but no row, else DOWN."""
    try:
        rc, out, _ = await _nmcli([
            "-t", "-f", "IN-USE,SSID,SIGNAL,CHAN",
            "device", "wifi",
        ])
        if rc != 0:
            state = "SCANNING" if _wifi_connected() else "DOWN"
            return {"wifi_state": state, "wifi_ssid": None, "wifi_signal_pct": None, "wifi_channel": None}
        for line in out.splitlines():
            fields = _split_terse(line)
            if len(fields) >= 4 and fields[0] == "*":
                _, ssid, signal_s, chan_s = fields[:4]
                return {
                    "wifi_state": "ASSOCIATED",
                    "wifi_ssid": ssid or None,
                    "wifi_signal_pct": int(signal_s) if signal_s.isdigit() else None,
                    "wifi_channel": int(chan_s) if chan_s.isdigit() else None,
                }
        state = "SCANNING" if _wifi_connected() else "DOWN"
        return {"wifi_state": state, "wifi_ssid": None, "wifi_signal_pct": None, "wifi_channel": None}
    except Exception:
        return {"wifi_state": "DOWN", "wifi_ssid": None, "wifi_signal_pct": None, "wifi_channel": None}


async def _read_iface_ip(iface: str) -> str | None:
    """Best-effort IPv4 lookup via `ip -4 -o addr show <iface>`. Async to avoid
    blocking the event loop; missing binary or no IPv4 returns None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "-4", "-o", "addr", "show", iface,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    if proc.returncode != 0:
        return None
    for part in stdout.decode(errors="replace").split():
        if "/" in part and part[0].isdigit():
            return part.split("/")[0]
    return None


async def _read_lan_info(_net_dir: Path = Path("/sys/class/net")) -> dict:
    """First eth*/en* interface with operstate==up; IP via `ip` binary."""
    if not _net_dir.exists():
        return {"lan_state": "DOWN", "lan_iface": None, "lan_ip": None}
    for iface_dir in sorted(_net_dir.iterdir()):
        name = iface_dir.name
        if not (name.startswith("eth") or name.startswith("en")):
            continue
        try:
            state = (iface_dir / "operstate").read_text().strip()
        except OSError:
            continue
        if state != "up":
            continue
        return {"lan_state": "LINKED", "lan_iface": name, "lan_ip": await _read_iface_ip(name)}
    return {"lan_state": "DOWN", "lan_iface": None, "lan_ip": None}


_WAN_STATE_MAP = {"online": "REACHABLE", "offline": "UNREACHABLE", "unknown": "UNKNOWN"}


async def _probe(name: str, port: int, client: httpx.AsyncClient) -> ServiceHealth:
    url = f"http://localhost:{port}/"
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        r = await client.get(url, timeout=1.0)
        latency_ms = int((loop.time() - started) * 1000)
        return ServiceHealth(
            name=name,
            url=url,
            state="ok" if r.status_code < 500 else "down",
            status_code=r.status_code,
            latency_ms=latency_ms,
        )
    except httpx.RequestError:
        return ServiceHealth(name=name, url=url, state="down", status_code=None, latency_ms=None)


async def read_diagnostics(cfg: Settings) -> Diagnostics:
    """Aggregate every Status-tab signal in a single batched call.

    Sync sysfs reads execute inline (microsecond kernel reads — thread-pool
    overhead would exceed the I/O cost). The three loopback HTTP probes run
    concurrently via gather with a 1s timeout each.
    """
    # Deferred import to break circular reference with notifications.py chain.
    from app.services.connectivity import get_connectivity_snapshot

    registry = load_registry(cfg)
    storage = get_storage_info(cfg)
    loadavg = read_loadavg()
    meminfo = read_meminfo()

    async with httpx.AsyncClient() as client:
        services = await asyncio.gather(
            _probe("kiwix", cfg.kiwix_port, client),
            _probe("mbtileserver", cfg.mbtiles_port, client),
            _probe("cyberdeck", cfg.app_port, client),
        )

    wifi_info = await _read_wifi_info()
    lan_info = await _read_lan_info()
    conn = get_connectivity_snapshot()

    return Diagnostics(
        uptime_s=read_uptime_s(),
        brightness_pct=read_brightness(),
        storage_used_bytes=storage["used_bytes"],
        storage_free_bytes=storage["free_bytes"],
        storage_total_bytes=storage["used_bytes"] + storage["free_bytes"],
        updates_available=len([m for m in registry.modules if m.has_update]),
        firmware_version=current_version(cfg),
        active_modules=len([m for m in registry.modules if m.active]),
        total_modules=len(registry.modules),
        loadavg_1m=loadavg[0] if loadavg else None,
        loadavg_5m=loadavg[1] if loadavg else None,
        mem_total_kb=meminfo[0] if meminfo else None,
        mem_available_kb=meminfo[1] if meminfo else None,
        temp_c=read_temp_c(),
        services=list(services),
        wifi_state=wifi_info["wifi_state"],
        wifi_ssid=wifi_info["wifi_ssid"],
        wifi_signal_pct=wifi_info["wifi_signal_pct"],
        wifi_channel=wifi_info["wifi_channel"],
        lan_state=lan_info["lan_state"],
        lan_iface=lan_info["lan_iface"],
        lan_ip=lan_info["lan_ip"],
        wan_state=_WAN_STATE_MAP.get(conn["last_state"], "UNKNOWN"),
        wan_target=cfg.connectivity_target,
        wan_latency_ms=conn["last_latency_ms"],
        wan_checked_at=conn["last_checked_at"],
    )
