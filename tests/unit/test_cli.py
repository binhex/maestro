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


class TestImport:
    """Tests for the ``import`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_import_no_library_roots(self) -> None:
        """Import with no library roots should show message."""
        mock_config = Mock()
        mock_config.library_roots = []
        mock_setup = Mock(return_value=(mock_config, Mock(), Mock()))

        with patch("maestro.cli._setup", mock_setup):
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
        ):
            result = self.runner.invoke(cli, ["import"])
            assert result.exit_code == 0
            assert "imported=3" in result.output
            mock_import_dl.assert_called_once()
            assert mock_session.close.called


class TestTag:
    """Tests for the ``tag`` subcommand."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_tag_no_tracks(self) -> None:
        """Tag with no tracks should show message."""
        mock_session = Mock()
        mock_session.query.return_value.join.return_value.join.return_value.all.return_value = []
        mock_setup = Mock(return_value=(Mock(), Mock(), mock_session))

        with patch("maestro.cli._setup", mock_setup):
            result = self.runner.invoke(cli, ["tag"])
            assert result.exit_code == 0
            assert "No tracks found to tag" in result.output

    def test_tag_clear_flag(self) -> None:
        """Tag --clear should call clear_tags."""
        mock_track = Mock()
        mock_track.file_path = "/music/track.flac"
        mock_track.album = None

        mock_session = Mock()
        mock_session.query.return_value.join.return_value.join.return_value.all.return_value = [
            mock_track,
        ]
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
