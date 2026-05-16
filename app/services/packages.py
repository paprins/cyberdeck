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
from app.services.registry import load_registry, save_registry, merge_remote_manifest

log = logging.getLogger(__name__)

_active_tasks: dict[str, asyncio.Task] = {}
_pending: list[str] = []


# ── Path helpers ──────────────────────────────────────────────────────────────

def _final_path(module: Module, settings: Settings) -> Path:
    if module.category == "maps":
        return settings.maps_dir / f"{module.id}.mbtiles"
    return settings.zim_dir / f"{module.id}.zim"


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
        final.unlink()
    _total_path(module, settings).unlink(missing_ok=True)
    if module.category != "maps":
        _kiwix_remove(module, settings)
    _signal_service(module)
    registry = load_registry(settings)
    for m in registry.modules:
        if m.id == module.id:
            m.installed_version = None
            m.installed_checksum = None
            m.active = False
            break
    save_registry(settings, registry)


async def activate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, True)
    if module.category != "maps":
        _kiwix_add(module, settings)
    _signal_service(module)


async def deactivate_module(module: Module, settings: Settings) -> None:
    from app.services.registry import set_module_active
    set_module_active(settings, module.id, False)
    if module.category != "maps":
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
    if module.category != "maps":
        _kiwix_add(module, settings)
    _signal_service(module)


async def discard_checksum_mismatch(module: Module, settings: Settings) -> None:
    _part_path(module, settings).unlink(missing_ok=True)
    _mismatch_path(module, settings).unlink(missing_ok=True)
    _total_path(module, settings).unlink(missing_ok=True)


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
    library_xml = settings.zim_dir / "library.xml"
    zim_path = settings.zim_dir / f"{module.id}.zim"
    if not library_xml.exists():
        return
    if not zim_path.exists():
        log.warning("kiwix_add: %s not found, skipping library update", zim_path)
        return
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
    if module.category == "maps":
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


async def check_for_updates(settings: Settings) -> int:
    registry = load_registry(settings)
    async with httpx.AsyncClient() as client:
        r = await client.get(registry.update_server, timeout=10.0)
        r.raise_for_status()
        remote_modules = r.json()
    before_ids = {m.id for m in load_registry(settings).modules}
    before_versions = {m.id: m.latest_version for m in load_registry(settings).modules}
    merge_remote_manifest(settings, remote_modules)
    after = load_registry(settings).modules
    return sum(
        1 for m in after
        if m.id not in before_ids or m.latest_version != before_versions.get(m.id)
    )


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

        registry = load_registry(settings)
        for m in registry.modules:
            if m.id == module.id:
                m.installed_version = module.latest_version
                m.installed_checksum = module.checksum
                m.active = True
                break
        save_registry(settings, registry)

        if module.category != "maps":
            _kiwix_add(module, settings)
        _signal_service(module)

    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Download failed for %s", module.id)
    finally:
        _active_tasks.pop(module.id, None)
        _drain_pending(settings)
