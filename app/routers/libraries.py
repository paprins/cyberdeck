from __future__ import annotations
import asyncio
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.config import Settings
from app.models.library import (
    LibraryAlreadyExistsError,
    LibraryEntry,
    LibraryError,
    LibraryInvalidUrlError,
    LibraryNotFoundError,
    LibraryParseError,
    LibraryUnreachableError,
)
import app.services.libraries as lib_svc
import app.services.registry as registry_svc


def _error_response(exc: LibraryError) -> JSONResponse:
    if isinstance(exc, LibraryInvalidUrlError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, LibraryNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, LibraryAlreadyExistsError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, (LibraryUnreachableError, LibraryParseError)):
        return JSONResponse({"error": str(exc)}, status_code=502)
    return JSONResponse({"error": str(exc)}, status_code=500)


class ValidateUrlRequest(BaseModel):
    url: str


class AddLibraryRequest(BaseModel):
    url: str
    display_name: str
    lang: Optional[str] = None


class RegisterRequest(BaseModel):
    entries: list[LibraryEntry]


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/api/libraries/validate")
    async def validate(req: ValidateUrlRequest):
        try:
            result = await lib_svc.validate_library(req.url)
        except LibraryError as e:
            return _error_response(e)
        return result.model_dump()

    @router.post("/api/libraries", status_code=201)
    async def add(req: AddLibraryRequest):
        try:
            library = registry_svc.add_library(cfg, req.url, req.display_name, req.lang)
        except LibraryError as e:
            return _error_response(e)
        return library.model_dump()

    @router.delete("/api/libraries/{library_id}", status_code=204)
    async def delete(library_id: str):
        try:
            registry_svc.remove_library(cfg, library_id)
        except LibraryError as e:
            return _error_response(e)
        return Response(status_code=204)

    @router.get("/api/libraries/{library_id}/entries")
    async def browse(library_id: str, start: int = 0, count: int = 20):
        libraries = registry_svc.list_libraries(cfg)
        library = next((lib for lib in libraries if lib.id == library_id), None)
        if library is None:
            return _error_response(LibraryNotFoundError(library_id))
        try:
            page = await lib_svc.fetch_page(library, start, count)
        except LibraryError as e:
            return _error_response(e)
        return page.model_dump()

    @router.post("/api/libraries/{library_id}/register")
    async def register(library_id: str, req: RegisterRequest):
        libraries = registry_svc.list_libraries(cfg)
        library = next((lib for lib in libraries if lib.id == library_id), None)
        if library is None:
            return _error_response(LibraryNotFoundError(library_id))

        results = await asyncio.gather(
            *(lib_svc.resolve_entry(entry, library, cfg) for entry in req.entries),
            return_exceptions=True,
        )

        registered: list[dict] = []
        failed: list[dict] = []
        for entry, outcome in zip(req.entries, results):
            if isinstance(outcome, Exception):
                failed.append({"title": entry.title, "reason": str(outcome)})
            else:
                registered.append(outcome)

        if registered:
            registry_svc.merge_remote_manifest(cfg, registered)

        return {
            "registered": [m["id"] for m in registered],
            "failed": failed,
        }

    return router
