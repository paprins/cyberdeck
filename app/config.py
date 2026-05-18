from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    app_port: int = 8000
    kiwix_port: int = 8080
    mbtiles_port: int = 8081
    install_root: Path = Path("/opt/cyberdeck")
    github_repo: str = ""
    upgrade_versions_keep: int = 3
    check_for_updates: bool = True
    connectivity_check: bool = False
    connectivity_poll_seconds: int = 60
    connectivity_grace_minutes: int = 10
    connectivity_target: str = "1.1.1.1:53"

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
    def images_dir(self) -> Path:
        return self.data_dir / "static" / "images"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "packages" / "registry.json"

    @property
    def upgrade_dir(self) -> Path:
        return self.install_root / "upgrade"

    @property
    def upgrade_state_path(self) -> Path:
        return self.upgrade_dir / "state.json"

    @property
    def current_symlink(self) -> Path:
        return self.install_root / "current"

    @property
    def preferences_path(self) -> Path:
        return self.data_dir / "preferences.json"
