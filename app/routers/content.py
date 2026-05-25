"""Serve installed static-content modules.

Markdown files are rendered server-side and wrapped in `base.html` so they
inherit the cyberdeck chrome. All other file types are returned as-is.
"""
from __future__ import annotations
from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_MD_EXTENSIONS = ("fenced_code", "tables", "toc")


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    @router.get("/content/{module_id}/{path:path}")
    async def serve_content(request: Request, module_id: str, path: str):
        registry = load_registry(cfg)
        module = next(
            (m for m in registry.modules if m.id == module_id and m.kind == "static"),
            None,
        )
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)

        base = (cfg.content_dir / module_id).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            return JSONResponse({"error": "invalid path"}, status_code=400)
        if not target.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)

        if target.suffix.lower() in (".md", ".markdown"):
            html = markdown.markdown(target.read_text(encoding="utf-8"), extensions=list(_MD_EXTENSIONS))
            status = read_system_status(cfg)
            return templates.TemplateResponse(request, "content_viewer.html", {
                "module": module,
                "rendered_html": html,
                "battery_pct": status.battery_pct,
                "battery_charging": status.battery_charging,
                "wifi_connected": status.wifi_connected,
                "is_online": status.is_online,
            })
        return FileResponse(target)

    return router
