from __future__ import annotations
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.registry import Module, Registry
from app.routers.map_viewer import MAP_TOKENS, MAP_TOKENS_LIGHT, _parse_theme_tokens
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _seed_mbtiles_module(tmp_settings, module_id="netherlands"):
    save_registry(tmp_settings, Registry(modules=[
        Module(
            id=module_id, display_name="Netherlands", category="maps",
            description="NL", latest_version="2026-05", size_gb=0.8,
            kind="mbtiles",
            checksum="sha256:abc",
            active=True,
        )
    ]))


# ── _parse_theme_tokens ───────────────────────────────────────────────────

def test_parse_theme_tokens_extracts_colors():
    css = """
    @import "tailwindcss";

    @theme {
      --color-surface: #131313;
      --color-primary-container: #ff6b00;
      --font-headline: 'Space Grotesk', sans-serif;
      --radius: 0px;
    }
    """
    tokens = _parse_theme_tokens(css)
    assert tokens["--color-surface"] == "#131313"
    assert tokens["--color-primary-container"] == "#ff6b00"
    # Non-color tokens are still parsed (the regex is generic).
    assert tokens["--font-headline"] == "'Space Grotesk', sans-serif"


def test_parse_theme_tokens_no_theme_block():
    assert _parse_theme_tokens("body { color: red; }") == {}


# ── /map/{id} HTML viewer ────────────────────────────────────────────────

async def test_map_viewer_renders(client, tmp_settings):
    _seed_mbtiles_module(tmp_settings)
    r = await client.get("/map/netherlands")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text  # extends base.html
    assert "maplibre-gl.js" in r.text
    assert "/map/netherlands/style.json" in r.text
    # Coords overlay scaffold (tap-to-readout + jump-to-coords).
    assert 'placeholder="LAT, LON"' in r.text
    assert "doJump()" in r.text
    assert "parseCoords" in r.text
    # Measurement scaffold (distance / route).
    assert "measureToggle" in r.text
    assert "_haversine" in r.text
    assert "measure-line" in r.text  # GeoJSON source/layer id


async def test_map_viewer_unknown_module_404(client, tmp_settings):
    save_registry(tmp_settings, Registry())
    r = await client.get("/map/missing")
    assert r.status_code == 404


async def test_map_viewer_non_mbtiles_module_404(client, tmp_settings):
    # A zim module with the same id should NOT match the mbtiles viewer.
    save_registry(tmp_settings, Registry(modules=[
        Module(
            id="netherlands", display_name="NL", category="maps",
            description="", latest_version="x", size_gb=0.01,
            checksum="sha256:abc",
            kind="zim",
        )
    ]))
    r = await client.get("/map/netherlands")
    assert r.status_code == 404


# ── /map/{id}/style.json ─────────────────────────────────────────────────

async def test_style_json_returns_json(client, tmp_settings):
    _seed_mbtiles_module(tmp_settings)
    r = await client.get("/map/netherlands/style.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["version"] == 8
    # MapLibre requires absolute URLs for sprite / glyphs / source.url —
    # derived from the request's base_url so the style works for any client.
    assert body["sources"]["openmaptiles"]["url"].endswith("/maps/netherlands")
    assert body["sprite"].endswith("/static/maps/sprite")
    assert "://" in body["sprite"]
    assert body["glyphs"].endswith("/static/maps/glyphs/{fontstack}/{range}.pbf")
    assert "://" in body["glyphs"]
    # Tokens were substituted: at least the background-color must resolve to a
    # hex value, not the raw Jinja expression.
    bg = next(l for l in body["layers"] if l["id"] == "background")
    assert bg["paint"]["background-color"].startswith("#")


async def test_style_json_unknown_module_404(client, tmp_settings):
    save_registry(tmp_settings, Registry())
    r = await client.get("/map/missing/style.json")
    assert r.status_code == 404


async def test_style_json_light_theme(client, tmp_settings):
    _seed_mbtiles_module(tmp_settings)
    r = await client.get("/map/netherlands/style.json?theme=light")
    assert r.status_code == 200
    body = r.json()
    bg = next(l for l in body["layers"] if l["id"] == "background")
    # The light palette must replace the dark one entirely.
    assert bg["paint"]["background-color"] == MAP_TOKENS_LIGHT["--color-surface"]
    assert bg["paint"]["background-color"] != MAP_TOKENS["--color-surface"]


async def test_style_json_defaults_to_dark(client, tmp_settings):
    _seed_mbtiles_module(tmp_settings)
    r = await client.get("/map/netherlands/style.json")
    body = r.json()
    bg = next(l for l in body["layers"] if l["id"] == "background")
    assert bg["paint"]["background-color"] == MAP_TOKENS["--color-surface"]


# ── Home tile routing ────────────────────────────────────────────────────

async def test_home_tile_links_to_map_viewer(client, tmp_settings):
    _seed_mbtiles_module(tmp_settings)
    r = await client.get("/")
    assert r.status_code == 200
    # mbtiles modules must link directly to the new viewer, not through /view
    # (which would iframe and double-render the chrome).
    assert 'href="/map/netherlands"' in r.text
    assert "/view?url=/maps/" not in r.text
