from __future__ import annotations
import uuid
from typing import Any, Optional
from app.config import Settings
from app.models.library import (
    Library,
    LibraryAlreadyExistsError,
    LibraryNotFoundError,
)
from app.models.registry import Module, Registry

def load_registry(settings: Settings) -> Registry:
    path = settings.registry_path
    if not path.exists():
        reg = Registry()
        save_registry(settings, reg)
        return reg
    return Registry.model_validate_json(path.read_text())


def save_registry(settings: Settings, registry: Registry) -> None:
    path = settings.registry_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2))


def get_active_modules(settings: Settings) -> list[Module]:
    return [m for m in load_registry(settings).modules if m.active]


def set_module_active(settings: Settings, module_id: str, active: bool) -> None:
    registry = load_registry(settings)
    for module in registry.modules:
        if module.id == module_id:
            module.active = active
            save_registry(settings, registry)
            return
    raise KeyError(module_id)


def merge_remote_manifest(
    settings: Settings, remote_modules: list[dict[str, Any]]
) -> list[Module]:
    registry = load_registry(settings)
    existing = {m.id: m for m in registry.modules}
    for remote in remote_modules:
        module_id = remote["id"]
        if module_id in existing:
            current = existing[module_id]
            overrides = {
                "installed_version": current.installed_version,
                "installed_checksum": current.installed_checksum,
                "active": current.active,
                # The category was assigned by the user in the import wizard; a
                # later library refresh must not revert it to the manifest value.
                "category": current.category,
            }
            # Preserve the locally-resolved bundled image (set at install time
            # by _resolve_bundled_image) when the manifest doesn't ship an
            # HTTP image_url. Without this, every refresh would clear the
            # image we copied from inside the package tarball.
            if not remote.get("image") and current.image:
                overrides["image"] = current.image
            updated = Module(**{**remote, **overrides})
            existing[module_id] = updated
        else:
            existing[module_id] = Module(**remote)
    registry.modules = list(existing.values())
    save_registry(settings, registry)
    return registry.modules


def list_libraries(settings: Settings) -> list[Library]:
    return load_registry(settings).libraries


def add_library(
    settings: Settings,
    url: str,
    display_name: str,
    lang: Optional[str] = None,
    library_type: str = "opds",
) -> Library:
    if library_type == "opds":
        from app.services.libraries import normalize_opds_url
        canonical_url, lang_from_url = normalize_opds_url(url)
    else:
        from app.services.git_libraries import normalize_git_url
        canonical_url = normalize_git_url(url, library_type)
        lang_from_url = None
    registry = load_registry(settings)
    for existing in registry.libraries:
        if existing.url == canonical_url:
            raise LibraryAlreadyExistsError(f"library already exists: {canonical_url}")
    library = Library(
        id=uuid.uuid4().hex,
        display_name=display_name,
        url=canonical_url,
        lang=lang or lang_from_url,
        type=library_type,
    )
    registry.libraries.append(library)
    save_registry(settings, registry)
    return library


def remove_library(settings: Settings, library_id: str) -> None:
    """Remove a library; prune Available modules from it, clear source on Installed."""
    from app.services.thumbnails import delete_thumbnail

    registry = load_registry(settings)
    if not any(lib.id == library_id for lib in registry.libraries):
        raise LibraryNotFoundError(library_id)

    kept_modules: list[Module] = []
    dropped_ids: list[str] = []
    for m in registry.modules:
        if m.source_library_id != library_id:
            kept_modules.append(m)
            continue
        if m.is_installed:
            m.source_library_id = None
            kept_modules.append(m)
        else:
            dropped_ids.append(m.id)
    registry.modules = kept_modules
    registry.libraries = [lib for lib in registry.libraries if lib.id != library_id]
    save_registry(settings, registry)

    for module_id in dropped_ids:
        delete_thumbnail(module_id, settings)
