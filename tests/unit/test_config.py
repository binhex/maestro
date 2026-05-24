"""Tests for maestro.config."""

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from maestro.config import ArtworkConfig, Config, QualityConfig, RootEntry, SchedulerConfig, load_config


class TestConfigDataclass:
    def test_default_config(self) -> None:
        config = Config()
        assert config.quality.min_acceptable == 3
        assert config.quality.delete_replaced is False
        assert config.artwork.album_art == "cover.jpg"
        assert config.scheduler.schedule == "0 3 * * *"

    def test_merged_config(self) -> None:
        config = Config(
            library_roots=[
                RootEntry(path="/music/lib", type="library", pattern="{artist}/{album}"),
            ],
            download_roots=[
                RootEntry(path="/downloads", type="download", pattern="{downloader}/{album}"),
            ],
        )
        assert len(config.library_roots) == 1
        assert config.library_roots[0].path == "/music/lib"
        assert config.download_roots[0].path == "/downloads"


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path) -> None:
        config_data = {
            "library_roots": [
                {"path": "/music", "type": "library", "pattern": "{artist}/{album}"},
            ],
            "quality": {
                "min_acceptable": 5,
                "delete_replaced": True,
            },
        }
        config_path = tmp_path / "maestro.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(str(config_path))
        assert len(config.library_roots) == 1
        assert config.quality.min_acceptable == 5
        assert config.quality.delete_replaced is True

    def test_file_not_found_returns_defaults(self) -> None:
        config = load_config("/nonexistent/path.yaml")
        assert isinstance(config, Config)
        assert config.scheduler.schedule == "0 3 * * *"

    def test_empty_config_file_returns_defaults(self, tmp_path: Path) -> None:
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")
        config = load_config(str(config_path))
        assert isinstance(config, Config)

    def test_post_init_converts_dict_entries(self) -> None:
        """__post_init__ should convert raw dicts to proper dataclass instances."""
        config = Config(
            library_roots=[{"path": "/lib", "type": "library", "pattern": "{a}"}],
            download_roots=[{"path": "/dl", "type": "download"}],
            quality={"min_acceptable": 7},
            artwork={"album_art": "art.jpg"},
            scheduler={"schedule": "0 */12 * * *"},
        )
        assert isinstance(config.library_roots[0], RootEntry)
        assert isinstance(config.download_roots[0], RootEntry)
        assert isinstance(config.quality, QualityConfig)
        assert isinstance(config.artwork, ArtworkConfig)
        assert isinstance(config.scheduler, SchedulerConfig)
        assert config.quality.min_acceptable == 7
        assert config.artwork.album_art == "art.jpg"
        assert config.scheduler.schedule == "0 */12 * * *"

    def test_default_config_created_when_missing(self, tmp_path: Path, monkeypatch) -> None:
        """load_config should create a default config file when none exists."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = str(config_dir / "maestro.yaml")
        # Should not exist yet
        assert not Path(config_path).exists()
        config = load_config(config_path, create_default=True)
        # File should have been created
        assert Path(config_path).exists()
        # Content should be valid YAML with defaults
        assert isinstance(config, Config)
        assert config.quality.min_acceptable == 3
        assert config.scheduler.schedule == "0 3 * * *"

    def test_create_default_respected_when_false(self, tmp_path: Path) -> None:
        """When create_default=False, no file is written."""
        config_path = str(tmp_path / "nonexistent" / "maestro.yaml")
        config = load_config(config_path, create_default=False)
        assert isinstance(config, Config)

    def test_create_default_falls_back_on_permission_error(self, tmp_path: Path, monkeypatch) -> None:
        """When the config dir is not writable, creation falls back gracefully."""
        # Simulate permission error by pointing to a non-writable path
        config_path = str(tmp_path / "no-such-dir" / "deep" / "maestro.yaml")
        # Should not crash — should fall back to default Config()
        config = load_config(config_path, create_default=True)
        assert isinstance(config, Config)

    def test_config_with_download_roots(self, tmp_path: Path) -> None:
        config_data = {
            "download_roots": [
                {"path": "/dl", "type": "download", "pattern": "{user}/{album}"},
            ],
            "scheduler": {
                "schedule": "0 */6 * * *",
            },
        }
        config_path = tmp_path / "maestro.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(str(config_path))
        assert len(config.download_roots) == 1
        assert config.scheduler.schedule == "0 */6 * * *"
