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
    assert result == "/data-static/images/mod1.png"
    cached = tmp_settings.images_dir / "mod1.png"
    assert cached.read_bytes() == b"\x89PNG\r\n\x1a\nbody"


async def test_cache_thumbnail_handles_content_type_with_params(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"jpegbody", "image/jpeg; charset=binary")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod2", "https://example.com/x", tmp_settings)
    assert result == "/data-static/images/mod2.jpg"


async def test_cache_thumbnail_returns_none_for_unsupported_mime(tmp_settings, monkeypatch):
    async def fake_fetch(url):
        return (b"pdfbody", "application/pdf")
    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail("mod3", "https://example.com/x", tmp_settings)
    assert result is None
    assert list(tmp_settings.images_dir.glob("mod3.*")) == []


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
    assert list(tmp_settings.images_dir.glob("mod5.*")) == []


async def test_cache_thumbnail_idempotent_for_local_url(tmp_settings, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"png", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    result = await thumbnails.cache_thumbnail(
        "mod6", "/data-static/images/mod6.png", tmp_settings
    )
    assert result == "/data-static/images/mod6.png"
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

    tmp_settings.images_dir.mkdir(parents=True, exist_ok=True)
    (tmp_settings.images_dir / "mod7b.png").write_bytes(b"old")

    result = await thumbnails.cache_thumbnail("mod7b", None, tmp_settings)
    assert result == "/data-static/images/mod7b.png"
    assert calls == []


async def test_cache_thumbnail_short_circuits_when_file_exists(tmp_settings, monkeypatch):
    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return (b"new", "image/png")

    monkeypatch.setattr(thumbnails, "_fetch_image", fake_fetch)

    tmp_settings.images_dir.mkdir(parents=True, exist_ok=True)
    (tmp_settings.images_dir / "mod8.jpg").write_bytes(b"old")

    result = await thumbnails.cache_thumbnail("mod8", "https://example.com/x", tmp_settings)
    assert result == "/data-static/images/mod8.jpg"
    assert calls == []
    assert (tmp_settings.images_dir / "mod8.jpg").read_bytes() == b"old"


def test_delete_thumbnail_removes_file(tmp_settings):
    tmp_settings.images_dir.mkdir(parents=True, exist_ok=True)
    (tmp_settings.images_dir / "mod9.png").write_bytes(b"x")

    thumbnails.delete_thumbnail("mod9", tmp_settings)
    assert not (tmp_settings.images_dir / "mod9.png").exists()


def test_delete_thumbnail_is_noop_when_missing(tmp_settings):
    thumbnails.delete_thumbnail("ghost", tmp_settings)
    tmp_settings.images_dir.mkdir(parents=True, exist_ok=True)
    thumbnails.delete_thumbnail("ghost", tmp_settings)
