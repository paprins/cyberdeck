from __future__ import annotations
from fastapi import APIRouter
from app.config import Settings
from app.services.system import read_system_status


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/system")
    async def system_status():
        status = read_system_status(cfg)
        return {
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
        }

    return router
