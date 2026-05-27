"""Tests for maestro.cli."""

import importlib
import tempfile
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

import maestro.cli
from maestro.cli import cli


class TestCliGroup:
    """Tests for the CLI group (shared options, version, help)."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_help_output(self) -> None:
        """--help should display usage with all subcommands."""
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Maestro" in result.output
        assert "scan" in result.output
        assert "identify" in result.output
        assert "check" in result.output
        assert "import" in result.output
        assert "tag" in result.output
        assert "artwork" in result.output
        assert "daemon" in result.output
        assert "config" in result.output
        assert "--database-path" in result.output
        assert "--log-level" in result.output
        assert "--log-path" in result.output

    def test_bare_invocation_initialises_config(self) -> None:
        """Running 'maestro' with no subcommand should call load_config to generate default config."""
        from maestro.config import load_config as real_load

        call_count: list[int] = [0]

        def tracking_load(*args: object, **kwargs: object) -> object:
            call_count[0] += 1
            return real_load(*args, **kwargs)

        with patch("maestro.cli.load_config", tracking_load):
            self.runner.invoke(cli, [])

        assert call_count[0] == 1, (
            f"load_config was called {call_count[0]} times, expected 1 — "
            "bare 'maestro' should trigger default config creation"
        )

    def test_version_output(self) -> None:
        """--version should display version information."""
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "maestro" in result.output

    def test_version_fallback_on_package_not_found(self) -> None:
        """When the package isn't installed, _VERSION should fall back to 'unknown'."""
        with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
            importlib.reload(maestro.cli)
            assert maestro.cli._VERSION == "unknown"
        # Reload again to restore normal state
        importlib.reload(maestro.cli)
        assert maestro.cli._VERSION != "unknown"


class TestSubcommandHelp:
    """Each subcommand should display its own help text."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["scan", "--help"], "scan"),
            (["identify", "--help"], "identify"),
            (["check", "--help"], "check"),
            (["import", "--help"], "import"),
            (["tag", "--help"], "tag"),
            (["artwork", "--help"], "artwork"),
            (["daemon", "--help"], "daemon"),
            (["config", "--help"], "config"),
        ],
    )
    def test_subcommand_help(self, args: list[str], expected: str) -> None:
        """Each subcommand --help should exit 0 and mention its name."""
        result = self.runner.invoke(cli, args)
        assert result.exit_code == 0
        assert expected in result.output


class TestScan:
    """Tests for the ``scan`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_scan_with_roots(self) -> None:
        """Scan with explicit roots should call scan_download_root for each."""
        mock_session = Mock()
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        mock_scan = Mock(return_value={"created": 2, "skipped": 1, "removed": 0})

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.scanner.scan_download_root", mock_scan),
            self.runner.isolated_filesystem(),
        ):
            import os

            tmp_dir = os.path.join(os.getcwd(), "mydir")
            os.makedirs(tmp_dir)

            result = self.runner.invoke(cli, ["scan", tmp_dir])
            assert result.exit_code == 0
            assert "Scanning" in result.output
            mock_scan.assert_called_once()
            assert mock_session.close.called

    def test_scan_no_roots_from_config(self) -> None:
        """Scan with no roots and no config roots should show message."""
        mock_config = Mock()
        mock_config.download_roots = []
        mock_setup = Mock(return_value=(mock_config, Mock(), Mock()))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["scan"])
            assert result.exit_code == 0
            assert "No download roots to scan" in result.output

    def test_scan_library_flag(self) -> None:
        """Scan --library should call scan_library_root for each library root."""
        mock_config = Mock()
        mock_config.library_roots = [
            Mock(path="/music/lib1", enabled=True),
            Mock(path="/music/lib2", enabled=True),
        ]
        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        mock_lib_scan = Mock(return_value={"artists": 3, "albums": 5, "tracks": 20})

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.scanner.scan_library_root", mock_lib_scan),
        ):
            result = self.runner.invoke(cli, ["scan", "--library"])
            assert result.exit_code == 0
            # Should have called scan_library_root twice (once per library root)
            assert mock_lib_scan.call_count == 2
            assert "Library scan complete" in result.output

    def test_scan_library_no_roots(self) -> None:
        """Scan --library with no enabled library roots should show message."""
        mock_config = Mock()
        mock_config.library_roots = []
        mock_setup = Mock(return_value=(mock_config, Mock(), Mock()))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["scan", "--library"])
            assert result.exit_code == 0
            assert "No library roots to scan" in result.output


class TestIdentify:
    """Tests for the ``identify`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_identify_calls_identify_downloads(self) -> None:
        """Identify should call identify_downloads and report."""
        mock_session = Mock()
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        mock_identify = Mock(return_value=[Mock(), Mock()])

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.identifier.identify_downloads", mock_identify),
        ):
            result = self.runner.invoke(cli, ["identify"])
            assert result.exit_code == 0
            assert "Identified 2 download(s)" in result.output
            mock_identify.assert_called_once_with(mock_session)
            assert mock_session.close.called


class TestCheck:
    """Tests for the ``check`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_check_shows_library_stats(self) -> None:
        """Check should query DB and display statistics."""
        mock_session = Mock()
        # Mock the query chain for counts
        mock_session.query.return_value.count.return_value = 0
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["check"])
            assert result.exit_code == 0
            assert "Maestro Library Status" in result.output
            assert "Artists:" in result.output
            assert mock_session.close.called

    def test_check_shows_quality_tiers(self) -> None:
        """Check should display quality tiers when tracks exist in the DB."""
        mock_track_flac = Mock()
        mock_track_flac.format = "FLAC"
        mock_track_flac.bitrate = None

        mock_track_mp3 = Mock()
        mock_track_mp3.format = "MP3"
        mock_track_mp3.bitrate = 320

        mock_session = Mock()

        def query_side_effect(model: object) -> Mock:
            q = Mock()
            q.count.return_value = 0
            filter_mock = Mock()
            filter_mock.count.return_value = 0
            q.filter.return_value = filter_mock

            name = model.__name__  # type: ignore[attr-defined]
            if name == "Track":
                q.count.return_value = 2
                q.all.return_value = [mock_track_flac, mock_track_mp3]

            return q

        mock_session.query.side_effect = query_side_effect

        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["check"])
            assert result.exit_code == 0
            assert "Quality tiers" in result.output
            assert "Tier 10" in result.output  # FLAC tier


class TestImport:
    """Tests for the ``import`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_import_no_library_roots(self) -> None:
        """Import with no library roots should show message."""
        mock_config = Mock()
        mock_config.download_roots = []
        mock_config.library_roots = []
        mock_setup = Mock(return_value=(mock_config, Mock(), Mock()))

        with (
            patch("maestro.cli._setup", mock_setup),
            patch(
                "maestro.identifier.identify_downloads",
            ),
        ):
            result = self.runner.invoke(cli, ["import"])
            assert result.exit_code == 0
            assert "No enabled library roots" in result.output

    def test_import_calls_import_downloads(self) -> None:
        """Import with a library root should call import_downloads."""
        mock_lib_root = Mock()
        mock_lib_root.enabled = True
        mock_lib_root.path = "/music/library"
        mock_lib_root.destination_pattern = None

        mock_config = Mock()
        mock_config.download_roots = []
        mock_config.dry_run = False
        mock_config.library_roots = [mock_lib_root]
        mock_config.quality.delete_replaced = False

        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        mock_import_dl = Mock(
            return_value={
                "imported": 3,
                "skipped": 0,
                "replaced": 0,
                "errors": 0,
            },
        )

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.organizer.import_downloads", mock_import_dl),
            patch("maestro.identifier.identify_downloads"),
            patch("maestro.scanner.scan_download_root"),
        ):
            result = self.runner.invoke(cli, ["import"])
            assert result.exit_code == 0
            assert "imported=3" in result.output
            mock_import_dl.assert_called_once()
            assert mock_session.close.called

    def test_import_dry_run_shows_actions(self) -> None:
        """Import --dry-run should display action lines for each operation."""
        mock_lib_root = Mock()
        mock_lib_root.enabled = True
        mock_lib_root.path = "/music/library"
        mock_lib_root.destination_pattern = None

        mock_config = Mock()
        mock_config.download_roots = [
            Mock(enabled=True, path="/downloads", pattern=None),
        ]
        mock_config.dry_run = False
        mock_config.library_roots = [mock_lib_root]
        mock_config.quality.delete_replaced = False

        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        mock_import = Mock(
            return_value={
                "imported": 2,
                "skipped": 0,
                "replaced": 0,
                "errors": 0,
                "actions": ["  /src/track.flac -> /dst/track.flac"],
            },
        )

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.organizer.import_downloads", mock_import),
            patch("maestro.identifier.identify_downloads"),
            patch("maestro.scanner.scan_download_root"),
        ):
            result = self.runner.invoke(cli, ["import", "--dry-run"])
            assert result.exit_code == 0
            assert "DRY RUN" in result.output
            assert "/src/track.flac" in result.output
            assert "would import=2" in result.output


class TestTag:
    """Tests for the ``tag`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_tag_no_tracks(self) -> None:
        """Tag with no tracks should show message."""
        mock_session = Mock()
        mock_session.query.return_value.all.return_value = []
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["tag"])
            assert result.exit_code == 0
            assert "No tracks found to tag" in result.output

    def test_tag_clear_flag(self) -> None:
        """Tag --clear should call clear_tags."""
        mock_track = Mock()
        mock_track.file_path = "/music/track.flac"

        mock_session = Mock()
        mock_session.query.return_value.all.return_value = [mock_track]
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        mock_clear = Mock(return_value=True)

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.tagger.clear_tags", mock_clear),
        ):
            result = self.runner.invoke(cli, ["tag", "--clear"])
            assert result.exit_code == 0
            assert "Clearing tags" in result.output
            mock_clear.assert_called_once_with("/music/track.flac")

    def test_tag_writes_tags(self) -> None:
        """Tag without --clear should call write_tags for each track."""
        mock_track = Mock()
        mock_track.file_path = "/music/track.flac"
        mock_track.album = Mock()
        mock_track.album.artist = Mock()
        mock_track.album.artist.name = "Test Artist"
        mock_track.album.title = "Test Album"
        mock_track.album.year = 2024
        mock_track.album.genre = "Rock"
        mock_track.title = "Test Track"
        mock_track.track_number = 1

        mock_session = Mock()
        mock_session.query.return_value.all.return_value = [mock_track]
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.tagger.write_tags", return_value=True) as mock_write,
        ):
            result = self.runner.invoke(cli, ["tag"])
            assert result.exit_code == 0
            assert "Writing tags" in result.output
            assert "Tagged" in result.output
            mock_write.assert_called_once()


class TestArtwork:
    """Tests for the ``artwork`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_artwork_no_albums(self) -> None:
        """Artwork with no albums should show message."""
        mock_session = Mock()
        mock_session.query.return_value.join.return_value.all.return_value = []
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["artwork"])
            assert result.exit_code == 0
            assert "No albums found" in result.output

    def test_artwork_with_albums(self) -> None:
        """Artwork with albums should call download_artwork_for_album."""
        mock_artist = Mock()
        mock_artist.name = "Test Artist"

        mock_track = Mock()
        mock_track.file_path = "/music/Test Artist/Album/track.flac"

        mock_album = Mock()
        mock_album.artist = mock_artist
        mock_album.title = "Test Album"
        mock_album.tracks = [mock_track]

        mock_session = Mock()
        mock_session.query.return_value.join.return_value.all.return_value = [
            mock_album,
        ]

        mock_config = Mock()
        mock_config.artwork.album_art = "cover.jpg"
        mock_config.artwork.fanart = "fanart.jpg"
        mock_config.artwork.sources = ["musicbrainz"]

        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))
        mock_download = Mock(return_value={"album_art": True, "fanart": False})

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.artwork.download_artwork_for_album", mock_download),
        ):
            result = self.runner.invoke(cli, ["artwork"])
            assert result.exit_code == 0
            assert "Test Artist" in result.output
            mock_download.assert_called_once()
            assert mock_session.close.called


class TestSetup:
    """Tests for the _setup helper and _resolve_db_path."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_resolve_db_path_defaults(self) -> None:
        """_resolve_db_path should fall back to default when no path given."""
        mock_ctx = Mock()
        mock_ctx.parent = Mock()
        mock_ctx.parent.params = {"database_path": None}

        from maestro.cli import _resolve_db_path

        result = _resolve_db_path(None, mock_ctx)
        assert isinstance(result, str)
        assert "maestro.db" in result

    def test_resolve_db_path_with_directory(self) -> None:
        """A directory path should have maestro.db appended."""
        from maestro.cli import _resolve_db_path

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_ctx = Mock()
            mock_ctx.parent = Mock()
            mock_ctx.parent.params = {"database_path": None}

            result = _resolve_db_path(tmpdir, mock_ctx)
            assert result == str(Path(tmpdir) / "maestro.db")

    def test_resolve_setup_config_path(self) -> None:
        """_resolve_setup_config_path should return config from parent params."""
        from maestro.cli import _resolve_setup_config_path

        mock_ctx = Mock()
        mock_ctx.parent = Mock()
        mock_ctx.parent.params = {"config": "/custom/config.yaml"}

        result = _resolve_setup_config_path(mock_ctx, None)
        assert result == "/custom/config.yaml"

    def test_resolve_setup_config_path_default(self) -> None:
        """When no config in params, returns the passed config_path."""
        from maestro.cli import _resolve_setup_config_path

        mock_ctx = Mock()
        mock_ctx.parent = Mock()
        mock_ctx.parent.params = {}

        result = _resolve_setup_config_path(mock_ctx, "/my/config.yaml")
        assert result == "/my/config.yaml"

    def test_setup_raises_without_parent(self) -> None:
        """_setup should raise click.UsageError when ctx.parent is None."""
        import click

        from maestro.cli import _setup

        mock_ctx = Mock()
        mock_ctx.parent = None

        with pytest.raises(click.UsageError, match="_setup must be called"):
            _setup(mock_ctx)

    def test_clear_tags_for_tracks_direct(self) -> None:
        """_clear_tags_for_tracks should call clear_tags for each track."""
        from maestro.cli import _clear_tags_for_tracks

        mock_track = Mock()
        mock_track.file_path = "/music/track.flac"

        with patch("maestro.tagger.clear_tags", return_value=True) as mock_clear:
            _clear_tags_for_tracks([mock_track, mock_track])
            assert mock_clear.call_count == 2

    def test_write_tags_for_tracks_direct(self) -> None:
        """_write_tags_for_tracks should call write_tags for each track."""
        from maestro.cli import _write_tags_for_tracks

        mock_track = Mock()
        mock_track.file_path = "/music/track.flac"
        mock_track.album = Mock()
        mock_track.album.artist = Mock()
        mock_track.album.artist.name = "Artist"
        mock_track.album.title = "Album"
        mock_track.album.year = 2024
        mock_track.album.genre = "Genre"
        mock_track.title = "Title"
        mock_track.track_number = 1

        with patch("maestro.tagger.write_tags", return_value=True) as mock_write:
            _write_tags_for_tracks([mock_track])
            mock_write.assert_called_once()
            args, kwargs = mock_write.call_args
            assert kwargs["artist"] == "Artist"


class TestDaemon:
    """Tests for the ``daemon`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_daemon_starts(self) -> None:
        """Daemon should create a Daemon instance and call run()."""
        mock_config = Mock()
        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        mock_daemon_instance = Mock()
        mock_daemon_class = Mock(return_value=mock_daemon_instance)

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.daemon.Daemon", mock_daemon_class),
        ):
            result = self.runner.invoke(cli, ["daemon"])
            assert result.exit_code == 0
            mock_daemon_class.assert_called_once_with(mock_config, db_path=None)
            mock_daemon_instance.run.assert_called_once()
            assert mock_session.close.called

    def test_daemon_dry_run_flag(self) -> None:
        """Daemon --dry-run should set config.dry_run = True."""
        mock_config = Mock()
        mock_config.dry_run = False
        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))
        mock_daemon_instance = Mock()
        mock_daemon_class = Mock(return_value=mock_daemon_instance)

        with (
            patch("maestro.cli._setup", mock_setup),
            patch("maestro.daemon.Daemon", mock_daemon_class),
        ):
            result = self.runner.invoke(cli, ["daemon", "--dry-run"])
            assert result.exit_code == 0
            assert mock_config.dry_run is True


class TestShowConfig:
    """Tests for the ``config`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_config_display(self) -> None:
        """Config should display configuration values."""
        mock_config = Mock()
        mock_config.library_roots = []
        mock_config.download_roots = []
        mock_config.quality.min_acceptable = 3
        mock_config.quality.delete_replaced = False
        mock_config.artwork.album_art = "cover.jpg"
        mock_config.artwork.fanart = "fanart.jpg"
        mock_config.artwork.skip_if_exists = True
        mock_config.artwork.sources = ["musicbrainz"]
        mock_config.scheduler.schedule = "0 3 * * *"
        mock_config.scheduler.run_on_start = True
        mock_config.scheduler.retry_failed = True
        mock_config.scheduler.max_retries = 3

        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["config"])
            assert result.exit_code == 0
            assert "Maestro Configuration" in result.output
            assert "Library roots: 0" in result.output
            assert "Download roots: 0" in result.output
            assert "cover.jpg" in result.output
            assert mock_session.close.called

    def test_config_with_roots(self) -> None:
        """Config display should show library and download root details."""
        mock_lib_root = Mock()
        mock_lib_root.path = "/music/lib"
        mock_lib_root.enabled = True

        mock_dl_root = Mock()
        mock_dl_root.path = "/downloads/new"
        mock_dl_root.enabled = False

        mock_config = Mock()
        mock_config.library_roots = [mock_lib_root]
        mock_config.download_roots = [mock_dl_root]
        mock_config.quality.min_acceptable = 3
        mock_config.quality.delete_replaced = False
        mock_config.artwork.album_art = "cover.jpg"
        mock_config.artwork.fanart = "fanart.jpg"
        mock_config.artwork.skip_if_exists = True
        mock_config.artwork.sources = ["musicbrainz"]
        mock_config.artwork.download_album_art = True
        mock_config.artwork.download_fanart = True
        mock_config.dry_run = False
        mock_config.scheduler.schedule = "0 3 * * *"
        mock_config.scheduler.run_on_start = True
        mock_config.scheduler.retry_failed = True
        mock_config.scheduler.max_retries = 3

        mock_session = Mock()
        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["config"])
            assert result.exit_code == 0
            assert "/music/lib" in result.output
            assert "/downloads/new" in result.output
            assert "enabled=True" in result.output
            assert "enabled=False" in result.output


class TestLastfmApiKey:
    """Tests for the _lastfm_api_key helper."""

    def test_returns_env_var(self) -> None:
        """Should return the MAESTRO_LASTFM_API_KEY env var."""
        config = Mock()
        with patch.dict("os.environ", {"LASTFM_API_KEY": "my-secret-key"}):
            result = maestro.cli._lastfm_api_key(config)
            assert result == "my-secret-key"

    def test_returns_none_when_not_set(self) -> None:
        """Should return None when no env var is set."""
        config = Mock()
        with patch.dict("os.environ", clear=True):
            result = maestro.cli._lastfm_api_key(config)
            assert result is None


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
        self,
        mock_init_db,
        mock_get_engine,
        mock_create_session,
        mock_load_config,
    ) -> None:
        """Passing --dry-run to import should override config.dry_run=False."""
        from unittest.mock import MagicMock

        from maestro.config import Config

        mock_load_config.return_value = Config(
            dry_run=False,
            library_roots=[MagicMock(path="/music/lib", enabled=True)],
        )
        mock_session = MagicMock()
        mock_create_session.return_value = mock_session

        with patch("maestro.organizer.import_downloads") as mock_import:
            self.runner.invoke(cli, ["import", "--dry-run"])
            assert mock_import.called, "import_downloads should have been called"
            call_kwargs = mock_import.call_args[1] if len(mock_import.call_args) > 1 else {}
            assert call_kwargs.get("dry_run") is True


class TestCliArtworkDisabled:
    """Tests for artwork disable config affecting CLI artwork command."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_process_artwork_album_no_artist(self) -> None:
        """_process_artwork_album should return early when album has no artist."""
        from maestro.cli import _process_artwork_album

        album = Mock()
        album.artist = None
        album.title = "Some Album"

        config = Mock()

        # Should complete without raising when album has no artist
        _process_artwork_album(album, config, None, None)
        # Reaching here means the early-return path worked (no crash)

    def test_artwork_no_tracks_in_database(self) -> None:
        """Artwork should skip albums with no tracks in database."""
        mock_artist = Mock()
        mock_artist.name = "Test Artist"

        mock_album = Mock()
        mock_album.artist = mock_artist
        mock_album.title = "Test Album"
        mock_album.tracks = []  # No tracks

        mock_session = Mock()
        mock_session.query.return_value.join.return_value.all.return_value = [
            mock_album,
        ]

        mock_config = Mock()
        mock_config.artwork.download_album_art = True
        mock_config.artwork.download_fanart = True
        mock_config.artwork.album_art = "cover.jpg"
        mock_config.artwork.fanart = "fanart.jpg"
        mock_config.artwork.sources = ["musicbrainz"]

        mock_setup = Mock(return_value=(mock_config, Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["artwork"])
            assert result.exit_code == 0
            assert "no tracks in database" in result.output

    def test_artwork_early_exit_when_both_disabled(self) -> None:
        """When both download_album_art and download_fanart are False, artwork command should exit early."""

        from maestro.config import ArtworkConfig, Config

        config = Config(artwork=ArtworkConfig(download_album_art=False, download_fanart=False))

        with (
            patch("maestro.cli.load_config", return_value=config),
            patch("maestro.cli.create_session"),
            patch("maestro.cli.get_engine"),
            patch("maestro.cli.init_db"),
        ):
            result = self.runner.invoke(cli, ["artwork"])
            assert "disabled" in result.output.lower()


class TestImportAutoPipeline:
    """Tests that 'maestro import' auto-scans and identifies before importing."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.get_engine")
    @patch("maestro.cli.init_db")
    def test_import_auto_scans_and_identifies(
        self,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        mock_load_config: Mock,
        tmp_path: Path,
    ) -> None:
        """When import is called with no identified downloads, it should
        auto-scan download roots and identify before importing."""
        from maestro.config import Config, RootEntry

        # Create a temp download directory with audio files
        dl_root = tmp_path / "downloads"
        album_dir = dl_root / "TestArtist" / "TestAlbum"
        album_dir.mkdir(parents=True)
        (album_dir / "track01.flac").write_bytes(b"audio data 01")
        (album_dir / "track02.flac").write_bytes(b"audio data 02")

        # Configure download root + library root
        config = Config(
            download_roots=[
                RootEntry(path=str(dl_root), type="download", enabled=True),
            ],
            library_roots=[
                RootEntry(
                    path=str(tmp_path / "library"),
                    type="library",
                    enabled=True,
                    destination_pattern="{artist}/{album}/{filename}.{ext}",
                ),
            ],
        )
        config.dry_run = False
        mock_load_config.return_value = config

        # Patch create_session to return a real session
        from maestro.db.core import create_session, get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)
        session = create_session(engine)
        mock_get_engine.return_value = engine

        with (
            patch("maestro.cli.create_session", return_value=session),
            patch("maestro.scanner.scan_download_root") as mock_scan,
            patch("maestro.identifier.identify_downloads") as mock_identify,
            patch("maestro.organizer.import_downloads") as mock_import,
        ):
            self.runner.invoke(cli, ["import"])

            # After fix: scan and identify should have been called before import
            assert mock_scan.called, "import should auto-scan download roots before importing"
            assert mock_identify.called, "import should auto-identify downloads before importing"
            assert mock_import.called, "import should call import_downloads"


class TestImportUnifiedPipeline:
    """Tests that ``maestro import --all`` runs the full pipeline (tag + artwork)."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.get_engine")
    def test_import_all_triggers_tag_and_artwork(
        self,
        mock_get_engine: Mock,
        mock_load_config: Mock,
        tmp_path: Path,
    ) -> None:
        """When ``--all`` is passed, import runs tag and artwork after import."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        album_dir = dl_root / "TestArtist" / "TestAlbum"
        album_dir.mkdir(parents=True)
        (album_dir / "track01.flac").write_bytes(b"audio data")

        config = Config(
            download_roots=[
                RootEntry(path=str(dl_root), type="download", enabled=True),
            ],
            library_roots=[
                RootEntry(
                    path=str(tmp_path / "library"),
                    type="library",
                    enabled=True,
                    destination_pattern="{artist}/{album}/{filename}.{ext}",
                ),
            ],
        )
        config.dry_run = False
        mock_load_config.return_value = config

        from maestro.db.core import create_session, get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)
        session = create_session(engine)
        mock_get_engine.return_value = engine

        # Seed a track in the DB so tag/artwork phases have something to process
        from maestro.db.models import Album, Artist, Track

        artist = Artist(name="Test Artist", slug="test-artist")
        session.add(artist)
        session.flush()
        album = Album(title="Test Album", artist_id=artist.id)
        session.add(album)
        session.flush()
        track = Track(
            album_id=album.id,
            title="track01",
            format="FLAC",
            file_path=str(album_dir / "track01.flac"),
            file_size=100,
            file_hash="aabbccddeeff0011",
        )
        session.add(track)
        session.commit()

        with (
            patch("maestro.cli.create_session", return_value=session),
            patch("maestro.scanner.scan_download_root"),
            patch("maestro.identifier.identify_downloads"),
            patch("maestro.organizer.import_downloads"),
            patch("maestro.cli._write_tags_for_tracks") as mock_tag,
            patch("maestro.cli._process_artwork_album") as mock_artwork,
        ):
            self.runner.invoke(cli, ["import", "--all"])

            assert mock_tag.called, "--all should trigger tag phase after import"
            assert mock_artwork.called, "--all should trigger artwork phase after import"

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.get_engine")
    @patch("maestro.cli.init_db")
    def test_import_help_shows_all_flag(
        self,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        mock_load_config: Mock,
        tmp_path: Path,
    ) -> None:
        """--help on import should show --all, --tag, --artwork flags."""
        result = self.runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0
        assert "--all" in result.output
        assert "--tag" in result.output
        assert "--artwork" in result.output


class TestTopLevelUnifiedPipeline:
    """Tests that top-level ``maestro`` shows new options."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_maestro_help_shows_path_options(self) -> None:
        """--help on top-level maestro should show the new path and daemon options."""
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--download-path" in result.output
        assert "--library-path" in result.output
        assert "--daemon" in result.output

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.create_session")
    @patch("maestro.cli.get_engine")
    @patch("maestro.cli.init_db")
    def test_maestro_runs_pipeline_from_config_roots(
        self,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        mock_load_config: Mock,
        mock_create_session: Mock,
    ) -> None:
        """Running bare ``maestro`` should run the pipeline when roots exist in config."""
        from maestro.config import Config, RootEntry

        # Config has both download and library roots (no CLI paths provided)
        config = Config(
            download_roots=[
                RootEntry(path="/downloads/music", type="download", enabled=True),
            ],
            library_roots=[
                RootEntry(path="/library/music", type="library", enabled=True),
            ],
        )
        mock_load_config.return_value = config

        with patch("maestro.cli._run_pipeline_inline") as mock_pipeline:
            self.runner.invoke(cli, [])

            assert mock_pipeline.called, "bare maestro should run pipeline when config has roots"


class TestCliConfigDisplay:
    """Tests for 'maestro config' display output."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_config_shows_new_fields(self) -> None:
        """The config command should display the new config fields."""
        from unittest.mock import MagicMock

        from maestro.config import Config

        with (
            patch("maestro.cli.load_config") as mock_load,
            patch("maestro.cli.create_session") as mock_session,
            patch("maestro.cli.get_engine"),
            patch("maestro.cli.init_db"),
        ):
            mock_load.return_value = Config()
            mock_session.return_value = MagicMock()

            result = self.runner.invoke(cli, ["config"])
            assert "Dry run" in result.output
            assert "download album art" in result.output.lower() or "download_album_art" in result.output
            assert "download fanart" in result.output.lower() or "download_fanart" in result.output


class TestImportScanError:
    """Tests for scan error handling in the import command (lines 511-512)."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    @patch("maestro.cli.load_config")
    @patch("maestro.cli.get_engine")
    def test_import_scan_error_handled(
        self,
        mock_get_engine: Mock,
        mock_load_config: Mock,
        tmp_path: Path,
    ) -> None:
        """When scan_download_root raises, import should catch and report the error."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        dl_root.mkdir()
        config = Config(
            download_roots=[RootEntry(path=str(dl_root), type="download", enabled=True)],
            library_roots=[RootEntry(path=str(tmp_path / "library"), type="library", enabled=True)],
        )
        config.dry_run = False
        mock_load_config.return_value = config

        from maestro.db.core import create_session, get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)
        session = create_session(engine)
        mock_get_engine.return_value = engine

        with (
            patch("maestro.cli.create_session", return_value=session),
            patch("maestro.scanner.scan_download_root", side_effect=PermissionError("denied")),
            patch("maestro.identifier.identify_downloads"),
            patch("maestro.organizer.import_downloads"),
        ):
            result = self.runner.invoke(cli, ["import"])
            assert "Error scanning" in result.output


class TestTopLevelDaemon:
    """Tests for ``maestro --daemon`` (top-level daemon invocation, lines 274-281)."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_top_level_daemon_starts(self) -> None:
        """--daemon flag should start the daemon."""
        mock_daemon_instance = Mock()
        mock_daemon_class = Mock(return_value=mock_daemon_instance)

        with (
            patch("maestro.cli.load_config", return_value=Mock()),
            patch("maestro.daemon.Daemon", mock_daemon_class),
        ):
            result = self.runner.invoke(cli, ["--daemon"])
            assert result.exit_code == 0
            assert "Starting Maestro daemon" in result.output
            mock_daemon_class.assert_called_once()
            mock_daemon_instance.run.assert_called_once()


class TestRunPipelineInline:
    """Tests for _run_pipeline_inline, invoked via --download-path/--library-path
    (lines 56-129 and 283-297)."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    @patch("maestro.db.core.get_engine")
    @patch("maestro.db.core.init_db")
    @patch("maestro.db.core.create_session")
    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.organizer.import_downloads")
    @patch("maestro.cli.load_config")
    def test_pipeline_happy_path(
        self,
        mock_load_config: Mock,
        mock_import: Mock,
        mock_identify: Mock,
        mock_scan: Mock,
        mock_create_session: Mock,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        tmp_path: Path,
    ) -> None:
        """Full pipeline: scan, identify, import, tag, artwork all run."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        dl_root.mkdir()
        lib_root = tmp_path / "library"
        lib_root.mkdir()

        config = Config(
            download_roots=[RootEntry(path=str(dl_root), type="download", enabled=True)],
            library_roots=[RootEntry(path=str(lib_root), type="library", enabled=True)],
        )
        config.dry_run = False
        config.artwork.download_album_art = True
        config.artwork.download_fanart = False
        mock_load_config.return_value = config

        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_scan.return_value = {"created": 2, "skipped": 0}
        mock_identify.return_value = [Mock(), Mock()]
        mock_import.return_value = {
            "imported": 2,
            "skipped": 0,
            "replaced": 0,
            "errors": 0,
        }

        # Mock Track query to return tracks (triggers tag phase)
        mock_track = Mock()
        mock_track.file_path = str(tmp_path / "track.flac")
        mock_track.album = Mock()
        mock_track.album.artist = Mock()
        mock_track.album.artist.name = "Artist"
        mock_track.album.title = "Album"
        mock_track.album.year = 2024
        mock_track.album.genre = "Rock"
        mock_track.title = "Track"
        mock_track.track_number = 1

        # Mock Album query for artwork phase
        mock_album = Mock()
        mock_album.artist = Mock()
        mock_album.artist.name = "Artist"
        mock_album.title = "Album"
        mock_album.tracks = [mock_track]

        def query_side_effect(model: object) -> Mock:
            q = Mock()
            q.join.return_value = q
            name = getattr(model, "__name__", "")
            if name == "Track":
                q.all.return_value = [mock_track]
            elif name == "Album":
                q.join.return_value.all.return_value = [mock_album]
            else:
                q.all.return_value = []
            return q

        mock_session.query.side_effect = query_side_effect

        with (
            patch("maestro.cli._write_tags_for_tracks") as mock_write_tags,
            patch("maestro.cli._process_artwork_album") as mock_artwork,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--download-path",
                    str(dl_root),
                    "--library-path",
                    str(lib_root),
                ],
            )
            assert result.exit_code == 0, f"Output: {result.output}"
            assert "Scanning download root" in result.output
            assert mock_scan.called
            assert mock_identify.called
            assert mock_import.called
            assert mock_write_tags.called
            assert mock_artwork.called
            mock_session.close.assert_called_once()

    @patch("maestro.db.core.get_engine")
    @patch("maestro.db.core.init_db")
    @patch("maestro.db.core.create_session")
    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.organizer.import_downloads")
    @patch("maestro.cli.load_config")
    def test_pipeline_dry_run(
        self,
        mock_load_config: Mock,
        mock_import: Mock,
        mock_identify: Mock,
        mock_scan: Mock,
        mock_create_session: Mock,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        tmp_path: Path,
    ) -> None:
        """Dry-run pipeline: skips tag/artwork, shows dry-run output."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        dl_root.mkdir()
        lib_root = tmp_path / "library"
        lib_root.mkdir()

        config = Config(
            download_roots=[RootEntry(path=str(dl_root), type="download", enabled=True)],
            library_roots=[RootEntry(path=str(lib_root), type="library", enabled=True)],
        )
        config.dry_run = False
        mock_load_config.return_value = config

        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_scan.return_value = {"created": 0, "skipped": 0}
        mock_identify.return_value = []
        mock_import.return_value = {
            "imported": 0,
            "skipped": 0,
            "replaced": 0,
            "errors": 0,
            "actions": ["  /src/track.flac -> /dst/track.flac"],
        }

        def query_side_effect(model: object) -> Mock:
            q = Mock()
            q.join.return_value = q
            name = getattr(model, "__name__", "")
            if name == "Track":
                q.all.return_value = [Mock()]
            elif name == "Album":
                q.join.return_value.all.return_value = []
            else:
                q.all.return_value = []
            return q

        mock_session.query.side_effect = query_side_effect

        with (
            patch("maestro.cli._write_tags_for_tracks") as mock_write_tags,
            patch("maestro.cli._process_artwork_album") as mock_artwork,
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--download-path",
                    str(dl_root),
                    "--library-path",
                    str(lib_root),
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0, f"Output: {result.output}"
            assert "DRY RUN" in result.output
            assert "would import=0" in result.output
            # Tag and artwork should NOT run in dry-run mode
            assert not mock_write_tags.called
            assert not mock_artwork.called
            mock_session.close.assert_called_once()

    @patch("maestro.db.core.get_engine")
    @patch("maestro.db.core.init_db")
    @patch("maestro.db.core.create_session")
    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.organizer.import_downloads")
    @patch("maestro.cli.load_config")
    def test_pipeline_scan_error(
        self,
        mock_load_config: Mock,
        mock_import: Mock,
        mock_identify: Mock,
        mock_scan: Mock,
        mock_create_session: Mock,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        tmp_path: Path,
    ) -> None:
        """Error during scan should be caught and reported."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        dl_root.mkdir()

        config = Config(
            download_roots=[RootEntry(path=str(dl_root), type="download", enabled=True)],
            library_roots=[RootEntry(path=str(tmp_path / "library"), type="library", enabled=True)],
        )
        config.dry_run = False
        config.artwork.download_album_art = False
        config.artwork.download_fanart = False
        mock_load_config.return_value = config

        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_scan.side_effect = PermissionError("denied")
        mock_identify.return_value = []
        mock_import.return_value = {
            "imported": 0,
            "skipped": 0,
            "replaced": 0,
            "errors": 0,
        }

        mock_session.query.return_value.all.return_value = []

        with (
            patch("maestro.cli._write_tags_for_tracks"),
            patch("maestro.cli._process_artwork_album"),
        ):
            result = self.runner.invoke(
                cli,
                [
                    "--download-path",
                    str(dl_root),
                    "--library-path",
                    str(tmp_path / "library"),
                ],
            )
            assert result.exit_code == 0, f"Output: {result.output}"
            assert "Error scanning" in result.output
            mock_session.close.assert_called_once()

    @patch("maestro.db.core.get_engine")
    @patch("maestro.db.core.init_db")
    @patch("maestro.db.core.create_session")
    @patch("maestro.organizer.import_downloads")
    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.cli.load_config")
    def test_pipeline_no_download_roots(
        self,
        mock_load_config: Mock,
        mock_identify: Mock,
        mock_scan: Mock,
        mock_import: Mock,
        mock_create_session: Mock,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        tmp_path: Path,
    ) -> None:
        """With no download roots, scan/identify skipped; import still runs with --library-path."""
        from maestro.config import Config

        lib_root = tmp_path / "library"
        lib_root.mkdir()

        config = Config(
            download_roots=[],
            library_roots=[],
        )
        config.dry_run = False
        config.artwork.download_album_art = False
        config.artwork.download_fanart = False
        mock_load_config.return_value = config

        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_import.return_value = {
            "imported": 0,
            "skipped": 0,
            "replaced": 0,
            "errors": 0,
        }
        mock_session.query.return_value.all.return_value = []

        result = self.runner.invoke(
            cli,
            [
                "--library-path",
                str(lib_root),
            ],
        )
        assert result.exit_code == 0, f"Output: {result.output}"
        # No download roots → scan/identify not called
        assert not mock_scan.called
        assert not mock_identify.called
        # --library-path sets a library root → import runs
        assert mock_import.called
        mock_session.close.assert_called_once()

    @patch("maestro.db.core.get_engine")
    @patch("maestro.db.core.init_db")
    @patch("maestro.db.core.create_session")
    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.cli.load_config")
    def test_pipeline_no_library_roots(
        self,
        mock_load_config: Mock,
        mock_identify: Mock,
        mock_scan: Mock,
        mock_create_session: Mock,
        mock_init_db: Mock,
        mock_get_engine: Mock,
        tmp_path: Path,
    ) -> None:
        """With no library roots, import phase is skipped."""
        from maestro.config import Config, RootEntry

        dl_root = tmp_path / "downloads"
        dl_root.mkdir()

        config = Config(
            download_roots=[RootEntry(path=str(dl_root), type="download", enabled=True)],
            library_roots=[],
        )
        config.dry_run = False
        config.artwork.download_album_art = False
        config.artwork.download_fanart = False
        mock_load_config.return_value = config

        mock_session = Mock()
        mock_create_session.return_value = mock_session
        mock_scan.return_value = {"created": 0, "skipped": 0}
        mock_identify.return_value = []
        mock_session.query.return_value.all.return_value = []

        with patch("maestro.organizer.import_downloads") as mock_import:
            result = self.runner.invoke(
                cli,
                [
                    "--download-path",
                    str(dl_root),
                ],
            )
            assert result.exit_code == 0, f"Output: {result.output}"
            assert "Importing downloads" not in result.output
            assert not mock_import.called
            mock_session.close.assert_called_once()
