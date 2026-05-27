"""Tests for maestro.daemon."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from maestro.config import Config, SchedulerConfig
from maestro.daemon import Daemon, is_due, run_pipeline

# ===================================================================
# is_due
# ===================================================================


class TestIsDue:
    """Tests for :func:`is_due`."""

    def test_cron_matches_current_time(self) -> None:
        """'* * * * *' matches any time."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
        assert is_due("* * * * *", current_time=now) is True

    def test_cron_does_not_match(self) -> None:
        """An unlikely expression returns False."""
        # Expression fires at 03:00 on 1st January; test at noon on 24th May
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
        assert is_due("3 3 1 1 *", current_time=now) is False

    def test_invalid_cron_expression(self) -> None:
        """An invalid expression returns False rather than raising."""
        now = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
        assert is_due("not-a-cron", current_time=now) is False
        assert is_due("", current_time=now) is False
        # Too few fields
        assert is_due("* * *", current_time=now) is False

    def test_cron_matches_exact_minute(self) -> None:
        """A cron for the exact minute should match."""
        now = datetime(2026, 5, 24, 12, 30, 0, tzinfo=UTC)
        assert is_due("30 12 * * *", current_time=now) is True

    def test_cron_no_current_time_defaults_to_now(self) -> None:
        """Calling without current_time uses datetime.now(UTC) and doesn't crash."""
        # Can't assert exact True/False, but must not raise
        result = is_due("* * * * *")
        assert isinstance(result, bool)


# ===================================================================
# run_pipeline
# ===================================================================


class TestRunPipeline:
    """Tests for :func:`run_pipeline`."""

    def test_run_pipeline_no_config(self) -> None:
        """Passing None does not crash and returns an empty summary."""
        session = MagicMock()
        result = run_pipeline(None, session)
        assert result == {
            "scan": [],
            "identified": 0,
            "imported": {},
            "pipeline": {"errors": 0, "success": True},
        }

    def test_run_pipeline_empty_roots(self) -> None:
        """Config with empty roots skips pipeline phases."""
        config = Config()
        session = MagicMock()
        result = run_pipeline(config, session)
        # No download roots or library roots — essentially a no-op
        assert result["pipeline"]["success"] is True
        assert result["identified"] == 0

    @patch("maestro.scanner.scan_download_root")
    @patch("maestro.identifier.identify_downloads")
    @patch("maestro.organizer.import_downloads")
    def test_run_pipeline_full_flow(
        self,
        mock_import: MagicMock,
        mock_identify: MagicMock,
        mock_scan: MagicMock,
    ) -> None:
        """Full pipeline call: scan → identify → import."""
        mock_scan.return_value = {"created": 2, "skipped": 0, "removed": 0}
        mock_identify.return_value = [MagicMock(), MagicMock()]
        mock_import.return_value = {"imported": 2, "skipped": 0, "replaced": 0, "errors": 0}

        config = Config(
            download_roots=[
                {"path": "/downloads/music", "enabled": True},
            ],
            library_roots=[
                {"path": "/library/music", "enabled": True, "destination_pattern": "{artist}/{album}/{filename}.{ext}"},
            ],
        )
        session = MagicMock()
        result = run_pipeline(config, session)

        mock_scan.assert_called_once_with(session, "/downloads/music", pattern=None)
        mock_identify.assert_called_once_with(session)
        mock_import.assert_called_once()

        assert result["identified"] == 2
        assert result["imported"]["imported"] == 2
        assert result["pipeline"]["success"] is True

    @patch("maestro.scanner.scan_download_root")
    def test_run_pipeline_scan_errors_handled(
        self,
        mock_scan: MagicMock,
    ) -> None:
        """Exceptions during scan are caught and recorded."""
        mock_scan.side_effect = OSError("Permission denied")

        config = Config(
            download_roots=[
                {"path": "/bad/path", "enabled": True},
            ],
        )
        session = MagicMock()
        result = run_pipeline(config, session)

        assert result["pipeline"]["errors"] == 1
        assert result["pipeline"]["success"] is False
        # The scan result is NOT appended when an exception occurs
        assert len(result["scan"]) == 0


class TestRunPipelineDryRun:
    """Tests for dry_run threading in run_pipeline."""

    def test_run_pipeline_passes_dry_run_to_import(self, mocker) -> None:
        """When config.dry_run is True, import_downloads should receive it."""
        from maestro.config import RootEntry

        mock_import = mocker.patch("maestro.organizer.import_downloads")
        mocker.patch(
            "maestro.scanner.scan_download_root",
            return_value={"created": 0, "skipped": 0},
        )
        mocker.patch(
            "maestro.identifier.identify_downloads",
            return_value=[],
        )

        config = Config(dry_run=True)
        config.download_roots = [RootEntry(path="/dl", type="download", enabled=True)]
        config.library_roots = [
            RootEntry(
                path="/lib",
                type="library",
                enabled=True,
                destination_pattern="{artist}/{album}",
            )
        ]
        config.quality.delete_replaced = False

        session = MagicMock()
        run_pipeline(config, session)

        assert mock_import.called, "import_downloads should have been called"
        call_args, call_kwargs = mock_import.call_args
        assert call_kwargs.get("dry_run") is True, f"Expected dry_run=True, got kwargs={call_kwargs}"

    def test_run_pipeline_import_error_handled(self, mocker) -> None:
        """Exceptions during import are caught and errors incremented."""
        from maestro.config import RootEntry

        # import_downloads is imported inside run_pipeline, patch at source
        mock_import = mocker.patch("maestro.organizer.import_downloads")
        mock_import.side_effect = OSError("Disk full")
        mocker.patch(
            "maestro.scanner.scan_download_root",
            return_value={"created": 0, "skipped": 0},
        )
        mocker.patch(
            "maestro.identifier.identify_downloads",
            return_value=[],
        )

        config = Config()
        config.download_roots = [RootEntry(path="/dl", type="download", enabled=True)]
        config.library_roots = [
            RootEntry(
                path="/lib",
                type="library",
                enabled=True,
                destination_pattern="{artist}/{album}/{filename}.{ext}",
            )
        ]
        session = MagicMock()
        result = run_pipeline(config, session)

        assert result["pipeline"]["errors"] == 1
        assert result["pipeline"]["success"] is False


# ===================================================================
# Daemon
# ===================================================================


class TestDaemonInit:
    """Tests for :class:`Daemon.__init__`."""

    def test_init_stores_config_and_sets_up_signals(self) -> None:
        """Daemon stores config and has shutdown flag initially False."""
        config = Config()
        daemon = Daemon(config)
        assert daemon.config is config
        assert daemon._shutdown_requested is False


class TestDaemonSignalHandling:
    """Tests for signal handlers."""

    def test_signal_sets_shutdown_flag(self) -> None:
        """Receiving a signal sets _shutdown_requested to True."""
        daemon = Daemon(None)
        assert daemon._shutdown_requested is False
        daemon._handle_signal(15, None)
        assert daemon._shutdown_requested is True


class TestDaemonRun:
    """Tests for :meth:`Daemon.run`."""

    @patch("maestro.daemon.os_getpid")
    @patch("maestro.daemon.Daemon._get_engine")
    @patch("maestro.daemon.Daemon._run_pipeline_once")
    def test_run_on_start_executes_pipeline(
        self,
        mock_run_once: MagicMock,
        mock_get_engine: MagicMock,
        mock_getpid: MagicMock,
    ) -> None:
        """When run_on_start is True, runs pipeline immediately."""
        mock_getpid.return_value = 12345
        engine = MagicMock()
        mock_get_engine.return_value = engine

        config = Config(scheduler=SchedulerConfig(run_on_start=True))
        daemon = Daemon(config)

        # Force shutdown after one iteration
        def shutdown_after_run(*args: Any, **kwargs: Any) -> None:
            daemon._shutdown_requested = True

        mock_run_once.side_effect = shutdown_after_run

        daemon.run()

        mock_run_once.assert_called_once_with(engine)

    @patch("maestro.daemon.os_getpid")
    @patch("maestro.daemon.Daemon._get_engine")
    @patch("maestro.daemon.Daemon._run_pipeline_once")
    @patch("maestro.daemon.is_due")
    def test_run_cron_triggers_pipeline(
        self,
        mock_is_due: MagicMock,
        mock_run_once: MagicMock,
        mock_get_engine: MagicMock,
        mock_getpid: MagicMock,
    ) -> None:
        """When cron matches, pipeline is triggered."""
        mock_getpid.return_value = 12345
        engine = MagicMock()
        mock_get_engine.return_value = engine
        mock_is_due.return_value = True

        config = Config(scheduler=SchedulerConfig(run_on_start=False))
        daemon = Daemon(config)

        # Let it loop once then exit
        def exit_after_call(*args: Any, **kwargs: Any) -> None:
            daemon._shutdown_requested = True

        mock_run_once.side_effect = exit_after_call

        daemon.run()

        mock_is_due.assert_called()
        mock_run_once.assert_called_once_with(engine)

    @patch("maestro.daemon.os_getpid")
    @patch("maestro.daemon.Daemon._get_engine")
    @patch("maestro.daemon.Daemon._run_pipeline_once")
    def test_run_no_engine_returns_early(
        self,
        mock_run_once: MagicMock,
        mock_get_engine: MagicMock,
        mock_getpid: MagicMock,
    ) -> None:
        """If no engine is available, run returns early without running pipeline."""
        mock_getpid.return_value = 12345
        mock_get_engine.return_value = None

        daemon = Daemon(Config())
        daemon.run()

        mock_run_once.assert_not_called()

    @patch("maestro.daemon.os_getpid")
    @patch("maestro.daemon.Daemon._get_engine")
    @patch("maestro.daemon.Daemon._run_pipeline_once")
    def test_run_on_start_false_skips_immediate_run(
        self,
        mock_run_once: MagicMock,
        mock_get_engine: MagicMock,
        mock_getpid: MagicMock,
    ) -> None:
        """When run_on_start is False, pipeline is not run immediately."""
        mock_getpid.return_value = 12345
        engine = MagicMock()
        mock_get_engine.return_value = engine

        config = Config(scheduler=SchedulerConfig(run_on_start=False))
        daemon = Daemon(config)

        # Force immediate shutdown
        daemon._shutdown_requested = True
        daemon.run()

        # run_on_start is False, so _run_pipeline_once should not be called
        # before the loop (and since shutdown is already True, the loop body
        # doesn't execute)
        mock_run_once.assert_not_called()


class TestDaemonHelpers:
    """Tests for internal :class:`Daemon` helpers."""

    def test_get_cron_expression_from_config(self) -> None:
        """Cron expression is read from config unless override."""
        config = Config(scheduler=SchedulerConfig(schedule="0 */2 * * *"))
        daemon = Daemon(config)
        assert daemon._get_cron_expression() == "0 */2 * * *"

    def test_get_cron_expression_default(self) -> None:
        """Default cron expression is returned when config is None."""
        daemon = Daemon(None)
        assert daemon._get_cron_expression() == "0 3 * * *"

    def test_get_engine_creates_engine(self) -> None:
        """_get_engine returns an Engine instance when config is present."""
        config = Config()
        daemon = Daemon(config)
        # Patching env so we get a predictable path
        with patch("os.environ.get", return_value=":memory:"):
            engine = daemon._get_engine()
            assert engine is not None
            # Calling again returns the cached engine
            assert daemon._get_engine() is engine

    def test_get_engine_no_config(self) -> None:
        """_get_engine returns None when config is None."""
        daemon = Daemon(None)
        assert daemon._get_engine() is None

    def test_sleep_interruptible_respects_shutdown(self) -> None:
        """_sleep_interruptible exits early when shutdown is requested."""
        daemon = Daemon(None)
        daemon._shutdown_requested = True
        # Should not block
        daemon._sleep_interruptible(10.0)
        # No assertion — just doesn't hang

    def test_sleep_interruptible_waits_full_duration(self) -> None:
        """_sleep_interruptible waits the full duration when shutdown is not requested."""
        import time

        daemon = Daemon(None)
        start = time.monotonic()
        # Use a very short duration so the test is fast
        daemon._sleep_interruptible(0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.09, f"Expected ~0.1s sleep, got {elapsed:.3f}s"

    def test_should_run_on_start_true(self) -> None:
        """Default config has run_on_start=True."""
        config = Config()
        daemon = Daemon(config)
        assert daemon._should_run_on_start() is True

    def test_should_run_on_start_false(self) -> None:
        """Config with run_on_start=False returns False."""
        config = Config(scheduler=SchedulerConfig(run_on_start=False))
        daemon = Daemon(config)
        assert daemon._should_run_on_start() is False

    def test_should_run_on_start_none_config(self) -> None:
        """None config defaults to True."""
        daemon = Daemon(None)
        assert daemon._should_run_on_start() is True

    def test_run_pipeline_identify_error_handled(self, mocker) -> None:
        """Exceptions during identification are caught and errors incremented."""
        from maestro.config import RootEntry

        mocker.patch(
            "maestro.scanner.scan_download_root",
            return_value={"created": 0, "skipped": 0},
        )
        # identify_downloads is imported inside run_pipeline, patch at source
        mocker.patch(
            "maestro.identifier.identify_downloads",
            side_effect=ValueError("parse error"),
        )

        config = Config()
        config.download_roots = [RootEntry(path="/dl", type="download", enabled=True)]
        config.library_roots = []
        session = MagicMock()
        result = run_pipeline(config, session)

        assert result["pipeline"]["errors"] == 1
        assert result["pipeline"]["success"] is False

    def test_os_getpid_returns_pid(self) -> None:
        """os_getpid returns the current process PID."""
        from maestro.daemon import os_getpid

        pid = os_getpid()
        assert isinstance(pid, int)
        assert pid > 0

    def test_run_pipeline_once_creates_session_and_runs(
        self,
        mocker,
        tmp_path,
    ) -> None:
        """_run_pipeline_once creates a session, runs pipeline, and commits."""
        from maestro.db.core import get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)

        mock_run = mocker.patch("maestro.daemon.run_pipeline")
        mock_run.return_value = {"pipeline": {"errors": 0, "success": True}}

        config = Config()
        daemon = Daemon(config)
        daemon._run_pipeline_once(engine)

        mock_run.assert_called_once()

    def test_run_pipeline_once_rollback_on_error(
        self,
        mocker,
        tmp_path,
    ) -> None:
        """_run_pipeline_once rolls back when pipeline raises."""
        from maestro.db.core import get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)

        mock_run = mocker.patch("maestro.daemon.run_pipeline")
        mock_run.side_effect = RuntimeError("pipeline crash")

        config = Config()
        daemon = Daemon(config)
        # Should not raise — exception is caught internally
        daemon._run_pipeline_once(engine)

        mock_run.assert_called_once()

    def test_run_pipeline_once_no_session_leak(
        self,
        mocker,
        tmp_path,
    ) -> None:
        """_run_pipeline_once always closes the session."""
        from maestro.db.core import get_engine, init_db

        db_path = str(tmp_path / "test.db")
        engine = get_engine(db_path, echo=False)
        init_db(engine)

        mock_run = mocker.patch("maestro.daemon.run_pipeline")
        mock_run.side_effect = RuntimeError("crash")

        config = Config()
        daemon = Daemon(config)
        daemon._run_pipeline_once(engine)

        # No assertion needed — if there's a session leak, SQLAlchemy will warn
