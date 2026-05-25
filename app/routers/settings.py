from __future__ import annotations
import asyncio
from dataclasses import asdict
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import Settings
from app.services.connectivity import request_immediate_probe
from app.services.diagnostics import read_diagnostics
from app.services.library_refresh import maybe_refresh_libraries
from app.services.notifications import (
    effective_check_for_updates,
    effective_connectivity_check,
    save_preference,
)
from app.services.packages import (
    _active_tasks,
    get_download_status,
    get_storage_info,
)
from app.services.registry import load_registry
from app.services.system import read_system_status
from app.services.upgrade import current_version, read_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class CheckForUpdatesBody(BaseModel):
    enabled: bool


class ConnectivityCheckBody(BaseModel):
    enabled: bool


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    def _sys_ctx():
        status = read_system_status(cfg)
        return {
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "is_online": status.is_online,
            "current_version": current_version(cfg),
            "check_for_updates": effective_check_for_updates(cfg),
            "connectivity_check": effective_connectivity_check(cfg),
        }

    @router.post("/api/settings/check-for-updates", status_code=204)
    async def set_check_for_updates(body: CheckForUpdatesBody):
        save_preference(cfg, "check_for_updates", body.enabled)
        return Response(status_code=204)

    @router.post("/api/settings/connectivity-check", status_code=204)
    async def set_connectivity_check(body: ConnectivityCheckBody):
        save_preference(cfg, "connectivity_check", body.enabled)
        if body.enabled:
            await request_immediate_probe()
        return Response(status_code=204)

    @router.get("/settings")
    async def settings_index():
        # Land on the first tab (STATUS) — it's the dashboard view most users
        # want when they click the global Settings affordance. The device
        # preferences panel lives at /settings/preferences.
        return RedirectResponse(url="/settings/status", status_code=307)

    @router.get("/settings/preferences", response_class=HTMLResponse)
    async def settings_preferences(request: Request):
        return templates.TemplateResponse(request, "settings.html", {
            "active_tab": "settings",
            "upgrade_status": read_status(cfg).model_dump(mode="json"),
            **_sys_ctx(),
        })

    @router.get("/settings/status", response_class=HTMLResponse)
    async def settings_status(request: Request):
        diagnostics = await read_diagnostics(cfg)
        return templates.TemplateResponse(request, "settings.html", {
            "active_tab": "status",
            "diagnostics": asdict(diagnostics),
            **_sys_ctx(),
        })

    @router.get("/settings/packages", response_class=HTMLResponse)
    async def settings_packages(request: Request):
        sys_ctx = _sys_ctx()
        if sys_ctx["check_for_updates"] and sys_ctx["wifi_connected"]:
            asyncio.create_task(maybe_refresh_libraries(cfg))
        registry = load_registry(cfg)
        storage = get_storage_info(cfg)
        all_statuses = {m.id: get_download_status(m, cfg) for m in registry.modules}

        _in_flight = ("downloading", "interrupted", "checksum_mismatch", "queued")
        installed = [
            m for m in registry.modules
            if m.is_installed or all_statuses[m.id]["status"] in _in_flight
        ]

        return templates.TemplateResponse(request, "settings.html", {
            "active_tab": "packages",
            "installed": installed,
            "module_statuses": all_statuses,
            "storage": storage,
            "libraries": [lib.model_dump() for lib in registry.libraries],
            "has_active_download": bool(_active_tasks),
            **sys_ctx,
        })

    return router
