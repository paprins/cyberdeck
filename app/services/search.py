from __future__ import annotations
import httpx
from app.models.registry import Module

_EXCLUDE_CATEGORIES = {"maps", "packages", "internet"}


async def kiwix_suggestions(
    query: str,
    module: Module,
    kiwix_port: int,
    client: httpx.AsyncClient,
    count: int = 3,
) -> list[str]:
    url = f"http://localhost:{kiwix_port}/suggest?content={module.id}&term={query}&count={count}"
    try:
        r = await client.get(url, timeout=2.0)
        if r.status_code == 200:
            return r.json()
    except httpx.RequestError:
        pass
    return []


async def search_modules(
    query: str,
    active_modules: list[Module],
    kiwix_port: int,
    client: httpx.AsyncClient,
) -> list[dict]:
    results = []
    searchable = [m for m in active_modules if m.category not in _EXCLUDE_CATEGORIES]
    for module in searchable:
        titles = await kiwix_suggestions(query, module, kiwix_port, client)
        search_url = f"http://localhost:{kiwix_port}/search?content={module.id}&pattern={query}"
        for title in titles:
            results.append({
                "title": title,
                "module": module.display_name,
                "url": search_url,
            })
    return results
