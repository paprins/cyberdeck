from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.config import Settings
from app.models.wifi import (
    ConnectRequest,
    ForgetRequest,
    WifiAuthError,
    WifiError,
    WifiNotFoundError,
    WifiTimeoutError,
)
import app.services.wifi as wifi_svc


def _error_response(exc: WifiError) -> JSONResponse:
    if isinstance(exc, WifiAuthError):
        return JSONResponse({"error": str(exc)}, status_code=401)
    if isinstance(exc, WifiTimeoutError):
        return JSONResponse({"error": str(exc)}, status_code=408)
    if isinstance(exc, WifiNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"error": str(exc)}, status_code=500)


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/api/wifi/networks")
    async def list_networks():
        try:
            status = await wifi_svc.scan_networks()
        except WifiError as e:
            return _error_response(e)
        return status.model_dump()

    @router.post("/api/wifi/connect", status_code=204)
    async def connect(req: ConnectRequest):
        try:
            await wifi_svc.connect(req)
        except WifiError as e:
            return _error_response(e)
        return Response(status_code=204)

    @router.post("/api/wifi/disconnect", status_code=204)
    async def disconnect():
        try:
            await wifi_svc.disconnect()
        except WifiError as e:
            return _error_response(e)
        return Response(status_code=204)

    @router.post("/api/wifi/forget", status_code=204)
    async def forget(req: ForgetRequest):
        try:
            await wifi_svc.forget(req.ssid)
        except WifiError as e:
            return _error_response(e)
        return Response(status_code=204)

    return router
