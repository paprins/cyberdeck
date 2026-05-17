from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import Settings
from app.models.registry import Module
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


@dataclass
class ModuleCard:
    module: Module
    url: str


def _external_url(module: Module) -> str | None:
    if module.category == "maps":
        return "/maps/"
    if module.category == "internet":
        return "https://duckduckgo.com"
    if module.category != "packages":
        return f"/kiwix/content/{module.id}/"
    return None


def _tile_url(module: Module) -> str:
    if module.category == "packages":
        return "/settings/packages"
    ext = _external_url(module)
    return f"/view?url={ext}" if ext else "/settings/packages"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        active = [m for m in registry.modules if m.active]
        cards = [ModuleCard(module=m, url=_tile_url(m)) for m in active]
        return templates.TemplateResponse(request, "home.html", {
            "cards": cards,
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
        })

    @router.get("/view", response_class=HTMLResponse)
    async def view_service(request: Request, url: str):
        status = read_system_status(cfg)
        return templates.TemplateResponse(request, "viewer.html", {
            "url": url,
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
        })

    return router
