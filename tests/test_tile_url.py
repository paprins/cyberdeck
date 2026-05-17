from __future__ import annotations
from app.models.registry import Module
from app.routers.home import _tile_url


def _mod(id: str, category: str) -> Module:
    return Module(
        id=id, display_name=id, category=category,
        description="", latest_version="", size_gb=0, checksum="",
    )


def test_tile_url_maps():
    assert _tile_url(_mod("maps-world", "maps")) == "/view?url=/maps/"


def test_tile_url_packages():
    assert _tile_url(_mod("_packages", "packages")) == "/settings/packages"


def test_tile_url_internet():
    assert _tile_url(_mod("_internet", "internet")) == "/view?url=https://duckduckgo.com"


def test_tile_url_kiwix_content():
    assert _tile_url(_mod("medical-wikimed", "medical")) == "/view?url=/kiwix/content/medical-wikimed/"


def test_tile_url_kiwix_uses_module_id():
    result = _tile_url(_mod("survival-wikihow", "survival"))
    assert "survival-wikihow" in result
