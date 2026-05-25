from __future__ import annotations
import logging
import shutil
from pathlib import Path
from typing import Optional

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

USER_AGENT = "Cyberdeck/1.0 (+https://github.com/paprins/cyberdeck)"
MAX_THUMBNAIL_BYTES = 4 * 1024 * 1024  # OPDS thumbnails are tiny; cap defends against runaway responses.
FETCH_TIMEOUT = 8.0
LOCAL_URL_PREFIX = "/data-cache/"
# HTTP-fetched thumbnails have no tarball-relative path, so they get a stable
# synthetic name inside the per-module cache dir. Keeps cache layout uniform
# whether the image came from the manifest's image_url or a bundled card.png.
_HTTP_FILENAME_STEM = "cover"

# SVG is intentionally excluded: served as a raw static asset it carries an
# XSS surface (embedded scripts), and OPDS catalogs do not use it.
_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


async def _fetch_image(url: str) -> tuple[bytes, str]:
    """Fetch image bytes and Content-Type. Monkeypatchable test seam."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_THUMBNAIL_BYTES:
                raise ValueError(f"thumbnail exceeds {MAX_THUMBNAIL_BYTES} bytes")
            content_type = r.headers.get("Content-Type", "")
            total = 0
            chunks: list[bytes] = []
            async for chunk in r.aiter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > MAX_THUMBNAIL_BYTES:
                    raise ValueError(f"thumbnail exceeds {MAX_THUMBNAIL_BYTES} bytes")
                chunks.append(chunk)
            return b"".join(chunks), content_type


def _ext_for_content_type(content_type: str) -> Optional[str]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return _MIME_TO_EXT.get(media_type)


def _module_cache_dir(module_id: str, settings: Settings) -> Path:
    return settings.cache_dir / module_id


async def cache_thumbnail(
    module_id: str, url: Optional[str], settings: Settings
) -> Optional[str]:
    """Cache a remote thumbnail locally; return the local ``/data-cache`` URL.

    Idempotent in two ways: returns the input unchanged when it is already a
    local URL, and returns the existing local URL when a cached file is already
    on disk (so repeated manifest refreshes do not re-download).

    Returns ``None`` on any failure (network, oversized, unsupported MIME) so
    callers can fall back to the category icon.
    """
    if url and url.startswith(LOCAL_URL_PREFIX):
        return url

    # Check disk first so a previously-cached file survives even when the
    # upstream manifest later drops the image (sends null/omits the field).
    mod_dir = _module_cache_dir(module_id, settings)
    if mod_dir.exists():
        existing = next(iter(mod_dir.glob(f"{_HTTP_FILENAME_STEM}.*")), None)
        if existing is not None:
            return f"{LOCAL_URL_PREFIX}{module_id}/{existing.name}"

    if not url:
        return None

    try:
        data, content_type = await _fetch_image(url)
    except Exception as exc:
        log.debug("thumbnail fetch failed for %s: %s", module_id, exc)
        return None

    ext = _ext_for_content_type(content_type)
    if not ext:
        log.debug("thumbnail unsupported MIME for %s: %r", module_id, content_type)
        return None

    mod_dir.mkdir(parents=True, exist_ok=True)
    target = mod_dir / f"{_HTTP_FILENAME_STEM}.{ext}"
    target.write_bytes(data)
    return f"{LOCAL_URL_PREFIX}{module_id}/{_HTTP_FILENAME_STEM}.{ext}"


def delete_thumbnail(module_id: str, settings: Settings) -> None:
    """Remove the per-module cache directory (image + anything else cached)."""
    shutil.rmtree(_module_cache_dir(module_id, settings), ignore_errors=True)
