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
