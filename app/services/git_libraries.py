"""Git-backed library: fetch ``manifest.json`` from a public Git repo and
expose its packages as ``LibraryEntry`` records that resolve to ``static``
Modules.

Supports github.com, gitlab.com, and codeberg.org. To add a new host, add an
entry to ``_GIT_HOSTS``.

Parallels :mod:`app.services.libraries` (OPDS); same public surface:
``validate_library``, ``fetch_page``, ``resolve_entry``. The ``_fetch_manifest``
seam is module-level for monkeypatching in tests.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse

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
from app.services.libraries import _fetch_bytes
from app.services.thumbnails import cache_thumbnail

log = logging.getLogger(__name__)

GitType = Literal["github", "gitlab", "codeberg"]
LibraryType = Literal["opds", "github", "gitlab", "codeberg"]

_REPO_RE = re.compile(r"^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)$")


@dataclass(frozen=True)
class _HostConfig:
    raw_template: str
    allowed_asset_hosts: frozenset[str]
    url_hosts: frozenset[str]
    accepts_shorthand: bool
    # If True, segments past {owner}/{repo} are silently dropped (trailing
    # branch/blob/tree paths). If False, extra segments are an error — gitlab
    # and codeberg use deeper paths for groups/subgroups, which we do not
    # support today.
    accepts_trailing_path: bool


_GIT_HOSTS: dict[str, _HostConfig] = {
    "github": _HostConfig(
        raw_template="https://raw.githubusercontent.com/{repo}/main/manifest.json",
        allowed_asset_hosts=frozenset({
            "github.com", "objects.githubusercontent.com", "raw.githubusercontent.com",
        }),
        url_hosts=frozenset({"github.com", "raw.githubusercontent.com"}),
        accepts_shorthand=True,
        accepts_trailing_path=True,
    ),
    "gitlab": _HostConfig(
        raw_template="https://gitlab.com/{repo}/-/raw/main/manifest.json",
        allowed_asset_hosts=frozenset({"gitlab.com", "assets.gitlab-static.net"}),
        url_hosts=frozenset({"gitlab.com"}),
        accepts_shorthand=False,
        accepts_trailing_path=False,
    ),
    "codeberg": _HostConfig(
        raw_template="https://codeberg.org/{repo}/raw/branch/main/manifest.json",
        allowed_asset_hosts=frozenset({"codeberg.org"}),
        url_hosts=frozenset({"codeberg.org"}),
        accepts_shorthand=False,
        accepts_trailing_path=False,
    ),
}


def detect_type(raw_url: str) -> LibraryType:
    """Pick a library type from the URL alone. Defaults to ``opds``.

    Mirror this logic in the frontend (`detectType` in the LIBRARIES Alpine
    component) so the UI can preview the detected type before submit.
    """
    raw = (raw_url or "").strip()
    if not raw:
        return "opds"
    if _REPO_RE.match(raw):
        return "github"
    if not raw.startswith(("http://", "https://")):
        return "opds"
    host = (urlparse(raw).hostname or "").lower()
    for git_type, cfg in _GIT_HOSTS.items():
        if host in cfg.url_hosts:
            return git_type  # type: ignore[return-value]
    return "opds"


def normalize_git_url(raw_url: str, git_type: GitType) -> str:
    """Return the canonical ``owner/repo`` shorthand for the given Git host.

    Subgroup paths (e.g. gitlab ``{group}/{sub}/{repo}``) are rejected with a
    clear error so the user knows the limit.
    """
    raw = (raw_url or "").strip()
    if not raw:
        raise LibraryInvalidUrlError("URL is empty")
    cfg = _GIT_HOSTS.get(git_type)
    if cfg is None:
        raise LibraryInvalidUrlError(f"unknown git host type: {git_type}")
    if cfg.accepts_shorthand and _REPO_RE.match(raw):
        return raw
    if raw.startswith(("http://", "https://")):
        parts = urlparse(raw)
        host = (parts.hostname or "").lower()
        segments = [s for s in parts.path.split("/") if s]
        if host in cfg.url_hosts:
            if len(segments) > 2 and not cfg.accepts_trailing_path:
                raise LibraryInvalidUrlError(
                    f"only {{owner}}/{{repo}} paths are supported on {host} (no subgroups)"
                )
            if len(segments) >= 2:
                owner, repo = segments[0], segments[1]
                if _REPO_RE.match(f"{owner}/{repo}"):
                    return f"{owner}/{repo}"
    raise LibraryInvalidUrlError(f"not a {git_type} repo reference: {raw_url}")


def manifest_url_for(repo_shorthand: str, git_type: GitType) -> str:
    cfg = _GIT_HOSTS.get(git_type)
    if cfg is None:
        raise LibraryInvalidUrlError(f"unknown git host type: {git_type}")
    return cfg.raw_template.format(repo=repo_shorthand)


async def _fetch_manifest(url: str) -> dict:
    """Fetch + parse a manifest. Monkeypatchable test seam."""
    raw = await _fetch_bytes(url)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise LibraryParseError(f"manifest is not valid JSON: {exc}") from exc


def _package_to_entry(pkg: dict, git_type: GitType) -> Optional[LibraryEntry]:
    try:
        return LibraryEntry(
            entry_id=pkg["id"],
            kind=git_type,
            title=pkg["display_name"],
            summary=pkg.get("description"),
            language=pkg.get("language"),
            size_bytes=pkg.get("size_bytes"),
            thumbnail_url=pkg.get("image_url"),
            tarball_url=pkg["tarball_url"],
            signature_url=pkg["signature_url"],
            entry=pkg["entry"],
            version=pkg["version"],
            category=pkg.get("category"),
        )
    except (KeyError, ValueError) as exc:
        log.debug("skipping malformed %s package: %s", git_type, exc)
        return None


def _parse_manifest(
    data: dict, git_type: GitType
) -> tuple[list[LibraryEntry], Optional[str]]:
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise LibraryParseError("manifest has no 'packages' list")
    entries: list[LibraryEntry] = []
    for pkg in packages:
        if isinstance(pkg, dict):
            entry = _package_to_entry(pkg, git_type)
            if entry is not None:
                entries.append(entry)
    title = data.get("title") if isinstance(data.get("title"), str) else None
    return entries, title


async def validate_library(raw_url: str, git_type: GitType = "github") -> ValidateResult:
    repo = normalize_git_url(raw_url, git_type)
    url = manifest_url_for(repo, git_type)
    try:
        data = await _fetch_manifest(url)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise LibraryUnreachableError(str(exc)) from exc
    entries, title = _parse_manifest(data, git_type)
    return ValidateResult(
        canonical_url=repo,
        display_name=title or repo,
        entry_count=len(entries),
    )


async def fetch_page(library: Library, start: int, count: int) -> CatalogPage:
    git_type: GitType = library.type  # type: ignore[assignment]
    url = manifest_url_for(library.url, git_type)
    try:
        data = await _fetch_manifest(url)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise LibraryUnreachableError(str(exc)) from exc
    entries, _ = _parse_manifest(data, git_type)
    sliced = entries[start:start + count]
    return CatalogPage(
        library_id=library.id,
        entries=sliced,
        total_results=len(entries),
        start=start,
        count=count,
    )


def _assert_asset_host(asset_url: str, git_type: GitType) -> None:
    cfg = _GIT_HOSTS[git_type]
    host = (urlparse(asset_url).hostname or "").lower()
    if host not in cfg.allowed_asset_hosts:
        raise LibraryParseError(f"asset host {host!r} not in {git_type} allow-list")


async def resolve_entry(
    entry: LibraryEntry, library: Library, settings: Settings
) -> dict:
    """Build a Module-shaped dict from a git entry.

    No additional network calls (the manifest entry already has everything);
    only the thumbnail is fetched + cached so the home-page card image works
    offline.
    """
    git_type: GitType = library.type  # type: ignore[assignment]
    _assert_asset_host(entry.tarball_url or "", git_type)
    _assert_asset_host(entry.signature_url or "", git_type)

    # image_url in the manifest can be either an HTTP(S) URL (fetched now and
    # cached) or a relative path inside the package tarball (resolved later at
    # install time, when the package is on disk). If omitted, the install step
    # falls back to looking for ``card.{png,jpg,jpeg,webp,gif}`` at the package
    # root.
    raw_image = entry.thumbnail_url
    if raw_image and raw_image.startswith(("http://", "https://")):
        cached_image = await cache_thumbnail(entry.entry_id, raw_image, settings)
        image_path = None
    else:
        cached_image = None
        image_path = raw_image or None

    size_gb = round((entry.size_bytes or 0) / (1024 ** 3), 3)
    return {
        "id": entry.entry_id,
        "display_name": entry.title,
        # User-assigned in the import wizard (carried on LibraryEntry.category);
        # coerced so an unknown/legacy manifest value can't crash registration.
        "category": coerce_category(entry.category),
        "description": entry.summary or "",
        "latest_version": entry.version,
        "size_gb": size_gb,
        "kind": "static",
        "download_url": entry.tarball_url,
        "signature_url": entry.signature_url,
        "entry": entry.entry,
        "image": cached_image,
        "image_path": image_path,
        "source_library_id": library.id,
    }
