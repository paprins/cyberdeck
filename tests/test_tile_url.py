from __future__ import annotations
from app.config import Settings
from app.models.registry import Module
from app.routers.home import _tile_url


def _mod(id: str, category: str) -> Module:
    return Module(
        id=id, display_name=id, category=category,
        description="", latest_version="", size_gb=0, checksum="",
    )


def test_tile_url_maps():
    cfg = Settings(data_dir="/tmp")
    assert _tile_url(_mod("maps-world", "maps"), cfg) == "/view?url=http://localhost:8081/"


def test_tile_url_packages():
    cfg = Settings(data_dir="/tmp")
    assert _tile_url(_mod("_packages", "packages"), cfg) == "/settings/packages"


def test_tile_url_internet():
    cfg = Settings(data_dir="/tmp")
    assert _tile_url(_mod("_internet", "internet"), cfg) == "/view?url=https://duckduckgo.com"


def test_tile_url_kiwix_content():
    cfg = Settings(data_dir="/tmp")
    assert _tile_url(_mod("medical-wikimed", "medical"), cfg) == "/view?url=http://localhost:8080/medical-wikimed/"


def test_tile_url_kiwix_uses_module_id():
    cfg = Settings(data_dir="/tmp")
    result = _tile_url(_mod("survival-wikihow", "survival"), cfg)
    assert "survival-wikihow" in result
