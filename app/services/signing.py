"""Minisign verification for content packages.

Mirrors the shell verification in `scripts/upgrade.sh` so the same
`release.pub` and trusted-comment pattern apply to both firmware tarballs
and content tarballs.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


class SignatureError(RuntimeError):
    """Verification failed (bad signature, wrong trusted comment, or minisign missing)."""


def _run_minisign(args: list[str]) -> subprocess.CompletedProcess:
    """Monkeypatchable test seam."""
    return subprocess.run(args, capture_output=True, text=True, timeout=30)


def verify_minisign(
    tarball_path: Path,
    sig_path: Path,
    expected_trusted_comment: str,
    pubkey_path: Path,
) -> None:
    """Verify ``tarball_path`` against ``sig_path`` with ``pubkey_path``.

    Asserts the signature's trusted comment matches ``expected_trusted_comment``
    exactly. Raises :class:`SignatureError` on any failure.
    """
    if not pubkey_path.exists():
        raise SignatureError(f"public key not found at {pubkey_path}")
    try:
        result = _run_minisign([
            "minisign", "-V",
            "-p", str(pubkey_path),
            "-m", str(tarball_path),
            "-x", str(sig_path),
        ])
    except FileNotFoundError as exc:
        raise SignatureError("minisign binary not found on PATH") from exc
    if result.returncode != 0:
        raise SignatureError(f"signature_invalid: {result.stderr.strip() or result.stdout.strip()}")
    expected_line = f"Trusted comment: {expected_trusted_comment}"
    if expected_line not in result.stdout:
        raise SignatureError(
            f"trusted_comment_mismatch: expected {expected_trusted_comment!r}"
        )
