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


async def test_category_unknown_slug_404(client):
    r = await client.get("/category/not-a-category")
    assert r.status_code == 404


async def test_category_valid_slug_200(client):
    r = await client.get("/category/medical")
    assert r.status_code == 200


async def test_category_shows_active_module_card(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[_module()]))
    r = await client.get("/category/medical")
    assert "Medical_Wiki" in r.text
    assert "0.8_GB" in r.text
    assert 'href="/view?url=/kiwix/content/medical-wikimed/' in r.text


async def test_category_hides_inactive_module(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[_module(active=False)]))
    r = await client.get("/category/medical")
    assert "Medical_Wiki" not in r.text
    assert "NO_ACTIVE_MODULES" in r.text


async def test_category_excludes_other_categories(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[
        _module(),
        _module(id="garden-wiki", display_name="Garden Wiki", category="gardening"),
    ]))
    r = await client.get("/category/medical")
    assert "Medical_Wiki" in r.text
    assert "Garden_Wiki" not in r.text


async def test_category_mbtiles_links_to_map_viewer(client, tmp_settings):
    save_registry(tmp_settings, Registry(modules=[
        _module(id="maps-world", display_name="World Maps", category="navigation",
                kind="mbtiles", size_gb=10),
    ]))
    r = await client.get("/category/navigation")
    assert 'href="/map/maps-world"' in r.text


async def test_category_hides_routing_backing_module(client, tmp_settings):
    # Routing modules back the map nav feature; they must not show as their own
    # (unviewable) card in the navigation grid.
    save_registry(tmp_settings, Registry(modules=[
        _module(id="maps-world", display_name="World Maps", category="navigation",
                kind="mbtiles", size_gb=10),
        _module(id="world-routing", display_name="World Routing", category="navigation",
                kind="routing", checksum="sha256:def", routing_for="maps-world",
                installed_version="1", size_gb=2),
    ]))
    r = await client.get("/category/navigation")
    assert 'href="/map/maps-world"' in r.text
    assert "World_Routing" not in r.text
