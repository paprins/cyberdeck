from __future__ import annotations
import io
import tarfile
import pytest

from app.services.content import extract_static_package


def _make_tarball(tmp_path, files: dict[str, bytes]):
    path = tmp_path / "pkg.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_extract_simple_tarball(tmp_path):
    tarball = _make_tarball(tmp_path, {"index.md": b"# hello\n", "assets/note.txt": b"x"})
    target = tmp_path / "content" / "first-aid"
    extract_static_package(tarball, target)
    assert (target / "index.md").read_bytes() == b"# hello\n"
    assert (target / "assets" / "note.txt").read_bytes() == b"x"


def test_extract_overwrites_existing(tmp_path):
    target = tmp_path / "content" / "first-aid"
    target.mkdir(parents=True)
    (target / "old.md").write_text("stale")
    tarball = _make_tarball(tmp_path, {"new.md": b"fresh"})
    extract_static_package(tarball, target)
    assert (target / "new.md").exists()
    assert not (target / "old.md").exists()


def test_extract_rejects_traversal(tmp_path):
    # Build a tarball containing a parent-relative path; filter='data' should
    # reject it and the extraction must fail without leaving the staging dir.
    path = tmp_path / "evil.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"evil"))
    target = tmp_path / "content" / "evil"
    with pytest.raises(Exception):
        extract_static_package(path, target)
    assert not (tmp_path / "escape.txt").exists()
    assert not target.exists()


def test_extract_rejects_oversize_total(tmp_path, monkeypatch):
    from app.services import content as content_svc
    monkeypatch.setattr(content_svc, "MAX_EXTRACT_BYTES", 10)
    tarball = _make_tarball(tmp_path, {"big.txt": b"x" * 100})
    target = tmp_path / "content" / "big"
    with pytest.raises(content_svc.ExtractionError, match="bytes"):
        extract_static_package(tarball, target)
    assert not target.exists()


def test_extract_rejects_too_many_files(tmp_path, monkeypatch):
    from app.services import content as content_svc
    monkeypatch.setattr(content_svc, "MAX_EXTRACT_FILES", 2)
    tarball = _make_tarball(tmp_path, {"a": b"1", "b": b"2", "c": b"3"})
    target = tmp_path / "content" / "many"
    with pytest.raises(content_svc.ExtractionError, match="files"):
        extract_static_package(tarball, target)
    assert not target.exists()
