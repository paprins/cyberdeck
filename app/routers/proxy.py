from __future__ import annotations
import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from app.config import Settings

# RFC 7230 hop-by-hop headers — must not be forwarded.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
})


def _filter_pairs(headers) -> list[tuple[str, str]]:
    # multi_items (httpx) preserves duplicate Set-Cookie; starlette items() already does.
    pairs = headers.multi_items() if hasattr(headers, "multi_items") else headers.items()
    return [(k, v) for k, v in pairs if k.lower() not in _HOP_BY_HOP]


async def _stream(resp: httpx.Response):
    # Guarantee aclose even if upstream errors mid-body.
    try:
        async for chunk in resp.aiter_raw():
            yield chunk
    finally:
        await resp.aclose()


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()
    upstreams = {
        "/kiwix": f"http://127.0.0.1:{cfg.kiwix_port}",
        "/maps": f"http://127.0.0.1:{cfg.mbtiles_port}",
    }

    async def _proxy(prefix: str, path: str, request: Request) -> Response:
        client: httpx.AsyncClient = request.app.state.http_client
        # Raw query string preserves percent-encoding fidelity.
        suffix = f"?{request.url.query}" if request.url.query else ""
        url = f"{upstreams[prefix]}{prefix}/{path}{suffix}"
        req = client.build_request(
            request.method, url, headers=_filter_pairs(request.headers),
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.RequestError:
            return Response(status_code=502)

        out = StreamingResponse(_stream(resp), status_code=resp.status_code)
        # Set raw_headers directly so multi-value headers (e.g. Set-Cookie) survive.
        out.raw_headers = [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in _filter_pairs(resp.headers)
        ]
        return out

    @router.api_route("/kiwix/{path:path}", methods=["GET", "HEAD"])
    async def kiwix_proxy(path: str, request: Request):
        return await _proxy("/kiwix", path, request)

    @router.api_route("/maps/{path:path}", methods=["GET", "HEAD"])
    async def maps_proxy(path: str, request: Request):
        return await _proxy("/maps", path, request)

    return router
