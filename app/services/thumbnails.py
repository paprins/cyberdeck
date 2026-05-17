from __future__ import annotations
import logging
from typing import Optional

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

USER_AGENT = "Cyberdeck/1.0 (+https://github.com/paprins/cyberdeck)"
MAX_THUMBNAIL_BYTES = 4 * 1024 * 1024  # OPDS thumbnails are tiny; cap defends against runaway responses.
FETCH_TIMEOUT = 8.0
LOCAL_URL_PREFIX = "/data-static/images/"

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


async def cache_thumbnail(
    module_id: str, url: Optional[str], settings: Settings
) -> Optional[str]:
    """Cache a remote thumbnail locally; return the local ``/data-static`` URL.

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
    images_dir = settings.images_dir
    if images_dir.exists():
        existing = next(iter(images_dir.glob(f"{module_id}.*")), None)
        if existing is not None:
            return f"{LOCAL_URL_PREFIX}{existing.name}"

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

    images_dir.mkdir(parents=True, exist_ok=True)
    target = images_dir / f"{module_id}.{ext}"
    target.write_bytes(data)
    return f"{LOCAL_URL_PREFIX}{module_id}.{ext}"


def delete_thumbnail(module_id: str, settings: Settings) -> None:
    """Remove any cached thumbnail file for the given module id."""
    images_dir = settings.images_dir
    if not images_dir.exists():
        return
    for path in images_dir.glob(f"{module_id}.*"):
        path.unlink(missing_ok=True)
