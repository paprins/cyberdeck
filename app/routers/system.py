from __future__ import annotations
from dataclasses import asdict
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.config import Settings
import app.services.system as sys_svc
from app.services.diagnostics import read_diagnostics
from app.services.notifications import (
    build_snapshot,
    schedule_firmware_refresh_if_eligible,
)


class BrightnessRequest(BaseModel):
    level: int = Field(..., ge=0, le=100)


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/system")
    async def system_status():
        status = sys_svc.read_system_status(cfg)
        schedule_firmware_refresh_if_eligible(cfg, status.wifi_connected)
        snapshot = build_snapshot(cfg, status.wifi_connected)
        return {
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
            "notifications": asdict(snapshot),
        }

    @router.get("/api/diagnostics")
    async def diagnostics():
        return asdict(await read_diagnostics(cfg))

    @router.get("/api/system/brightness")
    async def get_brightness():
        return {"brightness_pct": sys_svc.read_brightness()}

    @router.post("/api/system/brightness", status_code=204)
    async def set_brightness(body: BrightnessRequest):
        sys_svc.write_brightness(body.level)
        return Response(status_code=204)

    @router.post("/api/system/restart-services", status_code=204)
    async def restart_services():
        await sys_svc.restart_services()
        return Response(status_code=204)

    @router.post("/api/system/reboot", status_code=202)
    async def reboot():
        await sys_svc.reboot()
        return Response(status_code=202)

    @router.post("/api/system/shutdown", status_code=202)
    async def shutdown():
        await sys_svc.poweroff()
        return Response(status_code=202)

    return router
