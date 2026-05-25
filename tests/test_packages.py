from __future__ import annotations
import asyncio
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
import httpx

from app.config import Settings
from app.main import create_app
from app.models.registry import Module, Registry
from app.services.registry import load_registry, save_registry
import app.services.packages as pkg_service


# ── helpers ───────────────────────────────────────────────────────────────────

def _mod(**overrides) -> Module:
    defaults = dict(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="Medical reference",
        latest_version="2024-10",
        size_gb=1.0,
        checksum="sha256:abc",
        download_url="https://example.com/wikimed.zim",
    )
    defaults.update(overrides)
    return Module(**defaults)


def _seed(tmp_settings, modules=None):
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(modules=modules or [])
    tmp_settings.registry_path.write_text(reg.model_dump_json())


@pytest.fixture(autouse=True)
def clear_active_tasks():
    pkg_service._active_tasks.clear()
    pkg_service._pending.clear()
    yield
    pkg_service._active_tasks.clear()
    pkg_service._pending.clear()


# ── get_download_status ───────────────────────────────────────────────────────

def test_get_download_status_not_installed(tmp_settings):
    m = _mod()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "not_installed"
    assert result["bytes_downloaded"] == 0
    assert result["pct"] == 0


def test_get_download_status_interrupted(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "interrupted"
    assert result["bytes_downloaded"] == 500


def test_get_download_status_downloading(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 200)
    pkg_service._active_tasks["medical-wikimed"] = object()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "downloading"
    assert result["bytes_downloaded"] == 200


def test_get_download_status_installed(tmp_settings):
    m = _mod()
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "installed"
    assert result["pct"] == 100


def test_get_download_status_maps_uses_mbtiles(tmp_settings):
    m = _mod(id="maps-world", category="maps", kind="mbtiles")
    mbt = tmp_settings.maps_dir / "maps-world.mbtiles"
    mbt.parent.mkdir(parents=True, exist_ok=True)
    mbt.write_bytes(b"tiles")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "installed"


def test_get_download_status_checksum_mismatch(tmp_settings):
    m = _mod(checksum="sha256:expected")
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 1000)
    mismatch.write_text("sha256:actual")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "checksum_mismatch"
    assert result["actual_checksum"] == "sha256:actual"
    assert result["expected_checksum"] == "sha256:expected"
    assert result["pct"] == 100


def test_get_download_status_interrupted_without_mismatch_file(tmp_settings):
    m = _mod()
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    # No .mismatch file — should still be interrupted, not checksum_mismatch
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "interrupted"


# ── get_storage_info ──────────────────────────────────────────────────────────

def test_get_storage_info_returns_used_and_free(tmp_settings):
    result = pkg_service.get_storage_info(tmp_settings)
    assert "used_bytes" in result
    assert "free_bytes" in result
    assert result["used_bytes"] > 0
    assert result["free_bytes"] > 0


# ── uninstall_module ──────────────────────────────────────────────────────────

async def test_uninstall_deletes_final_file(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not zim.exists()


async def test_uninstall_deletes_part_file_if_present(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"partial")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not part.exists()


# ── _resolve_bundled_image ──────────────────────────────────────────────────


def _static_mod(**overrides) -> Module:
    defaults = dict(
        id="first-aid",
        display_name="First Aid",
        category="medical",
        description="",
        latest_version="1.0",
        size_gb=0.0,
        kind="static",
        signature_url="https://example.com/x.minisig",
        download_url="https://example.com/x.tar.gz",
        entry="index.md",
    )
    defaults.update(overrides)
    return Module(**defaults)


def test_bundled_image_skipped_when_http_already_cached(tmp_settings):
    m = _static_mod(image="/data-cache/first-aid/cover.png")
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / "card.png").write_bytes(b"x")
    assert pkg_service._resolve_bundled_image(m, tmp_settings, final_dir) is None


def test_bundled_image_uses_card_png_by_default(tmp_settings):
    m = _static_mod()
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / "card.png").write_bytes(b"data")
    url = pkg_service._resolve_bundled_image(m, tmp_settings, final_dir)
    # No copy — URL points at the extracted file via the existing /content/ route.
    assert url == "/content/first-aid/card.png"
    assert not (tmp_settings.cache_dir / "first-aid").exists()


@pytest.mark.parametrize("ext", ["png", "jpg", "webp", "gif"])
def test_bundled_image_default_supports_each_extension(tmp_settings, ext):
    m = _static_mod()
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / f"card.{ext}").write_bytes(b"data")
    url = pkg_service._resolve_bundled_image(m, tmp_settings, final_dir)
    assert url == f"/content/first-aid/card.{ext}"


def test_bundled_image_preserves_jpeg_extension(tmp_settings):
    """No jpeg→jpg munging; the URL matches the tarball filename verbatim."""
    m = _static_mod()
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / "card.jpeg").write_bytes(b"data")
    url = pkg_service._resolve_bundled_image(m, tmp_settings, final_dir)
    assert url == "/content/first-aid/card.jpeg"


def test_bundled_image_no_card_returns_none(tmp_settings):
    m = _static_mod()
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / "index.md").write_text("hello")
    assert pkg_service._resolve_bundled_image(m, tmp_settings, final_dir) is None


def test_bundled_image_unsupported_extension_ignored(tmp_settings):
    m = _static_mod()
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    (final_dir / "card.bmp").write_bytes(b"data")
    assert pkg_service._resolve_bundled_image(m, tmp_settings, final_dir) is None


def test_bundled_image_uses_image_path_preserving_relative_layout(tmp_settings):
    """image_path produces a URL with the same relative path as in the tarball."""
    m = _static_mod(image_path="images/logo.png")
    final_dir = tmp_settings.content_dir / "first-aid"
    (final_dir / "images").mkdir(parents=True)
    (final_dir / "images" / "logo.png").write_bytes(b"logo-bytes")
    # A card.png at the root must NOT win when image_path is explicit.
    (final_dir / "card.png").write_bytes(b"card-bytes")
    url = pkg_service._resolve_bundled_image(m, tmp_settings, final_dir)
    assert url == "/content/first-aid/images/logo.png"
    # No copy at all.
    assert not (tmp_settings.cache_dir / "first-aid").exists()


def test_bundled_image_path_traversal_rejected(tmp_settings):
    m = _static_mod(image_path="../../etc/passwd")
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    # Even if the resolved file existed, the guard refuses to leave final_dir.
    assert pkg_service._resolve_bundled_image(m, tmp_settings, final_dir) is None


def test_bundled_image_path_missing_file_returns_none(tmp_settings):
    m = _static_mod(image_path="images/logo.png")
    final_dir = tmp_settings.content_dir / "first-aid"
    final_dir.mkdir(parents=True)
    assert pkg_service._resolve_bundled_image(m, tmp_settings, final_dir) is None


def test_mark_installed_writes_image_when_passed(tmp_settings):
    m = _static_mod()
    _seed(tmp_settings, [m])
    pkg_service._mark_installed(m, tmp_settings, checksum=None, image="/content/first-aid/card.png")
    reg = load_registry(tmp_settings)
    saved = reg.modules[0]
    assert saved.installed_version == "1.0"
    assert saved.image == "/content/first-aid/card.png"


def test_mark_installed_keeps_existing_image_when_none_passed(tmp_settings):
    m = _static_mod(image="/content/first-aid/card.png")
    _seed(tmp_settings, [m])
    pkg_service._mark_installed(m, tmp_settings, checksum=None)
    reg = load_registry(tmp_settings)
    assert reg.modules[0].image == "/content/first-aid/card.png"


async def test_uninstall_wipes_cache_dir(tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    cache = tmp_settings.cache_dir / m.id
    (cache / "images").mkdir(parents=True)
    (cache / "card.png").write_bytes(b"x")
    (cache / "images" / "logo.jpg").write_bytes(b"y")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not cache.exists()


async def test_uninstall_removes_registry_row(tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    await pkg_service.uninstall_module(m, tmp_settings)
    reg = load_registry(tmp_settings)
    assert reg.modules == []


async def test_accept_checksum_mismatch_installs_file(tmp_settings, monkeypatch):
    m = _mod(checksum="sha256:expected")
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"file content")
    mismatch_file.write_text("sha256:actual")
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.accept_checksum_mismatch(m, tmp_settings)

    final = tmp_settings.zim_dir / "medical-wikimed.zim"
    assert final.exists(), "file must be moved to final path"
    assert not part.exists(), ".part must be gone"
    assert not mismatch_file.exists(), ".mismatch must be gone"
    reg = load_registry(tmp_settings)
    mod = reg.modules[0]
    assert mod.installed_checksum == "sha256:actual"
    assert mod.installed_version == "2024-10"
    assert mod.active is True


async def test_accept_checksum_mismatch_raises_if_no_mismatch_pending(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    with pytest.raises(RuntimeError):
        await pkg_service.accept_checksum_mismatch(m, tmp_settings)


async def test_discard_checksum_mismatch_deletes_files(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actual")

    await pkg_service.discard_checksum_mismatch(m, tmp_settings)

    assert not part.exists()
    assert not mismatch_file.exists()


async def test_discard_checksum_mismatch_removes_registry_row(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    await pkg_service.discard_checksum_mismatch(m, tmp_settings)
    reg = load_registry(tmp_settings)
    assert reg.modules == []


async def test_uninstall_clears_mismatch_file(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actual")

    await pkg_service.uninstall_module(m, tmp_settings)

    assert not part.exists()
    assert not mismatch_file.exists()


# ── activate / deactivate ─────────────────────────────────────────────────────

async def test_activate_sets_active_true(tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=False)
    _seed(tmp_settings, [m])
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)
    await pkg_service.activate_module(m, tmp_settings)
    assert load_registry(tmp_settings).modules[0].active is True


async def test_deactivate_sets_active_false(tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    monkeypatch.setattr(pkg_service, "_kiwix_remove", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)
    await pkg_service.deactivate_module(m, tmp_settings)
    assert load_registry(tmp_settings).modules[0].active is False


# ── start_download ────────────────────────────────────────────────────────────

async def test_start_download_queues_when_busy(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["other-module"] = object()
    await pkg_service.start_download(m, tmp_settings)
    assert "medical-wikimed" in pkg_service._pending
    assert "medical-wikimed" not in pkg_service._active_tasks


async def test_start_download_idempotent_when_already_queued(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["other-module"] = object()
    await pkg_service.start_download(m, tmp_settings)
    await pkg_service.start_download(m, tmp_settings)
    assert pkg_service._pending.count("medical-wikimed") == 1


async def test_start_download_raises_if_no_url(tmp_settings):
    m = _mod(download_url=None)
    _seed(tmp_settings, [m])
    with pytest.raises(ValueError, match="no download_url"):
        await pkg_service.start_download(m, tmp_settings)


def test_get_download_status_returns_queued(tmp_settings):
    m = _mod()
    pkg_service._pending.append("medical-wikimed")
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["status"] == "queued"


async def test_cancel_queued_removes_from_pending(tmp_settings):
    pkg_service._pending.append("medical-wikimed")
    await pkg_service.cancel_download("medical-wikimed")
    assert "medical-wikimed" not in pkg_service._pending


async def test_drain_pending_starts_next_after_completion(tmp_settings, monkeypatch):
    """When the active download finishes, the next pending module starts automatically."""
    import hashlib
    fake_bytes = b"second module content"
    correct_checksum = "sha256:" + hashlib.sha256(fake_bytes).hexdigest()

    first = _mod(id="first-module", checksum="sha256:irrelevant")
    second = _mod(id="second-module", checksum=correct_checksum,
                  download_url="https://example.com/second.zim")
    _seed(tmp_settings, [first, second])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    started: list[str] = []

    class _Resp:
        status_code = 200
        headers = {"Content-Length": str(len(fake_bytes))}
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url, headers=None, timeout=None):
            started.append(url)
            return _Stream()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    # Simulate: first is already active, second gets queued
    pkg_service._active_tasks["first-module"] = object()
    await pkg_service.start_download(second, tmp_settings)
    assert "second-module" in pkg_service._pending

    # First "completes": clear it and call _drain_pending directly
    pkg_service._active_tasks.pop("first-module")
    pkg_service._drain_pending(tmp_settings)
    assert "second-module" in pkg_service._active_tasks
    assert "second-module" not in pkg_service._pending
    # Let the actual download task run to completion
    task = pkg_service._active_tasks["second-module"]
    await task
    assert started == ["https://example.com/second.zim"]


async def test_uninstall_module_removes_from_pending(tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._pending.append("medical-wikimed")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert "medical-wikimed" not in pkg_service._pending


async def test_download_writes_mismatch_file_on_checksum_failure(tmp_settings, monkeypatch):
    m = _mod(checksum="sha256:expectedbutnotthis")
    _seed(tmp_settings, [m])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    fake_bytes = b"fake file content"

    class _Resp:
        status_code = 200
        headers = {"Content-Length": str(len(fake_bytes))}
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url, headers=None, timeout=None):
            return _Stream()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.start_download(m, tmp_settings)
    task = pkg_service._active_tasks["medical-wikimed"]
    await task

    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    assert part.exists(), ".part file must be kept on mismatch"
    assert mismatch.exists(), ".mismatch file must be written"
    import hashlib
    expected_digest = "sha256:" + hashlib.sha256(fake_bytes).hexdigest()
    assert mismatch.read_text().strip() == expected_digest


async def test_download_does_not_write_mismatch_on_correct_checksum(tmp_settings, monkeypatch):
    fake_bytes = b"correct content"
    import hashlib
    correct_checksum = "sha256:" + hashlib.sha256(fake_bytes).hexdigest()
    m = _mod(checksum=correct_checksum)
    _seed(tmp_settings, [m])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    class _Resp:
        status_code = 200
        headers = {"Content-Length": str(len(fake_bytes))}
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        def stream(self, method, url, headers=None, timeout=None):
            return _Stream()

    monkeypatch.setattr(pkg_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)

    await pkg_service.start_download(m, tmp_settings)
    task = pkg_service._active_tasks.get("medical-wikimed")
    if task:
        await task

    mismatch = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    assert not mismatch.exists(), ".mismatch must not exist on successful download"


# ── _finalize_static (integration) ────────────────────────────────────────────


async def test_finalize_static_extracts_and_marks_installed(tmp_settings, monkeypatch):
    import io, tarfile
    from app.services import signing
    from app.services import packages as pkg
    # Real pubkey path so the SignatureError("public key not found") branch is skipped.
    pubkey = tmp_settings.data_dir / "release.pub"
    pubkey.parent.mkdir(parents=True, exist_ok=True)
    pubkey.write_text("dummy")
    tmp_settings.release_pubkey_path = pubkey

    module = _mod(id="my-pkg", kind="static", checksum=None,
                  signature_url="https://github.com/o/r/x.minisig",
                  download_url="https://github.com/o/r/x.tar.gz",
                  latest_version="1.0")
    _seed(tmp_settings, modules=[module])

    # Build a real tarball at the .part location.
    part = tmp_settings.downloads_dir / "my-pkg.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(part, "w:gz") as tar:
        data = b"# hello"
        info = tarfile.TarInfo(name="index.md"); info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    # Stub the signature download and minisign call.
    import subprocess
    class _Resp:
        content = b"sigbytes"
        def raise_for_status(self): pass
    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url): return _Resp()
    monkeypatch.setattr(pkg.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(signing, "_run_minisign",
                        lambda args: subprocess.CompletedProcess(args=[], returncode=0,
                                stdout="Trusted comment: cyberdeck content my-pkg v1.0\n", stderr=""))

    await pkg._finalize_static(module, tmp_settings, part)

    final = tmp_settings.content_dir / "my-pkg"
    assert (final / "index.md").read_text() == "# hello"
    assert not part.exists()
    reg = load_registry(tmp_settings)
    assert reg.modules[0].installed_version == "1.0"
    assert reg.modules[0].active is True


async def test_finalize_static_cleans_up_on_bad_signature(tmp_settings, monkeypatch):
    import io, tarfile, subprocess
    from app.services import signing, packages as pkg
    pubkey = tmp_settings.data_dir / "release.pub"
    pubkey.parent.mkdir(parents=True, exist_ok=True)
    pubkey.write_text("dummy")
    tmp_settings.release_pubkey_path = pubkey

    module = _mod(id="bad-pkg", kind="static", checksum=None,
                  signature_url="https://github.com/o/r/x.minisig",
                  download_url="https://github.com/o/r/x.tar.gz", latest_version="1.0")
    _seed(tmp_settings, modules=[module])

    part = tmp_settings.downloads_dir / "bad-pkg.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(part, "w:gz") as tar:
        info = tarfile.TarInfo(name="index.md"); info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))

    class _Resp:
        content = b"sig"
        def raise_for_status(self): pass
    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url): return _Resp()
    monkeypatch.setattr(pkg.httpx, "AsyncClient", _FakeClient)
    # Bad signature: nonzero exit
    monkeypatch.setattr(signing, "_run_minisign",
                        lambda args: subprocess.CompletedProcess(args=[], returncode=1,
                                stdout="", stderr="bad sig"))

    await pkg._finalize_static(module, tmp_settings, part)

    # Cleanup must have happened
    assert not part.exists()
    assert not (tmp_settings.downloads_dir / "bad-pkg.minisig").exists()
    # Content dir untouched (no extraction attempted)
    assert not (tmp_settings.content_dir / "bad-pkg").exists()
    # Registry not marked installed
    assert load_registry(tmp_settings).modules[0].installed_version is None


# ── HTTP fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_settings):
    return create_app(tmp_settings)


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── GET /settings/packages ────────────────────────────────────────────────────

async def test_packages_page_returns_200(client):
    r = await client.get("/settings/packages")
    assert r.status_code == 200


async def test_packages_page_returns_html(client):
    r = await client.get("/settings/packages")
    assert "text/html" in r.headers["content-type"]


async def test_packages_page_shows_installed_module(client, tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    r = await client.get("/settings/packages")
    assert "WikiMed" in r.text


async def test_packages_page_omits_uninstalled_module(client, tmp_settings):
    """An uninstalled-but-still-registered module must not appear; the AVAILABLE section is gone."""
    m = _mod()  # installed_version=None
    _seed(tmp_settings, [m])
    r = await client.get("/settings/packages")
    assert "WikiMed" not in r.text


async def test_packages_page_shows_update_affordance_inline(client, tmp_settings):
    """A module with has_update stays in INSTALLED but renders an UPDATE button + version-bump."""
    m = _mod(
        installed_version="2024-09",
        installed_checksum="sha256:old",
        latest_version="2024-10",
        active=True,
    )
    _seed(tmp_settings, [m])
    r = await client.get("/settings/packages")
    # No standalone UPDATES section.
    assert "UPDATES_AVAILABLE" not in r.text
    # UPDATE action button is present on the installed row.
    assert "UPDATE" in r.text
    # Version-bump badge "→ v2024-10" appears next to the installed version.
    assert "→ v2024-10" in r.text


async def test_packages_page_omits_update_button_when_no_update(client, tmp_settings):
    """An installed module without an update does not render the UPDATE button or bump arrow."""
    m = _mod(
        installed_version="2024-10",
        installed_checksum="sha256:abc",
        latest_version="2024-10",
        active=True,
    )
    _seed(tmp_settings, [m])
    r = await client.get("/settings/packages")
    assert "UPDATE</button>" not in r.text
    assert "→ v" not in r.text


# ── GET /api/packages/active-download ────────────────────────────────────────

async def test_active_download_returns_null_when_idle(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/api/packages/active-download")
    assert r.status_code == 200
    assert r.json()["module_id"] is None


async def test_active_download_returns_module_id_when_active(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["medical-wikimed"] = object()
    r = await client.get("/api/packages/active-download")
    assert r.status_code == 200
    assert r.json()["module_id"] == "medical-wikimed"


# ── GET /api/packages/{id}/status ────────────────────────────────────────────

async def test_status_returns_404_for_unknown_module(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.get("/api/packages/nonexistent/status")
    assert r.status_code == 404


async def test_status_returns_not_installed(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    r = await client.get("/api/packages/medical-wikimed/status")
    assert r.status_code == 200
    assert r.json()["status"] == "not_installed"


# ── POST /api/packages/{id}/install ──────────────────────────────────────────

async def test_install_returns_404_for_unknown_module(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/install")
    assert r.status_code == 404


async def test_install_returns_202_and_queues_when_download_active(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._active_tasks["other"] = object()
    r = await client.post("/api/packages/medical-wikimed/install")
    assert r.status_code == 202
    assert "medical-wikimed" in pkg_service._pending


async def test_cancel_endpoint_handles_queued(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    pkg_service._pending.append("medical-wikimed")
    r = await client.post("/api/packages/medical-wikimed/cancel")
    assert r.status_code == 204
    assert "medical-wikimed" not in pkg_service._pending


# ── POST /api/packages/{id}/cancel ───────────────────────────────────────────

async def test_cancel_returns_404_when_not_downloading(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/medical-wikimed/cancel")
    assert r.status_code == 404


# ── POST /api/packages/{id}/uninstall ────────────────────────────────────────

async def test_uninstall_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc")
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "uninstall_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/uninstall")
    assert r.status_code == 204


async def test_uninstall_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/uninstall")
    assert r.status_code == 404


async def test_accept_checksum_endpoint_returns_204(client, tmp_settings, monkeypatch):
    # Set up real mismatch state — endpoint calls the actual service function
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actual")
    monkeypatch.setattr(pkg_service, "_kiwix_add", lambda *a: None)
    monkeypatch.setattr(pkg_service, "_signal_service", lambda *a: None)
    r = await client.post("/api/packages/medical-wikimed/accept-checksum")
    assert r.status_code == 204


async def test_accept_checksum_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/accept-checksum")
    assert r.status_code == 404


async def test_accept_checksum_endpoint_returns_409_when_no_mismatch_pending(client, tmp_settings):
    # No .part or .mismatch files — service raises RuntimeError → 409
    m = _mod()
    _seed(tmp_settings, [m])
    r = await client.post("/api/packages/medical-wikimed/accept-checksum")
    assert r.status_code == 409


async def test_discard_checksum_endpoint_returns_204(client, tmp_settings):
    # discard works even with no files present (missing_ok=True)
    m = _mod()
    _seed(tmp_settings, [m])
    r = await client.post("/api/packages/medical-wikimed/discard-checksum")
    assert r.status_code == 204


async def test_discard_checksum_endpoint_returns_404_for_unknown(client, tmp_settings):
    _seed(tmp_settings)
    r = await client.post("/api/packages/nonexistent/discard-checksum")
    assert r.status_code == 404


async def test_packages_page_shows_mismatch_module_in_installed_section(client, tmp_settings):
    m = _mod()
    _seed(tmp_settings, [m])
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    mismatch_file = tmp_settings.downloads_dir / "medical-wikimed.mismatch"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"content")
    mismatch_file.write_text("sha256:actualhash")
    r = await client.get("/settings/packages")
    assert r.status_code == 200
    assert "checksum_mismatch" in r.text


# ── POST /api/packages/{id}/activate ─────────────────────────────────────────

async def test_activate_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=False)
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "activate_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/activate")
    assert r.status_code == 204


# ── POST /api/packages/{id}/deactivate ───────────────────────────────────────

async def test_deactivate_endpoint_returns_204(client, tmp_settings, monkeypatch):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])

    async def _noop(*a): pass
    monkeypatch.setattr(pkg_service, "deactivate_module", _noop)
    r = await client.post("/api/packages/medical-wikimed/deactivate")
    assert r.status_code == 204


# ── init_kiwix_library / _kiwix_add / _kiwix_remove ──────────────────────────

def test_init_kiwix_library_creates_file(tmp_settings):
    pkg_service.init_kiwix_library(tmp_settings)
    library_xml = tmp_settings.zim_dir / "library.xml"
    assert library_xml.exists()
    assert "<library" in library_xml.read_text()


def test_init_kiwix_library_is_idempotent(tmp_settings):
    pkg_service.init_kiwix_library(tmp_settings)
    pkg_service.init_kiwix_library(tmp_settings)
    text = (tmp_settings.zim_dir / "library.xml").read_text()
    assert text.count("<library") == 1


def test_kiwix_add_writes_book_entry(tmp_settings, monkeypatch):
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.write_bytes(b"content")
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: None)
    pkg_service._kiwix_add(m, tmp_settings)
    text = (tmp_settings.zim_dir / "library.xml").read_text()
    assert 'path="medical-wikimed.zim"' in text
    assert 'name="medical-wikimed"' in text


def test_kiwix_add_is_idempotent(tmp_settings, monkeypatch):
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.write_bytes(b"content")
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: None)
    pkg_service._kiwix_add(m, tmp_settings)
    pkg_service._kiwix_add(m, tmp_settings)
    import xml.etree.ElementTree as ET
    tree = ET.parse(tmp_settings.zim_dir / "library.xml")
    assert len(tree.getroot().findall("book")) == 1


def test_kiwix_remove_removes_book_entry(tmp_settings, monkeypatch):
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.write_bytes(b"content")
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: None)
    pkg_service._kiwix_add(m, tmp_settings)
    pkg_service._kiwix_remove(m, tmp_settings)
    text = (tmp_settings.zim_dir / "library.xml").read_text()
    assert "medical-wikimed.zim" not in text


def test_kiwix_add_self_bootstraps_library_xml(tmp_settings, monkeypatch):
    """If library.xml doesn't exist yet (kiwix-serve race), _kiwix_add must
    create it and still register the book instead of silently no-opping."""
    m = _mod()
    tmp_settings.zim_dir.mkdir(parents=True, exist_ok=True)
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.write_bytes(b"content")
    library_xml = tmp_settings.zim_dir / "library.xml"
    assert not library_xml.exists()
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: None)

    pkg_service._kiwix_add(m, tmp_settings)

    assert library_xml.exists()
    assert 'path="medical-wikimed.zim"' in library_xml.read_text()


def test_reconcile_adds_installed_zims_missing_from_library(tmp_settings):
    """Self-heals registry rows that were installed while library.xml was
    missing (e.g. kiwix-serve hadn't created it yet)."""
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    # library.xml does not exist yet.

    pkg_service.reconcile_kiwix_library(tmp_settings)

    text = (tmp_settings.zim_dir / "library.xml").read_text()
    assert 'path="medical-wikimed.zim"' in text


def test_reconcile_removes_entries_for_missing_files(tmp_settings):
    """An entry whose .zim file is gone gets cleaned up."""
    import xml.etree.ElementTree as ET
    pkg_service.init_kiwix_library(tmp_settings)
    tree = ET.parse(tmp_settings.zim_dir / "library.xml")
    root = tree.getroot()
    ET.SubElement(root, "book", {
        "id": "stale-id", "path": "vanished.zim", "name": "vanished",
    })
    tree.write(str(tmp_settings.zim_dir / "library.xml"), encoding="unicode", xml_declaration=True)
    _seed(tmp_settings, [])

    pkg_service.reconcile_kiwix_library(tmp_settings)

    text = (tmp_settings.zim_dir / "library.xml").read_text()
    assert "vanished.zim" not in text


def test_reconcile_preserves_entries_with_existing_files_not_in_registry(tmp_settings):
    """A manually-copied ZIM (not tracked in the registry) but present on
    disk and in library.xml is kept — conservative, doesn't wipe user state."""
    import xml.etree.ElementTree as ET
    pkg_service.init_kiwix_library(tmp_settings)
    (tmp_settings.zim_dir / "manual.zim").write_bytes(b"x")
    tree = ET.parse(tmp_settings.zim_dir / "library.xml")
    root = tree.getroot()
    ET.SubElement(root, "book", {
        "id": "manual-id", "path": "manual.zim", "name": "manual",
    })
    tree.write(str(tmp_settings.zim_dir / "library.xml"), encoding="unicode", xml_declaration=True)
    _seed(tmp_settings, [])

    pkg_service.reconcile_kiwix_library(tmp_settings)

    assert 'path="manual.zim"' in (tmp_settings.zim_dir / "library.xml").read_text()


def test_reconcile_is_idempotent(tmp_settings):
    m = _mod(installed_version="2024-10", installed_checksum="sha256:abc", active=True)
    _seed(tmp_settings, [m])
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.parent.mkdir(parents=True, exist_ok=True)
    zim.write_bytes(b"content")
    pkg_service.reconcile_kiwix_library(tmp_settings)
    pkg_service.reconcile_kiwix_library(tmp_settings)
    import xml.etree.ElementTree as ET
    tree = ET.parse(tmp_settings.zim_dir / "library.xml")
    assert len(tree.getroot().findall("book")) == 1


def test_kiwix_add_signals_kiwix_serve(tmp_settings, monkeypatch):
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    zim = tmp_settings.zim_dir / "medical-wikimed.zim"
    zim.write_bytes(b"content")
    calls = []
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: calls.append(cmd))
    pkg_service._kiwix_add(m, tmp_settings)
    assert any("kiwix-serve" in " ".join(c) for c in calls)


def test_kiwix_remove_signals_kiwix_serve(tmp_settings, monkeypatch):
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    calls = []
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: calls.append(cmd))
    pkg_service._kiwix_remove(m, tmp_settings)
    assert any("kiwix-serve" in " ".join(c) for c in calls)


def test_kiwix_add_logs_warning_when_zim_missing(tmp_settings, monkeypatch, caplog):
    import logging
    m = _mod()
    pkg_service.init_kiwix_library(tmp_settings)
    monkeypatch.setattr(pkg_service, "_run", lambda cmd: None)
    with caplog.at_level(logging.WARNING, logger="app.services.packages"):
        pkg_service._kiwix_add(m, tmp_settings)
    assert any("not found" in r.message for r in caplog.records)


# ── .total sidecar: total-size fallback ───────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code: int, headers: dict[str, str]):
        self.status_code = status_code
        self.headers = headers


def test_parse_total_from_response_uses_content_length_on_200():
    r = _FakeResp(200, {"Content-Length": "12345"})
    assert pkg_service._parse_total_from_response(r) == 12345


def test_parse_total_from_response_parses_content_range_on_206():
    r = _FakeResp(206, {"Content-Range": "bytes 100-199/5000"})
    assert pkg_service._parse_total_from_response(r) == 5000


def test_parse_total_from_response_returns_none_when_total_unknown():
    r_206_star = _FakeResp(206, {"Content-Range": "bytes 0-99/*"})
    r_200_no_cl = _FakeResp(200, {})
    assert pkg_service._parse_total_from_response(r_206_star) is None
    assert pkg_service._parse_total_from_response(r_200_no_cl) is None


def test_get_download_status_prefers_sidecar_over_size_gb(tmp_settings):
    m = _mod(size_gb=0.0)
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    (tmp_settings.downloads_dir / "medical-wikimed.total").write_text("2000")
    pkg_service._active_tasks["medical-wikimed"] = object()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["total_bytes"] == 2000
    assert result["pct"] == 25  # 500 / 2000


def test_get_download_status_falls_back_to_size_gb_without_sidecar(tmp_settings):
    m = _mod(size_gb=1.0)  # 1 GB
    part = tmp_settings.downloads_dir / "medical-wikimed.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"x" * 500)
    pkg_service._active_tasks["medical-wikimed"] = object()
    result = pkg_service.get_download_status(m, tmp_settings)
    assert result["total_bytes"] == 1024 ** 3


async def test_uninstall_removes_total_sidecar(tmp_settings):
    m = _mod()
    _seed(tmp_settings, modules=[m])
    (tmp_settings.downloads_dir).mkdir(parents=True, exist_ok=True)
    (tmp_settings.downloads_dir / "medical-wikimed.total").write_text("12345")
    await pkg_service.uninstall_module(m, tmp_settings)
    assert not (tmp_settings.downloads_dir / "medical-wikimed.total").exists()


async def test_discard_checksum_mismatch_removes_total_sidecar(tmp_settings):
    m = _mod()
    (tmp_settings.downloads_dir).mkdir(parents=True, exist_ok=True)
    (tmp_settings.downloads_dir / "medical-wikimed.total").write_text("12345")
    await pkg_service.discard_checksum_mismatch(m, tmp_settings)
    assert not (tmp_settings.downloads_dir / "medical-wikimed.total").exists()
