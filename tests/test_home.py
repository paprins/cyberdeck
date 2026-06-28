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


def _module(**kw) -> Module:
    base = dict(
        id="medical-wikimed", display_name="Medical Wiki", category="medical",
        description="Emergency medicine reference", latest_version="2024-01",
        size_gb=0.8, checksum="sha256:abc", active=True,
    )
    base.update(kw)
    return Module(**base)


async def test_home_returns_200(client):
    r = await client.get("/")
    assert r.status_code == 200


async def test_home_returns_html(client):
    r = await client.get("/")
    assert "text/html" in r.headers["content-type"]


async def test_home_renders_wordmark(client):
    r = await client.get("/")
    assert "SURVIVAL_DASHBOARD" in r.text


async def test_home_empty_state_when_no_active_modules(client):
    r = await client.get("/")
    assert "NO_ACTIVE_MODULES" in r.text


async def test_home_shows_category_card_for_active_module(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[_module()]))
    r = await client.get("/")
    # Homepage shows category cards, not individual modules.
    assert 'href="/category/medical"' in r.text
    assert "MEDICAL" in r.text


async def test_home_does_not_show_module_name(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[_module()]))
    r = await client.get("/")
    assert "Medical_Wiki" not in r.text


async def test_home_category_card_absent_without_active_module(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[_module(active=False)]))
    r = await client.get("/")
    assert 'href="/category/medical"' not in r.text


async def test_home_maps_module_shows_navigation_category(client, tmp_settings):
    # 'maps' migrates to the navigation category.
    save_registry(tmp_settings, Registry(modules=[
        _module(id="maps-world", category="maps", kind="mbtiles", size_gb=10),
    ]))
    r = await client.get("/")
    assert 'href="/category/navigation"' in r.text


async def test_view_route_renders_iframe(client):
    r = await client.get("/view?url=http://localhost:8080/test/")
    assert r.status_code == 200
    assert "http://localhost:8080/test/" in r.text
    assert "<iframe" in r.text
