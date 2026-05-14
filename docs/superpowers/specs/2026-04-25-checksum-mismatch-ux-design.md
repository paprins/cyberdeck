# Checksum Mismatch UX — Design Spec

**Date:** 2026-04-25
**Status:** Approved

## Problem

When a downloaded file's SHA256 digest doesn't match the manifest's expected checksum, the app silently deletes the `.part` file and logs an error. The user sees nothing — the module just disappears back into "available". There is no way to accept a mismatched file even when the manifest may be stale.

## Goal

Surface the mismatch to the user with the actual and expected checksums, and offer two actions: accept the download (install with actual checksum recorded) or discard it.

## Approach: Sidecar `.mismatch` File

On checksum mismatch, keep the `.part` file and write a sidecar `downloads/{id}.mismatch` containing the actual digest as a single line (e.g. `sha256:abcdef…`). This state survives server restarts — the mismatch warning reappears correctly after reboot.

## Backend Changes

### `app/services/packages.py`

**New helper:**
```python
def _mismatch_path(module: Module, settings: Settings) -> Path:
    return settings.downloads_dir / f"{module.id}.mismatch"
```

**On checksum mismatch** (currently raises ValueError, deletes `.part`):
- Keep `.part` file
- Write actual digest to `.mismatch` file
- Log a warning (not an exception — this is surfaced to the user now)
- Return without raising (download task ends cleanly)

**`get_download_status` new branch** — before the existing `.part` check:
```
if part.exists() and mismatch.exists():
    return {
        "status": "checksum_mismatch",
        "actual_checksum": mismatch.read_text().strip(),
        "expected_checksum": module.checksum,
        "bytes_downloaded": part.stat().st_size,
        "total_bytes": total_bytes,
        "pct": 100,
    }
```

**`uninstall_module`:** also unlinks `.mismatch` (missing_ok=True).

### `app/routers/packages.py`

**`POST /api/packages/{id}/accept-checksum`:**
1. Load `.mismatch` to get actual digest; 404 if absent
2. Move `.part` → final path (same as normal install)
3. Delete `.mismatch`
4. Save registry: `installed_version = latest_version`, `installed_checksum = actual_digest`, `active = True`
5. Run post-install steps: `_kiwix_add` (if not maps), `_signal_service`
6. Return 204

**`POST /api/packages/{id}/discard-checksum`:**
1. Delete `.part` and `.mismatch` (both missing_ok=True)
2. Return 204

**`installed` filter in packages page router:** add `"checksum_mismatch"` to the status set alongside `"downloading"` and `"interrupted"`.

## UI Changes (`app/templates/packages.html`)

The installed card's Alpine.js component already reloads on any non-`downloading` status — no polling changes needed.

**New state variables on Alpine component:**
- `actual_checksum` and `expected_checksum` — populated from initial status (SSR) and status poll response

**New display block** (alongside Downloading / Interrupted / Installed):
```
x-show="status === 'checksum_mismatch'"
```
Content:
- Label: `⚠ CHECKSUM_MISMATCH` in `text-error font-headline`
- Two rows showing truncated hashes (first 20 chars + `…`):
  - `EXPECTED: sha256:…`
  - `ACTUAL:   sha256:…`
- Body text color: `text-error/70`

**Action buttons for `checksum_mismatch`:**
- `ACCEPT` — `text-primary border-primary/40` (deliberate informed action, not danger)  
  calls `POST /api/packages/{id}/accept-checksum` then `location.reload()`
- `DISCARD` — `text-error border-error/40`  
  calls `POST /api/packages/{id}/discard-checksum` then `location.reload()`

**Guard fix:** `x-show="status === 'installed' || status === 'not_installed'"` on the info div (already correct in template — just ensure `checksum_mismatch` is not accidentally included).

## Checksum Field Semantics

- `module.checksum` — manifest's expected value; never modified
- `module.installed_checksum` — what was actually installed (may differ on accepted mismatch)

A future update check comparing `installed_checksum` vs `checksum` is not in scope here.

## Testing

- Unit test: `get_download_status` returns `checksum_mismatch` when both `.part` and `.mismatch` exist
- Unit test: `get_download_status` returns `interrupted` when only `.part` exists (no `.mismatch`)
- Integration test: download with injected bad checksum → verify `.mismatch` written, `.part` kept
- Integration test: `accept-checksum` → verify file moved, registry updated, `.mismatch` deleted
- Integration test: `discard-checksum` → verify both files deleted, status returns `not_installed`
- Integration test: `uninstall` with mismatch state → verify `.mismatch` cleaned up
