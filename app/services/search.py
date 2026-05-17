from __future__ import annotations
import asyncio
import httpx
from urllib.parse import urlencode
from app.models.registry import Module

_EXCLUDE_CATEGORIES = {"maps", "packages", "internet"}


async def kiwix_suggestions(
    query: str,
    module: Module,
    kiwix_port: int,
    client: httpx.AsyncClient,
    count: int = 3,
) -> list[str]:
    try:
        r = await client.get(
            f"http://localhost:{kiwix_port}/kiwix/suggest",
            params={"content": module.id, "term": query, "count": count},
            timeout=2.0,
        )
        if r.status_code == 200:
            return r.json()
    except (httpx.RequestError, ValueError):
        pass
    return []


async def search_modules(
    query: str,
    active_modules: list[Module],
    kiwix_port: int,
    client: httpx.AsyncClient,
) -> list[dict]:
    searchable = [m for m in active_modules if m.category not in _EXCLUDE_CATEGORIES]
    if not searchable:
        return []

    all_titles = await asyncio.gather(
        *[kiwix_suggestions(query, m, kiwix_port, client) for m in searchable]
    )
    results = []
    for module, titles in zip(searchable, all_titles):
        search_url = "/kiwix/search?" + urlencode({"content": module.id, "pattern": query})
        for title in titles:
            results.append({"title": title, "module": module.display_name, "url": search_url})
    return results
