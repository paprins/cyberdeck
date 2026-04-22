from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_home_returns_200(client):
    r = await client.get("/")
    assert r.status_code == 200


async def test_home_returns_html(client):
    r = await client.get("/")
    assert "text/html" in r.headers["content-type"]


async def test_home_renders_wordmark(client):
    r = await client.get("/")
    assert "CYBERDECK" in r.text


async def test_home_shows_active_module_name(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OpenStreetMap offline", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Maps" in r.text


async def test_home_shows_empty_state_when_no_active_modules(client):
    r = await client.get("/")
    assert "No modules active" in r.text


async def test_home_packages_tile_always_rendered(client):
    r = await client.get("/")
    assert "Packages" in r.text



async def test_maps_tile_has_mbtiles_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="maps-world", display_name="Maps", category="maps",
                description="OSM", latest_version="2024-01",
                size_gb=10, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8081/' in r.text


async def test_medical_tile_has_kiwix_url(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert 'href="http://localhost:8080/medical-wikimed/' in r.text


async def test_packages_tile_has_packages_url(client):
    r = await client.get("/")
    assert 'href="/packages"' in r.text


async def test_empty_state_cta_links_to_packages(client):
    r = await client.get("/")
    assert "No modules active" in r.text
    # The CTA text should be a link, not just plain text
    assert '<a href="/packages"' in r.text
    assert 'Open Packages to install content</a>' in r.text


async def test_chrome_has_no_modules_label(client):
    r = await client.get("/")
    assert "Modules" not in r.text


async def test_chrome_wifi_no_text(client):
    r = await client.get("/")
    assert ">connected<" not in r.text
    assert ">offline<" not in r.text


async def test_chrome_has_no_updates_badge(client):
    r = await client.get("/")
    assert "bg-tile-survival" not in r.text
