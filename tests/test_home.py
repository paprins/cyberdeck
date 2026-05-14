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
    assert "SURVIVAL_DASHBOARD" in r.text


async def test_home_import_module_card_always_present(client):
    r = await client.get("/")
    assert "IMPORT_MODULE" in r.text
    assert 'href="/settings/packages"' in r.text


async def test_home_shows_active_module_name(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical Wiki", category="medical",
                description="Emergency medicine reference", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Medical_Wiki" in r.text


async def test_home_shows_module_size(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical Wiki", category="medical",
                description="Emergency medicine reference", latest_version="2024-01",
                size_gb=3.2, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "3.2" in r.text


async def test_home_maps_module_has_viewer_url(client, tmp_settings):
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
    assert 'href="/view?url=http://localhost:8081/' in r.text


async def test_home_medical_module_has_viewer_url(client, tmp_settings):
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
    assert 'href="/view?url=http://localhost:8080/medical-wikimed/' in r.text


async def test_view_route_renders_iframe(client):
    r = await client.get("/view?url=http://localhost:8080/test/")
    assert r.status_code == 200
    assert "http://localhost:8080/test/" in r.text
    assert "<iframe" in r.text


async def test_home_inactive_modules_not_shown(client, tmp_settings):
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=[
            Module(
                id="medical-wikimed", display_name="Secret Module", category="medical",
                description="Should not appear", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=False,
            )
        ],
    )
    save_registry(tmp_settings, reg)
    r = await client.get("/")
    assert "Secret Module" not in r.text
