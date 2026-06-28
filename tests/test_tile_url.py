from __future__ import annotations
from app.models.registry import Module
from app.routers.home import _tile_url


def _mod(id: str, category: str, kind: str = "zim") -> Module:
    return Module(
        id=id, display_name=id, category=category, kind=kind,
        description="", latest_version="", size_gb=0,
        checksum="sha256:x" if kind in ("zim", "mbtiles") else None,
        signature_url="https://x/" if kind == "static" else None,
    )


def test_tile_url_maps():
    # mbtiles modules link directly to the in-cyberdeck map viewer (which
    # extends base.html); wrapping in /view would double-render the chrome.
    assert _tile_url(_mod("maps-world", "navigation", kind="mbtiles")) == "/map/maps-world"


def test_tile_url_kiwix_content():
    assert _tile_url(_mod("medical-wikimed", "medical")) == "/view?url=/kiwix/content/medical-wikimed/"


def test_tile_url_kiwix_uses_module_id():
    result = _tile_url(_mod("survival-wikihow", "reference"))
    assert "survival-wikihow" in result


def test_tile_url_static_links_direct_not_viewer():
    """Static content already extends base.html — must not be wrapped in /view."""
    m = _mod("first-aid", "medical", kind="static")
    m.entry = "index.md"
    result = _tile_url(m)
    assert result == "/content/first-aid/index.md"
    assert "/view?" not in result
