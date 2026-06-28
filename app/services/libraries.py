from __future__ import annotations
import logging
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
import httpx

from app.config import Settings
from app.models.library import (
    CatalogPage,
    Library,
    LibraryEntry,
    LibraryInvalidUrlError,
    LibraryParseError,
    LibraryUnreachableError,
    ValidateResult,
)
from app.categories import coerce_category
from app.services.thumbnails import cache_thumbnail

log = logging.getLogger(__name__)

USER_AGENT = "Cyberdeck/1.0 (+https://github.com/paprins/cyberdeck)"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # OPDS pages + meta4 are tiny; cap defends against runaway responses.

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/terms/",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_META4_NS = {"ml": "urn:ietf:params:xml:ns:metalink"}

_OPDS_PATH = "/catalog/v2/entries"
_ACQUISITION_RELS = (
    "http://opds-spec.org/acquisition/open-access",
    "http://opds-spec.org/acquisition",
)


# ── URL normalization ────────────────────────────────────────────────────────


def normalize_opds_url(raw_url: str) -> tuple[str, Optional[str]]:
    """Return (canonical_url, lang_filter).

    Accepts a browse-style URL with a fragment (e.g. ``#lang=nld``) or a
    direct OPDS endpoint. Fragments are parsed for filter params (the server
    never receives them via the browser, but the form may forward them).
    """
    raw = (raw_url or "").strip()
    if not raw:
        raise LibraryInvalidUrlError("URL is empty")
    if not raw.startswith(("http://", "https://")):
        raise LibraryInvalidUrlError("URL must be http or https")

    parts = urlparse(raw)
    if not parts.netloc:
        raise LibraryInvalidUrlError("URL has no host")

    lang = None
    if parts.fragment:
        frag_params = parse_qs(parts.fragment)
        lang_values = frag_params.get("lang")
        if lang_values:
            lang = lang_values[0]

    path = parts.path or "/"
    if _OPDS_PATH not in path:
        path = _OPDS_PATH

    canonical = urlunparse((parts.scheme, parts.netloc, path, "", "", ""))
    return canonical, lang


# ── HTTP seams (monkeypatchable in tests) ────────────────────────────────────


async def _fetch_bytes(url: str, timeout: float = 10.0) -> bytes:
    """Fetch a URL with a hard byte cap to defend against runaway responses."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            total = 0
            chunks: list[bytes] = []
            async for chunk in r.aiter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise LibraryParseError(
                        f"response exceeded {MAX_RESPONSE_BYTES} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks)


async def _fetch_catalog(url: str) -> bytes:
    """Fetch raw OPDS catalog bytes. Monkeypatchable test seam."""
    return await _fetch_bytes(url)


async def _fetch_meta4(url: str) -> bytes:
    """Fetch raw Metalink bytes. Monkeypatchable test seam."""
    return await _fetch_bytes(url)


# ── OPDS parsing ─────────────────────────────────────────────────────────────


def _text(elem, path: str) -> Optional[str]:
    child = elem.find(path, _NS)
    if child is None or child.text is None:
        return None
    txt = child.text.strip()
    return txt or None


def _parse_entry(elem, base_url: str) -> Optional[LibraryEntry]:
    entry_id = _text(elem, "atom:id")
    title = _text(elem, "atom:title")
    if not entry_id or not title:
        return None

    meta4_url = None
    size_bytes = None
    for link in elem.findall("atom:link", _NS):
        if link.get("rel") in _ACQUISITION_RELS:
            href = link.get("href", "").strip()
            if href:
                meta4_url = urljoin(base_url, href)
                length = link.get("length")
                if length and length.isdigit():
                    size_bytes = int(length)
                break
    if not meta4_url:
        return None

    acquisition_url = meta4_url[:-len(".meta4")] if meta4_url.endswith(".meta4") else meta4_url

    thumbnail_url = None
    for link in elem.findall("atom:link", _NS):
        if link.get("rel") == "http://opds-spec.org/image/thumbnail":
            href = link.get("href", "").strip()
            if href:
                thumbnail_url = urljoin(base_url, href)
            break

    summary = _text(elem, "atom:summary") or _text(elem, "atom:content")
    language = _text(elem, "dc:language") or _text(elem, "atom:language")

    return LibraryEntry(
        entry_id=entry_id,
        title=title,
        summary=summary,
        language=language,
        size_bytes=size_bytes,
        acquisition_url=acquisition_url,
        meta4_url=meta4_url,
        thumbnail_url=thumbnail_url,
    )


def _parse_catalog_page(
    library_id: str, raw_xml: bytes, base_url: str, start: int, count: int
) -> tuple[CatalogPage, Optional[str]]:
    """Parse an OPDS feed. Returns (page, feed_title)."""
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise LibraryParseError(f"OPDS XML parse error: {e}") from e

    tag = root.tag.split("}", 1)[-1] if "}" in root.tag else root.tag
    if tag != "feed":
        raise LibraryParseError("response is not an Atom feed")

    feed_title = _text(root, "atom:title")

    entries: list[LibraryEntry] = []
    for elem in root.findall("atom:entry", _NS):
        entry = _parse_entry(elem, base_url)
        if entry is not None:
            entries.append(entry)

    total = None
    tr = root.find("opensearch:totalResults", _NS)
    if tr is not None and tr.text and tr.text.strip().isdigit():
        total = int(tr.text.strip())

    page = CatalogPage(
        library_id=library_id,
        entries=entries,
        total_results=total,
        start=start,
        count=count,
    )
    return page, feed_title


# ── Metalink parsing ─────────────────────────────────────────────────────────


def _parse_meta4(raw_xml: bytes) -> dict:
    """Return ``{"checksum": "sha256:<hex>", "download_url": str, "size_bytes": int|None}``.

    Picks the mirror with the lowest ``priority`` attribute; falls back to the
    first ``<url>`` when no priority is set.
    """
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise LibraryParseError(f"Metalink XML parse error: {e}") from e

    checksum = None
    for h in root.findall(".//ml:hash", _META4_NS):
        htype = (h.get("type") or "").lower()
        if htype in ("sha-256", "sha256") and h.text and h.text.strip():
            checksum = "sha256:" + h.text.strip()
            break
    if not checksum:
        raise LibraryParseError("Metalink has no sha-256 hash")

    urls: list[tuple[int, str]] = []
    for u in root.findall(".//ml:url", _META4_NS):
        href = (u.text or "").strip()
        if not href:
            continue
        try:
            priority = int(u.get("priority", "999"))
        except ValueError:
            priority = 999
        urls.append((priority, href))
    if not urls:
        raise LibraryParseError("Metalink has no download URLs")
    urls.sort(key=lambda t: t[0])
    download_url = urls[0][1]

    size_bytes = None
    size_elem = root.find(".//ml:size", _META4_NS)
    if size_elem is not None and size_elem.text and size_elem.text.strip().isdigit():
        size_bytes = int(size_elem.text.strip())

    return {
        "checksum": checksum,
        "download_url": download_url,
        "size_bytes": size_bytes,
    }


# ── Module id derivation ─────────────────────────────────────────────────────


def module_id_from_acquisition_url(acquisition_url: str) -> str:
    """``https://.../mdwiki_en_all_maxi_2025-11.zim`` → ``mdwiki_en_all_maxi_2025-11``."""
    name = PurePosixPath(urlparse(acquisition_url).path).name
    stem = PurePosixPath(name).stem
    if not stem:
        raise LibraryParseError(f"cannot derive module id from URL: {acquisition_url}")
    return stem


# ── High-level public API ────────────────────────────────────────────────────


async def validate_library(raw_url: str) -> ValidateResult:
    """Probe an OPDS URL; return the resolved canonical URL and feed title.

    Tries the normalised URL first; on failure falls back to a host rewrite
    (``browse.X`` → ``X``). The first response that parses as an Atom feed
    wins.
    """
    canonical_url, _ = normalize_opds_url(raw_url)

    candidates = [canonical_url]
    parts = urlparse(canonical_url)
    if parts.netloc.startswith("browse."):
        stripped = parts.netloc[len("browse."):]
        candidates.append(urlunparse((parts.scheme, stripped, parts.path, "", "", "")))

    last_exc: Optional[Exception] = None
    for candidate in candidates:
        probe = candidate + "?count=1"
        try:
            raw = await _fetch_catalog(probe)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            continue
        try:
            page, _ = _parse_catalog_page(
                library_id="", raw_xml=raw, base_url=candidate, start=0, count=1
            )
        except LibraryParseError as exc:
            last_exc = exc
            continue
        # Use the URL origin as the human label; the feed <title> mutates per
        # query (e.g. Kiwix returns "Filtered Entries (count=1)" for our probe).
        cand_parts = urlparse(candidate)
        display_name = f"{cand_parts.scheme}://{cand_parts.netloc}"
        return ValidateResult(
            canonical_url=candidate,
            display_name=display_name,
            entry_count=page.total_results,
        )

    if isinstance(last_exc, LibraryParseError):
        raise last_exc
    raise LibraryUnreachableError(
        f"unable to reach OPDS catalog at {canonical_url}: {last_exc}"
    )


async def fetch_page(library: Library, start: int, count: int) -> CatalogPage:
    parts = urlparse(library.url)
    query_pairs = []
    if library.lang:
        query_pairs.append(("lang", library.lang))
    query_pairs.append(("start", str(start)))
    query_pairs.append(("count", str(count)))
    url = urlunparse(
        (parts.scheme, parts.netloc, parts.path, "", urlencode(query_pairs), "")
    )
    try:
        raw = await _fetch_catalog(url)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise LibraryUnreachableError(str(exc)) from exc
    page, _ = _parse_catalog_page(
        library_id=library.id, raw_xml=raw, base_url=library.url,
        start=start, count=count,
    )
    return page


def _assert_meta4_host_matches(meta4_url: str, library_url: str) -> None:
    """Reject meta4 URLs whose host is unrelated to the library's host.

    The Kiwix OPDS catalog references a CDN host (e.g. ``lbo.download.kiwix.org``)
    rather than the catalog host itself, so the check accepts the catalog host,
    its parent domain, and any subdomain of the parent.
    """
    meta_host = urlparse(meta4_url).hostname or ""
    lib_host = urlparse(library_url).hostname or ""
    if not meta_host or not lib_host:
        raise LibraryParseError(f"meta4 URL has no host: {meta4_url}")
    if meta_host == lib_host:
        return
    lib_parts = lib_host.split(".")
    parent = ".".join(lib_parts[-2:]) if len(lib_parts) >= 2 else lib_host
    if meta_host == parent or meta_host.endswith("." + parent):
        return
    raise LibraryParseError(
        f"meta4 URL host {meta_host!r} does not match library host {lib_host!r}"
    )


async def resolve_entry(
    entry: LibraryEntry, library: Library, settings: Settings
) -> dict:
    """Fetch + parse the entry's ``.meta4`` and return a Module-shaped dict.

    Also caches the entry's thumbnail to disk so the home page card image
    remains available when the device is offline.
    """
    _assert_meta4_host_matches(entry.meta4_url, library.url)
    try:
        raw = await _fetch_meta4(entry.meta4_url)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise LibraryUnreachableError(str(exc)) from exc

    parsed = _parse_meta4(raw)
    module_id = module_id_from_acquisition_url(entry.acquisition_url)
    size_bytes = parsed["size_bytes"] or entry.size_bytes or 0
    cached_image = await cache_thumbnail(module_id, entry.thumbnail_url, settings)

    return {
        "id": module_id,
        "display_name": entry.title,
        # User-assigned in the import wizard (carried on LibraryEntry.category);
        # OPDS catalogs don't supply one, so this coerces to the reference slug.
        "category": coerce_category(entry.category),
        "description": entry.summary or "",
        "latest_version": module_id,
        "size_gb": round(size_bytes / (1024 ** 3), 3),
        "checksum": parsed["checksum"],
        "download_url": parsed["download_url"],
        "image": cached_image,
        "source_library_id": library.id,
    }
