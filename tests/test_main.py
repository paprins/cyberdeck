import pytest
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.config import Settings


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_health_returns_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_status_returns_module_count(client, tmp_settings):
    r = await client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["active_modules"] == 0
    assert data["total_modules"] == 0


async def test_status_data_dirs_listed(client):
    r = await client.get("/api/status")
    data = r.json()
    assert "data_dirs" in data


async def test_404_returns_json(client):
    r = await client.get("/nonexistent")
    assert r.status_code == 404
    assert r.json() == {"error": "not found"}
