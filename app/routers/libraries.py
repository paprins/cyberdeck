from __future__ import annotations
import asyncio
from typing import Literal, Optional

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
import app.services.git_libraries as git_svc
import app.services.libraries as lib_svc
import app.services.library_refresh as library_refresh
import app.services.packages as packages_svc
import app.services.registry as registry_svc


def _svc_for(library_type: str):
    """Return the backend service module for a library type."""
    return lib_svc if library_type == "opds" else git_svc


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
    type: Optional[Literal["opds", "github", "gitlab", "codeberg"]] = None


class AddLibraryRequest(BaseModel):
    url: str
    display_name: str
    lang: Optional[str] = None
    type: Optional[Literal["opds", "github", "gitlab", "codeberg"]] = None


class RegisterRequest(BaseModel):
    entries: list[LibraryEntry]


def make_router(cfg: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/api/libraries/validate")
    async def validate(req: ValidateUrlRequest):
        library_type = req.type or git_svc.detect_type(req.url)
        try:
            if library_type == "opds":
                result = await lib_svc.validate_library(req.url)
            else:
                result = await git_svc.validate_library(req.url, library_type)
        except LibraryError as e:
            return _error_response(e)
        result.type = library_type
        return result.model_dump()

    @router.post("/api/libraries", status_code=201)
    async def add(req: AddLibraryRequest):
        library_type = req.type or git_svc.detect_type(req.url)
        try:
            library = registry_svc.add_library(
                cfg, req.url, req.display_name, req.lang, library_type=library_type
            )
        except LibraryError as e:
            return _error_response(e)
        return library.model_dump()

    @router.post("/api/libraries/refresh")
    async def refresh():
        result = await library_refresh.refresh_all_libraries(cfg)
        return {
            "refreshed_libraries": result.refreshed_libraries,
            "updated_modules": result.updated_modules,
            "errors": result.errors,
        }

    @router.post("/api/libraries/{library_id}/refresh")
    async def refresh_one(library_id: str):
        try:
            result = await library_refresh.refresh_one_library(library_id, cfg)
        except LibraryError as e:
            return _error_response(e)
        return {
            "refreshed_libraries": result.refreshed_libraries,
            "updated_modules": result.updated_modules,
            "errors": result.errors,
        }

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
            page = await _svc_for(library.type).fetch_page(library, start, count)
        except LibraryError as e:
            return _error_response(e)
        return page.model_dump()

    @router.post("/api/libraries/{library_id}/register")
    async def register(library_id: str, req: RegisterRequest):
        libraries = registry_svc.list_libraries(cfg)
        library = next((lib for lib in libraries if lib.id == library_id), None)
        if library is None:
            return _error_response(LibraryNotFoundError(library_id))

        svc = _svc_for(library.type)
        results = await asyncio.gather(
            *(svc.resolve_entry(entry, library, cfg) for entry in req.entries),
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
            by_id = {m.id: m for m in registry_svc.merge_remote_manifest(cfg, registered)}
            for remote in registered:
                module = by_id.get(remote["id"])
                if module and not module.is_installed:
                    await packages_svc.start_download(module, cfg)

        return {
            "registered": [m["id"] for m in registered],
            "failed": failed,
        }

    return router
