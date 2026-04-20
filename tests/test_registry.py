import json
import pytest
from app.models.registry import Module, Registry


def test_module_defaults():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed Medical Encyclopedia",
        category="medical",
        description="Offline medical reference",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc123",
    )
    assert m.installed_version is None
    assert m.installed_checksum is None
    assert m.active is False


def test_module_is_installed():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc123",
        installed_version="2024-10",
        installed_checksum="sha256:abc123",
    )
    assert m.is_installed is True
    assert m.has_update is False


def test_module_has_update():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-11",
        size_gb=0.8,
        checksum="sha256:newchecksum",
        installed_version="2024-10",
        installed_checksum="sha256:oldchecksum",
    )
    assert m.is_installed is True
    assert m.has_update is True


def test_registry_defaults():
    r = Registry(update_server="https://example.com/manifest.json")
    assert r.modules == []


def test_registry_serialises_to_json():
    r = Registry(update_server="https://example.com/manifest.json")
    data = json.loads(r.model_dump_json())
    assert data["update_server"] == "https://example.com/manifest.json"
    assert data["modules"] == []


from app.services.registry import (
    load_registry,
    save_registry,
    get_active_modules,
    set_module_active,
    merge_remote_manifest,
)


# ── helpers ──────────────────────────────────────────────

def _seed(tmp_settings, modules=None):
    """Write a registry.json to the tmp data dir."""
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    reg = Registry(
        update_server="https://example.com/manifest.json",
        modules=modules or [],
    )
    tmp_settings.registry_path.write_text(reg.model_dump_json())


def _sample_module(**overrides) -> Module:
    defaults = dict(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="Medical reference",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
    )
    defaults.update(overrides)
    return Module(**defaults)


# ── tests ─────────────────────────────────────────────────

def test_load_empty_registry(tmp_settings):
    _seed(tmp_settings)
    reg = load_registry(tmp_settings)
    assert reg.update_server == "https://example.com/manifest.json"
    assert reg.modules == []


def test_load_missing_creates_default(tmp_settings):
    reg = load_registry(tmp_settings)
    assert reg.modules == []
    assert tmp_settings.registry_path.exists()


def test_save_and_reload(tmp_settings):
    _seed(tmp_settings)
    reg = load_registry(tmp_settings)
    reg.update_server = "https://new.example.com/manifest.json"
    save_registry(tmp_settings, reg)
    reloaded = load_registry(tmp_settings)
    assert reloaded.update_server == "https://new.example.com/manifest.json"


def test_get_active_modules_empty(tmp_settings):
    _seed(tmp_settings)
    assert get_active_modules(tmp_settings) == []


def test_get_active_modules_returns_only_active(tmp_settings):
    m1 = _sample_module(id="medical-wikimed", active=True)
    m2 = _sample_module(id="survival-wikihow", active=False)
    _seed(tmp_settings, modules=[m1, m2])
    active = get_active_modules(tmp_settings)
    assert len(active) == 1
    assert active[0].id == "medical-wikimed"


def test_set_module_active_true(tmp_settings):
    _seed(tmp_settings, modules=[_sample_module(active=False)])
    set_module_active(tmp_settings, "medical-wikimed", True)
    active = get_active_modules(tmp_settings)
    assert len(active) == 1


def test_set_module_active_false(tmp_settings):
    _seed(tmp_settings, modules=[_sample_module(active=True)])
    set_module_active(tmp_settings, "medical-wikimed", False)
    assert get_active_modules(tmp_settings) == []


def test_set_module_active_nonexistent_raises(tmp_settings):
    _seed(tmp_settings)
    with pytest.raises(KeyError, match="nonexistent"):
        set_module_active(tmp_settings, "nonexistent", True)


def test_merge_remote_manifest_adds_new_modules(tmp_settings):
    _seed(tmp_settings)
    remote = [
        {
            "id": "medical-wikimed",
            "display_name": "WikiMed",
            "category": "medical",
            "description": "Medical reference",
            "latest_version": "2024-10",
            "size_gb": 0.8,
            "checksum": "sha256:abc",
        }
    ]
    merge_remote_manifest(tmp_settings, remote)
    reg = load_registry(tmp_settings)
    assert len(reg.modules) == 1
    assert reg.modules[0].id == "medical-wikimed"


def test_merge_remote_manifest_preserves_installed_state(tmp_settings):
    existing = _sample_module(
        installed_version="2024-10",
        installed_checksum="sha256:abc",
        active=True,
    )
    _seed(tmp_settings, modules=[existing])
    remote = [
        {
            "id": "medical-wikimed",
            "display_name": "WikiMed",
            "category": "medical",
            "description": "Medical reference",
            "latest_version": "2024-11",
            "size_gb": 0.9,
            "checksum": "sha256:newchecksum",
        }
    ]
    merge_remote_manifest(tmp_settings, remote)
    reg = load_registry(tmp_settings)
    m = reg.modules[0]
    assert m.latest_version == "2024-11"
    assert m.installed_version == "2024-10"
    assert m.active is True
