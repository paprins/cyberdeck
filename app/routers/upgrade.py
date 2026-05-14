from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.config import Settings
from app.models.upgrade import (
    InstallRequest,
    UpgradeAlreadyRunningError,
    UpgradeDowngradeError,
    UpgradeError,
    UpgradeNetworkError,
)
import app.services.upgrade as upgrade_svc


def _error_response(exc: UpgradeError) -> JSONResponse:
    if isinstance(exc, (UpgradeAlreadyRunningError, UpgradeDowngradeError)):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, UpgradeNetworkError):
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"error": str(exc)}, status_code=500)


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/upgrade/status")
    async def status():
        return upgrade_svc.read_status(cfg).model_dump(mode="json")

    @router.post("/api/upgrade/check")
    async def check():
        try:
            result = await upgrade_svc.check_for_updates(cfg)
        except UpgradeError as e:
            return _error_response(e)
        return {
            "current_version": result["current_version"],
            "releases": [r.model_dump(mode="json") for r in result["releases"]],
            "online_error": result["online_error"],
        }

    @router.post("/api/upgrade/install", status_code=202)
    async def install(req: InstallRequest):
        try:
            await upgrade_svc.start_upgrade(cfg, req)
        except UpgradeError as e:
            return _error_response(e)
        return Response(status_code=202)

    @router.post("/api/upgrade/cancel", status_code=204)
    async def cancel():
        try:
            upgrade_svc.cancel(cfg)
        except UpgradeError as e:
            return _error_response(e)
        return Response(status_code=204)

    return router
