import json
import pytest
from app.models.registry import Module, Registry


def test_module_id_rejects_path_traversal():
    """Module.id flows directly into filesystem paths — must reject `..` and `/`."""
    import pytest
    from pydantic import ValidationError
    for bad in ("../escape", "foo/bar", "etc/passwd", "..", "x y"):
        with pytest.raises(ValidationError):
            Module(
                id=bad, display_name="x", category="medical", description="",
                latest_version="1", size_gb=0, checksum="sha256:abc",
            )


def _mod(**kw) -> Module:
    base = dict(
        id="m", display_name="x", category="medical", description="",
        latest_version="1", size_gb=0, checksum="sha256:abc",
    )
    base.update(kw)
    return Module(**base)


def test_category_accepts_all_canonical_slugs():
    from app.categories import CATEGORY_SLUGS
    for slug in CATEGORY_SLUGS:
        assert _mod(category=slug).category == slug


def test_category_migrates_legacy_values():
    assert _mod(category="maps").category == "navigation"
    assert _mod(category="library").category == "reference"
    assert _mod(category="internet").category == "reference"
    assert _mod(category="packages").category == "reference"


def test_category_rejects_unknown_value():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _mod(category="not-a-real-category")


def test_legacy_category_round_trips_through_json():
    # A pre-existing registry.json with a legacy category must still load.
    raw = (
        '{"modules": [{"id": "m", "display_name": "x", "category": "maps",'
        ' "description": "", "latest_version": "1", "size_gb": 0,'
        ' "kind": "mbtiles", "checksum": "sha256:abc"}], "libraries": []}'
    )
    reg = Registry.model_validate_json(raw)
    assert reg.modules[0].category == "navigation"


def test_routing_module_requires_checksum():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Module(
            id="nl-routing", display_name="NL Routing", category="navigation",
            description="", latest_version="1", size_gb=0.5, kind="routing",
        )


def test_routing_module_links_to_region():
    m = _mod(kind="routing", routing_for="netherlands")
    assert m.kind == "routing"
    assert m.routing_for == "netherlands"


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
    r = Registry()
    assert r.modules == []
    assert r.libraries == []


def test_registry_serialises_to_json():
    r = Registry()
    data = json.loads(r.model_dump_json())
    assert data["modules"] == []
    assert data["libraries"] == []


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
    reg = Registry(modules=modules or [])
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
    assert reg.modules == []
    assert reg.libraries == []


def test_load_missing_creates_default(tmp_settings):
    reg = load_registry(tmp_settings)
    assert reg.modules == []
    assert tmp_settings.registry_path.exists()


def test_save_and_reload(tmp_settings):
    _seed(tmp_settings, modules=[_sample_module()])
    reg = load_registry(tmp_settings)
    save_registry(tmp_settings, reg)
    reloaded = load_registry(tmp_settings)
    assert len(reloaded.modules) == 1
    assert reloaded.modules[0].id == "medical-wikimed"


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


def test_merge_remote_manifest_preserves_locally_resolved_image(tmp_settings):
    """A locally-resolved bundled image (set by install) must survive refresh
    even when the manifest doesn't ship an HTTP image_url."""
    from app.services.registry import merge_remote_manifest, load_registry
    existing = Module(
        id="first-aid", display_name="First Aid", category="medical",
        description="", latest_version="1.0", size_gb=0.0, kind="static",
        signature_url="https://example.com/x.minisig",
        download_url="https://example.com/x.tar.gz", entry="index.md",
        installed_version="1.0", active=True,
        image="/content/first-aid/card.png",
        source_library_id="L1",
    )
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.registry_path.write_text(Registry(modules=[existing]).model_dump_json())
    remote = {
        "id": "first-aid", "display_name": "First Aid (renamed)",
        "category": "medical", "description": "", "latest_version": "1.1",
        "size_gb": 0.0, "kind": "static",
        "signature_url": "https://example.com/x.minisig",
        "download_url": "https://example.com/x.tar.gz", "entry": "index.md",
        "image": None, "image_path": None, "source_library_id": "L1",
    }
    merge_remote_manifest(tmp_settings, [remote])
    refreshed = load_registry(tmp_settings).modules[0]
    assert refreshed.image == "/content/first-aid/card.png"
    assert refreshed.latest_version == "1.1"
    assert refreshed.display_name == "First Aid (renamed)"


def test_merge_remote_manifest_overwrites_image_when_remote_has_one(tmp_settings):
    """When the manifest does ship an HTTP image (already cached), it wins."""
    from app.services.registry import merge_remote_manifest, load_registry
    existing = Module(
        id="first-aid", display_name="x", category="medical", description="",
        latest_version="1.0", size_gb=0.0, kind="static",
        signature_url="https://example.com/x.minisig",
        download_url="https://example.com/x.tar.gz", entry="index.md",
        installed_version="1.0", active=True,
        image="/content/first-aid/card.png",
        source_library_id="L1",
    )
    tmp_settings.registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_settings.registry_path.write_text(Registry(modules=[existing]).model_dump_json())
    remote = {
        "id": "first-aid", "display_name": "x", "category": "medical",
        "description": "", "latest_version": "1.0", "size_gb": 0.0,
        "kind": "static", "signature_url": "https://example.com/x.minisig",
        "download_url": "https://example.com/x.tar.gz", "entry": "index.md",
        "image": "/data-cache/first-aid/cover.jpg",
        "image_path": None, "source_library_id": "L1",
    }
    merge_remote_manifest(tmp_settings, [remote])
    assert load_registry(tmp_settings).modules[0].image == "/data-cache/first-aid/cover.jpg"


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


def test_module_download_url_defaults_to_none():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
    )
    assert m.download_url is None


def test_module_download_url_round_trips():
    m = Module(
        id="medical-wikimed",
        display_name="WikiMed",
        category="medical",
        description="",
        latest_version="2024-10",
        size_gb=0.8,
        checksum="sha256:abc",
        download_url="https://example.com/wikimed.zim",
    )
    data = m.model_dump_json()
    m2 = Module.model_validate_json(data)
    assert m2.download_url == "https://example.com/wikimed.zim"
