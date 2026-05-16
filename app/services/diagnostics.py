from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Literal

import httpx

from app.config import Settings
from app.services.packages import get_storage_info
from app.services.registry import load_registry
from app.services.system import (
    read_brightness,
    read_loadavg,
    read_meminfo,
    read_temp_c,
    read_uptime_s,
)
from app.services.upgrade import current_version


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
    )
