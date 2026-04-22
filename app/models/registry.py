from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, computed_field


class Module(BaseModel):
    id: str
    display_name: str
    category: str
    description: str
    latest_version: str
    size_gb: float
    checksum: str
    installed_version: Optional[str] = None
    installed_checksum: Optional[str] = None
    download_url: Optional[str] = None
    active: bool = False

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
    update_server: str
    modules: list[Module] = []
