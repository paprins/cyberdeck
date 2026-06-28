from __future__ import annotations
import pytest
import httpx
from httpx import AsyncClient, ASGITransport
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import save_registry
from app.services.search import search_modules, kiwix_suggestions


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mod(id: str, category: str, active: bool = True, kind: str = "zim") -> Module:
    return Module(
        id=id, display_name=id.replace("-", " ").title(), category=category,
        description=f"{id} description", latest_version="2024-01",
        size_gb=1.0, kind=kind, active=active,
        checksum="sha256:abc" if kind in ("zim", "mbtiles") else None,
        signature_url="https://x/" if kind == "static" else None,
    )


class _MockClient:
    """Stand-in for httpx.AsyncClient — returns preset JSON by URL fragment."""
    def __init__(self, responses: dict[str, list]):
        self._responses = responses  # {url_fragment: [titles]}

    async def get(self, url: str, *, params: dict | None = None, timeout: float = 2.0):
        # Build a composite string from url + params values to search fragments in
        search_str = url
        if params:
            search_str += "&".join(f"{k}={v}" for k, v in params.items())
        for fragment, data in self._responses.items():
            if fragment in search_str:
                return _MockResponse(data, 200)
        return _MockResponse([], 404)


class _MockResponse:
    def __init__(self, data, status_code: int):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class _ErrorClient:
    async def get(self, url: str, *, params: dict | None = None, timeout: float = 2.0):
        raise httpx.RequestError("connection refused")


# ── kiwix_suggestions unit tests ─────────────────────────────────────────────

async def test_kiwix_suggestions_returns_titles():
    mod = _mod("medical-wikimed", "medical")
    client = _MockClient({"medical-wikimed": ["First Aid", "Wound Care"]})
    titles = await kiwix_suggestions("first", mod, 8080, client)
    assert titles == ["First Aid", "Wound Care"]


async def test_kiwix_suggestions_returns_empty_on_404():
    mod = _mod("medical-wikimed", "medical")
    client = _MockClient({})  # no match → 404
    titles = await kiwix_suggestions("first", mod, 8080, client)
    assert titles == []


async def test_kiwix_suggestions_returns_empty_on_request_error():
    mod = _mod("medical-wikimed", "medical")
    titles = await kiwix_suggestions("first", mod, 8080, _ErrorClient())
    assert titles == []


# ── search_modules unit tests ─────────────────────────────────────────────────

async def test_search_modules_returns_results():
    modules = [_mod("medical-wikimed", "medical")]
    client = _MockClient({"medical-wikimed": ["First Aid", "Bandaging"]})
    results = await search_modules("first", modules, 8080, client)
    assert len(results) == 2
    assert results[0]["title"] == "First Aid"
    assert results[0]["module"] == "Medical Wikimed"
    assert "medical-wikimed" in results[0]["url"]


async def test_search_modules_excludes_maps():
    # mbtiles maps have no kiwix full-text index.
    modules = [_mod("maps-world", "navigation", kind="mbtiles")]
    results = await search_modules("world", modules, 8080, _MockClient({}))
    assert results == []


async def test_search_modules_excludes_static():
    # static packages aren't served through kiwix either.
    modules = [_mod("first-aid", "medical", kind="static")]
    results = await search_modules("aid", modules, 8080, _MockClient({}))
    assert results == []


async def test_search_modules_returns_empty_when_no_active():
    results = await search_modules("test", [], 8080, _MockClient({}))
    assert results == []


async def test_search_modules_handles_kiwix_down():
    modules = [_mod("medical-wikimed", "medical")]
    results = await search_modules("first", modules, 8080, _ErrorClient())
    assert results == []


async def test_search_modules_result_url_contains_query():
    modules = [_mod("medical-wikimed", "medical")]
    client = _MockClient({"medical-wikimed": ["First Aid"]})
    results = await search_modules("first", modules, 8080, client)
    assert "first" in results[0]["url"]


async def test_search_modules_aggregates_multiple_modules():
    modules = [
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "reference"),
    ]
    client = _MockClient({
        "medical-wikimed": ["CPR"],
        "survival-wikihow": ["Fire Starting"],
    })
    results = await search_modules("s", modules, 8080, client)
    modules_in_results = {r["module"] for r in results}
    assert len(modules_in_results) == 2


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_search_endpoint_missing_q_returns_422(client):
    r = await client.get("/api/search")
    assert r.status_code == 422


async def test_search_endpoint_short_q_returns_422(client):
    r = await client.get("/api/search?q=a")
    assert r.status_code == 422


async def test_search_endpoint_returns_200_with_valid_q(client):
    # Kiwix not running in tests → graceful empty list
    r = await client.get("/api/search?q=test")
    assert r.status_code == 200


async def test_search_endpoint_returns_list(client):
    r = await client.get("/api/search?q=test")
    assert isinstance(r.json(), list)


async def test_search_modules_encodes_special_chars_in_url():
    modules = [_mod("medical-wikimed", "medical")]
    client = _MockClient({"medical-wikimed": ["Fire & Rescue"]})
    results = await search_modules("fire & rescue", modules, 8080, client)
    assert len(results) == 1
    assert "%26" in results[0]["url"]


async def test_search_endpoint_result_shape(client, tmp_settings, monkeypatch):
    reg = Registry(
        
        modules=[
            Module(
                id="medical-wikimed", display_name="Medical", category="medical",
                description="WikiMed", latest_version="2024-01",
                size_gb=0.8, checksum="sha256:abc", active=True,
            )
        ],
    )
    save_registry(tmp_settings, reg)

    import app.routers.search as search_router_module
    async def _fake_search(query, active_modules, kiwix_port, http_client):
        return [{"title": "First Aid", "module": "Medical", "url": "/kiwix/search?content=medical-wikimed&pattern=first"}]
    monkeypatch.setattr(search_router_module, "search_modules", _fake_search)

    r = await client.get("/api/search?q=first")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert "title" in data[0]
    assert "module" in data[0]
    assert "url" in data[0]
