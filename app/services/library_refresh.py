"""Refresh ``latest_version`` (and other metadata) for already-registered
modules by re-fetching each Git-host library's manifest.

OPDS libraries are skipped: Kiwix encodes the version in the module id itself
(e.g. ``mdwiki_..._2025-11``), so a "new version" is a different module rather
than an updated one — there's no ``has_update`` semantics to refresh.

Mirrors the firmware-refresh pattern in :mod:`app.services.notifications`: a
small module-level cache with an in-flight lock and a TTL.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from app.config import Settings
from app.models.library import Library, LibraryError, LibraryNotFoundError
from app.models.registry import Registry
import app.services.git_libraries as git_svc
import app.services.packages as packages_svc
import app.services.registry as registry_svc

log = logging.getLogger(__name__)

# How often opportunistic refreshes are allowed. Manual refresh ignores this.
REFRESH_TTL_S = 15 * 60


@dataclass
class _RefreshState:
    in_flight: bool = False
    checked_at: Optional[float] = None


_state = _RefreshState()


@dataclass
class RefreshResult:
    refreshed_libraries: int = 0
    updated_modules: int = 0
    errors: list[str] = field(default_factory=list)


def _is_stale() -> bool:
    if _state.checked_at is None:
        return True
    return (time.monotonic() - _state.checked_at) > REFRESH_TTL_S


def _known_module_ids(registry: Registry, library_id: str) -> set[str]:
    return {m.id for m in registry.modules if m.source_library_id == library_id}


async def _refresh_one(
    library: Library, registry: Registry, cfg: Settings, result: RefreshResult
) -> None:
    """Refresh a single Git-host library. OPDS libraries are silently skipped."""
    if library.type == "opds":
        return
    known = _known_module_ids(registry, library.id)
    if not known:
        return  # library is registered but has no installed modules yet
    try:
        page = await git_svc.fetch_page(library, start=0, count=10000)
    except LibraryError as exc:
        log.warning("refresh %s failed: %s", library.id, exc)
        result.errors.append(f"{library.display_name}: {exc}")
        return

    refreshed: list[dict] = []
    for entry in page.entries:
        if entry.entry_id not in known:
            continue
        try:
            refreshed.append(await git_svc.resolve_entry(entry, library, cfg))
        except LibraryError as exc:
            log.warning("refresh %s/%s failed: %s", library.id, entry.entry_id, exc)
            result.errors.append(f"{entry.entry_id}: {exc}")

    if refreshed:
        registry_svc.merge_remote_manifest(cfg, refreshed)
        result.updated_modules += len(refreshed)

    # Heal already-installed modules whose Module.image is null but whose
    # extracted package happens to bundle a card.{png,jpg,...}. Catches both
    # the migration case (installed before the bundled-image feature shipped)
    # and the user who added a card to a future release.
    reg = registry_svc.load_registry(cfg)
    mutated = False
    for m in reg.modules:
        if m.source_library_id != library.id:
            continue
        if m.kind != "static" or m.image is not None:
            continue
        url = packages_svc.rescan_bundled_image(m, cfg)
        if url:
            m.image = url
            mutated = True
    if mutated:
        registry_svc.save_registry(cfg, reg)

    result.refreshed_libraries += 1


async def refresh_all_libraries(cfg: Settings) -> RefreshResult:
    """Re-fetch each Git-host library's manifest and merge updated metadata
    for any module already in the registry that originated from it.

    Always runs (no TTL / in-flight gating); use :func:`maybe_refresh_libraries`
    for the opportunistic variant.
    """
    result = RefreshResult()
    registry = registry_svc.load_registry(cfg)
    for library in registry.libraries:
        await _refresh_one(library, registry, cfg, result)
    _state.checked_at = time.monotonic()
    return result


async def refresh_one_library(library_id: str, cfg: Settings) -> RefreshResult:
    """Refresh a single library by id. Raises ``LibraryNotFoundError`` if the
    id isn't in the registry.

    Always runs (no TTL / in-flight gating) since this is an explicit user
    action; does not update the opportunistic-refresh timestamp so the next
    visit can still trigger a full refresh of any libraries the user didn't
    poke individually.
    """
    registry = registry_svc.load_registry(cfg)
    library = next((lib for lib in registry.libraries if lib.id == library_id), None)
    if library is None:
        raise LibraryNotFoundError(library_id)
    result = RefreshResult()
    await _refresh_one(library, registry, cfg, result)
    return result


async def maybe_refresh_libraries(cfg: Settings) -> Optional[RefreshResult]:
    """Opportunistic refresh: respects in-flight lock and TTL.

    Returns ``None`` when the call was skipped (still warm or already running).
    Callers (typically request handlers) should schedule this with
    ``asyncio.create_task`` and ignore the result.
    """
    if _state.in_flight or not _is_stale():
        return None
    _state.in_flight = True
    try:
        return await refresh_all_libraries(cfg)
    except Exception:
        log.exception("library refresh failed")
        _state.checked_at = time.monotonic()  # back off even on failure
        return None
    finally:
        _state.in_flight = False


def reset_state_for_tests() -> None:
    """Test helper: clear the in-flight lock and TTL state."""
    _state.in_flight = False
    _state.checked_at = None
