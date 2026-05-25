from __future__ import annotations
import asyncio
import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

import httpx

from app.config import Settings
from app.models.registry import Module
from app.services.content import extract_static_package
from app.services.registry import load_registry, save_registry
from app.services.signing import SignatureError, verify_minisign

log = logging.getLogger(__name__)

_active_tasks: dict[str, asyncio.Task] = {}
_pending: list[str] = []


# ── Path helpers ──────────────────────────────────────────────────────────────

def _final_path(module: Module, settings: Settings) -> Path:
    if module.kind == "mbtiles":
        return settings.maps_dir / f"{module.id}.mbtiles"
    if module.kind == "static":
        return settings.content_dir / module.id
    return settings.zim_dir / f"{module.id}.zim"


def _sig_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.minisig"


def _trusted_comment(module: Module) -> str:
    return f"cyberdeck content {module.id} v{module.latest_version}"


def _part_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.part"


def _mismatch_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.mismatch"


def _total_path(module: Module, settings: Settings) -> Path:
    """Sidecar holding the real download total in bytes, captured from the
    HTTP response. Authoritative when present — overrides registry size_gb."""
    return settings.downloads_dir / f"{module.id}.total"


def _read_total_sidecar(module: Module, settings: Settings) -> int | None:
    p = _total_path(module, settings)
    if not p.exists():
        return None
    try:
        v = int(p.read_text().strip())
        return v if v > 0 else None
    except (OSError, ValueError):
        return None


def _parse_total_from_response(r: "httpx.Response") -> int | None:
    """Derive total file size from response headers. Returns None if unknown."""
    if r.status_code == 206:
        # Content-Range: bytes <start>-<end>/<total>   (total may be '*')
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            tail = cr.rsplit("/", 1)[1].strip()
            if tail.isdigit():
                return int(tail)
        return None
    if r.status_code == 200:
        cl = r.headers.get("Content-Length")
        if cl and cl.isdigit():
            return int(cl)
    return None


# ── Status and storage ────────────────────────────────────────────────────────

def get_download_status(module: Module, settings: Settings) -> dict:
    total_bytes = _read_total_sidecar(module, settings) or int(module.size_gb * 1024 ** 3)
    part = _part_path(module, settings)
    final = _final_path(module, settings)

    if final.exists():
        return {
            "status": "installed",
            "bytes_downloaded": total_bytes,
            "total_bytes": total_bytes,
            "pct": 100,
        }

    bytes_downloaded = part.stat().st_size if part.exists() else 0
    pct = min(int(bytes_downloaded * 100 / total_bytes), 100) if total_bytes > 0 else 0

    mismatch = _mismatch_path(module, settings)
    if part.exists() and mismatch.exists():
        return {
            "status": "checksum_mismatch",
            "actual_checksum": mismatch.read_text().strip(),
            "expected_checksum": module.checksum,
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": 100,
        }

    if module.id in _active_tasks:
        return {
            "status": "downloading",
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": pct,
        }

    if module.id in _pending:
        return {
            "status": "queued",
            "bytes_downloaded": 0,
            "total_bytes": total_bytes,
            "pct": 0,
        }

    if part.exists():
        return {
            "status": "interrupted",
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": pct,
        }

    return {
        "status": "not_installed",
        "bytes_downloaded": 0,
        "total_bytes": total_bytes,
        "pct": 0,
    }


def get_storage_info(settings: Settings) -> dict:
    usage = shutil.disk_usage(settings.data_dir)
    return {"used_bytes": usage.used, "free_bytes": usage.free}


# ── Install / uninstall / activate / deactivate ───────────────────────────────

async def uninstall_module(module: Module, settings: Settings) -> None:
    await cancel_download(module.id)
    part = _part_path(module, settings)
    final = _final_path(module, settings)
    mismatch = _mismatch_path(module, settings)
    if part.exists():
        part.unlink()
    if mismatch.exists():
        mismatch.unlink()
    if final.exists():
        if module.kind == "static":
            shutil.rmtree(final, ignore_errors=True)
        else:
            final.unlink()
    _total_path(module, settings).unlink(missing_ok=True)
    _sig_path(module, settings).unlink(missing_ok=True)
    if module.kind == "zim":
        _kiwix_remove(module, settings)
    _signal_service(module)
    # Cached images and any other per-module cache state go too — the row is
    # being removed; nothing else references the cache dir.
    from app.services.thumbnails import delete_thumbnail
    delete_thumbnail(module.id, settings)
    registry = load_registry(settings)
    registry.modules = [m for m in registry.modules if m.id != module.id]
    save_registry(settings, registry)


async def activate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, True)
    if module.kind == "zim":
        _kiwix_add(module, settings)
    _signal_service(module)


async def deactivate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, False)
    if module.kind == "zim":
        _kiwix_remove(module, settings)
    _signal_service(module)


async def accept_checksum_mismatch(module: Module, settings: Settings) -> None:
    mismatch = _mismatch_path(module, settings)
    part = _part_path(module, settings)
    if not mismatch.exists() or not part.exists():
        raise RuntimeError(f"No checksum mismatch pending for {module.id}")
    actual_digest = mismatch.read_text().strip()
    final = _final_path(module, settings)
    final.parent.mkdir(parents=True, exist_ok=True)
    part.rename(final)
    mismatch.unlink()
    registry = load_registry(settings)
    for m in registry.modules:
        if m.id == module.id:
            m.installed_version = module.latest_version
            m.installed_checksum = actual_digest
            m.active = True
            break
    save_registry(settings, registry)
    if module.kind == "zim":
        _kiwix_add(module, settings)
    _signal_service(module)


async def discard_checksum_mismatch(module: Module, settings: Settings) -> None:
    _part_path(module, settings).unlink(missing_ok=True)
    _mismatch_path(module, settings).unlink(missing_ok=True)
    _total_path(module, settings).unlink(missing_ok=True)
    registry = load_registry(settings)
    registry.modules = [m for m in registry.modules if m.id != module.id]
    save_registry(settings, registry)


# ── Kiwix library.xml management ──────────────────────────────────────────────

_LIBRARY_EMPTY = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<library version="20110515">\n'
    '</library>\n'
)


def init_kiwix_library(settings: Settings) -> None:
    library_xml = settings.zim_dir / "library.xml"
    if not library_xml.exists():
        library_xml.parent.mkdir(parents=True, exist_ok=True)
        library_xml.write_text(_LIBRARY_EMPTY, encoding="utf-8")


def _kiwix_add(module: Module, settings: Settings) -> None:
    import uuid
    import xml.etree.ElementTree as ET
    zim_path = settings.zim_dir / f"{module.id}.zim"
    if not zim_path.exists():
        log.warning("kiwix_add: %s not found, skipping library update", zim_path)
        return
    # Self-bootstrap if the file is missing — fixes the silent no-op that
    # would happen if kiwix-serve hadn't yet created its empty library.xml.
    init_kiwix_library(settings)
    library_xml = settings.zim_dir / "library.xml"
    tree = ET.parse(library_xml)
    root = tree.getroot()
    for book in root.findall("book"):
        if book.get("path") == f"{module.id}.zim":
            return
    ET.SubElement(root, "book", {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, module.id)),
        "path": f"{module.id}.zim",
        "name": module.id,
    })
    tree.write(str(library_xml), encoding="unicode", xml_declaration=True)
    _run(["pkill", "-HUP", "kiwix-serve"])


def reconcile_kiwix_library(settings: Settings) -> None:
    """Make library.xml match the on-disk state: add entries for installed ZIM
    modules in the registry whose .zim file exists, and remove entries whose
    .zim file is gone.

    Idempotent and conservative — entries pointing at existing files but not in
    the registry are kept (covers manually-copied ZIMs). Run at startup so an
    install that raced kiwix-serve coming up still ends up registered.
    """
    import uuid
    import xml.etree.ElementTree as ET
    init_kiwix_library(settings)
    library_xml = settings.zim_dir / "library.xml"
    tree = ET.parse(library_xml)
    root = tree.getroot()

    existing_paths = {book.get("path"): book for book in root.findall("book")}
    mutated = False

    registry = load_registry(settings)
    for m in registry.modules:
        if m.kind != "zim" or not m.is_installed:
            continue
        path_attr = f"{m.id}.zim"
        if not (settings.zim_dir / path_attr).exists():
            continue
        if path_attr in existing_paths:
            continue
        ET.SubElement(root, "book", {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, m.id)),
            "path": path_attr,
            "name": m.id,
        })
        mutated = True

    for path_attr, book in list(existing_paths.items()):
        if not path_attr or not (settings.zim_dir / path_attr).exists():
            root.remove(book)
            mutated = True

    if mutated:
        tree.write(str(library_xml), encoding="unicode", xml_declaration=True)


def _kiwix_remove(module: Module, settings: Settings) -> None:
    import xml.etree.ElementTree as ET
    library_xml = settings.zim_dir / "library.xml"
    if not library_xml.exists():
        return
    tree = ET.parse(library_xml)
    root = tree.getroot()
    for book in root.findall("book"):
        if book.get("path") == f"{module.id}.zim":
            root.remove(book)
            break
    tree.write(str(library_xml), encoding="unicode", xml_declaration=True)
    _run(["pkill", "-HUP", "kiwix-serve"])


def _signal_service(module: Module) -> None:
    if module.kind == "mbtiles":
        _run(["pkill", "-HUP", "mbtileserver"])


def _run(cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
        if result.returncode != 0:
            log.debug("%s exited %d", cmd[0], result.returncode)
    except FileNotFoundError:
        log.debug("%s not found, skipping signal", cmd[0])


# ── cancel_download (needed by uninstall) ─────────────────────────────────────

async def cancel_download(module_id: str) -> None:
    if module_id in _pending:
        _pending.remove(module_id)
        return
    task = _active_tasks.get(module_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _active_tasks.pop(module_id, None)


# ── start_download / check_for_updates ───────────────────────────────────────

async def start_download(module: Module, settings: Settings) -> None:
    if not module.download_url:
        raise ValueError(f"Module {module.id} has no download_url")
    if module.id in _active_tasks or module.id in _pending:
        return
    if _active_tasks:
        _pending.append(module.id)
        return
    task = asyncio.create_task(_download_task(module, settings))
    _active_tasks[module.id] = task


def _drain_pending(settings: Settings) -> None:
    """Start the next pending download. No-op if one is active or the queue is empty."""
    if _active_tasks:
        return
    while _pending:
        next_id = _pending.pop(0)
        registry = load_registry(settings)
        module = next((m for m in registry.modules if m.id == next_id), None)
        if module is None or not module.download_url:
            continue
        task = asyncio.create_task(_download_task(module, settings))
        _active_tasks[module.id] = task
        return


async def _download_task(module: Module, settings: Settings) -> None:
    part = _part_path(module, settings)
    part.parent.mkdir(parents=True, exist_ok=True)
    offset = part.stat().st_size if part.exists() else 0
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}
            async with client.stream(
                "GET", module.download_url, headers=headers, timeout=30.0
            ) as r:
                r.raise_for_status()
                if offset > 0 and r.status_code == 200:
                    part.unlink(missing_ok=True)
                    part.parent.mkdir(parents=True, exist_ok=True)
                    offset = 0
                total = _parse_total_from_response(r)
                if total:
                    _total_path(module, settings).write_text(str(total))
                with part.open("ab") as f:
                    async for chunk in r.aiter_bytes(65536):
                        f.write(chunk)

        if module.kind == "static":
            await _finalize_static(module, settings, part)
        else:
            await _finalize_hashed(module, settings, part)

    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Download failed for %s", module.id)
    finally:
        _active_tasks.pop(module.id, None)
        _drain_pending(settings)


async def _finalize_hashed(module: Module, settings: Settings, part: Path) -> None:
    sha = hashlib.sha256()
    with part.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    digest = f"sha256:{sha.hexdigest()}"
    if digest != module.checksum:
        _mismatch_path(module, settings).write_text(digest)
        log.warning(
            "Checksum mismatch for %s: expected %s, got %s",
            module.id, module.checksum, digest,
        )
        return

    final = _final_path(module, settings)
    final.parent.mkdir(parents=True, exist_ok=True)
    part.rename(final)
    _total_path(module, settings).unlink(missing_ok=True)

    _mark_installed(module, settings, digest)

    if module.kind == "zim":
        _kiwix_add(module, settings)
    _signal_service(module)


async def _finalize_static(module: Module, settings: Settings, part: Path) -> None:
    """Fetch the .minisig sidecar, verify, then extract into content_dir."""
    if not module.signature_url:
        log.error("Static module %s has no signature_url", module.id)
        return
    sig_path = _sig_path(module, settings)
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            r = await client.get(module.signature_url)
            r.raise_for_status()
            sig_path.write_bytes(r.content)
        verify_minisign(
            tarball_path=part,
            sig_path=sig_path,
            expected_trusted_comment=_trusted_comment(module),
            pubkey_path=settings.release_pubkey_path,
        )
        final_dir = _final_path(module, settings)
        extract_static_package(part, final_dir)
        bundled_image = _resolve_bundled_image(module, settings, final_dir)
        _mark_installed(module, settings, checksum=None, image=bundled_image)
    except (httpx.RequestError, httpx.HTTPStatusError, SignatureError) as exc:
        log.error("Static install failed for %s: %s", module.id, exc)
    except Exception:
        # extract_static_package raises on bad tarball, ExtractionError, OSError.
        # Cleanup must run regardless — the finally block handles it.
        log.exception("Static extraction failed for %s", module.id)
    finally:
        part.unlink(missing_ok=True)
        sig_path.unlink(missing_ok=True)
        _total_path(module, settings).unlink(missing_ok=True)


_BUNDLED_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "gif")


def _resolve_bundled_image(
    module: Module, settings: Settings, final_dir: Path
) -> str | None:
    """Resolve a card image bundled inside the extracted package and return a
    URL that serves it directly from ``content_dir`` (no copy). Returns
    ``None`` if no usable bundled image is found.

    Bundled files are already on disk after extraction; serving them via the
    existing ``/content/{id}/...`` route avoids duplicating bytes into the
    cache dir. The cache dir is reserved for things the device fetched
    separately (e.g. HTTP image_url thumbnails).

    Precedence: a manifest ``image_url`` that was an HTTP URL (already cached
    at register time) wins — this helper is a no-op in that case. Otherwise
    the rule is: ``image_path`` (the relative path captured from the manifest)
    if set, else default to ``card.{ext}`` at the package root.
    """
    if module.image:
        return None  # HTTP-cached image already wins
    if not final_dir.exists():
        return None

    final_root = final_dir.resolve()
    if module.image_path:
        candidate = (final_dir / module.image_path).resolve()
        try:
            candidate.relative_to(final_root)
        except ValueError:
            log.warning(
                "image_path %r for %s escapes package root; ignoring",
                module.image_path, module.id,
            )
            return None
        if not candidate.is_file():
            log.debug("image_path %r for %s not found in package", module.image_path, module.id)
            return None
        source = candidate
    else:
        source = next(
            (final_dir / f"card.{ext}" for ext in _BUNDLED_IMAGE_EXTS
             if (final_dir / f"card.{ext}").is_file()),
            None,
        )
        if source is None:
            return None

    ext = source.suffix.lower().lstrip(".")
    if ext not in _BUNDLED_IMAGE_EXTS:
        log.debug("bundled image %s has unsupported extension %r", source, ext)
        return None

    rel_path = source.resolve().relative_to(final_root)
    return f"/content/{module.id}/{rel_path.as_posix()}"


def rescan_bundled_image(module: Module, settings: Settings) -> str | None:
    """Look for a bundled card image inside an already-installed static
    package and copy it into ``images_dir``. Returns the local URL or None.

    Used by library refresh to heal modules installed before the bundled-image
    feature shipped (or whose image was cleared by a stale registry merge).
    No-op for non-static kinds.
    """
    if module.kind != "static":
        return None
    return _resolve_bundled_image(module, settings, _final_path(module, settings))


def _mark_installed(
    module: Module, settings: Settings, checksum: str | None,
    image: str | None = None,
) -> None:
    registry = load_registry(settings)
    for m in registry.modules:
        if m.id == module.id:
            m.installed_version = module.latest_version
            m.installed_checksum = checksum
            m.active = True
            if image is not None:
                m.image = image
            break
    save_registry(settings, registry)
