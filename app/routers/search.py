from __future__ import annotations
import httpx
from fastapi import APIRouter, Query
from app.config import Settings
from app.services.registry import load_registry
from app.services.search import search_modules


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/search")
    async def search(q: str = Query(..., min_length=2)):
        registry = load_registry(cfg)
        active = [m for m in registry.modules if m.active]
        async with httpx.AsyncClient() as client:
            return await search_modules(q, active, cfg.kiwix_port, client)

    return router
