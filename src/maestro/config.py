"""YAML config loading and validation for Maestro."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from maestro.utils import get_project_root

# Current config schema version. Increment when fields are added or changed.
# Migration functions in _MIGRATIONS handle upgrading from older versions.
CONFIG_VERSION = 2

_DEFAULT_CONFIG_PATHS = [
    os.environ.get("MAESTRO_CONFIG", ""),
    str(Path(get_project_root()) / "configs" / "maestro.yaml"),
    str(Path.home() / ".config" / "maestro" / "maestro.yaml"),
    str(Path.home() / ".maestro.yaml"),
]


@dataclass
class RootEntry:
    """A root directory entry for library or download paths."""

    path: str
    type: str = "library"
    enabled: bool = True
    pattern: str | None = None
    source_pattern: str | None = None
    destination_pattern: str | None = None


@dataclass
class QualityConfig:
    """Quality-related configuration."""

    min_acceptable: int = 3
    delete_replaced: bool = False


@dataclass
class ArtworkConfig:
    """Artwork-related configuration."""

    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    skip_if_exists: bool = True
    sources: list[str] = field(default_factory=lambda: ["musicbrainz", "lastfm"])
    width: int = 500
    height: int = 500
    aspect_tolerance: float = 0.15


@dataclass
class SchedulerConfig:
    """Scheduler-related configuration."""

    schedule: str = "0 3 * * *"
    run_on_start: bool = True
    retry_failed: bool = True
    max_retries: int = 3


@dataclass
class Config:
    """Top-level Maestro configuration."""

    library_roots: list[RootEntry] = field(default_factory=list)
    download_roots: list[RootEntry] = field(default_factory=list)
    quality: QualityConfig = field(default_factory=QualityConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    def __post_init__(self) -> None:
        """Convert raw dict entries to RootEntry / sub-config objects."""
        self.library_roots = [RootEntry(**r) if isinstance(r, dict) else r for r in self.library_roots]
        self.download_roots = [RootEntry(**r) if isinstance(r, dict) else r for r in self.download_roots]
        if isinstance(self.quality, dict):
            self.quality = QualityConfig(**self.quality)
        if isinstance(self.artwork, dict):
            self.artwork = ArtworkConfig(**self.artwork)
        if isinstance(self.scheduler, dict):
            self.scheduler = SchedulerConfig(**self.scheduler)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """Create a Config instance from a dictionary of raw YAML data."""
        lib_roots = [RootEntry(**entry) for entry in data.get("library_roots", [])]
        dl_roots = [RootEntry(**entry) for entry in data.get("download_roots", [])]
        quality = QualityConfig(**(data.get("quality", {})))
        artwork = ArtworkConfig(**(data.get("artwork", {})))
        scheduler = SchedulerConfig(**(data.get("scheduler", {})))
        return cls(
            library_roots=lib_roots,
            download_roots=dl_roots,
            quality=quality,
            artwork=artwork,
            scheduler=scheduler,
        )


def _generate_default_yaml() -> str:
    """Return a default config YAML string with all settings and examples."""
    comment = (
        "# Maestro Configuration\n"
        "#\n"
        "# Available path pattern variables:\n"
        "#   {artist}     - Artist name (from ID3 tag or heuristic)\n"
        "#   {album}      - Album title (from ID3 tag or heuristic)\n"
        "#   {title}      - Track title (from ID3 tag)\n"
        "#   {track}      - Track number (from ID3 tag or parsed filename)\n"
        "#   {year}       - Release year (from ID3 tag)\n"
        "#   {genre}      - Genre (from ID3 tag)\n"
        "#   {subgenre}   - Subgenre (from ID3 tag or path-extracted)\n"
        "#   {filename}   - File basename without extension\n"
        "#   {ext}        - File extension (e.g. flac, mp3)\n"
        "#   {format}     - Normalised format (e.g. FLAC, MP3)\n"
        "#   {bitrate}    - Audio bitrate in kbps\n"
        "#   {path}       - Full original path to the file\n"
        "#   {downloader} - Downloader name (extracted from download path)\n"
        "#   {owner}      - Library owner (extracted from library path)\n"
        "#   {type}       - Media type (extracted from library path)\n"
        "#   {hash}       - File hash (first 8 hex chars)\n"
        "#\n"
        "# Missing variables are silently collapsed from the path.\n"
    )
    return comment + yaml.dump(  # type: ignore[no-any-return]
        _default_config_dict(),
        default_flow_style=False,
        sort_keys=False,
    )


def _write_default_config(target_path: str) -> str:
    """Write a default config YAML file to *target_path*.

    Creates parent directories if they don't exist.

    Returns:
        The path where the config was written.
    """
    p = Path(target_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    content = _generate_default_yaml()
    p.write_text(content)
    return target_path


def _default_config_dict() -> dict:
    """Return the default config as a plain dict for comparison."""
    return {
        "version": CONFIG_VERSION,
        "library_roots": [
            {
                "path": "/path/to/music/library",
                "type": "library",
                "enabled": True,
                "pattern": "{artist}/{album}/{filename}.{ext}",
            },
        ],
        "download_roots": [
            {"path": "/path/to/downloads", "type": "download", "enabled": True, "pattern": "{downloader}/{album}"},
        ],
        "quality": {"min_acceptable": 3, "delete_replaced": False},
        "artwork": {
            "album_art": "cover.jpg",
            "fanart": "fanart.jpg",
            "skip_if_exists": True,
            "sources": ["musicbrainz", "lastfm"],
            "width": 500,
            "height": 500,
            "aspect_tolerance": 0.15,
        },
        "scheduler": {
            "schedule": "0 3 * * *",
            "run_on_start": True,
            "retry_failed": True,
            "max_retries": 3,
        },
    }


# ---- Config file versioning -----------------------------------------------
# To add a new migration:
#   1. Increment CONFIG_VERSION at the top of this file
#   2. Add a migration function _migrate_v{N}_to_v{N+1}(data) that transforms
#      the data dict in-place
#   3. Register it in _MIGRATIONS below
#
# Migrations are run in order from the file's current version up to
# CONFIG_VERSION - 1. Each migration receives the raw YAML dict and can
# add, remove, or modify keys before the next migration runs.


_MIGRATIONS: dict[int, Any] = {}


def _migrate_v1_to_v2(data: dict) -> None:
    """Migration from version 1 to 2: add artwork dimensions, quality fields, scheduler."""
    quality = data.setdefault("quality", {})
    quality.setdefault("delete_replaced", False)

    artwork = data.setdefault("artwork", {})
    artwork.setdefault("fanart", "fanart.jpg")
    artwork.setdefault("skip_if_exists", True)
    artwork.setdefault("sources", ["musicbrainz", "lastfm"])
    artwork.setdefault("width", 500)
    artwork.setdefault("height", 500)
    artwork.setdefault("aspect_tolerance", 0.15)

    scheduler = data.setdefault("scheduler", {})
    scheduler.setdefault("schedule", "0 3 * * *")
    scheduler.setdefault("run_on_start", True)
    scheduler.setdefault("retry_failed", True)
    scheduler.setdefault("max_retries", 3)

    library_roots = data.setdefault("library_roots", [])
    for entry in library_roots:
        if isinstance(entry, dict):
            entry.setdefault("enabled", True)

    download_roots = data.setdefault("download_roots", [])
    for entry in download_roots:
        if isinstance(entry, dict):
            entry.setdefault("enabled", True)


_MIGRATIONS[1] = _migrate_v1_to_v2


def _upgrade_config(data: dict, file_path: str) -> dict:
    """Migrate a config from its current version to CONFIG_VERSION.

    Runs migration functions sequentially. Preserves all user values.
    Saves the upgraded file to disk. Returns the upgraded data dict.
    """
    file_version = data.get("version", 1)

    if file_version >= CONFIG_VERSION:
        return data

    for ver in range(file_version, CONFIG_VERSION):
        migrate = _MIGRATIONS.get(ver)
        if migrate:
            migrate(data)

    data["version"] = CONFIG_VERSION

    with open(file_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return data


def _try_load(path: str) -> Config | None:
    """Try to load a Config from *path*. Returns None if not found."""
    if not path:
        return None
    p = Path(path)
    if p.exists() and p.is_file():
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        data = _upgrade_config(data, str(p))
        return Config.from_dict(data)
    return None


def _resolve_config_path(config_path: str | None) -> str | None:
    """If config_path is a directory, append the default filename."""
    if config_path:
        cp = Path(config_path)
        if cp.is_dir() or not cp.suffix:
            config_path = str(cp / "maestro.yaml")
    return config_path


def _create_default_config(paths_to_try: list[str]) -> Config | None:
    """Try to write a default config file to the first writable path."""
    for target in paths_to_try:
        if not target:
            continue
        try:
            written = _write_default_config(target)
            with open(written) as f:
                data = yaml.safe_load(f) or {}
            return Config.from_dict(data)
        except (OSError, PermissionError):
            continue
    return None


def load_config(config_path: str | None = None, *, create_default: bool = True) -> Config:
    """Load configuration from a YAML file.  See module docstring for details."""
    config_path = _resolve_config_path(config_path)
    paths_to_try = [config_path] if config_path else [p for p in _DEFAULT_CONFIG_PATHS if p]

    for path in paths_to_try:
        result = _try_load(path)
        if result is not None:
            return result

    if create_default:
        result = _create_default_config(paths_to_try)
        if result is not None:
            return result

    return Config()
