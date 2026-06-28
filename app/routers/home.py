from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.categories import CATEGORIES, CATEGORY_MAP, CATEGORY_SLUGS, CategoryDef
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


@dataclass
class CategoryCard:
    category: CategoryDef
    url: str
    count: int


def _external_url(module: Module) -> str:
    if module.kind == "mbtiles":
        return f"/map/{module.id}"
    if module.kind == "static":
        entry = module.entry or "index.md"
        return f"/content/{module.id}/{entry}"
    return f"/kiwix/content/{module.id}/"


def _tile_url(module: Module) -> str:
    ext = _external_url(module)
    return ext if module.kind in _NATIVE_VIEWER_KINDS else f"/view?url={ext}"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        counts: dict[str, int] = {}
        for m in registry.modules:
            # routing modules are backing data for the map navigation feature,
            # not browsable content — they get no card and no count.
            if m.active and m.kind != "routing":
                counts[m.category] = counts.get(m.category, 0) + 1
        # One card per category that has at least one active module, in the
        # canonical display order.
        cards = [
            CategoryCard(category=c, url=f"/category/{c.slug}", count=counts[c.slug])
            for c in CATEGORIES
            if counts.get(c.slug)
        ]
        return templates.TemplateResponse(request, "home.html", {
            "cards": cards,
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "is_online": status.is_online,
        })

    @router.get("/category/{slug}", response_class=HTMLResponse)
    async def category(request: Request, slug: str):
        if slug not in CATEGORY_SLUGS:
            raise HTTPException(status_code=404)
        registry = load_registry(cfg)
        status = read_system_status(cfg)
        # Exclude routing modules — they back the map navigation feature and
        # aren't directly viewable (no /map page; /view would 404).
        modules = [
            m for m in registry.modules
            if m.active and m.category == slug and m.kind != "routing"
        ]
        cards = [ModuleCard(module=m, url=_tile_url(m)) for m in modules]
        return templates.TemplateResponse(request, "category.html", {
            "category": CATEGORY_MAP[slug],
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
