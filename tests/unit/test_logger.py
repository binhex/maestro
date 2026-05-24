"""Tests for maestro.logger."""

import os
import tempfile

from maestro.logger import create_logger


class TestCreateLogger:
    """Tests for create_logger()."""

    def test_returns_logger(self) -> None:
        """create_logger() should return a Loguru logger instance."""
        logger = create_logger(log_format="{message}")
        assert logger is not None
        # Loguru loggers have a .info() method
        assert hasattr(logger, "info")

    def test_logger_with_custom_level(self) -> None:
        """Should accept different log levels."""
        logger = create_logger(log_format="{message}", log_level="DEBUG")
        assert logger is not None
        assert hasattr(logger, "debug")

    def test_logger_with_log_path(self) -> None:
        """Should create a log file when log_path is provided."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name

        try:
            logger = create_logger(
                log_format="{message}",
                log_level="INFO",
                log_path=log_path,
            )
            assert logger is not None

            # Log a message
            logger.info("test message")

            # The log file should have been created
            assert os.path.exists(log_path)
            with open(log_path) as fh:
                content = fh.read()
            assert "test message" in content
        finally:
            if os.path.exists(log_path):
                os.unlink(log_path)

    def test_logger_creates_parent_directory(self) -> None:
        """Should create parent directories for the log path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "subdir", "nested", "test.log")

            logger = create_logger(
                log_format="{message}",
                log_level="INFO",
                log_path=log_path,
            )
            assert logger is not None

            # Log a message
            logger.info("nested dir test")

            # The parent directory and log file should exist
            assert os.path.exists(log_path)
            with open(log_path) as fh:
                content = fh.read()
            assert "nested dir test" in content

    def test_logger_multiple_calls(self) -> None:
        """Calling create_logger multiple times should not raise."""
        create_logger(log_format="{message}")
        # Second call should also work (remove() tolerates no handlers)
        create_logger(log_format="{message}", log_level="DEBUG")
