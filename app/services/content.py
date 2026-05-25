"""Static-content tarball extraction."""
from __future__ import annotations
import shutil
import tarfile
from pathlib import Path

# Defense in depth: minisign already restricts publishers, but a Pi SD card
# has tight storage and a decompression bomb would wedge the device. These
# caps are generous for legit Markdown/HTML packages.
MAX_EXTRACT_BYTES = 500 * 1024 * 1024  # 500 MB total
MAX_EXTRACT_FILES = 10_000


class ExtractionError(RuntimeError):
    """Tarball exceeded size/file limits or otherwise failed to extract safely."""


def extract_static_package(tarball_path: Path, target_dir: Path) -> None:
    """Extract ``tarball_path`` into ``target_dir`` atomically.

    Uses ``filter='data'`` (Python 3.12+) to reject absolute paths, parent
    traversal, device files, and other tarslip attack surfaces. Writes to a
    staging directory then renames so partial extracts never become live
    content. Enforces total-size and file-count caps to defend against
    decompression bombs.
    """
    target_dir = Path(target_dir)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    staging = target_dir.with_name(target_dir.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with tarfile.open(tarball_path, "r:gz") as tar:
            members = tar.getmembers()
            if len(members) > MAX_EXTRACT_FILES:
                raise ExtractionError(
                    f"tarball contains {len(members)} files (max {MAX_EXTRACT_FILES})"
                )
            total = sum(max(m.size, 0) for m in members)
            if total > MAX_EXTRACT_BYTES:
                raise ExtractionError(
                    f"tarball extracts to {total} bytes (max {MAX_EXTRACT_BYTES})"
                )
            tar.extractall(staging, members=members, filter="data")
        staging.rename(target_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
