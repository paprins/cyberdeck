from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class Library(BaseModel):
    id: str
    display_name: str
    url: str
    lang: Optional[str] = None


class LibraryEntry(BaseModel):
    """Ephemeral catalog entry. Returned from browse; never persisted."""
    entry_id: str
    title: str
    summary: Optional[str] = None
    language: Optional[str] = None
    size_bytes: Optional[int] = None
    acquisition_url: str
    meta4_url: str
    thumbnail_url: Optional[str] = None


class CatalogPage(BaseModel):
    library_id: str
    entries: list[LibraryEntry]
    total_results: Optional[int] = None
    start: int = 0
    count: int = 0


class ValidateResult(BaseModel):
    canonical_url: str
    display_name: str
    entry_count: Optional[int] = None


class LibraryError(RuntimeError):
    """Base. Maps to HTTP 500."""


class LibraryInvalidUrlError(LibraryError):
    """URL is malformed or cannot be normalized. Maps to 400."""


class LibraryUnreachableError(LibraryError):
    """Network failure or non-2xx from the catalog. Maps to 502."""


class LibraryParseError(LibraryError):
    """XML parse failure or missing required fields. Maps to 502."""


class LibraryNotFoundError(LibraryError):
    """Library id not in registry. Maps to 404."""


class LibraryAlreadyExistsError(LibraryError):
    """A library with this canonical URL already exists. Maps to 409."""
