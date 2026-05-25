from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, model_validator


class Library(BaseModel):
    id: str
    display_name: str
    url: str
    lang: Optional[str] = None
    type: Literal["opds", "github", "gitlab", "codeberg"] = "opds"


class LibraryEntry(BaseModel):
    """Ephemeral catalog entry. Returned from browse; never persisted.

    OPDS sets `entry_id` to an Atom <id> (often a URN like ``urn:uuid:...``),
    used only as the modal checkbox key. Git hosts set it to the package id,
    which becomes the Module.id at registration — Module.id has its own
    filesystem-safe pattern enforced there.
    """
    entry_id: str
    title: str
    kind: Literal["opds", "github", "gitlab", "codeberg"] = "opds"
    summary: Optional[str] = None
    language: Optional[str] = None
    size_bytes: Optional[int] = None
    thumbnail_url: Optional[str] = None
    # OPDS-only fields
    acquisition_url: Optional[str] = None
    meta4_url: Optional[str] = None
    # Git-host fields (github / gitlab / codeberg)
    tarball_url: Optional[str] = None
    signature_url: Optional[str] = None
    entry: Optional[str] = None
    version: Optional[str] = None
    category: Optional[str] = None

    @model_validator(mode="after")
    def _require_kind_fields(self) -> "LibraryEntry":
        if self.kind == "opds":
            if not self.meta4_url:
                raise ValueError("opds entries require meta4_url")
        else:
            missing = [f for f in ("tarball_url", "signature_url", "entry", "version")
                       if getattr(self, f) is None]
            if missing:
                raise ValueError(f"{self.kind} entries require: {', '.join(missing)}")
        return self


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
    type: Optional[Literal["opds", "github", "gitlab", "codeberg"]] = None


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
