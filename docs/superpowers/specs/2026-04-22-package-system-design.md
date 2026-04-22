# Package System — Design Spec

**Date:** 2026-04-22
**Plan:** 4 of 4
**Depends on:** Plans 1–3

---

## Goal

Add a fully functional package manager to the cyberdeck: fetch an update manifest from the network, download ZIM / mbtiles content modules with resumable HTTP transfers, verify checksums, install/uninstall, and control bento-grid visibility via activate/deactivate. All managed through a new `/packages` screen.

---

## Scope

**In scope:**
- `GET /packages` — server-rendered packages screen
- `POST /api/packages/check-updates` — manual manifest fetch and registry merge
- `GET /api/packages/{id}/status` — download progress polling
- `POST /api/packages/{id}/install` — start (or resume) download
- `POST /api/packages/{id}/cancel` — cancel active download, leave `.part` file
- `POST /api/packages/{id}/uninstall` — delete file, clear registry
- `POST /api/packages/{id}/activate` — show module on bento grid; add to kiwix library
- `POST /api/packages/{id}/deactivate` — hide module from bento grid; remove from kiwix library
- Chrome simplification in `base.html`: remove modules count, remove updates badge, wifi dot-only (no text) — applies to all pages

**Out of scope:**
- Background/automatic update checking
- Concurrent downloads (one at a time; 409 if busy)
- Custom update server configuration UI
- Module detail pages

---

## Model changes

### `app/models/registry.py`

Add one optional field to `Module`:

```python
download_url: Optional[str] = None
```

This is populated from the remote manifest and persisted in `registry.json`. It is the URL used for both initial download and resume. No other model changes.

---

## Filesystem state

Download state is derived entirely from the filesystem — no extra JSON file.

| Condition | Derived status |
|---|---|
| Active asyncio task in `_active_tasks[id]` | `downloading` |
| `/data/downloads/{id}.part` exists, no active task | `interrupted` |
| Final file exists in `/data/zim/` or `/data/maps/` | `installed` |
| None of the above | `not_installed` |

**Paths:**
- Partial file: `/data/downloads/{id}.part`
- ZIM final: `/data/zim/{id}.zim`
- MBTiles final: `/data/maps/{id}.mbtiles`

`bytes_downloaded` is the `.part` file's current size on disk. `total_bytes` is derived from `Module.size_gb * 1024³` (already in the registry — no separate tracking needed).

---

## Services

### `app/services/packages.py`

Single service module. Owns the download manager and all install/uninstall/activate logic.

**Download manager state (module-level):**
```python
_active_tasks: dict[str, asyncio.Task] = {}
```

**Public interface:**

```python
async def start_download(module: Module, settings: Settings) -> None
    """Starts or resumes a download. Raises RuntimeError if another download is active."""

async def cancel_download(module_id: str) -> None
    """Cancels the active task. Leaves .part file for future resume."""

def get_download_status(module: Module, settings: Settings) -> dict
    """Returns {status, bytes_downloaded, total_bytes, pct}. Reads filesystem."""

async def uninstall_module(module: Module, settings: Settings) -> None
    """Deletes final file and .part file if present. Updates registry."""

async def activate_module(module: Module, settings: Settings) -> None
    """Sets active=True in registry. Adds ZIM to kiwix library and signals reload."""

async def deactivate_module(module: Module, settings: Settings) -> None
    """Sets active=False in registry. Removes ZIM from kiwix library and signals reload."""
```

**Download task internals:**
1. Compute `offset = .part file size` (0 if no partial file)
2. `GET module.download_url` with `Range: bytes={offset}-` header
3. Stream response in 64 KB chunks, appending to `.part`
4. On completion: verify SHA-256 against `module.checksum`; move `.part` to final path; update registry (`installed_version`, `installed_checksum`, `active=True`); call activate to update kiwix; remove from `_active_tasks`
5. On error or cancellation: remove from `_active_tasks`; leave `.part` file intact

**Kiwix integration:**
- Add: `subprocess.run(["kiwix-manage", str(library_xml), "add", str(zim_path)])`
- Remove: `subprocess.run(["kiwix-manage", str(library_xml), "delete", module_id])`
- After either: send SIGHUP to kiwix-serve via `subprocess.run(["pkill", "-HUP", "kiwix-serve"])`
- Both calls are best-effort: failures are logged, not raised (kiwix may not be running in dev)

**mbtileserver integration:**
- No library file to manage — mbtileserver auto-discovers files in `/data/maps/`
- After install/uninstall: `subprocess.run(["pkill", "-HUP", "mbtileserver"])`
- Best-effort, same as kiwix

**Check for updates:**
```python
async def check_for_updates(settings: Settings) -> int
    """Fetches manifest, calls merge_remote_manifest(), returns count of new/updated modules."""
```
Fetches `registry.update_server` via httpx with a 10-second timeout. On network error, raises so the router can return a 502. On success, calls the existing `merge_remote_manifest()`.

**Storage info:**
```python
def get_storage_info(settings: Settings) -> dict
    """Returns {used_bytes, free_bytes} for the data_dir filesystem."""
```
Uses `shutil.disk_usage(settings.data_dir)`.

---

## Router

### `app/routers/packages.py`

```
GET  /packages                      → HTML (server-rendered)
POST /api/packages/check-updates    → {updated: int} | 502
GET  /api/packages/{id}/status      → {status, bytes_downloaded, total_bytes, pct}
POST /api/packages/{id}/install     → 202 | 404 | 409
POST /api/packages/{id}/cancel      → 204 | 404
POST /api/packages/{id}/uninstall   → 204 | 404
POST /api/packages/{id}/activate    → 204 | 404
POST /api/packages/{id}/deactivate  → 204 | 404
```

The `GET /packages` route renders `packages.html` with:
- Full registry (all modules)
- Storage info (`used_bytes`, `free_bytes`)
- Download status for any module with a `.part` file or active task

Alpine.js on the page polls `GET /api/packages/{id}/status` every second for any module currently `downloading`, stopping when status changes to `installed` or `interrupted`. All mutating actions (`install`, `cancel`, etc.) are `fetch()` POSTs; on response the page re-fetches the status of the affected module and updates its row reactively without a full page reload.

---

## Template

### `app/templates/packages.html`

Extends `base.html`. Three sections rendered server-side; Alpine.js handles live progress and reactive button state per row.

**Sections (in order):**
1. **Updates available** (amber) — modules where `has_update` is True; shown only if count > 0
2. **Installed** — modules where `is_installed` is True (includes downloading and interrupted states)
3. **Available** — remaining modules (not installed); dimmed styling

**Row states and actions:**

| State | Actions shown |
|---|---|
| Active | Active badge (click to deactivate) · Remove |
| Inactive (installed) | Activate · Remove |
| Downloading | Progress bar + "X GB of Y GB · Z%" · Cancel |
| Interrupted | "⚠ Interrupted · X GB of Y GB" · Resume · Remove |
| Update available | Update · Remove |
| Not installed | Install |

**While any download is active:** all Install buttons on not-installed modules are disabled (greyed, non-clickable). Only one download at a time.

**Storage bar:** thin progress bar below the page header. `used / (used + free)` fill width. Label: `"X GB used · Y GB free"`.

**Check for updates button:** top-right of page header. Shows a spinner state while the request is in flight (Alpine.js). On success, triggers a full page reload so new modules appear. On failure, shows an inline error for 3 seconds.

---

## Chrome changes (`base.html`)

Remove from the top chrome on **all pages**:
- "Modules N active" label + value
- Updates-available badge (amber bubble with count)
- "connected" / "offline" text next to the wifi dot

After: chrome shows `⬡ CYBERDECK` · `Net [dot]` · `Bat [pct]`

The packages screen already surfaces update counts via its own section header. The home portal bento already communicates active module count visually. The wifi dot alone is sufficient — green = connected, grey = offline.

---

## Testing

### `tests/test_packages.py`

**Service unit tests (no HTTP):**
- `test_get_download_status_not_installed` — no `.part`, no final file → `not_installed`
- `test_get_download_status_interrupted` — `.part` exists, no active task → `interrupted`, correct byte count
- `test_get_download_status_installed` — final file exists → `installed`
- `test_get_storage_info_returns_used_and_free`
- `test_uninstall_deletes_final_file`
- `test_uninstall_deletes_part_file_if_present`
- `test_uninstall_clears_registry_fields`

**HTTP endpoint tests (AsyncClient + ASGITransport):**
- `test_packages_page_returns_200`
- `test_packages_page_returns_html`
- `test_packages_page_shows_installed_module`
- `test_packages_page_shows_available_module`
- `test_packages_page_shows_updates_section_when_update_exists`
- `test_check_updates_returns_502_on_network_error` (monkeypatched httpx)
- `test_install_returns_409_when_download_active`
- `test_install_returns_404_for_unknown_module`
- `test_status_returns_not_installed_for_unknown`
- `test_cancel_returns_404_for_inactive_module`
- `test_uninstall_endpoint_returns_204`
- `test_activate_endpoint_returns_204`
- `test_deactivate_endpoint_returns_204`

Download task tests use monkeypatching to avoid real HTTP; kiwix/mbtileserver subprocess calls are mocked.

---

## File map

| File | Action |
|---|---|
| `app/models/registry.py` | Add `download_url: Optional[str] = None` to `Module` |
| `app/services/packages.py` | Create — download manager, install/uninstall/activate/deactivate, kiwix integration |
| `app/routers/packages.py` | Create — all `/packages` and `/api/packages/*` routes |
| `app/templates/packages.html` | Create — packages screen (extends base.html) |
| `app/templates/base.html` | Modify — remove modules count, updates badge, wifi text |
| `app/main.py` | Modify — include packages router |
| `tests/test_packages.py` | Create |

---

## Self-review

**Placeholder scan:** No TBDs or incomplete sections found.

**Internal consistency:**
- `download_url` added to model → used in `start_download()` for both initial fetch and resume ✓
- Filesystem state derivation is the single source of truth — no parallel state in model ✓
- `merge_remote_manifest()` already exists in `app/services/registry.py` — reused for check-updates ✓
- Kiwix/mbtileserver calls are best-effort in both activate and the post-install step ✓
- Chrome changes affect `base.html` — both home and packages templates extend it, so both get the update ✓

**Scope check:** Focused. One plan's worth of work.

**Ambiguity check:**
- "One download at a time" — second `POST /api/packages/{id}/install` returns 409 (not queue) ✓
- "Update" action = cancel any existing download, delete old final file, start fresh download with new `download_url` and `checksum` from manifest ✓
- "Remove" on a downloading module = cancel first, then delete `.part`, then clear registry ✓
