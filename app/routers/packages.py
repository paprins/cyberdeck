from __future__ import annotations
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
import httpx

from app.config import Settings
from app.services.packages import (
    _active_tasks,
    _pending,
    accept_checksum_mismatch,
    activate_module,
    cancel_download,
    check_for_updates,
    deactivate_module,
    discard_checksum_mismatch,
    get_download_status,
    start_download,
    uninstall_module,
)
from app.services.registry import load_registry


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/api/packages/check-updates")
    async def check_updates_endpoint():
        try:
            count = await check_for_updates(cfg)
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return {"updated": count}

    @router.get("/api/packages/active-download")
    async def active_download():
        if not _active_tasks:
            return {"module_id": None}
        module_id = next(iter(_active_tasks))
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return {"module_id": module_id, "status": "downloading", "pct": 0, "bytes_downloaded": 0, "total_bytes": 0}
        return {"module_id": module_id, **get_download_status(module, cfg)}

    @router.get("/api/packages/{module_id}/status")
    async def module_status(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return get_download_status(module, cfg)

    @router.post("/api/packages/{module_id}/install")
    async def install(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            await start_download(module, cfg)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return Response(status_code=202)

    @router.post("/api/packages/{module_id}/cancel")
    async def cancel(module_id: str):
        if module_id not in _active_tasks and module_id not in _pending:
            return JSONResponse({"error": "not downloading"}, status_code=404)
        await cancel_download(module_id)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/uninstall")
    async def uninstall(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await uninstall_module(module, cfg)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/activate")
    async def activate(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await activate_module(module, cfg)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/deactivate")
    async def deactivate(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await deactivate_module(module, cfg)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/accept-checksum")
    async def accept_checksum(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            await accept_checksum_mismatch(module, cfg)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/discard-checksum")
    async def discard_checksum(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await discard_checksum_mismatch(module, cfg)
        return Response(status_code=204)

    return router
