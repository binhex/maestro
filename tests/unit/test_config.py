"""Tests for maestro.config."""

from pathlib import Path

import yaml

from maestro.config import Config, load_config


class TestConfigDataclass:
    def test_default_config(self):
        config = Config()
        assert config.quality.min_acceptable == 3
        assert config.quality.delete_replaced is False
        assert config.artwork.album_art == "cover.jpg"
        assert config.scheduler.schedule == "0 3 * * *"

    def test_merged_config(self):
        config = Config(
            library_roots=[
                {"path": "/music/lib", "type": "library", "pattern": "{artist}/{album}"},
            ],
            download_roots=[
                {"path": "/downloads", "type": "download", "pattern": "{downloader}/{album}"},
            ],
        )
        assert len(config.library_roots) == 1
        assert config.library_roots[0].path == "/music/lib"
        assert config.download_roots[0].path == "/downloads"


class TestLoadConfig:
    def test_load_from_file(self, tmp_path: Path):
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

    def test_file_not_found_returns_defaults(self):
        config = load_config("/nonexistent/path.yaml")
        assert isinstance(config, Config)
        assert config.scheduler.schedule == "0 3 * * *"

    def test_empty_config_file_returns_defaults(self, tmp_path: Path):
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")
        config = load_config(str(config_path))
        assert isinstance(config, Config)

    def test_config_with_download_roots(self, tmp_path: Path):
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
