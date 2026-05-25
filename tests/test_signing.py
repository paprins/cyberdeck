from __future__ import annotations
import subprocess
import pytest

from app.services import signing


def _result(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_verify_minisign_happy(tmp_path, monkeypatch):
    pub = tmp_path / "release.pub"
    pub.write_text("dummy")
    monkeypatch.setattr(
        signing, "_run_minisign",
        lambda args: _result(0, "Signature and comment signature verified\nTrusted comment: cyberdeck content foo v1\n"),
    )
    signing.verify_minisign(tmp_path / "x.tar.gz", tmp_path / "x.sig", "cyberdeck content foo v1", pub)


def test_verify_minisign_wrong_trusted_comment(tmp_path, monkeypatch):
    pub = tmp_path / "release.pub"
    pub.write_text("dummy")
    monkeypatch.setattr(
        signing, "_run_minisign",
        lambda args: _result(0, "Trusted comment: cyberdeck content other v1\n"),
    )
    with pytest.raises(signing.SignatureError, match="trusted_comment_mismatch"):
        signing.verify_minisign(tmp_path / "x.tar.gz", tmp_path / "x.sig", "cyberdeck content foo v1", pub)


def test_verify_minisign_nonzero_exit(tmp_path, monkeypatch):
    pub = tmp_path / "release.pub"
    pub.write_text("dummy")
    monkeypatch.setattr(
        signing, "_run_minisign",
        lambda args: _result(1, "", "Signature verification failed"),
    )
    with pytest.raises(signing.SignatureError, match="signature_invalid"):
        signing.verify_minisign(tmp_path / "x.tar.gz", tmp_path / "x.sig", "cyberdeck content foo v1", pub)


def test_verify_minisign_missing_pubkey(tmp_path):
    with pytest.raises(signing.SignatureError, match="public key not found"):
        signing.verify_minisign(
            tmp_path / "x.tar.gz", tmp_path / "x.sig",
            "cyberdeck content foo v1", tmp_path / "missing.pub",
        )


def test_verify_minisign_binary_missing(tmp_path, monkeypatch):
    pub = tmp_path / "release.pub"
    pub.write_text("dummy")
    def boom(args):
        raise FileNotFoundError("minisign")
    monkeypatch.setattr(signing, "_run_minisign", boom)
    with pytest.raises(signing.SignatureError, match="minisign binary not found"):
        signing.verify_minisign(tmp_path / "x.tar.gz", tmp_path / "x.sig", "cyberdeck content foo v1", pub)
