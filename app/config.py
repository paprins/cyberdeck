from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    app_port: int = 8000
    kiwix_port: int = 8080
    mbtiles_port: int = 8081

    model_config = SettingsConfigDict(env_prefix="CYBERDECK_")

    @property
    def zim_dir(self) -> Path:
        return self.data_dir / "zim"

    @property
    def maps_dir(self) -> Path:
        return self.data_dir / "maps"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "packages" / "registry.json"
