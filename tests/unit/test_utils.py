"""Tests for maestro.utils."""

from pathlib import Path

from maestro.utils import get_project_root


class TestGetProjectRoot:
    """Tests for get_project_root()."""

    def test_returns_path(self) -> None:
        """get_project_root() should return a Path instance."""
        root = get_project_root()
        assert isinstance(root, Path)

    def test_returns_absolute_path(self) -> None:
        """get_project_root() should return an absolute path."""
        root = get_project_root()
        assert root.is_absolute()

    def test_points_to_project_root(self) -> None:
        """get_project_root() should point to the project root
        (parent of the src directory)."""
        root = get_project_root()
        assert (root / "src").is_dir()
        assert (root / "pyproject.toml").exists()

    def test_parent_of_src_maestro(self) -> None:
        """Verify the root contains the expected source files."""
        root = get_project_root()
        assert (root / "src" / "maestro" / "utils.py").exists()
