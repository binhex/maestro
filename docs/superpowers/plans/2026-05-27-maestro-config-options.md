# Maestro Config Options — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three config toggles — dry-run mode for the import pipeline, and per-feature booleans to disable album art and/or fanart downloading.

**Architecture:** Each feature is a focused change in the config dataclass, then threaded through the affected module. Dry-run adds a `bool` parameter to `import_downloads()` that skips all filesystem and DB mutations. Artwork toggles add two `bool` params to `download_artwork_for_album()` that are checked before fetching. CLI `--dry-run` flags on `import` and `daemon` override the config value.

**Tech Stack:** Python 3.12, Click (CLI), Mutagen (tagger), musicbrainzngs/requests (artwork), pytest + pytest-mock.

---
### Task 1: Config dataclass and migration

**Files:**
- Modify: `src/maestro/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing tests for new config fields**

```python
# — tests/unit/test_config.py —

class TestConfigDataclass:
    # ... existing tests ...

    def test_default_dry_run_is_false(self) -> None:
        config = Config()
        assert config.dry_run is False

    def test_default_download_album_art_is_true(self) -> None:
        config = ArtworkConfig()
        assert config.download_album_art is True

    def test_default_download_fanart_is_true(self) -> None:
        config = ArtworkConfig()
        assert config.download_fanart is True

    def test_custom_dry_run_from_config(self) -> None:
        config = Config(dry_run=True)
        assert config.dry_run is True

    def test_custom_artwork_disables(self) -> None:
        config = ArtworkConfig(download_album_art=False, download_fanart=False)
        assert config.download_album_art is False
        assert config.download_fanart is False

    def test_post_init_converts_dict_with_new_fields(self) -> None:
        """__post_init__ should handle the new artwork fields from dict."""
        config = Config(
            artwork={"download_album_art": False, "download_fanart": False},
        )
        assert isinstance(config.artwork, ArtworkConfig)
        assert config.artwork.download_album_art is False
        assert config.artwork.download_fanart is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v -k "dry_run or download_album_art or download_fanart or new_fields"`

Expected: FAIL — `Config` has no field `dry_run`, `ArtworkConfig` has no field `download_album_art`.

- [ ] **Step 3: Add fields, bump version, add migration**

In `src/maestro/config.py`:

```python
CONFIG_VERSION = 3  # bump from 2

@dataclass
class ArtworkConfig:
    download_album_art: bool = True     # NEW
    download_fanart: bool = True        # NEW
    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    # ... rest unchanged ...

@dataclass
class Config:
    dry_run: bool = False               # NEW — top-level
    library_roots: list[RootEntry] = field(default_factory=list)
    # ... rest unchanged ...
```

Register the migration:

```python
_MIGRATIONS: dict[int, Any] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
}

def _migrate_v2_to_v3(data: dict) -> None:
    """Add dry_run at root, download_album_art/fanart under artwork."""
    data.setdefault("dry_run", False)
    artwork = data.setdefault("artwork", {})
    artwork.setdefault("download_album_art", True)
    artwork.setdefault("download_fanart", True)
```

Also update the default YAML generation and `_default_config_dict()`:

```python
# In _default_config_dict(), add to the root:
"dry_run": False,
# And under artwork section:
"download_album_art": True,
"download_fanart": True,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: All pass, including the 6 new tests.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/config.py tests/unit/test_config.py
git commit -m "feat: add dry_run, download_album_art, download_fanart config fields"
```

---

### Task 2: Organizer — dry-run support

**Files:**
- Modify: `src/maestro/organizer.py` — add `dry_run` param to `import_downloads()`
- Test: `tests/unit/test_organizer.py` — add dry-run tests

- [ ] **Step 1: Write failing test for dry-run behaviour**

In `tests/unit/test_organizer.py`, after existing test class:

```python
# Need to import the Download model for assertions
from maestro.db.models import Download


# Must be added before use; insert in the test class
class TestImportDownloadsDryRun:
    """Tests for dry-run mode in import_downloads."""

    def test_import_downloads_dry_run_returns_actions(
        self, engine, download_dir,
    ) -> None:
        """Dry run should return actions list instead of mutating files."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        assert result["dry_run"] is True
        assert isinstance(result["actions"], list)
        # Should have at least one "Would move:" action for the track(s)
        move_actions = [a for a in result["actions"] if a.startswith("Would move")]
        assert len(move_actions) > 0

    def test_import_downloads_dry_run_does_not_mutate_db(
        self, engine, download_dir,
    ) -> None:
        """Dry run must NOT create Artist/Album/Track records or change download status."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        # Count records before
        artist_count_before = session.query(Artist).count()
        album_count_before = session.query(Album).count()
        track_count_before = session.query(Track).count()
        dl = session.query(Download).first()
        assert dl is not None
        dl_status_before = dl.status

        lib_root = str(download_dir.parent.parent / "library")
        import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        # No new records
        assert session.query(Artist).count() == artist_count_before
        assert session.query(Album).count() == album_count_before
        assert session.query(Track).count() == track_count_before

        # Download status unchanged
        session.refresh(dl)
        assert dl.status == dl_status_before

    def test_import_downloads_dry_run_does_not_create_files(
        self, engine, download_dir,
    ) -> None:
        """Dry run must not create any files or directories in the library root."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        lib_path = Path(lib_root)

        import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        # Library root should not exist (was never created)
        assert not lib_path.exists()

    def test_import_downloads_dry_run_returns_zero_import_count(
        self, engine, download_dir,
    ) -> None:
        """Dry run must return imported=0 regardless of what would happen."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        assert result["imported"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_organizer.py -v -k "DryRun"`

Expected: FAIL — `import_downloads()` doesn't accept `dry_run` parameter yet.

- [ ] **Step 3: Implement dry-run in import_downloads**

In `src/maestro/organizer.py`, change the function signature and add early-exit logic:

```python
def import_downloads(
    session: Session,
    destination_root: str,
    destination_pattern: str,
    move: bool = True,
    delete_replaced: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    # ... docstring unchanged, add dry_run to Args section ...

    dest_root = Path(destination_root).resolve()
    counts: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "replaced": 0,
        "errors": 0,
    }

    downloads: list[Download] = session.query(Download).filter(Download.status == "identified").all()

    if not downloads:
        logger.info("No identified downloads to import")
        if dry_run:
            counts["dry_run"] = True
            counts["actions"] = []
        return counts

    # DRY RUN MODE — simulate without mutating
    if dry_run:
        actions: list[str] = []
        for dl in downloads:
            source = Path(dl.source_path)
            if not source.is_dir():
                actions.append(f"Would skip: {source} (source directory missing)")
                continue

            artist_name = dl.identified_artist or "Unknown Artist"
            album_title = dl.identified_album or source.name
            audio_files = sorted(
                f for f in source.iterdir()
                if f.is_file() and _is_audio_file(f)
            )
            if not audio_files:
                actions.append(f"Would skip: {source} (no audio files)")
                continue

            # Check quality against existing album
            if dl.identified_album_id is not None:
                existing_album = session.get(Album, dl.identified_album_id)
                if existing_album and existing_album.tracks:
                    skip_count = 0
                    for afile in audio_files:
                        track_key = afile.stem.lower()
                        for t in existing_album.tracks:
                            if t.file_path and Path(t.file_path).stem.lower() == track_key and t.format:
                                from maestro.quality import compare_tracks
                                decision = compare_tracks((t.format, t.bitrate), (afile.suffix.lstrip(".").upper(), None))
                                if decision == "skip":
                                    skip_count += 1
                                    break
                    if skip_count == len(audio_files):
                        actions.append(f"Would skip: {source.name} (all tracks equal/better quality in library)")
                        continue

            for afile in audio_files:
                stem = _fs_safe(afile.stem)
                ext = afile.suffix.lstrip(".")
                variables = {
                    "artist": artist_name or "",
                    "album": album_title or "",
                    "filename": stem,
                    "ext": ext,
                    "year": str(dl.identified_year) if dl.identified_year else "",
                    "genre": dl.identified_genre or "",
                }
                from maestro.template import render_path
                relative_path = render_path(variables, destination_pattern)
                full_target = (dest_root / relative_path).resolve()
                actions.append(f"Would move: {afile} → {full_target}")

        counts["dry_run"] = True
        counts["actions"] = actions
        return counts

    # ... existing normal logic continues unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_organizer.py -v`

Expected: All tests pass, including the 4 new dry-run tests.

- [ ] **Step 5: Check no regressions in existing tests**

Run: `uv run pytest tests/unit/ -v`

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/maestro/organizer.py tests/unit/test_organizer.py
git commit -m "feat: add dry-run support to import_downloads"
```

---

### Task 3: Artwork disable flags

**Files:**
- Modify: `src/maestro/artwork.py` — add `download_album_art` / `download_fanart` params to `download_artwork_for_album()`
- Test: `tests/unit/test_artwork.py` — add tests for disable flags

- [ ] **Step 1: Write failing tests for artwork disable flags**

```python
# — tests/unit/test_artwork.py — in a new test class

class TestDownloadArtworkForAlbumDisable:
    """Tests for the download_album_art / download_fanart disable flags."""

    def test_disable_album_art_returns_none(self, tmp_path, mocker) -> None:
        """When download_album_art is False, album_art in result should be None."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=False,
            download_fanart=True,
        )

        assert result["album_art"] is None
        assert result["source_used"] is None

    def test_disable_fanart_returns_none(self, tmp_path, mocker) -> None:
        """When download_fanart is False, fanart in result should be None."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=True,
            download_fanart=False,
        )

        assert result["fanart"] is None

    def test_disable_both_returns_early(self, tmp_path, mocker) -> None:
        """When both are False, should log and return no artwork."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=False,
            download_fanart=False,
        )

        assert result["album_art"] is None
        assert result["fanart"] is None
        assert result["source_used"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_artwork.py -v -k "Disable"`

Expected: FAIL — `download_artwork_for_album()` doesn't accept `download_album_art`/`download_fanart` params.

- [ ] **Step 3: Implement disable flags in artwork module**

In `src/maestro/artwork.py`, change the function signature:

```python
def download_artwork_for_album(
    album_dir: str,
    artist: str,
    album: str,
    album_art_filename: str = "cover.jpg",
    fanart_filename: str = "fanart.jpg",
    download_album_art: bool = True,       # NEW
    download_fanart: bool = True,          # NEW
    lastfm_api_key: str | None = None,
    sources: list[str] | None = None,
    max_width: int = 500,
    max_height: int = 500,
    aspect_tolerance_percentage: int = 5,
) -> dict[str, Any]:
```

Add early checks after the variables setup block (near the top of the function body):

```python
    # Early exit if all artwork is disabled
    if not download_album_art and not download_fanart:
        logger.info("Artwork downloading disabled for '{} — {}'", artist, album)
        return {"album_art": None, "fanart": None, "source_used": None}

    # Skip album art if disabled
    if not download_album_art:
        result["album_art"] = None
        result["source_used"] = None
    else:
        # ... existing album art logic ...

    # Skip fanart if disabled
    if not download_fanart:
        result["fanart"] = None
    else:
        # ... existing fanart logic ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_artwork.py -v`

Expected: All tests pass, including the 3 new disable tests.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/artwork.py tests/unit/test_artwork.py
git commit -m "feat: add download_album_art and download_fanart disable flags"
```

---

### Task 4: Daemon pipeline — thread dry_run

**Files:**
- Modify: `src/maestro/daemon.py` — pass `config.dry_run` in `run_pipeline()`
- Test: `tests/unit/test_daemon.py` — add test verifying dry_run passes through

- [ ] **Step 1: Write failing test**

```python
# — tests/unit/test_daemon.py —

class TestRunPipelineDryRun:
    """Tests for dry_run threading in run_pipeline."""

    def test_run_pipeline_passes_dry_run_to_import(self, mocker) -> None:
        """When config.dry_run is True, import_downloads should receive it."""
        from maestro.config import RootEntry

        mock_import = mocker.patch("maestro.daemon.import_downloads")
        mocker.patch(
            "maestro.daemon.scan_download_root",
            return_value={"created": 0, "skipped": 0},
        )
        mocker.patch(
            "maestro.daemon.identify_downloads",
            return_value=[],
        )

        config = Config(dry_run=True)
        config.download_roots = [RootEntry(path="/dl", type="download", enabled=True)]
        config.library_roots = [RootEntry(
            path="/lib", type="library", enabled=True,
            destination_pattern="{artist}/{album}",
        )]
        config.quality.delete_replaced = False

        session = MagicMock()
        run_pipeline(config, session)

        assert mock_import.called, "import_downloads should have been called"
        call_args, call_kwargs = mock_import.call_args
        assert call_kwargs.get("dry_run") is True, (
            f"Expected dry_run=True, got kwargs={call_kwargs}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_daemon.py -v -k "DryRun"`

- [ ] **Step 3: Pass dry_run from config to import_downloads**

In `src/maestro/daemon.py`, change the import phase inside `run_pipeline()`:

```python
    # --- 3. Import identified downloads ---
    library_roots = [r for r in config.library_roots if r.enabled]
    if not library_roots:
        logger.info("No enabled library roots — import phase skipped")
    else:
        lib_root = library_roots[0]
        dest_pattern = lib_root.destination_pattern or "{artist}/{album}/{filename}.{ext}"
        try:
            import_result = import_downloads(
                session=session,
                destination_root=lib_root.path,
                destination_pattern=dest_pattern,
                move=True,
                delete_replaced=config.quality.delete_replaced,
                dry_run=config.dry_run,          # NEW
            )
            result["imported"] = import_result
            logger.info("Import: {}", import_result)
        except Exception:
            logger.exception("Import phase failed")
            result["pipeline"]["errors"] += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_daemon.py -v`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/daemon.py tests/unit/test_daemon.py
git commit -m "feat: thread config.dry_run through daemon pipeline"
```

---

### Task 5: CLI — --dry-run flags and artwork wiring

**Files:**
- Modify: `src/maestro/cli.py` — `--dry-run` on `import` and `daemon`; wire artwork toggles; show new fields in `config`
- Test: `tests/unit/test_cli.py` — tests for new flags and display

- [ ] **Step 1: Write failing tests**

```python
# — tests/unit/test_cli.py —

from click.testing import CliRunner
from unittest.mock import patch
from maestro.cli import cli


class TestCliDryRun:
    """Tests for --dry-run CLI flags."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_import_has_dry_run_option(self) -> None:
        """--help on import should show --dry-run."""
        result = self.runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output

    def test_daemon_has_dry_run_option(self) -> None:
        """--help on daemon should show --dry-run."""
        result = self.runner.invoke(cli, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.create_session")
    @patch("maestro.cli.get_engine")
    @patch("maestro.cli.init_db")
    def test_import_dry_run_flag_overrides_config(
        self, mock_init_db, mock_get_engine, mock_create_session, mock_load_config,
    ) -> None:
        """Passing --dry-run to import should override config.dry_run=False."""
        from maestro.config import Config

        mock_load_config.return_value = Config(dry_run=False)
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        with patch("maestro.cli.import_downloads") as mock_import:
            self.runner.invoke(cli, ["import", "--dry-run"])
            _import_kwargs = mock_import.call_args.kwargs if hasattr(mock_import.call_args, 'kwargs') else {}
            # Simpler check: just verify it was called at all
            assert mock_import.called, "import_downloads should have been called"
            call_kwargs = mock_import.call_args[1] if len(mock_import.call_args) > 1 else {}
            assert call_kwargs.get("dry_run") is True


class TestCliArtworkDisabled:
    """Tests for artwork disable config affecting CLI artwork command."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_artwork_early_exit_when_both_disabled(self) -> None:
        """When both download_album_art and download_fanart are False, artwork command should exit early."""
        from maestro.config import ArtworkConfig, Config

        config = Config(artwork=ArtworkConfig(download_album_art=False, download_fanart=False))

        with patch("maestro.cli.load_config", return_value=config), \
             patch("maestro.cli.create_session"), \
             patch("maestro.cli.get_engine"), \
             patch("maestro.cli.init_db"):
            result = self.runner.invoke(cli, ["artwork"])
            assert "disabled" in result.output.lower()


class TestCliConfigDisplay:
    """Tests for 'maestro config' display output."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_config_shows_new_fields(self) -> None:
        """The config command should display the new config fields."""
        with patch("maestro.cli.load_config") as mock_load, \
             patch("maestro.cli.create_session") as mock_session, \
             patch("maestro.cli.get_engine"), \
             patch("maestro.cli.init_db"):
            from maestro.config import Config
            mock_load.return_value = Config()
            mock_session.return_value = MagicMock()

            result = self.runner.invoke(cli, ["config"])
            assert "Dry run" in result.output
            assert "download album art" in result.output.lower() or "download_album_art" in result.output
            assert "download fanart" in result.output.lower() or "download_fanart" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli.py -v -k "DryRun or ArtworkDisabled or ConfigDisplay"`

Expected: FAIL — missing `--dry-run` options and config display lines.

- [ ] **Step 3: Add --dry-run to import command**

In `src/maestro/cli.py`, modify the `import_` function:

```python
@cli.command(name="import")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Simulate import without making changes.",
)
@click.pass_context
def import_(ctx: click.Context, dry_run: bool) -> None:
    """Import identified downloads into the music library."""
    from maestro.organizer import import_downloads

    config, _engine, session = _setup(ctx)
    try:
        library_roots = [r for r in config.library_roots if r.enabled]
        if not library_roots:
            click.echo("No enabled library roots in config.")
            return

        lib_root = library_roots[0]
        dest_pattern = lib_root.destination_pattern or "{artist}/{album}/{filename}.{ext}"
        effective_dry_run = dry_run or config.dry_run

        click.echo(f"Importing downloads into {lib_root.path}...")
        result = import_downloads(
            session=session,
            destination_root=lib_root.path,
            destination_pattern=dest_pattern,
            move=True,
            delete_replaced=config.quality.delete_replaced,
            dry_run=effective_dry_run,
        )
        if effective_dry_run:
            click.echo("--- DRY RUN --- No files were changed ---")
            for action in result.get("actions", []):
                click.echo(f"  {action}")
            click.echo(
                f"Summary: would import={result.get('imported', 0)} "
                f"would skip={result.get('skipped', 0)} "
                f"would replace={result.get('replaced', 0)}",
            )
        else:
            click.echo(
                f"  imported={result['imported']} "
                f"skipped={result['skipped']} "
                f"replaced={result['replaced']} "
                f"errors={result['errors']}",
            )
    finally:
        session.close()
```

- [ ] **Step 4: Add --dry-run to daemon command**

```python
@cli.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Run daemon pipeline in dry-run mode (simulate import without changes).",
)
@click.pass_context
def daemon(ctx: click.Context, dry_run: bool) -> None:
    """Run the Maestro daemon (scheduled pipeline execution)."""
    from maestro.daemon import Daemon

    config, _engine, session = _setup(ctx)
    session.close()

    # Override config.dry_run if --dry-run flag is set
    if dry_run:
        config.dry_run = True

    click.echo("Starting Maestro daemon...")
    db_path = ctx.obj.get("database_path") if ctx.obj else None
    daemon_instance = Daemon(config, db_path=db_path)
    daemon_instance.run()
```

- [ ] **Step 5: Wire artwork disable flags in CLI**

In the `artwork` command, add the early-exit check and pass the flags:

```python
@cli.command()
@click.pass_context
def artwork(ctx: click.Context) -> None:
    """Download album art and fanart for all albums in the library."""
    from maestro.artwork import download_artwork_for_album
    from maestro.db.models import Album, Artist

    config, _engine, session = _setup(ctx)
    try:
        if not config.artwork.download_album_art and not config.artwork.download_fanart:
            click.echo("Artwork downloading is disabled in config.")
            return

        albums = session.query(Album).join(Artist, Album.artist_id == Artist.id).all()
        if not albums:
            click.echo("No albums found in database.")
            click.echo("Run 'maestro scan --library' first to populate the database from your music library.")
            return

        api_key = _lastfm_api_key(config)
        sources = config.artwork.sources

        for album in albums:
            if not album.artist:
                continue
            if album.tracks:
                album_dir = str(Path(album.tracks[0].file_path).parent)
            else:
                click.echo(f"Skipping '{album.title}' — no tracks in database.")
                continue

            click.echo(f"Fetching artwork for '{album.artist.name} — {album.title}'...")
            result = download_artwork_for_album(
                album_dir=album_dir,
                artist=album.artist.name,
                album=album.title,
                album_art_filename=config.artwork.album_art,
                fanart_filename=config.artwork.fanart,
                download_album_art=config.artwork.download_album_art,   # NEW
                download_fanart=config.artwork.download_fanart,         # NEW
                lastfm_api_key=api_key,
                sources=sources,
                max_width=config.artwork.width,
                max_height=config.artwork.height,
                aspect_tolerance_percentage=config.artwork.aspect_tolerance_percentage,
            )
            source = result.get("source_used") or "none"
            click.echo(f"  Album art: {'✓' if result['album_art'] else '✗'} ({source})")
            click.echo(f"  Fanart:    {'✓' if result['fanart'] else '✗'}")
    finally:
        session.close()
```

- [ ] **Step 6: Show new fields in config display**

In the `show_config` function, add after the existing artwork lines:

```python
    click.echo(f"  Dry run: {config.dry_run}")
    click.echo(f"  Artwork download album art: {config.artwork.download_album_art}")
    click.echo(f"  Artwork download fanart: {config.artwork.download_fanart}")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cli.py -v`

Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add src/maestro/cli.py tests/unit/test_cli.py
git commit -m "feat: add --dry-run flags and artwork disable wiring to CLI"
```

---

### Task 6: Integration verification

**Files:** None — run the full suite.

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest --cov=src/maestro --cov-fail-under=80 -v`

Expected: All tests pass, coverage ≥ 80%.

- [ ] **Step 2: Run mypy**

Run: `uv run mypy . --no-error-summary`

Expected: 0 errors.

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: Clean.

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "chore: fix lint/type issues from config options"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `src/maestro/config.py` | Add `dry_run` field, `download_album_art`/`download_fanart` fields, bump `CONFIG_VERSION` to 3, add `_migrate_v2_to_v3` |
| `src/maestro/organizer.py` | Add `dry_run` param to `import_downloads()`, implement dry-run mode that logs actions without mutating files or DB |
| `src/maestro/artwork.py` | Add `download_album_art`/`download_fanart` params, early-exit when disabled |
| `src/maestro/daemon.py` | Pass `config.dry_run` to `import_downloads()` in pipeline |
| `src/maestro/cli.py` | `--dry-run` flag on `import` and `daemon`; wire artwork toggles; show new fields in `config` |
| `tests/unit/test_config.py` | 6 new tests (default field values, custom values, post-init dict conversion) |
| `tests/unit/test_organizer.py` | 4 new tests (dry-run actions, no DB mutation, no file creation, zero import count) |
| `tests/unit/test_artwork.py` | 3 new tests (disable album art, disable fanart, disable both) |
| `tests/unit/test_daemon.py` | 1 new test (dry_run threaded to import) |
| `tests/unit/test_cli.py` | 5 new tests (import help shows flag, daemon help shows flag, flag overrides config, artwork early exit, config display shows fields) |
