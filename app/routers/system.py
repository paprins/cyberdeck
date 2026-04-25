from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.config import Settings
import app.services.system as sys_svc
from app.services.system import read_system_status


class BrightnessRequest(BaseModel):
    level: int = Field(..., ge=0, le=100)


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

    @router.get("/api/system/brightness")
    async def get_brightness():
        return {"brightness_pct": sys_svc.read_brightness()}

    @router.post("/api/system/brightness", status_code=204)
    async def set_brightness(body: BrightnessRequest):
        sys_svc.write_brightness(body.level)
        return Response(status_code=204)

    return router
