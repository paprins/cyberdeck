from __future__ import annotations
import re
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, field_validator

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class UpgradeChannel(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class Release(BaseModel):
    version: str
    channel: UpgradeChannel
    tarball_url: str
    signature_url: str
    size_bytes: int | None = None
    published_at: datetime | None = None


UpgradePhase = Literal[
    "idle",
    "checking",
    "downloading",
    "verifying",
    "extracting",
    "building_venv",
    "migrating",
    "swapping",
    "restarting",
    "health_checking",
    "success",
    "failed",
    "rolled_back",
]


class UpgradeStatus(BaseModel):
    phase: UpgradePhase = "idle"
    current_version: str | None = None
    target_version: str | None = None
    channel: UpgradeChannel | None = None
    pct: int = 0
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class InstallRequest(BaseModel):
    version: str
    channel: UpgradeChannel
    tarball_url: str
    signature_url: str

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _VERSION_RE.match(v):
            raise ValueError("version must be X.Y.Z (three integers)")
        return v


class UpgradeError(RuntimeError):
    """Base class. Maps to HTTP 500."""


class UpgradeAlreadyRunningError(UpgradeError):
    """An upgrade or conflicting operation is in flight. Maps to 409."""


class UpgradeDowngradeError(UpgradeError):
    """Target version is not newer than current. Maps to 409."""


class UpgradeNetworkError(UpgradeError):
    """Online channel network failure. Maps to 502."""
