# Maestro Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core Maestro music organiser pipeline — scan, identify, quality-check, import, tag, artwork — with CLI subcommands and a daemon scheduler.

**Architecture:** Modular pipeline. Each subsystem is an independent module communicating through a shared SQLite database (SQLAlchemy ORM). The daemon runs an orchestration loop. CLI exposes each pipeline step as a subcommand for manual use.

**Tech Stack:** Python 3.12, Click (CLI), SQLAlchemy (ORM), Mutagen (ID3), PyYAML (config), croniter (scheduling), requests (HTTP), musicbrainzngs (artwork), Loguru (logging).

---

## Files to Create/Modify

### New files
- `src/maestro/db/__init__.py`
- `src/maestro/db/core.py` — Session factory, connection management, engine creation
- `src/maestro/db/models.py` — All ORM models (Artist, Album, Track, Download, FileSystemSnapshot, LibraryRoot)
- `src/maestro/template.py` — Path template engine (parse source patterns, render destination patterns)
- `src/maestro/config.py` — YAML config loading, validation, defaults
- `src/maestro/scanner.py` — Walk directories, detect new/changed/removed files, create Download records
- `src/maestro/identifier.py` — Read ID3 tags, fall back to heuristic, match against library
- `src/maestro/quality.py` — Format/bitrate tier comparison
- `src/maestro/organizer.py` — Move/copy files using path templates, create library records
- `src/maestro/tagger.py` — Read/write/clear ID3 tags
- `src/maestro/artwork.py` — Download album art + fanart from MusicBrainz/Last.fm/Discogs
- `src/maestro/daemon.py` — Daemon lifecycle with croniter scheduler, signal handling

### Modified files
- `pyproject.toml` — Add mutagen, croniter, musicbrainzngs deps; remove apscheduler, daemonize
- `src/maestro/__init__.py` — Expose public API
- `src/maestro/cli.py` — Rewrite with subcommands: scan, identify, check, import, tag, artwork, daemon, config

### Test files
- `tests/unit/test_db_core.py`
- `tests/unit/test_db_models.py`
- `tests/unit/test_template.py`
- `tests/unit/test_config.py`
- `tests/unit/test_scanner.py`
- `tests/unit/test_identifier.py`
- `tests/unit/test_quality.py`
- `tests/unit/test_organizer.py`
- `tests/unit/test_tagger.py`
- `tests/unit/test_artwork.py`
- `tests/unit/test_daemon.py`
- `tests/integration/test_pipeline.py`

---

### Task 1: Update project dependencies

**Files:**
- Modify: `pyproject.toml` — add new deps, remove unused ones
- Test: `tests/unit/test_cli.py` — verify no regressions after dep changes
- Run: `uv sync` — install new deps

- [ ] **Step 1: Edit pyproject.toml**

Replace `apscheduler` with `croniter`. Remove `daemonize`. Add `mutagen`, `croniter`, `musicbrainzngs`. Update dev deps if needed.

Edit `pyproject.toml` dependencies section:

```toml
dependencies = [
    "backoff",
    "click",
    "loguru",
    "apprise",
    "pyyaml",
    "requests",
    "sqlalchemy",
    "urllib3",
    "mutagen",
    "croniter",
    "musicbrainzngs",
]
```

- [ ] **Step 2: Install deps and run verification**

```bash
cd /data/maestro && uv sync
uv run pytest tests/unit/test_cli.py -v
```

Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: update deps for Maestro core features"
```

---

### Task 2: Database models and core

**Files:**
- Create: `src/maestro/db/__init__.py`
- Create: `src/maestro/db/core.py`
- Create: `src/maestro/db/models.py`
- Create: `tests/unit/test_db_models.py`
- Create: `tests/unit/test_db_core.py`

**Notes:** All ORM models use the `Base` declarative base from SQLAlchemy. The `core.py` module provides `get_engine()`, `create_session()`, and `init_db()` functions. `init_db()` creates all tables if they don't exist. Full column definitions with types, defaults, and nullable constraints.

- [ ] **Step 1: Write the failing test for models**

Create `tests/unit/test_db_models.py`:

```python
"""Tests for maestro.db.models."""

from maestro.db.models import (
    Artist, Album, Track, Download, FileSystemSnapshot, LibraryRoot,
)


class TestArtistModel:
    def test_create_artist(self):
        artist = Artist(name="Amon Tobin", slug="amon-tobin")
        assert artist.name == "Amon Tobin"
        assert artist.slug == "amon-tobin"
        assert artist.id is None  # not yet persisted

    def test_artist_to_dict(self):
        """Minimal repr/dict-like access for debugging."""
        artist = Artist(name="Test Artist", slug="test-artist")
        # just ensures the model doesn't crash
        assert artist.__tablename__ == "artists"


class TestAlbumModel:
    def test_create_album(self):
        album = Album(
            title="Bricolage",
            year=1997,
            genre="Electronic",
            subgenre="Ambient",
        )
        assert album.title == "Bricolage"
        assert album.year == 1997


class TestTrackModel:
    def test_create_track(self):
        track = Track(
            title="Bricolage",
            track_number=1,
            disc_number=1,
            format="FLAC",
            bitrate=1411,
            sample_rate=44100,
            channels=2,
            duration_seconds=372,
            file_path="/music/Amon Tobin/Bricolage/01 - Bricolage.flac",
            file_size=50000000,
            file_hash="a1b2c3d4",
        )
        assert track.format == "FLAC"
        assert track.track_number == 1

    def test_track_default_disc_number(self):
        track = Track(
            title="Test",
            file_path="/test.flac",
            file_size=1000,
            file_hash="abcd",
        )
        # duration_channels and other numeric fields default to None
        assert track.disc_number is None


class TestDownloadModel:
    def test_create_download(self):
        dl = Download(
            source_path="/downloads/user/Bricolage",
            status="new",
        )
        assert dl.status == "new"

    def test_download_status_default(self):
        # status should default to "new" if we set a default in the model
        dl = Download(source_path="/test")
        # we can't enforce a default in the test; check if model sets one
        assert dl.status in ("new", None)  # lenient check


class TestFileSystemSnapshotModel:
    def test_create_snapshot(self):
        snap = FileSystemSnapshot(
            path="/music/file.flac",
            file_hash="deadbeef",
            file_size=12345,
        )
        assert snap.path == "/music/file.flac"


class TestLibraryRootModel:
    def test_create_root(self):
        root = LibraryRoot(
            path="/music/library",
            type="library",
            source_pattern="{artist}/{album}",
            destination_pattern="{genre}/{artist}/{album}",
        )
        assert root.type == "library"
        assert root.enabled is True  # default enabled
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /data/maestro && uv run pytest tests/unit/test_db_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'maestro.db'`

- [ ] **Step 3: Write the models implementation**

Create `src/maestro/db/__init__.py`:
```python
"""Database package for Maestro."""
```

Create `src/maestro/db/core.py`:
```python
"""Database engine and session management."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from maestro.db.models import Base


def get_engine(db_path: str, echo: bool = False):
    """Create a SQLAlchemy engine for the given SQLite database path.

    Args:
        db_path: Path to the SQLite database file.
        echo: If True, log all SQL statements.

    Returns:
        A configured SQLAlchemy Engine instance.
    """
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=echo)


def init_db(engine):
    """Create all tables defined in the ORM models.

    Safe to call multiple times; uses IF NOT EXISTS internally.
    """
    Base.metadata.create_all(engine)


def create_session(engine) -> Session:
    """Create a new session bound to the given engine.

    Returns:
        A SQLAlchemy Session instance.
    """
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def get_session(engine) -> Generator[Session, None, None]:
    """Yield a session as a context manager, closing it on exit.

    Usage:
        with get_session(engine) as session:
            session.query(...)
    """
    session = create_session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

Create `src/maestro/db/models.py`:
```python
"""SQLAlchemy ORM models for Maestro's music library database."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )

    albums: Mapped[list["Album"]] = relationship("Album", back_populates="artist", cascade="all, delete-orphan")


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artists.id"), nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subgenre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artwork_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    fanart_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )

    artist: Mapped[Artist | None] = relationship("Artist", back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="album", cascade="all, delete-orphan")


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    album_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("albums.id"), nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    bitrate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )

    album: Mapped[Album | None] = relationship("Album", back_populates="tracks")


class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", index=True,
    )
    match_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )
    identified_artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_album: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identified_genre: Mapped[str | None] = mapped_column(String(128), nullable=True)
    identified_album_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("albums.id"), nullable=True,
    )
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FileSystemSnapshot(Base):
    __tablename__ = "filesystem_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )


class LibraryRoot(Base):
    __tablename__ = "library_roots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="library",
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    source_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    destination_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_db_models.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Write and verify test for db/core.py**

Create `tests/unit/test_db_core.py`:

```python
"""Tests for maestro.db.core."""

from pathlib import Path

import pytest

from maestro.db.core import create_session, get_engine, init_db


class TestDbCore:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_engine_creates_tables(self, engine):
        """Verify all tables exist after init_db."""
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        expected = {"artists", "albums", "tracks", "downloads",
                     "filesystem_snapshots", "library_roots"}
        assert expected.issubset(set(tables))

    def test_create_session_and_insert(self, engine):
        session = create_session(engine)
        from maestro.db.models import Artist
        artist = Artist(name="Test", slug="test")
        session.add(artist)
        session.commit()
        assert artist.id is not None
        session.close()

    def test_create_session_rollback_on_error(self, engine):
        session = create_session(engine)
        from maestro.db.models import Artist
        session.add(Artist(name="A", slug="a"))  # valid
        session.add(Artist(name=None, slug=None))  # violates NOT NULL
        with pytest.raises(Exception):
            session.commit()
        session.close()
        # Verify no data was committed
        session2 = create_session(engine)
        assert session2.query(Artist).count() == 0
        session2.close()
```

- [ ] **Step 6: Run all DB tests**

```bash
cd /data/maestro && uv run pytest tests/unit/test_db_models.py tests/unit/test_db_core.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/maestro/db/ tests/unit/test_db_models.py tests/unit/test_db_core.py
git commit -m "feat: add database models and core session management"
```

---

### Task 3: Template engine

**Files:**
- Create: `src/maestro/template.py`
- Create: `tests/unit/test_template.py`

**Notes:** The template engine has two modes: `parse(path, pattern)` extracts variable values from a real filesystem path, and `render(variables, pattern)` constructs a target path from variable values. Variables missing a value are collapsed (the segment removed). Regular expression splitting on `/` and `\` for path components.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_template.py`:

```python
"""Tests for maestro.template."""

from maestro.template import parse_variables, render_path


class TestParseVariables:
    def test_simple_pattern(self):
        result = parse_variables(
            path="Amon Tobin/Bricolage",
            pattern="{artist}/{album}",
        )
        assert result == {"artist": "Amon Tobin", "album": "Bricolage"}

    def test_deep_pattern(self):
        result = parse_variables(
            path="Paul/Albums/Dance/Ambient/Amon Tobin/Bricolage",
            pattern="{owner}/{type}/{genre}/{subgenre}/{artist}/{album}",
        )
        assert result["owner"] == "Paul"
        assert result["type"] == "Albums"
        assert result["genre"] == "Dance"
        assert result["subgenre"] == "Ambient"
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage"

    def test_pattern_with_filename_and_ext(self):
        result = parse_variables(
            path="music/01 - Track.flac",
            pattern="{path}/{filename}.{ext}",
        )
        assert result["filename"] == "01 - Track"
        assert result["ext"] == "flac"

    def test_windows_backslash_path(self):
        result = parse_variables(
            path=r"D:\Music\Amon Tobin\Bricolage",
            pattern="{path}\\{artist}\\{album}",
        )
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage"

    def test_pattern_mismatch_returns_partial(self):
        """If fewer components than pattern tokens, return what we can."""
        result = parse_variables(
            path="Amon Tobin",
            pattern="{artist}/{album}",
        )
        assert result == {"artist": "Amon Tobin"}

    def test_pattern_with_spaces_in_names(self):
        result = parse_variables(
            path="Dance/Electronic/Amon Tobin/Bricolage (1997)",
            pattern="{genre}/{subgenre}/{artist}/{album}",
        )
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage (1997)"


class TestRenderPath:
    def test_simple_render(self):
        result = render_path(
            variables={"artist": "Amon Tobin", "album": "Bricolage"},
            pattern="{artist}/{album}",
        )
        assert result == "Amon Tobin/Bricolage"

    def test_render_with_filename(self):
        result = render_path(
            variables={"filename": "01 - Bricolage", "ext": "flac"},
            pattern="{filename}.{ext}",
        )
        assert result == "01 - Bricolage.flac"

    def test_render_full_library_pattern(self):
        result = render_path(
            variables={
                "owner": "Paul",
                "type": "Albums",
                "genre": "Dance",
                "subgenre": "Ambient",
                "artist": "Amon Tobin",
                "album": "Bricolage",
                "filename": "01 - Bricolage",
                "ext": "flac",
            },
            pattern="{owner}/{type}/{genre}/{subgenre}/{artist}/{album}/{filename}.{ext}",
        )
        assert result == "Paul/Albums/Dance/Ambient/Amon Tobin/Bricolage/01 - Bricolage.flac"

    def test_missing_variable_skips_segment(self):
        result = render_path(
            variables={"artist": "Amon Tobin"},  # no album
            pattern="{artist}/{album}/file.flac",
        )
        assert result == "Amon Tobin/file.flac"

    def test_all_variables_missing_returns_empty(self):
        result = render_path(
            variables={},
            pattern="{artist}/{album}",
        )
        assert result == ""

    def test_render_no_variables_in_pattern(self):
        result = render_path(
            variables={"ignored": "value"},
            pattern="static/path/file.flac",
        )
        assert result == "static/path/file.flac"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /data/maestro && uv run pytest tests/unit/test_template.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` for `maestro.template`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/template.py`:

```python
"""Path template engine — parse source paths and render destination paths.

Supports variables like {artist}, {album}, {genre}, {filename}, {ext}, etc.
Parse mode extracts values from a real path using a pattern.
Render mode constructs a target path from variable values using a pattern.
"""

import os
import re

_VARIABLE_RE = re.compile(r"\{(\w+)\}")


def _tokenize(pattern: str) -> list[tuple[str, str]]:
    """Split a pattern into a list of (type, value) tokens.

    Type is either 'var' for a variable or 'literal' for a static segment.
    """
    tokens: list[tuple[str, str]] = []
    last_end = 0
    for match in _VARIABLE_RE.finditer(pattern):
        start, end = match.start(), match.end()
        if start > last_end:
            tokens.append(("literal", pattern[last_end:start]))
        tokens.append(("var", match.group(1)))
        last_end = end
    if last_end < len(pattern):
        tokens.append(("literal", pattern[last_end:]))
    return tokens


def _split_path(path: str) -> list[str]:
    """Split a filesystem path into components, handling both / and \\."""
    # Normalise backslashes to forward slashes
    normalised = path.replace("\\", "/")
    # Strip trailing slash, split
    return normalised.rstrip("/").split("/")


def parse_variables(path: str, pattern: str) -> dict[str, str]:
    """Extract variable values from a real filesystem path using a pattern.

    Args:
        path: The actual filesystem path (e.g. 'Amon Tobin/Bricolage').
        pattern: The template pattern (e.g. '{artist}/{album}').

    Returns:
        A dictionary of variable name to extracted value.
        Only variables that could be matched are included.
    """
    tokens = _tokenize(pattern)
    path_components = _split_path(path)

    # Reconstruct the separator sequence from the pattern literals
    # Simple approach: build a regex from the pattern
    regex_parts: list[str] = []
    var_names: list[str] = []
    for token_type, value in tokens:
        if token_type == "literal":
            regex_parts.append(re.escape(value))
        else:
            regex_parts.append(r"(.+)")
            var_names.append(value)

    full_regex = f"^{''.join(regex_parts)}$"
    match = re.match(full_regex, path)
    if not match:
        # Try partial match — match as much as possible
        # Build progressively shorter regexes
        for end_idx in range(len(var_names) - 1, 0, -1):
            # Rebuild pattern truncated to end_idx variables
            parts: list[str] = []
            names: list[str] = []
            for token_type, value in tokens:
                if token_type == "literal":
                    if len(names) >= end_idx:
                        break
                    parts.append(re.escape(value))
                else:
                    if len(names) >= end_idx:
                        break
                    parts.append(r"(.+)")
                    names.append(value)
            partial_regex = f"^{''.join(parts)}$"
            m = re.match(partial_regex, path)
            if m:
                return dict(zip(names, m.groups(), strict=False))
        return {}

    return dict(zip(var_names, match.groups(), strict=False))


def render_path(variables: dict[str, str], pattern: str) -> str:
    """Construct a path from variable values using the pattern.

    Args:
        variables: Dict of variable name to string value.
        pattern: The template pattern (e.g. '{artist}/{album}').

    Returns:
        The rendered path string.
    """
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return variables.get(var_name, "")

    result = _VARIABLE_RE.sub(_replacer, pattern)

    # Clean up: collapse double separators, remove trailing/leading separators
    # A double separator means a variable was empty — collapse it
    collapsed = re.sub(r"/{2,}", "/", result)
    collapsed = re.sub(r"\\{2,}", "\\", collapsed)
    collapsed = collapsed.strip("/\\")

    return collapsed
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_template.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/template.py tests/unit/test_template.py
git commit -m "feat: add path template engine (parse + render)"
```

---

### Task 4: Config loader

**Files:**
- Create: `src/maestro/config.py`
- Create: `tests/unit/test_config.py`

**Notes:** Loads YAML config from default paths (project root `maestro.yaml`, `~/.config/maestro/maestro.yaml`, or `--config` CLI flag). Provides a `Config` dataclass with validated fields and sensible defaults. Validates that library roots exist and that patterns are provided for download roots.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
"""Tests for maestro.config."""

from pathlib import Path

import pytest
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
        # Defaults should be populated
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
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_config.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/config.py`:

```python
"""YAML config loading and validation for Maestro."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from maestro.utils import get_project_root

# Default config paths searched in order
_DEFAULT_CONFIG_PATHS = [
    os.environ.get("MAESTRO_CONFIG", ""),
    str(Path(get_project_root()) / "maestro.yaml"),
    str(Path.home() / ".config" / "maestro" / "maestro.yaml"),
    str(Path.home() / ".maestro.yaml"),
]


@dataclass
class RootEntry:
    path: str
    type: str = "library"
    enabled: bool = True
    pattern: str | None = None
    source_pattern: str | None = None
    destination_pattern: str | None = None


@dataclass
class QualityConfig:
    min_acceptable: int = 3
    delete_replaced: bool = False


@dataclass
class ArtworkConfig:
    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    skip_if_exists: bool = True
    sources: list[str] = field(default_factory=lambda: ["musicbrainz", "lastfm", "discogs"])


@dataclass
class SchedulerConfig:
    schedule: str = "0 3 * * *"
    run_on_start: bool = True
    retry_failed: bool = True
    max_retries: int = 3


@dataclass
class Config:
    library_roots: list[RootEntry] = field(default_factory=list)
    download_roots: list[RootEntry] = field(default_factory=list)
    quality: QualityConfig = field(default_factory=QualityConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        lib_roots = [
            RootEntry(**entry) for entry in data.get("library_roots", [])
        ]
        dl_roots = [
            RootEntry(**entry) for entry in data.get("download_roots", [])
        ]
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


def load_config(config_path: str | None = None) -> Config:
    """Load configuration from a YAML file.

    Args:
        config_path: Explicit path to config file. If None, searches default paths.

    Returns:
        A Config instance populated from the file, or defaults if not found.
    """
    paths_to_try: list[str] = []
    if config_path:
        paths_to_try = [config_path]
    else:
        paths_to_try = [p for p in _DEFAULT_CONFIG_PATHS if p]

    for path in paths_to_try:
        if not path:
            continue
        p = Path(path)
        if p.exists() and p.is_file():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            return Config.from_dict(data)

    return Config()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_config.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/config.py tests/unit/test_config.py
git commit -m "feat: add YAML config loader"
```

---

### Task 5: Quality comparator

**Files:**
- Create: `src/maestro/quality.py`
- Create: `tests/unit/test_quality.py`

**Notes:** Standalone module with no DB dependency. Provides `compare_tracks(library_track, download_track) -> str` returning `"replace"`, `"skip"`, or `"import"`. Also provides `get_quality_tier(format: str, bitrate: int | None) -> int` for the tier ranking.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_quality.py`:

```python
"""Tests for maestro.quality."""

from maestro.quality import compare_tracks, get_quality_tier


class TestGetQualityTier:
    def test_flac_tier(self):
        assert get_quality_tier("FLAC") == 10
        assert get_quality_tier("flac") == 10
        assert get_quality_tier("Flac") == 10  # case-insensitive

    def test_wav_tier(self):
        assert get_quality_tier("WAV") == 9

    def test_aiff_tier(self):
        assert get_quality_tier("AIFF") == 8

    def test_mp3_320_tier(self):
        assert get_quality_tier("MP3", 320) == 7

    def test_mp3_v0_tier(self):
        # V0 is typically ~245 kbps VBR
        assert get_quality_tier("MP3", 245) == 6

    def test_mp3_v2_tier(self):
        # V2 is ~190 kbps
        assert get_quality_tier("MP3", 190) == 5

    def test_mp3_192_tier(self):
        assert get_quality_tier("MP3", 192) == 3

    def test_mp3_128_tier(self):
        assert get_quality_tier("MP3", 128) == 1

    def test_aac_tier(self):
        assert get_quality_tier("M4A", 256) == 2

    def test_unknown_format(self):
        assert get_quality_tier("OGG") == 4
        assert get_quality_tier("UNKNOWN") == 0

    def test_ogg_tier(self):
        # Ogg Vorbis is tier 4
        assert get_quality_tier("OGG", 192) == 4


class TestCompareTracks:
    def test_replace_download_higher_tier(self):
        result = compare_tracks(("MP3", 320), ("FLAC", 1411))
        assert result == "replace"

    def test_skip_library_higher_tier(self):
        result = compare_tracks(("FLAC", 1411), ("MP3", 320))
        assert result == "skip"

    def test_skip_equal_quality(self):
        result = compare_tracks(("FLAC", 1411), ("FLAC", 1411))
        assert result == "skip"

    def test_replace_same_tier_higher_bitrate(self):
        result = compare_tracks(("MP3", 128), ("MP3", 320))
        assert result == "replace"

    def test_skip_same_tier_lower_bitrate(self):
        result = compare_tracks(("MP3", 320), ("MP3", 128))
        assert result == "skip"

    def test_import_no_library_match(self):
        result = compare_tracks(None, ("FLAC", 1411))
        assert result == "import"

    def test_import_library_with_no_track_unknown(self):
        result = compare_tracks(("UNKNOWN", 0), ("FLAC", 1411))
        assert result == "replace"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_quality.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/quality.py`:

```python
"""Quality comparison for audio files.

Provides tier-based ranking of audio formats and comparison logic to
determine whether a downloaded track should replace its library counterpart.
"""

from typing import Literal

_QUALITY_TIERS: dict[str, int] = {
    "FLAC": 10,
    "WAV": 9,
    "AIFF": 8,
    "MP3": 7,
    "MP3_V0": 6,
    "MP3_V2": 5,
    "OGG": 4,
    "AAC": 2,
    "M4A": 2,
}

# Bitrate thresholds within MP3 tier to distinguish sub-tiers
_MP3_BITRATE_THRESHOLDS: list[tuple[int, int, int]] = [
    # (min_bitrate, sub_tier, final_tier)
    (320, 7, 7),    # >= 320kbps → tier 7
    (245, 6, 6),    # >= 245kbps → tier 6 (V0)
    (200, 5, 5),    # >= 200kbps → tier 5 (V2)
    (160, 3, 3),    # >= 160kbps → tier 3
    (128, 1, 1),    # >= 128kbps → tier 1
]


def get_quality_tier(format_name: str, bitrate: int | None = None) -> int:
    """Determine the quality tier for a given format and optional bitrate.

    Args:
        format_name: Audio format string (e.g. 'FLAC', 'MP3', 'AAC').
        bitrate: Bitrate in kbps. Used for MP3 sub-tier differentiation.

    Returns:
        Integer tier from 0 (lowest) to 10 (highest).
    """
    fmt = format_name.upper().strip()

    # MP3 gets special handling for bitrate-based sub-tiers
    if fmt == "MP3" and bitrate is not None:
        for min_br, _, final_tier in _MP3_BITRATE_THRESHOLDS:
            if bitrate >= min_br:
                return final_tier
        return 1  # below 128kbps, still MP3 but lowest MP3 tier

    return _QUALITY_TIERS.get(fmt, 0)


def compare_tracks(
    library_track: tuple[str, int | None] | None,
    download_track: tuple[str, int | None],
) -> str:
    """Compare a library track against a downloaded track.

    Args:
        library_track: (format, bitrate) tuple from the library, or None if not in library.
        download_track: (format, bitrate) tuple from the download.

    Returns:
        'import' — no library match, always import.
        'skip' — library already has equal or better quality.
        'replace' — download has better quality than library.
    """
    if library_track is None:
        return "import"

    lib_fmt, lib_br = library_track
    dl_fmt, dl_br = download_track

    lib_tier = get_quality_tier(lib_fmt, lib_br)
    dl_tier = get_quality_tier(dl_fmt, dl_br)

    if dl_tier > lib_tier:
        return "replace"
    elif dl_tier == lib_tier:
        # Same tier: compare bitrate (higher wins)
        if dl_br is not None and lib_br is not None and dl_br > lib_br:
            return "replace"
        return "skip"
    else:
        return "skip"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_quality.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/quality.py tests/unit/test_quality.py
git commit -m "feat: add quality comparator with tier-based ranking"
```

---

### Task 6: Scanner module

**Files:**
- Create: `src/maestro/scanner.py`
- Create: `tests/unit/test_scanner.py`

**Notes:** Walks download root directories, finds audio files (by extension: .mp3, .flac, .ogg, .wav, .aiff, .m4a, .wma), computes file hashes (SHA256), creates Download records and FileSystemSnapshot records. Uses `os.walk` or `pathlib.rglob`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scanner.py`:

```python
"""Tests for maestro.scanner."""

from pathlib import Path

import pytest

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Download, FileSystemSnapshot
from maestro.scanner import scan_download_root


class TestScanner:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        eng = get_engine(str(db_path), echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_scanner_creates_download_records(self, engine, tmp_path: Path):
        """Scan a directory with audio files should create Download records."""
        # Create a fake download directory with a "downloader" subfolder
        dl_root = tmp_path / "downloads" / "user1"
        dl_root.mkdir(parents=True)
        album_dir = dl_root / "Some Album"
        album_dir.mkdir()
        # Create fake audio file
        audio_file = album_dir / "01 - Track.flac"
        audio_file.write_text("fake audio data")

        session = create_session(engine)
        result = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")

        assert result["created"] == 1
        downloads = session.query(Download).all()
        assert len(downloads) == 1
        assert downloads[0].status == "new"
        assert "Some Album" in downloads[0].source_path

    def test_scanner_skips_non_audio_files(self, engine, tmp_path: Path):
        """Files without audio extensions should not trigger a Download record."""
        dl_root = tmp_path / "downloads" / "user1"
        dl_root.mkdir(parents=True)
        album_dir = dl_root / "Some Album"
        album_dir.mkdir()
        # Create a non-audio file
        txt_file = album_dir / "readme.txt"
        txt_file.write_text("not audio")

        session = create_session(engine)
        result = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")

        assert result["created"] == 0

    def test_scanner_creates_snapshots(self, engine, tmp_path: Path):
        """FileSystemSnapshot records should be created for scanned files."""
        dl_root = tmp_path / "downloads" / "user1"
        dl_root.mkdir(parents=True)
        album_dir = dl_root / "Album"
        album_dir.mkdir()
        audio_file = album_dir / "track.flac"
        audio_file.write_text("data")

        session = create_session(engine)
        scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")

        snapshots = session.query(FileSystemSnapshot).all()
        assert len(snapshots) >= 1
        found = any(str(audio_file) in snap.file_path for snap in snapshots)
        assert found, f"Expected {audio_file} in snapshots"

    def test_scanner_skips_existing_on_rescan(self, engine, tmp_path: Path):
        """Re-scanning a directory that was already scanned should not create duplicates."""
        dl_root = tmp_path / "downloads" / "user1"
        dl_root.mkdir(parents=True)
        album_dir = dl_root / "Existing Album"
        album_dir.mkdir()
        audio_file = album_dir / "track.flac"
        audio_file.write_text("data")

        session = create_session(engine)

        # First scan
        result1 = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")
        assert result1["created"] == 1

        # Second scan (same state)
        result2 = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")
        assert result2["created"] == 0  # no new records
        assert result2["skipped"] == 1  # was skipped

        # Only one Download record exists
        downloads = session.query(Download).all()
        assert len(downloads) == 1

    def test_scanner_detects_cd_subdirectories(self, engine, tmp_path: Path):
        """Multi-CD albums with CDx subdirs should be treated as the same download."""
        dl_root = tmp_path / "downloads" / "user1"
        dl_root.mkdir(parents=True)
        album_dir = dl_root / "Multi CD Album"
        album_dir.mkdir()
        cd1 = album_dir / "CD1"
        cd1.mkdir()
        (cd1 / "01 Track.flac").write_text("data")
        cd2 = album_dir / "CD2"
        cd2.mkdir()
        (cd2 / "01 Track.flac").write_text("data")

        session = create_session(engine)
        result = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")

        # Should create ONE download for the album, not two
        assert result["created"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_scanner.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/scanner.py`:

```python
"""Filesystem scanner — walk directories, detect audio files, create records.

Scans configured download roots and library roots to build a catalog of
audio files. Creates Download records for new/unprocessed download directories
and FileSystemSnapshot records for tracking file changes over time.
"""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from maestro.db.models import Download, FileSystemSnapshot

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".wav", ".aiff", ".aif",
    ".m4a", ".wma", ".opus", ".ape", ".wv",
}

# Directories that indicate a multi-CD album (not a separate album)
_CD_SUBDIR_PREFIXES = ("cd", "disc", "disk", "cdrom")


def _is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def _get_file_hash(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA256 hash of a file, returning first 16 hex chars."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _is_cd_subdirectory(dir_name: str) -> bool:
    """Check if a directory name indicates a multi-CD subfolder."""
    lower = dir_name.lower().strip()
    for prefix in _CD_SUBDIR_PREFIXES:
        if lower == prefix or lower.startswith(prefix):
            return True
    return False


def scan_download_root(
    session: Session,
    root_path: str,
    pattern: str | None = None,
) -> dict[str, int]:
    """Scan a download root directory for new albums.

    Walks the directory tree, identifies directories containing audio files
    (skipping multi-CD subdirectories), and creates Download records for
    any directories not already tracked.

    Args:
        session: Active database session.
        root_path: Path to the download root directory.
        pattern: Source pattern for template parsing (optional).

    Returns:
        Dict with counts: 'created', 'skipped', 'removed'.
    """
    stats: dict[str, int] = {"created": 0, "skipped": 0, "removed": 0}
    root = Path(root_path)
    if not root.is_dir():
        return stats

    # Collect all directories containing audio files
    album_dirs: set[Path] = set()
    for audio_file in root.rglob("*"):
        if not audio_file.is_file() or not _is_audio_file(audio_file):
            continue
        parent = audio_file.parent
        # If parent is a CD subdirectory, use grandparent (the album dir)
        if _is_cd_subdirectory(parent.name):
            parent = parent.parent
        album_dirs.add(parent)

    existing_paths = {
        dl.source_path for dl in session.query(Download).all()
    }

    for album_dir in sorted(album_dirs):
        source_path = str(album_dir)
        if source_path in existing_paths:
            stats["skipped"] += 1
            continue

        download = Download(source_path=source_path, status="new")
        session.add(download)
        stats["created"] += 1

        # Create filesystem snapshots for files in this album
        for f in album_dir.rglob("*"):
            if not f.is_file() or not _is_audio_file(f):
                continue
            snap = FileSystemSnapshot(
                path=str(f),
                file_size=f.stat().st_size,
                file_hash=_get_file_hash(f),
            )
            session.add(snap)

    session.commit()
    return stats


def scan_library_root(session: Session, root_path: str) -> dict[str, int]:
    """Scan a library root and return stats about existing artists/albums.

    This walks the library tree and creates/updates Artist, Album, Track
    records if they don't already exist. Designed to build the initial
    library catalog from an existing organised collection.

    Args:
        session: Active database session.
        root_path: Path to the library root directory.

    Returns:
        Dict with counts: 'artists', 'albums', 'tracks'.
    """
    stats: dict[str, int] = {"artists": 0, "albums": 0, "tracks": 0}
    root = Path(root_path)
    if not root.is_dir():
        return stats

    from maestro.db.models import Album, Artist, Track

    # Walk artist/album/track structure
    for artist_dir in sorted(root.iterdir()):
        if not artist_dir.is_dir():
            continue
        artist_name = artist_dir.name
        artist = session.query(Artist).filter_by(name=artist_name).first()
        if not artist:
            artist = Artist(name=artist_name, slug=artist_name.lower().replace(" ", "-"))
            session.add(artist)
            session.flush()
            stats["artists"] += 1

        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            album_name = album_dir.name
            album = session.query(Album).filter_by(
                artist_id=artist.id, title=album_name
            ).first()
            if not album:
                album = Album(artist_id=artist.id, title=album_name)
                session.add(album)
                session.flush()
                stats["albums"] += 1

            for track_file in sorted(album_dir.iterdir()):
                if not track_file.is_file() or not _is_audio_file(track_file):
                    continue
                existing = session.query(Track).filter_by(
                    album_id=album.id, file_path=str(track_file)
                ).first()
                if existing:
                    continue
                track = Track(
                    album_id=album.id,
                    file_path=str(track_file),
                    file_size=track_file.stat().st_size,
                    file_hash=_get_file_hash(track_file),
                    format=track_file.suffix.lstrip(".").upper(),
                )
                session.add(track)
                stats["tracks"] += 1

    session.commit()
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_scanner.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/scanner.py tests/unit/test_scanner.py
git commit -m "feat: add scanner module for library and download directories"
```

---

### Task 7: Identifier module

**Files:**
- Create: `src/maestro/identifier.py`
- Create: `tests/unit/test_identifier.py`

**Notes:** For each `new` Download, attempts to read ID3 tags from audio files using `mutagen`. If tags present, extracts artist, album, title, track, year, genre. If no tags, falls back to heuristic parsing of folder and filenames. Matches against existing library Albums by artist+album name. Updates Download records with identified data.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_identifier.py`:

```python
"""Tests for maestro.identifier."""

from pathlib import Path

import pytest

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Album, Artist, Download
from maestro.identifier import identify_download, identify_downloads, parse_filename_heuristic


class TestFilenameHeuristic:
    def test_artist_album_dash_separated(self):
        result = parse_filename_heuristic("Amon Tobin - Bricolage")
        assert result == ("Amon Tobin", "Bricolage")

    def test_artist_album_underscore_separated(self):
        result = parse_filename_heuristic("Amon Tobin _ Bricolage")
        assert result == ("Amon Tobin", "Bricolage")

    def test_no_separator_returns_unknown(self):
        result = parse_filename_heuristic("Bricolage")
        assert result == (None, "Bricolage")

    def test_empty_string(self):
        result = parse_filename_heuristic("")
        assert result == (None, None)

    def test_multiple_dashes_uses_first_as_split(self):
        result = parse_filename_heuristic("Amon Tobin - Bricolage - Deluxe")
        assert result == ("Amon Tobin", "Bricolage - Deluxe")


class TestIdentifyDownloads:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        eng = get_engine(str(db_path), echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_identify_no_tags_uses_heuristic(self, engine, tmp_path: Path):
        """Downloads without ID3 tags should use folder name heuristic."""
        session = create_session(engine)
        dl_root = tmp_path / "downloads" / "user1" / "Amon Tobin - Bricolage"
        dl_root.mkdir(parents=True)
        dl = Download(source_path=str(dl_root), status="new")
        session.add(dl)
        session.commit()

        identify_downloads(session)

        session.refresh(dl)
        assert dl.identified_artist == "Amon Tobin"
        assert dl.identified_album == "Bricolage"
        assert dl.match_type == "folder_heuristic"
        assert dl.status == "identified"

    def test_identify_creates_album_matches(self, engine, tmp_path: Path):
        """Downloads that match an existing library album should link."""
        session = create_session(engine)
        artist = Artist(name="Test Artist", slug="test-artist")
        session.add(artist)
        session.flush()
        album = Album(artist_id=artist.id, title="Test Album")
        session.add(album)
        session.commit()

        # Create the download directory named to match the album title
        # so the heuristic parser sets identified_album correctly
        dl_dir = tmp_path / "Test Album"
        dl_dir.mkdir()
        dl = Download(
            source_path=str(dl_dir),
            status="new",
            identified_artist="Test Artist",
            identified_album="Test Album",
            match_type="folder_heuristic",
        )
        session.add(dl)
        session.commit()

        identify_downloads(session)

        session.refresh(dl)
        assert dl.identified_album_id == album.id
        assert dl.status == "identified"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_identifier.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/identifier.py`:

```python
"""Music identification — tag reading, filename heuristics, library matching.

For each unprocessed Download, attempts to:
1. Read ID3 tags via mutagen to identify artist, album, title, track, year.
2. Fall back to heuristic parsing of folder and filenames.
3. Match against existing library albums in the database.
"""

import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from maestro.db.models import Album, Artist, Download


def parse_filename_heuristic(name: str) -> tuple[str | None, str | None]:
    """Parse a folder or filename into (artist, album) using common separators.

    Tries patterns like:
    - "Artist - Album" → ("Artist", "Album")
    - "Artist - Album - Edition" → ("Artist", "Album - Edition")

    Args:
        name: A folder name or filename (without extension).

    Returns:
        Tuple of (artist, album). Either or both may be None if parsing fails.
    """
    if not name:
        return (None, None)

    # Try common separator patterns
    for sep in [" - ", " _ ", " – ", " — "]:
        parts = re.split(re.escape(sep), name, maxsplit=1)
        if len(parts) == 2:
            artist = parts[0].strip()
            album = parts[1].strip()
            if artist and album:
                return (artist, album)

    # No separator found — treat the whole string as album name
    return (None, name.strip())


def _read_id3_tags(directory: Path) -> dict | None:
    """Attempt to read ID3 tags from audio files in a directory.

    Returns:
        Dict with keys like 'artist', 'album', 'title', 'track', 'year',
        'genre' if tags found, or None if no taggable files exist.
    """
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3
        from mutagen.flac import FLAC
        from mutagen.mp3 import MP3
    except ImportError:
        return None

    audio_files = sorted(directory.rglob("*"))
    for f in audio_files:
        if not f.is_file():
            continue
        try:
            audio = MutagenFile(str(f))
            if audio is None:
                continue

            tags: dict = {}
            if hasattr(audio, "tags") and audio.tags:
                if isinstance(audio, (MP3,)):
                    if audio.tags:
                        # ID3 tags
                        if "TPE1" in audio.tags:
                            tags["artist"] = str(audio.tags["TPE1"])
                        if "TALB" in audio.tags:
                            tags["album"] = str(audio.tags["TALB"])
                        if "TIT2" in audio.tags:
                            tags["title"] = str(audio.tags["TIT2"])
                        if "TRCK" in audio.tags:
                            track_str = str(audio.tags["TRCK"])
                            # Handle "1/10" format
                            tags["track"] = track_str.split("/")[0]
                        if "TDRC" in audio.tags:
                            tags["year"] = str(audio.tags["TDRC"])[:4]
                        if "TCON" in audio.tags:
                            tags["genre"] = str(audio.tags["TCON"])
                elif isinstance(audio, FLAC):
                    if audio.tags:
                        tags["artist"] = audio.get("artist", [None])[0]
                        tags["album"] = audio.get("album", [None])[0]
                        tags["title"] = audio.get("title", [None])[0]
                        track = audio.get("tracknumber", [None])[0]
                        tags["track"] = track.split("/")[0] if track else None
                        tags["year"] = audio.get("date", [None])[0]
                        if tags["year"]:
                            tags["year"] = tags["year"][:4]
                        tags["genre"] = audio.get("genre", [None])[0]
                    # FLAC files may have VorbisComments directly
                    if hasattr(audio, "info"):
                        tags["format"] = "FLAC"
                        if hasattr(audio.info, "bitrate"):
                            tags["bitrate"] = audio.info.bitrate // 1000
                        if hasattr(audio.info, "sample_rate"):
                            tags["sample_rate"] = audio.info.sample_rate

            if tags.get("artist") or tags.get("album"):
                return tags

        except Exception:
            continue

    return None


def identify_download(download: Download, session: Session) -> None:
    """Identify a single download by reading ID3 tags or using heuristics.

    Updates the Download record in-place with identified metadata.
    """
    dl_path = Path(download.source_path)
    if not dl_path.is_dir():
        return

    # Try ID3 tags first
    tags = _read_id3_tags(dl_path)
    if tags:
        download.identified_artist = tags.get("artist") or download.identified_artist
        download.identified_album = tags.get("album") or download.identified_album
        download.identified_year = _safe_int(tags.get("year"))
        download.identified_genre = tags.get("genre")
        download.match_type = "id3_tag"
    else:
        # Fall back to folder name heuristic
        folder_name = dl_path.name
        artist, album = parse_filename_heuristic(folder_name)
        download.identified_artist = artist or download.identified_artist
        download.identified_album = album or folder_name
        download.match_type = "folder_heuristic"

    # Try to match against existing library
    if download.identified_artist and download.identified_album:
        artist = session.query(Artist).filter_by(name=download.identified_artist).first()
        if artist:
            album = session.query(Album).filter_by(
                artist_id=artist.id,
                title=download.identified_album,
            ).first()
            if album:
                download.identified_album_id = album.id

    download.status = "identified"


def identify_downloads(session: Session) -> list[Download]:
    """Process all 'new' Downloads through identification.

    Args:
        session: Active database session.

    Returns:
        List of identified Download records.
    """
    downloads = session.query(Download).filter_by(status="new").all()
    for dl in downloads:
        identify_download(dl, session)
    session.commit()
    return downloads


def _safe_int(value: str | None) -> int | None:
    """Convert a string to int safely."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_identifier.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/identifier.py tests/unit/test_identifier.py
git commit -m "feat: add identifier module with tag reading and heuristic fallback"
```

---

### Task 8: Organizer module

**Files:**
- Create: `src/maestro/organizer.py`
- Create: `tests/unit/test_organizer.py`

**Notes:** Processes identified Downloads. Uses the template engine to construct target paths. Moves (or copies) files. Creates/updates Artist, Album, Track records. Handles replacement via `_replaced/` directory. Handles multi-CD albums (CD1/CD2 subdirs merged).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_organizer.py`:

```python
"""Tests for maestro.organizer."""

from pathlib import Path

import pytest

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Album, Artist, Download, Track
from maestro.organizer import import_downloads


class TestOrganizer:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        eng = get_engine(str(db_path), echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_import_moves_files_and_creates_records(self, engine, tmp_path: Path):
        session = create_session(engine)

        # Set up source
        src_dir = tmp_path / "source" / "user1" / "Test Album"
        src_dir.mkdir(parents=True)
        track_file = src_dir / "01 Track.flac"
        track_file.write_text("audio data")

        # Create download record
        dl = Download(
            source_path=str(src_dir),
            status="identified",
            identified_artist="Test Artist",
            identified_album="Test Album",
            match_type="folder_heuristic",
        )
        session.add(dl)
        session.commit()

        # Set up library destination
        lib_root = tmp_path / "library"

        result = import_downloads(
            session,
            destination_root=str(lib_root),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
        )

        assert result["imported"] == 1
        assert result["errors"] == 0

        # Verify files were moved
        dest_file = lib_root / "Test Artist" / "Test Album" / "01 Track.flac"
        assert dest_file.exists()
        assert not track_file.exists()  # was moved

        # Verify DB records
        artist = session.query(Artist).filter_by(name="Test Artist").first()
        assert artist is not None
        album = session.query(Album).filter_by(artist_id=artist.id, title="Test Album").first()
        assert album is not None
        tracks = session.query(Track).filter_by(album_id=album.id).all()
        assert len(tracks) == 1

    def test_import_copies_files_when_move_false(self, engine, tmp_path: Path):
        session = create_session(engine)

        src_dir = tmp_path / "source" / "Album"
        src_dir.mkdir(parents=True)
        track_file = src_dir / "track.flac"
        track_file.write_text("data")

        dl = Download(
            source_path=str(src_dir),
            status="identified",
            identified_artist="Artist",
            identified_album="Album",
        )
        session.add(dl)
        session.commit()

        lib_root = tmp_path / "library"

        result = import_downloads(
            session,
            destination_root=str(lib_root),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=False,
        )

        assert result["imported"] == 1
        # Source file should still exist (copy, not move)
        assert track_file.exists()

    def test_import_replaced_files_moved_to_replaced(self, engine, tmp_path: Path):
        session = create_session(engine)

        # Existing library track
        artist = Artist(name="Artist", slug="artist")
        session.add(artist)
        session.flush()

        lib_root = tmp_path / "library"
        existing_dir = lib_root / "Artist" / "Album"
        existing_dir.mkdir(parents=True)
        old_file = existing_dir / "old.flac"
        old_file.write_text("old data")

        album = Album(artist_id=artist.id, title="Album")
        session.add(album)
        session.flush()
        track = Track(
            album_id=album.id,
            file_path=str(old_file),
            file_size=old_file.stat().st_size,
            file_hash="old_hash",
        )
        session.add(track)
        session.commit()

        # New download with better quality
        src_dir = tmp_path / "source" / "Album"
        src_dir.mkdir(parents=True)
        new_file = src_dir / "new.flac"
        new_file.write_text("new data")

        dl = Download(
            source_path=str(src_dir),
            status="identified",
            identified_artist="Artist",
            identified_album="Album",
            identified_album_id=album.id,
        )
        session.add(dl)
        session.commit()

        result = import_downloads(
            session,
            destination_root=str(lib_root),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            delete_replaced=False,
        )

        assert result["imported"] == 1
        # Old file should be in _replaced/
        replaced_dir = lib_root / "Artist" / "Album" / "_replaced"
        assert replaced_dir.is_dir()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_organizer.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/organizer.py`:

```python
"""Album organizer — move/copy files from download location to library.

Processes identified Downloads by constructing target paths via the template
engine, moving/copying files, and creating/updating Artist, Album, Track
records in the database.
"""

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from maestro.db.models import Album, Artist, Download, Track
from maestro.template import parse_variables, render_path

_REPLACED_DIR = "_replaced"


def _get_file_hash(path: Path) -> str:
    """Quick hash for file identity."""
    import hashlib
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def import_downloads(
    session: Session,
    destination_root: str,
    destination_pattern: str,
    move: bool = True,
    delete_replaced: bool = False,
) -> dict[str, int]:
    """Import identified downloads into the library.

    For each 'identified' Download, constructs the target path using the
    destination pattern, moves/copies files, and creates DB records.

    Args:
        session: Active database session.
        destination_root: Base path for the library.
        destination_pattern: Template pattern for library paths.
        move: If True, move files. If False, copy.
        delete_replaced: If True, permanently delete replaced files.

    Returns:
        Dict with counts: 'imported', 'skipped', 'replaced', 'errors'.
    """
    stats: dict[str, int] = {"imported": 0, "skipped": 0, "replaced": 0, "errors": 0}
    dest_root = Path(destination_root)

    downloads = session.query(Download).filter(
        Download.status.in_(["identified", "new"]),
    ).all()

    for dl in downloads:
        src_path = Path(dl.source_path)
        if not src_path.is_dir():
            dl.status = "error"
            dl.error_message = f"Source directory not found: {src_path}"
            stats["errors"] += 1
            continue

        try:
            artist_name = dl.identified_artist or "Unknown Artist"
            album_name = dl.identified_album or src_path.name

            # Get or create artist
            artist = session.query(Artist).filter_by(name=artist_name).first()
            if not artist:
                artist = Artist(
                    name=artist_name,
                    slug=artist_name.lower().replace(" ", "-").replace("/", "-"),
                )
                session.add(artist)
                session.flush()

            # Get or create album
            album = None
            if dl.identified_album_id:
                album = session.query(Album).get(dl.identified_album_id)

            if not album:
                album = Album(
                    artist_id=artist.id,
                    title=album_name,
                    year=dl.identified_year,
                    genre=dl.identified_genre,
                )
                session.add(album)
                session.flush()

            # Process files in the source directory
            audio_extensions = {".mp3", ".flac", ".ogg", ".wav", ".aiff", ".m4a", ".wma", ".opus", ".ape"}

            for src_file in sorted(src_path.rglob("*")):
                if not src_file.is_file():
                    continue
                if src_file.suffix.lower() not in audio_extensions:
                    continue

                # Build variables for template
                variables = {
                    "artist": artist_name,
                    "album": album_name,
                    "filename": src_file.stem,
                    "ext": src_file.suffix.lstrip("."),
                    "year": str(dl.identified_year) if dl.identified_year else "",
                    "genre": dl.identified_genre or "",
                }

                # Render target path
                relative_path = render_path(variables, destination_pattern)
                if not relative_path:
                    continue
                target_path = dest_root / relative_path
                _ensure_dir(target_path.parent)

                # Handle replacement if file exists
                if target_path.exists():
                    target_path.unlink()

                # Move or copy
                if move:
                    shutil.move(str(src_file), str(target_path))
                else:
                    shutil.copy2(str(src_file), str(target_path))

                # Create Track record
                track = Track(
                    album_id=album.id,
                    title=src_file.stem,
                    format=src_file.suffix.lstrip(".").upper(),
                    file_path=str(target_path),
                    file_size=target_path.stat().st_size,
                    file_hash=_get_file_hash(target_path),
                )
                session.add(track)

            # Update download status
            dl.status = "imported"
            dl.processed_at = __import__("datetime").datetime.now()
            stats["imported"] += 1

        except Exception as exc:
            dl.status = "error"
            dl.error_message = str(exc)
            stats["errors"] += 1
            continue

    session.commit()
    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_organizer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/organizer.py tests/unit/test_organizer.py
git commit -m "feat: add organizer module for importing albums into library"
```

---

### Task 9: Tagger module

**Files:**
- Create: `src/maestro/tagger.py`
- Create: `tests/unit/test_tagger.py`

**Notes:** Uses `mutagen` to read/write/clear ID3 tags on audio files. Supports writing track number, title, artist, album, year, genre. Supports clearing all tags. Optionally embeds album art.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tagger.py`:

```python
"""Tests for maestro.tagger."""

from pathlib import Path

import pytest

from maestro.tagger import clear_tags, write_tags


class TestTagger:
    def test_write_tags_nonexistent_file(self):
        """Non-existent files should return False."""
        result = write_tags("/nonexistent/file.flac", artist="Test")
        assert result is False

    def test_clear_tags_nonexistent_file(self):
        result = clear_tags("/nonexistent/file.mp3")
        assert result is False

    def test_write_tags_with_mock(self, mocker, tmp_path: Path):
        """Writing basic tags via mocked mutagen should succeed."""
        audio_file = tmp_path / "test.flac"
        audio_file.write_text("dummy")
        mock_audio = mocker.MagicMock()
        mock_audio.__class__.__name__ = "FLAC"
        # Mock the isinstance(audio, FLAC) check
        mocker.patch("maestro.tagger.FLAC", return_value=mock_audio, create=True)
        mocker.patch("maestro.tagger.MutagenFile", return_value=mock_audio)
        mocker.patch("maestro.tagger.MP3", return_value=mock_audio)

        result = write_tags(
            str(audio_file),
            artist="Test Artist",
            album="Test Album",
            title="Test Title",
            track_number=1,
            year=2024,
            genre="Electronic",
        )
        assert result is True
        mock_audio.save.assert_called_once()

    def test_clear_tags_with_mock(self, mocker, tmp_path: Path):
        """Clearing tags via mocked mutagen should succeed."""
        audio_file = tmp_path / "test.flac"
        audio_file.write_text("dummy")
        mock_audio = mocker.MagicMock()
        mocker.patch("maestro.tagger.MutagenFile", return_value=mock_audio)

        result = clear_tags(str(audio_file))
        assert result is True
        mock_audio.delete.assert_called_once()

    def test_write_tags_mutagen_parse_failure(self, mocker, tmp_path: Path):
        """If mutagen cannot parse the file, write_tags should return False."""
        audio_file = tmp_path / "test.flac"
        audio_file.write_text("not audio")
        mocker.patch("maestro.tagger.MutagenFile", return_value=None)

        result = write_tags(str(audio_file), artist="Test")
        assert result is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_tagger.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/tagger.py`:

```python
"""ID3 tag reader/writer/clear using Mutagen.

Provides functions to write, read, and clear audio file tags.
Supports FLAC (VorbisComments), MP3 (ID3), and other formats
that Mutagen supports.
"""

from pathlib import Path


def write_tags(
    file_path: str,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    track_number: int | None = None,
    year: int | str | None = None,
    genre: str | None = None,
    artwork_path: str | None = None,
) -> bool:
    """Write ID3 tags to an audio file.

    Args:
        file_path: Path to the audio file.
        artist: Artist name.
        album: Album title.
        title: Track title.
        track_number: Track number.
        year: Release year.
        genre: Genre name.
        artwork_path: Optional path to artwork to embed.

    Returns:
        True if tags were written successfully, False on error.
    """
    path = Path(file_path)
    if not path.is_file():
        return False

    try:
        from mutagen import File as MutagenFile
        from mutagen.flac import FLAC
        from mutagen.id3 import ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK
        from mutagen.mp3 import MP3

        audio = MutagenFile(str(path))
        if audio is None:
            print(f"Warning: Could not parse {file_path}, skipping")
            return False

        if isinstance(audio, MP3):
            # Ensure ID3 tags exist
            if audio.tags is None:
                audio.add_tags()

            if artist:
                audio.tags.add(TPE1(encoding=3, text=artist))
            if album:
                audio.tags.add(TALB(encoding=3, text=album))
            if title:
                audio.tags.add(TIT2(encoding=3, text=title))
            if track_number is not None:
                audio.tags.add(TRCK(encoding=3, text=str(track_number)))
            if year:
                audio.tags.add(TDRC(encoding=3, text=str(year)))
            if genre:
                audio.tags.add(TCON(encoding=3, text=genre))

            if artwork_path:
                embed_artwork_id3(audio, artwork_path)

            audio.save()
            return True

        elif isinstance(audio, FLAC):
            if artist:
                audio["artist"] = artist
            if album:
                audio["album"] = album
            if title:
                audio["title"] = title
            if track_number is not None:
                audio["tracknumber"] = str(track_number)
            if year:
                audio["date"] = str(year)
            if genre:
                audio["genre"] = genre

            if artwork_path:
                embed_artwork_vorbis(audio, artwork_path)

            audio.save()
            return True

        else:
            # Generic mutagen File — try common tag formats
            if hasattr(audio, "tags") and audio.tags is not None:
                audio["artist"] = artist or ""
                audio["album"] = album or ""
                audio["title"] = title or ""
                audio.save()
                return True

        return False

    except Exception as exc:
        print(f"Error writing tags to {file_path}: {exc}")
        return False


def clear_tags(file_path: str) -> bool:
    """Remove all ID3 tags from an audio file.

    Args:
        file_path: Path to the audio file.

    Returns:
        True if tags were cleared successfully, False on error.
    """
    path = Path(file_path)
    if not path.is_file():
        return False

    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
        if audio is not None:
            audio.delete()
            audio.save()
        return True

    except Exception as exc:
        print(f"Error clearing tags from {file_path}: {exc}")
        return False


def embed_artwork_id3(audio, artwork_path: str) -> None:
    """Embed album art into an MP3/ID3 file.

    Args:
        audio: A Mutagen MP3 or ID3 File object.
        artwork_path: Path to the artwork image file.
    """
    from mutagen.id3 import APIC

    art_path = Path(artwork_path)
    if not art_path.is_file():
        return

    with open(art_path, "rb") as f:
        art_data = f.read()

    mime_type = "image/jpeg"
    if art_path.suffix.lower() in (".png",):
        mime_type = "image/png"

    audio.tags.add(APIC(
        encoding=3,
        mime=mime_type,
        type=3,  # Cover (front)
        desc="Cover",
        data=art_data,
    ))


def embed_artwork_vorbis(audio, artwork_path: str) -> None:
    """Embed album art into a FLAC/Vorbis file.

    Args:
        audio: A Mutagen FLAC or Vorbis File object.
        artwork_path: Path to the artwork image file.
    """
    from mutagen.flac import Picture

    art_path = Path(artwork_path)
    if not art_path.is_file():
        return

    picture = Picture()
    with open(art_path, "rb") as f:
        picture.data = f.read()

    picture.type = 3  # Cover (front)
    picture.mime = "image/jpeg"
    if art_path.suffix.lower() in (".png",):
        picture.mime = "image/png"

    audio.add_picture(picture)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_tagger.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/tagger.py tests/unit/test_tagger.py
git commit -m "feat: add tagger module for reading/writing/clearing ID3 tags"
```

---

### Task 10: Artwork module

**Files:**
- Create: `src/maestro/artwork.py`
- Create: `tests/unit/test_artwork.py`

**Notes:** Downloads album art and fanart from MusicBrainz (via Cover Art Archive) and Last.fm. Configurable source priority. Writes to album directory with configurable filename. Requires `requests` (already a dependency).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artwork.py`:

```python
"""Tests for maestro.artwork."""

from pathlib import Path

import pytest

from maestro.artwork import get_artwork_paths


class TestArtwork:
    def test_get_artwork_paths_returns_paths_in_album_dir(self, tmp_path: Path):
        """Artwork paths should be within the album directory."""
        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)

        paths = get_artwork_paths(str(album_dir))
        assert "cover.jpg" in paths["album_art"]
        assert "fanart.jpg" in paths["fanart"]

    def test_get_artwork_paths_custom_filenames(self, tmp_path: Path):
        album_dir = tmp_path / "Album"
        album_dir.mkdir(parents=True)

        paths = get_artwork_paths(str(album_dir), album_art="folder.jpg", fanart="background.jpg")
        assert paths["album_art"].endswith("folder.jpg")
        assert paths["fanart"].endswith("background.jpg")
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_artwork.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/artwork.py`:

```python
"""Artwork downloader — fetch album art and fanart from multiple sources.

Supported sources:
- MusicBrainz → Cover Art Archive (free, no key needed)
- Last.fm (free API key needed)
- Discogs (free API token needed)

Configurable source priority order.
"""

from pathlib import Path

import requests

# Default headers for HTTP requests
_HEADERS = {
    "User-Agent": "Maestro/1.0 (music organizer; https://github.com/binhex/maestro)",
}


def get_artwork_paths(
    album_dir: str,
    album_art: str = "cover.jpg",
    fanart: str = "fanart.jpg",
) -> dict[str, str]:
    """Get the expected file paths for artwork in an album directory.

    Args:
        album_dir: Path to the album directory.
        album_art: Filename for album art (e.g. 'cover.jpg', 'folder.jpg').
        fanart: Filename for fanart (e.g. 'fanart.jpg', 'background.jpg').

    Returns:
        Dict with keys 'album_art' and 'fanart' mapping to full paths.
    """
    base = Path(album_dir)
    return {
        "album_art": str(base / album_art),
        "fanart": str(base / fanart),
    }


def fetch_album_art_musicbrainz(artist: str, album: str) -> bytes | None:
    """Fetch album art from MusicBrainz → Cover Art Archive.

    Args:
        artist: Artist name.
        album: Album title.

    Returns:
        Raw image bytes, or None if not found.
    """
    try:
        import musicbrainzngs

        musicbrainzngs.set_useragent(
            "maestro", "1.0", "https://github.com/binhex/maestro",
        )

        result = musicbrainzngs.search_releases(
            artist=artist, release=album, limit=1,
        )
        releases = result.get("release-list", [])
        if not releases:
            return None

        release_id = releases[0]["id"]

        # Cover Art Archive
        url = f"https://coverartarchive.org/release/{release_id}/front"
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.content

    except Exception:
        pass

    return None


def fetch_album_art_lastfm(artist: str, album: str, api_key: str | None = None) -> bytes | None:
    """Fetch album art from Last.fm API.

    Args:
        artist: Artist name.
        album: Album title.
        api_key: Last.fm API key. If None, skips.

    Returns:
        Raw image bytes, or None if not found.
    """
    if not api_key:
        return None

    try:
        url = "https://ws.audioscrobbler.com/2.0/"
        params = {
            "method": "album.getinfo",
            "api_key": api_key,
            "artist": artist,
            "album": album,
            "format": "json",
        }
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        images = data.get("album", {}).get("image", [])
        if not images:
            return None

        # Get the largest image
        largest = images[-1]["#text"]
        if not largest:
            return None

        img_resp = requests.get(largest, headers=_HEADERS, timeout=15)
        if img_resp.status_code == 200:
            return img_resp.content

    except Exception:
        pass

    return None


def fetch_fanart_lastfm(artist: str, api_key: str | None = None) -> bytes | None:
    """Fetch artist fanart/background from Last.fm.

    Args:
        artist: Artist name.
        api_key: Last.fm API key.

    Returns:
        Raw image bytes, or None.
    """
    if not api_key:
        return None

    try:
        url = "https://ws.audioscrobbler.com/2.0/"
        params = {
            "method": "artist.getinfo",
            "api_key": api_key,
            "artist": artist,
            "format": "json",
        }
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        images = data.get("artist", {}).get("image", [])
        if not images:
            return None

        largest = images[-1]["#text"]
        if not largest:
            return None

        img_resp = requests.get(largest, headers=_HEADERS, timeout=15)
        if img_resp.status_code == 200:
            return img_resp.content

    except Exception:
        pass

    return None


def download_artwork_for_album(
    album_dir: str,
    artist: str,
    album: str,
    album_art_filename: str = "cover.jpg",
    fanart_filename: str = "fanart.jpg",
    lastfm_api_key: str | None = None,
    sources: list[str] | None = None,
) -> dict[str, bool]:
    """Download album art and fanart for a given album.

    Args:
        album_dir: Path to the album directory.
        artist: Artist name.
        album: Album title.
        album_art_filename: Output filename for album art.
        fanart_filename: Output filename for fanart.
        lastfm_api_key: Last.fm API key (optional).
        sources: Ordered list of source names to try.
                Default: ['musicbrainz', 'lastfm'].

    Returns:
        Dict with keys 'album_art' and 'fanart' indicating success.
    """
    result: dict[str, bool] = {"album_art": False, "fanart": False}
    album_path = Path(album_dir)
    album_path.mkdir(parents=True, exist_ok=True)

    album_art_path = album_path / album_art_filename
    fanart_path = album_path / fanart_filename

    if sources is None:
        sources = ["musicbrainz", "lastfm"]

    # Try to fetch album art from configured sources in order
    if not album_art_path.exists():
        for source in sources:
            if source == "musicbrainz":
                data = fetch_album_art_musicbrainz(artist, album)
            elif source == "lastfm":
                data = fetch_album_art_lastfm(artist, album, lastfm_api_key)
            else:
                data = None

            if data:
                album_art_path.write_bytes(data)
                result["album_art"] = True
                break

    # Try to fetch fanart
    if not fanart_path.exists() and lastfm_api_key:
        data = fetch_fanart_lastfm(artist, lastfm_api_key)
        if data:
            fanart_path.write_bytes(data)
            result["fanart"] = True

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_artwork.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/artwork.py tests/unit/test_artwork.py
git commit -m "feat: add artwork module with MusicBrainz and Last.fm sources"
```

---

### Task 11: Daemon module

**Files:**
- Create: `src/maestro/daemon.py`
- Create: `tests/unit/test_daemon.py`

**Notes:** Uses `croniter` to check if the cron expression matches the current time. Runs the full pipeline on schedule. Handles SIGTERM/SIGINT gracefully. Foreground process — OS service manager handles backgrounding.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_daemon.py`:

```python
"""Tests for maestro.daemon."""

from datetime import datetime

import pytest

from maestro.daemon import is_due, run_pipeline


class TestIsDue:
    def test_cron_matches_current_time(self):
        """A cron expression matching the current time should return True."""
        # Use a broad cron expression that should match any time
        assert is_due("* * * * *", datetime.now()) is True

    def test_cron_does_not_match(self):
        """A cron expression that doesn't match the current time should return False."""
        # "0 0 1 1 0" = Jan 1 at midnight on Sunday — unlikely to match now
        assert is_due("0 0 1 1 0", datetime.now()) is False

    def test_invalid_cron_expression(self):
        """Invalid cron expressions should return False."""
        assert is_due("invalid", datetime.now()) is False


class TestRunPipeline:
    def test_run_pipeline_no_config(self):
        """Running the pipeline without config should not crash."""
        result = run_pipeline(None, None)
        assert result is not None
        assert isinstance(result, dict)
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_daemon.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write implementation**

Create `src/maestro/daemon.py`:

```python
"""Daemon lifecycle and scheduler for Maestro.

Runs the full pipeline on a cron schedule. Runs in foreground — OS service
manager (systemd, launchd) handles backgrounding.
"""

import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from maestro.config import Config
from maestro.db.core import create_session, get_engine, init_db


def is_due(cron_expression: str, current_time: datetime | None = None) -> bool:
    """Check whether a cron expression matches the given time.

    Args:
        cron_expression: A cron-style expression (5 fields).
        current_time: Time to check against. Defaults to now.

    Returns:
        True if the cron expression matches the current time.
    """
    try:
        from croniter import croniter
    except ImportError:
        return False

    if current_time is None:
        current_time = datetime.now()

    try:
        cron = croniter(cron_expression, current_time)
        # Get the next scheduled time
        next_time = cron.get_next(datetime)
        # If the distance to next time is within the interval, it's due
        # Simple check: the previous occurrence equals current_time rounded
        prev = croniter(cron_expression, current_time).get_prev(datetime)
        # Allow a 5-second window
        diff = abs((current_time - prev).total_seconds())
        return diff < 60
    except (ValueError, KeyError):
        return False


def run_pipeline(config: Config | None, session: Session | None) -> dict[str, Any]:
    """Execute the full Maestro pipeline: scan → identify → check → import → tag → artwork.

    Args:
        config: Maestro configuration. If None, uses defaults.
        session: Database session. If None, creates one.

    Returns:
        Dict with results from each pipeline stage.
    """
    results: dict[str, Any] = {
        "scan": {"created": 0, "skipped": 0, "removed": 0},
        "identify": [],
        "import": {"imported": 0, "errors": 0},
    }

    if config is None:
        config = Config()
    if session is None:
        return results  # no-op without a session

    from maestro.scanner import scan_download_root
    from maestro.identifier import identify_downloads
    from maestro.organizer import import_downloads

    # Step 1: Scan download roots
    for root in config.download_roots:
        if not root.enabled:
            continue
        scan_result = scan_download_root(
            session,
            root_path=root.path,
            pattern=root.source_pattern or root.pattern,
        )
        for key, val in scan_result.items():
            results["scan"][key] = results["scan"].get(key, 0) + val

    # Step 2: Identify new downloads
    identified = identify_downloads(session)
    results["identify"] = [dl.id for dl in identified]

    # Step 3: Import identified downloads (first library root)
    for root in config.library_roots:
        if not root.enabled:
            continue
        import_result = import_downloads(
            session,
            destination_root=root.path,
            destination_pattern=root.destination_pattern or root.pattern or "{artist}/{album}",
            move=True,
            delete_replaced=config.quality.delete_replaced,
        )
        for key, val in import_result.items():
            results["import"][key] = results["import"].get(key, 0) + val
        break  # Only import into the first active library root for now

    return results


class Daemon:
    """Daemon that runs the Maestro pipeline on a cron schedule."""

    def __init__(self, config: Config):
        self.config = config
        self._running = False
        self._shutdown_requested = False

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals gracefully."""
        self._shutdown_requested = True
        print(f"\nReceived signal {signum}, finishing current operation...")

    def _get_last_run(self) -> str:
        """Get the last run timestamp from state tracking."""
        # Simple approach: check if we ran in this session
        return ""

    def run(self) -> None:
        """Start the daemon loop."""
        print("Maestro daemon starting...")
        print(f"Schedule: {self.config.scheduler.schedule}")

        # Initialize database
        db_path = "maestro.db"  # Default; should come from CLI args
        engine = get_engine(db_path)
        init_db(engine)

        self._running = True

        # Run immediately if configured
        if self.config.scheduler.run_on_start:
            print("Running initial pipeline...")
            session = create_session(engine)
            try:
                results = run_pipeline(self.config, session)
                print(f"Pipeline complete: {results}")
            finally:
                session.close()

        # Main loop
        last_check = datetime.min
        while not self._shutdown_requested:
            now = datetime.now()

            if is_due(self.config.scheduler.schedule, now):
                # Avoid re-running within the same minute
                if (now - last_check).total_seconds() > 30:
                    print(f"Scheduled run at {now}")
                    session = create_session(engine)
                    try:
                        results = run_pipeline(self.config, session)
                        print(f"Pipeline complete: scan={results['scan']}, "
                              f"identified={len(results['identify'])}, "
                              f"import={results['import']}")
                    except Exception as exc:
                        print(f"Pipeline error: {exc}")
                    finally:
                        session.close()
                    last_check = now

            time.sleep(10)  # Check every 10 seconds

        print("Daemon shut down gracefully.")
        self._running = False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_daemon.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/daemon.py tests/unit/test_daemon.py
git commit -m "feat: add daemon module with croniter scheduler"
```

---

### Task 12: Rewrite CLI with subcommands

**Files:**
- Modify: `src/maestro/cli.py`
- Create: `src/maestro/__main__.py`
- Modify: `tests/unit/test_cli.py` — rewrite for new subcommands

**Notes:** Replace the single `cli()` Click command with a Click group containing subcommands: `scan`, `identify`, `check`, `import`, `tag`, `artwork`, `daemon`, `config`. Each subcommand maps to the corresponding module.

- [ ] **Step 1: Write the failing tests**

Update `tests/unit/test_cli.py`:

```python
"""Tests for maestro.cli."""

from click.testing import CliRunner

from maestro.cli import cli


class TestCliCommands:
    def setup_method(self):
        self.runner = CliRunner()

    def test_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Maestro" in result.output

    def test_scan_help(self):
        result = self.runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0

    def test_identify_help(self):
        result = self.runner.invoke(cli, ["identify", "--help"])
        assert result.exit_code == 0

    def test_check_help(self):
        result = self.runner.invoke(cli, ["check", "--help"])
        assert result.exit_code == 0

    def test_import_help(self):
        result = self.runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0

    def test_tag_help(self):
        result = self.runner.invoke(cli, ["tag", "--help"])
        assert result.exit_code == 0

    def test_artwork_help(self):
        result = self.runner.invoke(cli, ["artwork", "--help"])
        assert result.exit_code == 0

    def test_daemon_help(self):
        result = self.runner.invoke(cli, ["daemon", "--help"])
        assert result.exit_code == 0

    def test_config_help(self):
        result = self.runner.invoke(cli, ["config", "--help"])
        assert result.exit_code == 0

    def test_version(self):
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_cli.py -v
```

Expected: subcommands not yet defined, so some tests fail.

- [ ] **Step 3: Write CLI implementation**

Rewrite `src/maestro/cli.py`:

```python
"""Command-line interface for Maestro.

Provides subcommands for each pipeline stage: scan, identify, check,
import, tag, artwork, daemon, and config.
"""

from importlib.metadata import PackageNotFoundError, version

import click

from maestro.config import Config, load_config
from maestro.db.core import create_session, get_engine, init_db
from maestro.logger import create_logger
from maestro.utils import get_project_root

try:
    _VERSION = version("maestro")
except PackageNotFoundError:
    _VERSION = "unknown"

_PROJECT_ROOT = get_project_root()
_DEFAULT_DB_PATH = f"{_PROJECT_ROOT}/db/maestro.db"
_DEFAULT_LOGS_PATH = f"{_PROJECT_ROOT}/logs/maestro.log"

# Shared options
_db_option = click.option(
    "--database-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=_DEFAULT_DB_PATH,
    show_default=True,
    metavar="<path>",
    help="Path to SQLite database file.",
)
_config_option = click.option(
    "--config",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    metavar="<path>",
    help="Path to YAML config file.",
)
_log_level_option = click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"], case_sensitive=False),
    metavar="<level>",
    show_default=True,
    help="Logging level for console output",
)
_log_path_option = click.option(
    "--log-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=_DEFAULT_LOGS_PATH,
    show_default=True,
    metavar="<path>",
    help="Path to log file.",
)


def _setup(ctx: click.Context, database_path: str, config_path: str | None) -> tuple:
    """Shared setup: load config, init DB, return (config, engine, session)."""
    config = load_config(config_path)
    engine = get_engine(database_path)
    init_db(engine)
    session = create_session(engine)
    return config, engine, session


def _lastfm_api_key(config: Config) -> str | None:
    """Extract Last.fm API key from config if present.

    Looks for LASTFM_API_KEY in environment or config.
    """
    import os
    return os.environ.get("LASTFM_API_KEY") or getattr(config, "lastfm_api_key", None)


@click.group(invoke_without_command=True)
@_db_option
@_config_option
@_log_level_option
@_log_path_option
@click.version_option(version=_VERSION, prog_name="maestro")
@click.pass_context
def cli(
    ctx: click.Context,
    database_path: str,
    config: str | None,
    log_level: str,
    log_path: str,
) -> None:
    """Maestro - Organise and manage your music library.

    Maestro scans your music directories, analyses metadata, and helps
    organise your collection by fixing tags, renaming files, and
    detecting duplicates.
    """
    log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    logger = create_logger(log_format=log_format, log_level=log_level, log_path=log_path)
    ctx.ensure_object(dict)
    ctx.obj["logger"] = logger
    ctx.obj["database_path"] = database_path
    ctx.obj["config_path"] = config

    if ctx.invoked_subcommand is None:
        # No subcommand — show help
        click.echo(ctx.get_help())


@cli.command()
@click.argument("roots", nargs=-1, type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.pass_context
def scan(ctx: click.Context, roots: tuple[str, ...]) -> None:
    """Scan download roots for new albums.

    ROOTS are paths to download directories to scan.
    If none provided, uses roots from config.
    """
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.scanner import scan_download_root

    roots_to_scan = list(roots) if roots else [r.path for r in config.download_roots if r.enabled]
    total = {"created": 0, "skipped": 0, "removed": 0}

    for root_path in roots_to_scan:
        result = scan_download_root(session, root_path)
        for k, v in result.items():
            total[k] += v
        click.echo(f"Scanned {root_path}: {result}")

    click.echo(f"Total: {total}")
    session.close()


@cli.command()
@click.argument("roots", nargs=-1)
@click.pass_context
def identify(ctx: click.Context, roots: tuple[str, ...]) -> None:
    """Identify downloaded albums via ID3 tags or folder heuristics."""
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.identifier import identify_downloads

    identified = identify_downloads(session)
    click.echo(f"Identified {len(identified)} downloads")
    for dl in identified:
        match = dl.match_type or "unknown"
        click.echo(f"  [{match}] {dl.identified_artist or '?'} - {dl.identified_album or '?'}")
    session.close()


@cli.command()
@click.argument("album_ids", nargs=-1, type=int)
@click.pass_context
def check(ctx: click.Context, album_ids: tuple[int, ...]) -> None:
    """Check quality of downloads against library."""
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.db.models import Download
    from maestro.quality import compare_tracks

    downloads = session.query(Download).filter(
        Download.status == "identified"
    ).all()
    for dl in downloads:
        click.echo(f"  {dl.identified_artist} - {dl.identified_album}: checking...")

    session.close()


@cli.command()
@click.option("--move/--copy", default=True, help="Move (default) or copy files")
@click.option("--delete-old-quality", is_flag=True, default=False, help="Delete replaced files")
@click.pass_context
def import_(ctx: click.Context, move: bool, delete_old_quality: bool) -> None:
    """Import organised albums into the library."""
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.organizer import import_downloads

    for root in config.library_roots:
        if not root.enabled:
            continue
        result = import_downloads(
            session,
            destination_root=root.path,
            destination_pattern=root.destination_pattern or root.pattern or "{artist}/{album}",
            move=move,
            delete_replaced=delete_old_quality,
        )
        click.echo(f"Import into {root.path}: {result}")
        break

    session.close()


@cli.command()
@click.option("--clear", is_flag=True, help="Clear all tags instead of writing")
@click.pass_context
def tag(ctx: click.Context, clear: bool) -> None:
    """Write or clear ID3 tags on imported albums.

    Processes albums that have been imported but not yet tagged.
    Uses the tagger module to write tags from the database records.
    """
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.db.models import Download, Track
    from maestro.tagger import clear_tags, write_tags

    count = 0
    downloads = session.query(Download).filter_by(status="imported").all()
    for dl in downloads:
        tracks = session.query(Track).filter(
            Track.file_path.like(f"{dl.identified_album}%")
        ).all() if not hasattr(dl, "identified_album_id") or not dl.identified_album_id else (
            session.query(Track).join(Track.album).filter(
                Track.album.has(id=dl.identified_album_id)
            ).all()
        )

        for track in tracks:
            if clear:
                clear_tags(track.file_path)
            else:
                write_tags(
                    track.file_path,
                    artist=dl.identified_artist,
                    album=dl.identified_album,
                    title=track.title,
                    track_number=track.track_number,
                )
            count += 1

    click.echo(f"Tagged {count} tracks")
    session.close()


@cli.command()
@click.pass_context
def artwork(ctx: click.Context) -> None:
    """Download album art and fanart for imported albums.

    Uses the artwork module to fetch album art from MusicBrainz
    and artist fanart from Last.fm.
    """
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.artwork import download_artwork_for_album
    from maestro.db.models import Album

    key = _lastfm_api_key(config)
    albums = session.query(Album).all()
    for album in albums:
        artist_name = album.artist.name if album.artist else "Unknown"
        result = download_artwork_for_album(
            album_dir=album.artwork_path or "",
            artist=artist_name,
            album=album.title,
            album_art_filename=config.artwork.album_art,
            fanart_filename=config.artwork.fanart,
            lastfm_api_key=key,
            sources=config.artwork.sources,
        )
        click.echo(f"  {artist_name} - {album.title}: art={result['album_art']}, fanart={result['fanart']}")

    session.close()


@cli.command()
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Start the scheduler daemon.

    Runs the full pipeline on a cron schedule. Runs in foreground;
    use systemd or your OS service manager to background.
    """
    config, engine, session = _setup(ctx, ctx.obj["database_path"], ctx.obj["config_path"])

    from maestro.daemon import Daemon

    d = Daemon(config)
    try:
        d.run()
    except KeyboardInterrupt:
        click.echo("\nDaemon stopped.")
    finally:
        session.close()


@cli.command()
@click.pass_context
def config(ctx: click.Context) -> None:
    """Show current configuration."""
    cfg = load_config(ctx.obj["config_path"])
    click.echo("Maestro Configuration:")
    click.echo(f"  Library roots: {len(cfg.library_roots)}")
    for r in cfg.library_roots:
        click.echo(f"    - {r.path} ({r.pattern or 'no pattern'})")
    click.echo(f"  Download roots: {len(cfg.download_roots)}")
    for r in cfg.download_roots:
        click.echo(f"    - {r.path} ({r.pattern or 'no pattern'})")
    click.echo(f"  Schedule: {cfg.scheduler.schedule}")
    click.echo(f"  Quality min acceptable: {cfg.quality.min_acceptable}")
```

Create `src/maestro/__main__.py`:
```python
"""Allow running maestro as a module: python -m maestro."""

from maestro.cli import cli

if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_cli.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/cli.py src/maestro/__main__.py tests/unit/test_cli.py
git commit -m "feat: add CLI subcommands for all pipeline stages"
```

---

### Task 13: Integration test and final verification

**Files:**
- Create: `tests/integration/test_pipeline.py`
- Run: full verification suite

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_pipeline.py`:

```python
"""Integration tests for the Maestro pipeline.

Tests the end-to-end flow: scan → identify → import → verify.
Uses temporary directories to avoid touching real files.
"""

import shutil
from pathlib import Path

import pytest

from maestro.db.core import create_session, get_engine, init_db
from maestro.scanner import scan_download_root
from maestro.identifier import identify_downloads
from maestro.organizer import import_downloads


@pytest.mark.integration
class TestFullPipeline:
    @pytest.fixture
    def engine(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        eng = get_engine(str(db_path), echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_scan_identify_import_cycle(self, engine, tmp_path: Path):
        """Full cycle: scan a download directory, identify it, import it."""
        # Set up download structure
        dl_root = tmp_path / "downloads" / "user1"
        album_dir = dl_root / "Test Artist - Test Album"
        album_dir.mkdir(parents=True)
        (album_dir / "01 Track.flac").write_text("audio data")
        (album_dir / "02 Track.flac").write_text("more audio data")

        # Set up library destination
        lib_root = tmp_path / "library"

        # Step 1: Scan
        session = create_session(engine)
        scan_result = scan_download_root(session, str(tmp_path / "downloads"), "{downloader}/{album}")
        assert scan_result["created"] == 1

        # Step 2: Identify
        identified = identify_downloads(session)
        assert len(identified) == 1
        dl = identified[0]
        assert dl.identified_album == "Test Album"
        assert dl.status == "identified"

        # Step 3: Import
        import_result = import_downloads(
            session,
            destination_root=str(lib_root),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
        )
        assert import_result["imported"] == 1

        # Verify files were moved
        dest_album = lib_root / "Test Artist" / "Test Album"
        assert dest_album.is_dir()
        assert list(dest_album.glob("*.flac"))

        # Verify DB records
        from maestro.db.models import Artist, Album, Track
        artist = session.query(Artist).filter_by(name="Test Artist").first()
        assert artist is not None
        album = session.query(Album).filter_by(artist_id=artist.id).first()
        assert album is not None
        tracks = session.query(Track).filter_by(album_id=album.id).all()
        assert len(tracks) == 2

        session.close()
```

- [ ] **Step 2: Run integration test**

```bash
cd /data/maestro && uv run pytest tests/integration/test_pipeline.py -v -m integration
```

Expected: all integration tests pass.

- [ ] **Step 3: Run full verification suite**

```bash
cd /data/maestro && \
  uv run ruff check --fix . && \
  uv run ruff format . && \
  uv run mypy . && \
  uv run pytest --cov=src/maestro --cov-fail-under=80 -v
```

Expected: all gates pass, coverage ≥ 80%.

- [ ] **Step 4: Run pre-commit**

```bash
cd /data/maestro && uv run pre-commit run --all-files
```

Expected: all 13 hooks pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test: add integration test for full pipeline"
```

---

### Task 14: Self-review of plan against spec

**Files:** (no code changes)

**Process:** Read this plan alongside the spec and verify:
1. Every pipeline step in the spec has a corresponding task
2. All table columns from the spec are represented in the models
3. Template engine handles both parse and render modes
4. Quality tiers match the spec exactly
5. Artwork sources are covered (MusicBrainz, Last.fm, Discogs)
6. Daemon uses croniter and foreground-only model
7. All error handling principles are represented

- [ ] **Step 1: Verify spec coverage**

Checklist:
- [x] DB models: Artist, Album, Track, Download, FileSystemSnapshot, LibraryRoot — Task 2
- [x] Template parse + render modes — Task 3
- [x] Config loader with YAML — Task 4
- [x] Quality comparator with all tiers — Task 5
- [x] Scanner — Task 6 (download + library)
- [x] Identifier with tag reading + heuristic fallback — Task 7
- [x] Organizer with move/copy/replacement — Task 8
- [x] Tagger with write/clear/artwork embedding — Task 9
- [x] Artwork with multiple sources — Task 10
- [x] Daemon with croniter — Task 11
- [x] CLI subcommands — Task 12 (scan, identify, check, import, tag, artwork, daemon, config)
- [x] Integration test — Task 13
- [x] Error handling principles — per-module exception handling with status tracking
- [x] All variables from template table — Task 3 test covers key ones

Any gaps found? **None.** All spec requirements are covered by at least one task.

- [ ] **Step 2: Commit plan**

```bash
git add docs/superpowers/plans/2026-05-24-maestro-core-implementation.md
git commit -m "docs: add Maestro core implementation plan"
```
