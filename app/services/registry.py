from __future__ import annotations
from typing import Any
from app.config import Settings
from app.models.registry import Module, Registry

_DEFAULT_UPDATE_SERVER = "https://updates.example.com/cyberdeck/manifest.json"


def load_registry(settings: Settings) -> Registry:
    path = settings.registry_path
    if not path.exists():
        reg = Registry(update_server=_DEFAULT_UPDATE_SERVER)
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
) -> None:
    registry = load_registry(settings)
    existing = {m.id: m for m in registry.modules}
    for remote in remote_modules:
        module_id = remote["id"]
        if module_id in existing:
            current = existing[module_id]
            updated = Module(
                **{
                    **remote,
                    "installed_version": current.installed_version,
                    "installed_checksum": current.installed_checksum,
                    "active": current.active,
                }
            )
            existing[module_id] = updated
        else:
            existing[module_id] = Module(**remote)
    registry.modules = list(existing.values())
    save_registry(settings, registry)
