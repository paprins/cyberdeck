import os
import pytest
from pathlib import Path
from app.config import Settings


@pytest.fixture(autouse=True)
def clean_cyberdeck_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("CYBERDECK_"):
            monkeypatch.delenv(key)


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointed at a temporary data directory."""
    return Settings(data_dir=tmp_path)
