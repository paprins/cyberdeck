from pathlib import Path
import pytest
from app.config import Settings


def test_default_data_dir():
    s = Settings()
    assert s.data_dir == Path("/data")


def test_default_ports():
    s = Settings()
    assert s.app_port == 8000
    assert s.kiwix_port == 8080
    assert s.mbtiles_port == 8081


def test_env_override(monkeypatch):
    monkeypatch.setenv("CYBERDECK_DATA_DIR", "/tmp/test-data")
    s = Settings()
    assert s.data_dir == Path("/tmp/test-data")


def test_derived_zim_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.zim_dir == Path("/tmp/x/zim")


def test_derived_maps_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.maps_dir == Path("/tmp/x/maps")


def test_derived_downloads_dir():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.downloads_dir == Path("/tmp/x/downloads")


def test_derived_registry_path():
    s = Settings(data_dir=Path("/tmp/x"))
    assert s.registry_path == Path("/tmp/x/packages/registry.json")
