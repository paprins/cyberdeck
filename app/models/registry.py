from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.library import Library

# Restricted character set: module ids become filesystem paths
# (downloads_dir/{id}.part, content_dir/{id}/, etc). Reject traversal characters
# at the boundary so attacker-controlled manifest fields can never reach a path
# operation with `..` or `/`. First char must be alphanumeric to forbid `.`/`..`/
# leading-dot hidden-file ids.
_ID_PATTERN = r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$"


class Module(BaseModel):
    id: str = Field(pattern=_ID_PATTERN)
    display_name: str
    category: str
    description: str
    latest_version: str
    size_gb: float
    kind: Literal["zim", "mbtiles", "static"] = "zim"
    checksum: Optional[str] = None
    signature_url: Optional[str] = None
    entry: Optional[str] = None
    installed_version: Optional[str] = None
    installed_checksum: Optional[str] = None
    download_url: Optional[str] = None
    active: bool = False
    image: Optional[str] = None
    image_path: Optional[str] = None
    source_library_id: Optional[str] = None

    @model_validator(mode="after")
    def _require_checksum_for_hashed_kinds(self) -> "Module":
        if self.kind in ("zim", "mbtiles") and not self.checksum:
            raise ValueError(f"{self.kind} modules require a checksum")
        if self.kind == "static" and not self.signature_url:
            raise ValueError("static modules require a signature_url")
        return self

    @computed_field
    @property
    def is_installed(self) -> bool:
        return self.installed_version is not None

    @computed_field
    @property
    def has_update(self) -> bool:
        if not self.is_installed:
            return False
        return self.latest_version != self.installed_version


class Registry(BaseModel):
    modules: list[Module] = []
    libraries: list[Library] = []
