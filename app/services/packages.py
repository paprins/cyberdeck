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


# ── Path helpers ──────────────────────────────────────────────────────────────

def _final_path(module: Module, settings: Settings) -> Path:
    if module.category == "maps":
        return settings.maps_dir / f"{module.id}.mbtiles"
    return settings.zim_dir / f"{module.id}.zim"


def _part_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.part"


# ── Status and storage ────────────────────────────────────────────────────────

def get_download_status(module: Module, settings: Settings) -> dict:
    total_bytes = int(module.size_gb * 1024 ** 3)
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
    pct = int(bytes_downloaded * 100 / total_bytes) if total_bytes > 0 else 0

    if module.id in _active_tasks:
        return {
            "status": "downloading",
            "bytes_downloaded": bytes_downloaded,
            "total_bytes": total_bytes,
            "pct": pct,
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
