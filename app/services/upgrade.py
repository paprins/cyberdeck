from __future__ import annotations
import asyncio
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
import httpx
from app.config import Settings
from app.models.upgrade import (
    InstallRequest,
    Release,
    UpgradeAlreadyRunningError,
    UpgradeChannel,
    UpgradeDowngradeError,
    UpgradeError,
    UpgradeNetworkError,
    UpgradeStatus,
)


_USB_ROOTS = (Path("/media"), Path("/mnt"))
_TARBALL_NAME_RE = re.compile(r"^cyberdeck-v?(?P<version>\d+\.\d+\.\d+)\.tar\.gz$")
_BUSY_PHASES = {
    "checking", "downloading", "verifying", "extracting",
    "building_venv", "migrating", "swapping", "restarting", "health_checking",
}


# ── Version helpers ───────────────────────────────────────────────────────────

def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into a comparable tuple."""
    parts = v.lstrip("v").split(".")
    return tuple(int(p) for p in parts if p.isdigit())


def current_version(cfg: Settings) -> str | None:
    """Return the version of the currently active install ('1.2.3' or None).

    Resolves the install_root/current symlink. None when running in dev (symlink
    absent) — callers must tolerate.
    """
    sym = cfg.current_symlink
    if not sym.is_symlink():
        return None
    return sym.resolve().name.lstrip("v")


def list_installed_versions(cfg: Settings) -> list[str]:
    """Return all v* directories under install_root, sorted newest-first."""
    if not cfg.install_root.exists():
        return []
    versions = []
    for entry in cfg.install_root.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith("v") and _parse_version(name):
            versions.append(name.lstrip("v"))
    return sorted(versions, key=_parse_version, reverse=True)


# ── State file ────────────────────────────────────────────────────────────────

def read_status(cfg: Settings) -> UpgradeStatus:
    """Read upgrade state.json; return idle status if absent."""
    path = cfg.upgrade_state_path
    if not path.exists():
        return UpgradeStatus(current_version=current_version(cfg))
    try:
        data = json.loads(path.read_text())
        return UpgradeStatus.model_validate(data)
    except (OSError, ValueError):
        return UpgradeStatus(
            phase="idle",
            current_version=current_version(cfg),
            message="state file unreadable",
        )


def _write_status(cfg: Settings, status: UpgradeStatus) -> None:
    """Atomic write of upgrade state.json."""
    cfg.upgrade_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg.upgrade_state_path.with_suffix(".tmp")
    tmp.write_text(status.model_dump_json())
    tmp.replace(cfg.upgrade_state_path)


# ── Channel: online ───────────────────────────────────────────────────────────

async def check_online(cfg: Settings) -> list[Release]:
    """Query GitHub Releases API; return newer-than-current releases as Release[].

    Returns [] if github_repo is unset. Raises UpgradeNetworkError on failure.
    """
    if not cfg.github_repo:
        return []
    url = f"https://api.github.com/repos/{cfg.github_repo}/releases"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise UpgradeNetworkError(str(exc)) from exc

    cur = current_version(cfg)
    cur_tuple = _parse_version(cur) if cur else (0, 0, 0)

    releases: list[Release] = []
    for item in r.json():
        tag = item.get("tag_name", "")
        if not tag:
            continue
        version = tag.lstrip("v")
        if not _parse_version(version):
            continue
        if _parse_version(version) <= cur_tuple:
            continue
        tarball_url = sig_url = None
        size = None
        for asset in item.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".tar.gz"):
                tarball_url = asset["browser_download_url"]
                size = asset.get("size")
            elif name.endswith(".tar.gz.minisig"):
                sig_url = asset["browser_download_url"]
        if not tarball_url or not sig_url:
            continue
        published_at = item.get("published_at")
        releases.append(Release(
            version=version,
            channel=UpgradeChannel.ONLINE,
            tarball_url=tarball_url,
            signature_url=sig_url,
            size_bytes=size,
            published_at=datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else None,
        ))
    return sorted(releases, key=lambda r: _parse_version(r.version), reverse=True)


# ── Channel: offline (USB) ────────────────────────────────────────────────────

def scan_usb(cfg: Settings) -> list[Release]:
    """Scan /media/* and /mnt/* for cyberdeck-v*.tar.gz + .minisig pairs.

    Never raises. Returns [] when nothing found.
    """
    cur = current_version(cfg)
    cur_tuple = _parse_version(cur) if cur else (0, 0, 0)

    releases: list[Release] = []
    for root in _USB_ROOTS:
        if not root.exists():
            continue
        for mount in root.iterdir():
            if not mount.is_dir():
                continue
            for tarball in mount.glob("cyberdeck-v*.tar.gz"):
                sig = tarball.with_suffix(".gz.minisig")
                if not sig.exists():
                    continue
                m = _TARBALL_NAME_RE.match(tarball.name)
                if not m:
                    continue
                version = m.group("version")
                if _parse_version(version) <= cur_tuple:
                    continue
                releases.append(Release(
                    version=version,
                    channel=UpgradeChannel.OFFLINE,
                    tarball_url=tarball.as_uri(),
                    signature_url=sig.as_uri(),
                    size_bytes=tarball.stat().st_size,
                    published_at=datetime.fromtimestamp(tarball.stat().st_mtime, tz=timezone.utc),
                ))
    return sorted(releases, key=lambda r: _parse_version(r.version), reverse=True)


# ── Aggregator ────────────────────────────────────────────────────────────────

async def check_for_updates(cfg: Settings) -> dict:
    """Aggregate both channels. Returns dict with 'current_version', 'releases', 'online_error'."""
    online_task = asyncio.create_task(check_online(cfg))
    usb_releases = scan_usb(cfg)

    online_releases: list[Release] = []
    online_error: str | None = None
    try:
        online_releases = await online_task
    except UpgradeNetworkError as exc:
        online_error = str(exc)

    # Combined newest-first; same version from both channels keeps online entry
    combined: dict[str, Release] = {}
    for r in usb_releases:
        combined[r.version] = r
    for r in online_releases:
        combined[r.version] = r

    return {
        "current_version": current_version(cfg),
        "releases": sorted(combined.values(), key=lambda r: _parse_version(r.version), reverse=True),
        "online_error": online_error,
    }


# ── Subprocess seam (monkeypatchable) ─────────────────────────────────────────

def _popen(cmd: list[str], **kwargs) -> subprocess.Popen:
    """Module-level Popen wrapper for monkeypatching."""
    return subprocess.Popen(cmd, **kwargs)


# ── Start upgrade ─────────────────────────────────────────────────────────────

async def start_upgrade(cfg: Settings, req: InstallRequest) -> None:
    """Validate, download (if online), then hand off to scripts/upgrade.sh in detached subprocess.

    Raises UpgradeAlreadyRunningError, UpgradeDowngradeError, UpgradeNetworkError,
    UpgradeError on input problems.
    """
    # Gate on the persisted state.json phase — this survives process restarts
    # and is the source of truth shared with the shell scripts.
    if read_status(cfg).phase in _BUSY_PHASES:
        raise UpgradeAlreadyRunningError("an upgrade is already in progress")

    from app.services import packages as pkg_svc
    if pkg_svc._active_tasks:
        raise UpgradeAlreadyRunningError("a package download is in progress")

    cur = current_version(cfg)
    if cur and _parse_version(req.version) <= _parse_version(cur):
        raise UpgradeDowngradeError(f"target {req.version} is not newer than current {cur}")

    cfg.upgrade_dir.mkdir(parents=True, exist_ok=True)
    tarball_path = cfg.upgrade_dir / f"cyberdeck-v{req.version}.tar.gz"
    sig_path = tarball_path.with_suffix(".gz.minisig")

    status = UpgradeStatus(
        phase="downloading" if req.channel == UpgradeChannel.ONLINE else "verifying",
        current_version=cur,
        target_version=req.version,
        channel=req.channel,
        started_at=datetime.now(timezone.utc),
    )
    _write_status(cfg, status)

    if req.channel == UpgradeChannel.ONLINE:
        await _download(req.tarball_url, tarball_path, req.signature_url, sig_path)
    else:
        src_tar = _file_uri_to_path(req.tarball_url)
        src_sig = _file_uri_to_path(req.signature_url)
        if not src_tar.exists() or not src_sig.exists():
            raise UpgradeError("USB tarball or signature not found at expected path")
        shutil.copy2(src_tar, tarball_path)
        shutil.copy2(src_sig, sig_path)

    upgrade_sh = cfg.current_symlink / "scripts" / "upgrade.sh"
    if not upgrade_sh.exists():
        raise UpgradeError(f"upgrade.sh not found at {upgrade_sh}")

    log_path = cfg.upgrade_dir / "upgrade.log"
    try:
        with open(log_path, "a") as log_fh:
            _popen(
                [str(upgrade_sh), str(tarball_path), str(sig_path), req.version],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
    except OSError as exc:
        # Popen failed before the script could write its own state (e.g. EACCES on upgrade.sh).
        # Mark failed so the UI can dismiss + retry instead of being stuck on "downloading".
        _write_status(cfg, UpgradeStatus(
            phase="failed",
            current_version=cur,
            target_version=req.version,
            channel=req.channel,
            started_at=status.started_at,
            finished_at=datetime.now(timezone.utc),
            message=f"spawn_failed: {exc}",
        ))
        raise UpgradeError(f"failed to spawn upgrade script: {exc}") from exc


def _file_uri_to_path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


async def _download(tarball_url: str, tarball_path: Path, sig_url: str, sig_path: Path) -> None:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        try:
            async with client.stream("GET", tarball_url) as r:
                r.raise_for_status()
                with open(tarball_path, "wb") as f:
                    async for chunk in r.aiter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
            sig = await client.get(sig_url)
            sig.raise_for_status()
            sig_path.write_bytes(sig.content)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            raise UpgradeNetworkError(str(exc)) from exc


# ── Cancel (reset failed state) ───────────────────────────────────────────────

def cancel(cfg: Settings) -> None:
    """Reset a terminal failed/rolled_back state back to idle. No-op otherwise."""
    status = read_status(cfg)
    if status.phase not in ("failed", "rolled_back"):
        raise UpgradeAlreadyRunningError("cannot cancel an active or successful upgrade")
    _write_status(cfg, UpgradeStatus(current_version=current_version(cfg)))


# ── Cleanup old versions ──────────────────────────────────────────────────────

def cleanup_old_versions(cfg: Settings | None = None, keep: int | None = None) -> list[str]:
    """Remove old versioned dirs from install_root.

    Keeps the active version (current symlink target) plus the `keep` most recent
    by semver. Returns list of removed version strings.
    """
    cfg = cfg or Settings()
    keep = keep if keep is not None else cfg.upgrade_versions_keep

    active = None
    if cfg.current_symlink.is_symlink():
        active = cfg.current_symlink.resolve().name.lstrip("v")

    versions = sorted(list_installed_versions(cfg), key=_parse_version, reverse=True)

    keepset = {active} if active else set()
    for v in versions:
        if len(keepset) >= keep + (1 if active else 0):
            break
        keepset.add(v)

    removed: list[str] = []
    for v in versions:
        if v in keepset:
            continue
        target = cfg.install_root / f"v{v}"
        if target.exists():
            shutil.rmtree(target)
            removed.append(v)
    return removed
