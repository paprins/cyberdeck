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

# Kinds whose viewers already extend base.html. Linking via /view would render
# the cyberdeck chrome twice (outer page + iframe), so they bypass /view.
_NATIVE_VIEWER_KINDS = {"static", "mbtiles"}


@dataclass
class ModuleCard:
    module: Module
    url: str


def _external_url(module: Module) -> str | None:
    if module.kind == "mbtiles":
        return f"/map/{module.id}"
    if module.kind == "static":
        entry = module.entry or "index.md"
        return f"/content/{module.id}/{entry}"
    if module.category == "internet":
        return "https://duckduckgo.com"
    if module.category != "packages":
        return f"/kiwix/content/{module.id}/"
    return None


def _tile_url(module: Module) -> str:
    if module.category == "packages":
        return "/settings/packages"
    ext = _external_url(module)
    if not ext:
        return "/settings/packages"
    return ext if module.kind in _NATIVE_VIEWER_KINDS else f"/view?url={ext}"


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
            "is_online": status.is_online,
        })

    @router.get("/view", response_class=HTMLResponse)
    async def view_service(request: Request, url: str):
        status = read_system_status(cfg)
        return templates.TemplateResponse(request, "viewer.html", {
            "url": url,
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "is_online": status.is_online,
        })

    return router
