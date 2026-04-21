from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import Settings
from app.services.registry import load_registry
from app.services.system import read_system_status
from app.services.bento import compute_layout

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        active_modules = [m for m in registry.modules if m.active]
        layout = compute_layout(active_modules, wifi_connected=status.wifi_connected)
        return templates.TemplateResponse(request, "home.html", {
            "layout": layout,
            "active_count": len(active_modules),
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "updates_available": status.updates_available,
            "uptime_s": status.uptime_s,
        })

    return router
