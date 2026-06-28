"""Render an offline-capable MapLibre viewer for `kind="mbtiles"` modules.

Two routes:
  GET /map/{id}             — HTML viewer page (extends base.html, MapLibre init)
  GET /map/{id}/style.json  — Jinja-rendered MapLibre style with cyberdeck tokens

Tiles themselves are served by mbtileserver through the cyberdeck `/maps/` proxy.
"""
from __future__ import annotations
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.routers.routing import find_active_routing
from app.services.registry import load_registry
from app.services.system import read_system_status

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_INPUT_CSS = Path(__file__).parent.parent / "static" / "css" / "input.css"


def _parse_theme_tokens(css_text: str) -> dict[str, str]:
    """Extract `--color-*` token values from the `@theme { ... }` block.

    Returns a dict mapping CSS variable name (including the leading `--`) to
    its raw value (hex string). Whitespace and trailing semicolons are stripped.
    """
    match = re.search(r"@theme\s*\{(.+?)\}", css_text, re.DOTALL)
    if not match:
        return {}
    body = match.group(1)
    return {
        f"--{name}": value.strip()
        for name, value in re.findall(r"--([\w-]+):\s*([^;]+);", body)
    }


# Parsed once at import. If input.css is missing or malformed the app should
# fail to start — every page in the UI depends on the same file.
MAP_TOKENS: dict[str, str] = _parse_theme_tokens(_INPUT_CSS.read_text(encoding="utf-8"))

# OpenTopoMap-inspired light palette. Mapped to the same 12 token semantics
# the map style consumes — same keys, different hex values. Cream paper,
# cyan water, forest-green parks, hierarchical road colors with vivid orange
# motorways for outdoor daylight readability (paper-topographic feel).
MAP_TOKENS_LIGHT: dict[str, str] = {
    "--color-surface":                  "#f4f0e3",  # cream paper background
    "--color-surface-container-lowest": "#a4c8e0",  # water fill
    "--color-surface-container-low":    "#ece5cc",  # glacier / residential
    "--color-surface-container":        "#cee0b1",  # woods + parks
    "--color-surface-container-high":   "#dcc9a5",  # buildings
    "--color-outline":                  "#3d3d3d",  # major road inner, country borders
    "--color-outline-variant":          "#9c8a73",  # road casings, minor lines
    "--color-primary":                  "#a83c00",  # motorway / major place labels
    "--color-primary-container":        "#ff7a00",  # motorway inner
    "--color-on-surface":               "#1a1a1a",  # main labels
    "--color-on-surface-variant":       "#5a4d3d",  # secondary labels
    "--color-tertiary":                 "#2a6da8",  # water labels
}

# Tokens referenced by map_style.json.j2. Validated at import to fail loud if
# a design-system token is renamed without updating the map style — otherwise
# the missing key would surface only as a 500 on the style.json route.
_REQUIRED_TOKENS = frozenset({
    "--color-surface", "--color-surface-container-lowest",
    "--color-surface-container-low", "--color-surface-container",
    "--color-surface-container-high",
    "--color-outline", "--color-outline-variant",
    "--color-primary", "--color-primary-container",
    "--color-on-surface", "--color-on-surface-variant",
    "--color-tertiary",
})
_missing = _REQUIRED_TOKENS - MAP_TOKENS.keys()
if _missing:
    raise RuntimeError(
        f"map_viewer: missing CSS tokens in input.css: {sorted(_missing)}"
    )


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    templates = Jinja2Templates(directory=_TEMPLATE_DIR)

    def _find_module(module_id: str):
        registry = load_registry(cfg)
        return next(
            (m for m in registry.modules if m.id == module_id and m.kind == "mbtiles"),
            None,
        )

    @router.get("/map/{module_id}")
    async def view_map(request: Request, module_id: str):
        module = _find_module(module_id)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        status = read_system_status(cfg)
        return templates.TemplateResponse(request, "map_viewer.html", {
            "module": module,
            "routing_available": find_active_routing(cfg, module.id) is not None,
            "battery_pct": status.battery_pct,
            "battery_charging": status.battery_charging,
            "wifi_connected": status.wifi_connected,
            "is_online": status.is_online,
        })

    @router.get("/map/{module_id}/style.json")
    async def map_style(request: Request, module_id: str, theme: str = "dark"):
        module = _find_module(module_id)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        # MapLibre requires absolute URLs for sprite / glyphs / source.url.
        # Derive the origin from the incoming request so the style works for any
        # client (localhost, LAN IP, hostname) without hardcoding.
        origin = str(request.base_url).rstrip("/")
        tokens = MAP_TOKENS_LIGHT if theme == "light" else MAP_TOKENS
        return templates.TemplateResponse(
            request,
            "map_style.json.j2",
            {"module_id": module.id, "tokens": tokens, "origin": origin},
            media_type="application/json",
        )

    return router
