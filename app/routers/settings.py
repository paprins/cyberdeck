from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.services.packages import (
    _active_tasks,
    get_download_status,
    get_storage_info,
)
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    def _sys_ctx():
        status = read_system_status(cfg)
        return {
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
        }

    @router.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(request, "settings.html", {
            "active_tab": "settings",
            **_sys_ctx(),
        })

    @router.get("/settings/packages", response_class=HTMLResponse)
    async def settings_packages(request: Request):
        registry = load_registry(cfg)
        storage = get_storage_info(cfg)
        all_statuses = {m.id: get_download_status(m, cfg) for m in registry.modules}

        _in_flight = ("downloading", "interrupted", "checksum_mismatch")
        updates = [
            m for m in registry.modules
            if m.has_update and all_statuses[m.id]["status"] not in _in_flight
        ]
        installed = [
            m for m in registry.modules
            if (m.is_installed and not m.has_update)
            or all_statuses[m.id]["status"] in _in_flight
        ]
        available = [
            m for m in registry.modules
            if not m.is_installed
            and not m.has_update
            and all_statuses[m.id]["status"] == "not_installed"
        ]

        return templates.TemplateResponse(request, "settings.html", {
            "active_tab": "packages",
            "updates": updates,
            "installed": installed,
            "available": available,
            "module_statuses": all_statuses,
            "storage": storage,
            "has_active_download": bool(_active_tasks),
            **_sys_ctx(),
        })

    return router
