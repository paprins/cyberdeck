from __future__ import annotations
import httpx

from app.services import thumbnails


async def test_cache_thumbnail_writes_png_and_returns_local_url(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"\x89PNG\r\n\x1a\nbody", "image/png")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail(
        "mod1", "https://example.com/x.png", tmp_settings
    )
    assert result == "/data-cache/mod1/cover.png"
    cached = tmp_settings.cache_dir / "mod1" / "cover.png"
    assert cached.read_bytes() == b"\x89PNG\r\n\x1a\nbody"


async def test_cache_thumbnail_handles_content_type_with_params(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"jpegbody", "image/jpeg; charset=binary")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod2", "https://example.com/x", tmp_settings)
    assert result == "/data-cache/mod2/cover.jpg"


async def test_cache_thumbnail_returns_none_for_unsupported_mime(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"pdfbody", "application/pdf")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod3", "https://example.com/x", tmp_settings)
    assert result is None
    assert not (tmp_settings.cache_dir / "mod3").exists() or \
        list((tmp_settings.cache_dir / "mod3").glob("cover.*")) == []


async def test_cache_thumbnail_rejects_svg(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"<svg/>", "image/svg+xml")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod4", "https://example.com/x.svg", tmp_settings)
    assert result is None


async def test_cache_thumbnail_returns_none_on_network_error(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        raise httpx.RequestError("down")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod5", "https://example.com/x", tmp_settings)
    assert result is None
    assert not (tmp_settings.cache_dir / "mod5").exists() or \
        list((tmp_settings.cache_dir / "mod5").glob("cover.*")) == []


async def test_cache_thumbnail_idempotent_for_local_url(tmp_settings, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"png", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail(
        "mod6", "/data-cache/mod6/cover.png", tmp_settings
    )
    assert result == "/data-cache/mod6/cover.png"
    assert calls == []


async def test_cache_thumbnail_returns_none_for_empty_url(tmp_settings, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"png", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    assert await thumbnails.cache_thumbnail("mod7", None, tmp_settings) is None
    assert await thumbnails.cache_thumbnail("mod7", "", tmp_settings) is None
    assert calls == []


async def test_cache_thumbnail_returns_cached_url_when_url_is_none(tmp_settings, monkeypatch):
    """If upstream later drops the thumbnail (url=None) but a cached file
    survives on disk, we keep using the cached file rather than orphaning it."""
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"new", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    mod_dir = tmp_settings.cache_dir / "mod7b"
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "cover.png").write_bytes(b"old")

    result = await thumbnails.cache_thumbnail("mod7b", None, tmp_settings)
    assert result == "/data-cache/mod7b/cover.png"
    assert calls == []


async def test_cache_thumbnail_short_circuits_when_file_exists(tmp_settings, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"new", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    mod_dir = tmp_settings.cache_dir / "mod8"
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / "cover.jpg").write_bytes(b"old")

    result = await thumbnails.cache_thumbnail("mod8", "https://example.com/x", tmp_settings)
    assert result == "/data-cache/mod8/cover.jpg"
    assert calls == []
    assert (mod_dir / "cover.jpg").read_bytes() == b"old"


def test_delete_thumbnail_removes_cache_dir(tmp_settings):
    mod_dir = tmp_settings.cache_dir / "mod9"
    (mod_dir / "images").mkdir(parents=True, exist_ok=True)
    (mod_dir / "cover.png").write_bytes(b"x")
    (mod_dir / "images" / "logo.jpg").write_bytes(b"y")

    thumbnails.delete_thumbnail("mod9", tmp_settings)
    assert not mod_dir.exists()


def test_delete_thumbnail_is_noop_when_missing(tmp_settings):
    thumbnails.delete_thumbnail("ghost", tmp_settings)
    tmp_settings.cache_dir.mkdir(parents=True, exist_ok=True)
    thumbnails.delete_thumbnail("ghost", tmp_settings)
