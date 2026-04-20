import pytest
from pathlib import Path
from app.config import Settings


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings pointed at a temporary data directory."""
    return Settings(data_dir=tmp_path)
