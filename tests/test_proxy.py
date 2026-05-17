from __future__ import annotations
import pytest
import httpx
from httpx import AsyncClient, ASGITransport, MockTransport, Response, Request
from app.main import create_app


class _Stream(httpx.AsyncByteStream):
    """Stream-friendly byte source so MockTransport responses survive client.send(stream=True)."""
    def __init__(self, data: bytes):
        self._data = data

    async def __aiter__(self):
        yield self._data

    async def aclose(self):
        pass


def _swap_upstream(app, handler) -> None:
    """Replace the proxy's httpx client with one routed through MockTransport."""
    app.state.http_client = AsyncClient(transport=MockTransport(handler))


@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def http_client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_proxy_returns_502_when_upstream_errors(app):
    def handler(req: Request) -> Response:
        raise httpx.ConnectError("connection refused")

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r_kiwix = await c.get("/kiwix/content/foo/")
        r_maps = await c.get("/maps/services")
    assert r_kiwix.status_code == 502
    assert r_maps.status_code == 502


async def test_proxy_post_returns_405(http_client):
    r = await http_client.post("/kiwix/content/foo/")
    assert r.status_code == 405


async def test_proxy_forwards_content_and_headers(app):
    def handler(req: Request) -> Response:
        return Response(200, headers={"content-type": "text/html", "etag": '"abc"'}, stream=_Stream(b"<html>hi</html>"))

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/kiwix/content/medical-wikimed/A/Main")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/html"
    assert r.headers["etag"] == '"abc"'
    assert r.content == b"<html>hi</html>"


async def test_proxy_forwards_query_string(app):
    captured: list[str] = []
    def handler(req: Request) -> Response:
        captured.append(str(req.url))
        return Response(200, stream=_Stream(b""))

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/kiwix/search?content=medical-wikimed&pattern=first+aid")
    assert len(captured) == 1
    assert "content=medical-wikimed" in captured[0]
    assert "pattern=first+aid" in captured[0]


async def test_proxy_targets_correct_upstream(app):
    captured: list[str] = []
    def handler(req: Request) -> Response:
        captured.append(str(req.url))
        return Response(200, stream=_Stream(b""))

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/kiwix/content/abc/")
        await c.get("/maps/foo/")
    assert "127.0.0.1:8080" in captured[0] and "/kiwix/content/abc/" in captured[0]
    assert "127.0.0.1:8081" in captured[1] and "/maps/foo/" in captured[1]


async def test_proxy_strips_hop_by_hop_response_headers(app):
    def handler(req: Request) -> Response:
        return Response(
            200,
            headers={"connection": "keep-alive", "content-type": "text/plain"},
            stream=_Stream(b"x"),
        )

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/kiwix/anything")
    assert "connection" not in {k.lower() for k in r.headers}
    assert r.headers["content-type"] == "text/plain"


async def test_proxy_preserves_multi_value_set_cookie(app):
    def handler(req: Request) -> Response:
        return Response(
            200,
            headers=[("set-cookie", "a=1"), ("set-cookie", "b=2"), ("content-type", "text/plain")],
            stream=_Stream(b"x"),
        )

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/kiwix/anything")
    cookies = r.headers.get_list("set-cookie")
    assert cookies == ["a=1", "b=2"]


async def test_proxy_head_method_forwarded(app):
    seen: list[str] = []
    def handler(req: Request) -> Response:
        seen.append(req.method)
        return Response(200, headers={"content-type": "text/html"}, stream=_Stream(b""))

    _swap_upstream(app, handler)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.head("/kiwix/content/foo/")
    assert r.status_code == 200
    assert seen == ["HEAD"]
