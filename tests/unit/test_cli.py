"""Tests for maestro.cli."""

import importlib
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from click.testing import CliRunner

import maestro.cli
from maestro.cli import cli


class TestCli:
    """Tests for the Maestro CLI."""

    def setup_method(self) -> None:
        self.runner = CliRunner()

    def test_help_output(self) -> None:
        """--help should display usage information."""
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Maestro" in result.output
        assert "--database-path" in result.output
        assert "--log-level" in result.output
        assert "--log-path" in result.output
        assert "--help" in result.output

    def test_version_output(self) -> None:
        """--version should display version information."""
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "maestro" in result.output

    def test_default_run(self) -> None:
        """Running the CLI with no arguments should succeed."""
        result = self.runner.invoke(cli)
        # Exit code 0 because there's no error, just WIP message
        assert result.exit_code == 0
        assert "WIP: CLI logic not yet implemented." in result.output

    def test_custom_log_level(self) -> None:
        """--log-level DEBUG should be accepted."""
        result = self.runner.invoke(cli, ["--log-level", "DEBUG"])
        assert result.exit_code == 0

    def test_custom_database_path(self) -> None:
        """--database-path should accept a custom path."""
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, ["--database-path", "/tmp/test_maestro.db"])
            # The path doesn't need to exist up front — just passed as arg
            assert result.exit_code == 0

    def test_invalid_log_level(self) -> None:
        """An invalid --log-level should exit with error."""
        result = self.runner.invoke(cli, ["--log-level", "INVALID"])
        assert result.exit_code != 0
        assert "INVALID" in result.output or "Error" in result.output

    def test_version_fallback_on_package_not_found(self) -> None:
        """When the package isn't installed, _VERSION should fall back to 'unknown'."""
        with patch("importlib.metadata.version", side_effect=PackageNotFoundError):
            importlib.reload(maestro.cli)
            assert maestro.cli._VERSION == "unknown"
        # Reload again to restore normal state
        importlib.reload(maestro.cli)
        assert maestro.cli._VERSION != "unknown"
