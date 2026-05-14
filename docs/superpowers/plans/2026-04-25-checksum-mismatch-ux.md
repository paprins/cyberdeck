# Checksum Mismatch UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a downloaded file's SHA256 digest doesn't match the manifest's expected checksum, surface the mismatch to the user with both checksums and offer ACCEPT (install anyway) or DISCARD (delete download) actions.

**Architecture:** On mismatch, `_download_task` writes a `downloads/{id}.mismatch` sidecar file containing the actual digest, then returns without installing. `get_download_status` detects the sidecar and returns a new `checksum_mismatch` status with both digests. Two new service functions (`accept_checksum_mismatch`, `discard_checksum_mismatch`) and two new API endpoints handle the user's choice. The packages template adds a new display state and action buttons for `checksum_mismatch`.

**Tech Stack:** Python/FastAPI, Jinja2, Alpine.js, pytest/httpx

---

## File Map

| File | Change |
|------|--------|
| `app/services/packages.py` | Add `_mismatch_path`, update `get_download_status`, update `_download_task`, update `uninstall_module`, add `accept_checksum_mismatch` + `discard_checksum_mismatch` |
| `app/routers/packages.py` | Add two endpoints, update `installed` filter, expand imports |
| `app/templates/packages.html` | Add `checksum_mismatch` state block and action buttons to installed card |
| `tests/test_packages.py` | Add tests for all new behaviour |

---

## Task 1: `_mismatch_path` helper and `get_download_status` mismatch branch

**Files:**
- Modify: `app/services/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_packages.py` after the existing `get_download_status` tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/pprins/projects/home/cyberdeck
uv run pytest tests/test_packages.py::test_get_download_status_checksum_mismatch tests/test_packages.py::test_get_download_status_interrupted_without_mismatch_file -v
```

Expected: FAIL — `_mismatch_path` not defined, `checksum_mismatch` status not returned.

- [ ] **Step 3: Add `_mismatch_path` helper and update `get_download_status`**

In `app/services/packages.py`, add `_mismatch_path` alongside the other path helpers (after `_part_path`):

```python
def _mismatch_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.mismatch"
```

In `get_download_status`, add the mismatch branch **before** the existing `if module.id in _active_tasks:` block. The full updated function:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_packages.py::test_get_download_status_checksum_mismatch tests/test_packages.py::test_get_download_status_interrupted_without_mismatch_file -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite to check for regressions**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: add _mismatch_path helper and checksum_mismatch status branch"
```

---

## Task 2: Update `_download_task` to write `.mismatch` instead of deleting `.part`

**Files:**
- Modify: `app/services/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_packages.py`:

```python
async def test_download_writes_mismatch_file_on_checksum_failure(tmp_settings, monkeypatch):
    m = _mod(checksum="sha256:expectedbutnotthis")
    _seed(tmp_settings, [m])
    tmp_settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    fake_bytes = b"fake file content"

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
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
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size):
            yield fake_bytes

    class _Stream:
        async def __aenter__(self): return _Resp()
        async def __aexit__(self, *a): pass

    class _Client:
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_packages.py::test_download_writes_mismatch_file_on_checksum_failure tests/test_packages.py::test_download_does_not_write_mismatch_on_correct_checksum -v
```

Expected: FAIL — first test fails because `.mismatch` is not written and `.part` is deleted.

- [ ] **Step 3: Update `_download_task` to handle mismatch inline**

Replace the checksum-mismatch section of `_download_task` in `app/services/packages.py`. The updated function body (full replacement from `async def _download_task` through its `finally` block):

```python
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
```

Note: the `except ValueError` block is gone — the mismatch is now handled inline with `return` (which still triggers `finally`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_packages.py::test_download_writes_mismatch_file_on_checksum_failure tests/test_packages.py::test_download_does_not_write_mismatch_on_correct_checksum -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: write .mismatch sidecar instead of deleting .part on checksum failure"
```

---

## Task 3: Service functions for accept/discard + update uninstall

**Files:**
- Modify: `app/services/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_packages.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_packages.py::test_accept_checksum_mismatch_installs_file tests/test_packages.py::test_accept_checksum_mismatch_raises_if_no_mismatch_pending tests/test_packages.py::test_discard_checksum_mismatch_deletes_files tests/test_packages.py::test_uninstall_clears_mismatch_file -v
```

Expected: FAIL — functions not defined.

- [ ] **Step 3: Add service functions and update `uninstall_module`**

In `app/services/packages.py`, add these two functions after `deactivate_module`:

```python
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
```

Replace `uninstall_module` with this updated version that also cleans up `.mismatch`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_packages.py::test_accept_checksum_mismatch_installs_file tests/test_packages.py::test_accept_checksum_mismatch_raises_if_no_mismatch_pending tests/test_packages.py::test_discard_checksum_mismatch_deletes_files tests/test_packages.py::test_uninstall_clears_mismatch_file -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/test_packages.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/packages.py tests/test_packages.py
git commit -m "feat: add accept/discard checksum mismatch service functions, update uninstall"
```

---

## Task 4: New API endpoints and router filter update

**Files:**
- Modify: `app/routers/packages.py`
- Modify: `tests/test_packages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_packages.py`:

```python
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
    r = await client.get("/packages")
    assert r.status_code == 200
    assert "checksum_mismatch" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_packages.py::test_accept_checksum_endpoint_returns_204 tests/test_packages.py::test_accept_checksum_endpoint_returns_404_for_unknown tests/test_packages.py::test_accept_checksum_endpoint_returns_409_when_no_mismatch_pending tests/test_packages.py::test_discard_checksum_endpoint_returns_204 tests/test_packages.py::test_discard_checksum_endpoint_returns_404_for_unknown tests/test_packages.py::test_packages_page_shows_mismatch_module_in_installed_section -v
```

Expected: FAIL — endpoints not found (404), page doesn't include `checksum_mismatch`.

- [ ] **Step 3: Update `app/routers/packages.py`**

Update the import block at the top:

```python
from app.services.packages import (
    _active_tasks,
    accept_checksum_mismatch,
    activate_module,
    cancel_download,
    check_for_updates,
    deactivate_module,
    discard_checksum_mismatch,
    get_download_status,
    get_storage_info,
    start_download,
    uninstall_module,
)
```

Update the `installed` list comprehension in `packages_page`:

```python
        installed = [
            m for m in registry.modules
            if (m.is_installed and not m.has_update)
            or (not m.is_installed and all_statuses[m.id]["status"] in ("downloading", "interrupted", "checksum_mismatch"))
        ]
```

Add these two endpoints before `return router` at the end of `make_router`:

```python
    @router.post("/api/packages/{module_id}/accept-checksum")
    async def accept_checksum(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            await accept_checksum_mismatch(module, cfg)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return Response(status_code=204)

    @router.post("/api/packages/{module_id}/discard-checksum")
    async def discard_checksum(module_id: str):
        registry = load_registry(cfg)
        module = next((m for m in registry.modules if m.id == module_id), None)
        if module is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        await discard_checksum_mismatch(module, cfg)
        return Response(status_code=204)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_packages.py::test_accept_checksum_endpoint_returns_204 tests/test_packages.py::test_accept_checksum_endpoint_returns_404_for_unknown tests/test_packages.py::test_accept_checksum_endpoint_returns_409_when_no_mismatch_pending tests/test_packages.py::test_discard_checksum_endpoint_returns_204 tests/test_packages.py::test_discard_checksum_endpoint_returns_404_for_unknown tests/test_packages.py::test_packages_page_shows_mismatch_module_in_installed_section -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/routers/packages.py tests/test_packages.py
git commit -m "feat: add accept-checksum and discard-checksum endpoints, include mismatch in installed list"
```

---

## Task 5: Template — `checksum_mismatch` display state and action buttons

**Files:**
- Modify: `app/templates/packages.html`

No test step needed here (template rendering is already covered by `test_packages_page_shows_mismatch_module_in_installed_section` in Task 4 which checks `checksum_mismatch` appears in the HTML).

- [ ] **Step 1: Add `actual_checksum` and `expected_checksum` to the Alpine component's `x-data`**

In `packages.html`, find the `x-data` block for the installed card (around line 99). It currently starts with:

```
    x-data="{
      status: '{{ s.status }}',
      pct: {{ s.pct }},
      bytes_dl: {{ s.bytes_downloaded }},
      total: {{ s.total_bytes }},
      _poll: null,
```

Replace with:

```
    x-data="{
      status: '{{ s.status }}',
      pct: {{ s.pct }},
      bytes_dl: {{ s.bytes_downloaded }},
      total: {{ s.total_bytes }},
      actual_checksum: '{{ s.actual_checksum | default("") }}',
      expected_checksum: '{{ s.expected_checksum | default("") }}',
      _poll: null,
```

- [ ] **Step 2: Add the `checksum_mismatch` display block**

After the existing `<!-- Interrupted -->` div (around line 143), add:

```html
    <!-- Checksum mismatch -->
    <div class="flex-1 min-w-0" x-show="status === 'checksum_mismatch'" x-cloak>
      <div class="font-headline font-bold text-[12px] text-error truncate tracking-[0.04em] uppercase">{{ m.display_name | replace(' ', '_') }}</div>
      <div class="font-body text-[10px] text-error font-bold mt-[2px]">⚠ CHECKSUM_MISMATCH</div>
      <div class="font-body text-[9px] text-error/60 mt-[2px]" x-text="'EXP: ' + expected_checksum.slice(0, 24) + '…'"></div>
      <div class="font-body text-[9px] text-error/60" x-text="'GOT: ' + actual_checksum.slice(0, 24) + '…'"></div>
    </div>
```

- [ ] **Step 3: Add action buttons for `checksum_mismatch`**

After the existing `<template x-if="status === 'interrupted'">` block (around line 170), add:

```html
      <template x-if="status === 'checksum_mismatch'">
        <div class="flex gap-[6px]">
          <button @click="act('/api/packages/{{ m.id }}/accept-checksum')"
                  class="font-headline text-[10px] font-bold px-2 py-[4px] border text-primary border-primary/40">
            ACCEPT
          </button>
          <button @click="act('/api/packages/{{ m.id }}/discard-checksum')"
                  class="font-headline text-[10px] font-bold px-2 py-[4px] border text-error border-error/40">
            DISCARD
          </button>
        </div>
      </template>
```

- [ ] **Step 4: Verify visually**

Start the dev server:

```bash
CYBERDECK_DATA_DIR=data uv run uvicorn app.main:app --reload --port 8000
```

To simulate a mismatch state, write a `.mismatch` sidecar and a dummy `.part` file:

```bash
echo "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" > data/downloads/medical-wikimed.mismatch
dd if=/dev/zero bs=1024 count=10 > data/downloads/medical-wikimed.part
```

Navigate to `http://localhost:8000/packages` and verify:
- WikiMed appears in the INSTALLED section (not AVAILABLE)
- `⚠ CHECKSUM_MISMATCH` label shows in error red
- Two truncated checksum lines appear (`EXP:` and `GOT:`)
- `ACCEPT` button is present in primary color
- `DISCARD` button is present in error red
- Clicking DISCARD removes the card (page reloads, module moves to AVAILABLE)
- Clicking ACCEPT with a real `.part` file installs it (module moves to installed state)

Clean up the test files after verification:

```bash
rm -f data/downloads/medical-wikimed.mismatch data/downloads/medical-wikimed.part
```

- [ ] **Step 5: Run full test suite one final time**

```bash
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/templates/packages.html
git commit -m "feat: show checksum mismatch warning and accept/discard actions in packages UI"
```
