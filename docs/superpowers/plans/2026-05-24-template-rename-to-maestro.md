# Maestro: Template Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the generic `AppName`/`appname` Python template to `maestro` — a music organizer CLI project — updating all package names, imports, paths, configs, and documentation.

**Architecture:** Rename-in-place: move the package directory from `src/appname/` to `src/maestro/`, update every string and import reference throughout the codebase, then update pyproject.toml metadata and README to reflect the new project identity.

**Tech Stack:** Python 3.12, `uv`, `setuptools`, `click`, `loguru`, `ruff` + `mypy` (linting), `pytest` (testing)

---

### Task 1: Move package directory and update pyproject.toml

**Files:**
- Create: `src/maestro/` (directory)
- Delete: `src/appname/` (directory — rename via move)
- Modify: `pyproject.toml`

- [ ] **Step 1: Move the package directory**

Run:
```bash
git mv src/appname src/maestro
```

This renames the Python package directory from `appname` to `maestro` while keeping git aware of the history.

- [ ] **Step 2: Update pyproject.toml metadata**

Edit `pyproject.toml`:

Changes:
- `name = "AppName"` → `name = "maestro"`
- `description = "Automated tool"` → `description = "Music organizer"`
- `keywords = ["movie", "imdb", "automation", "torrent"]` → `keywords = ["music", "organizer", "file-management", "automation"]`
- Remove `classifiers` that reference "Alpha" if desired, or keep them (acceptable for early stage)
- `[project.scripts]` `AppName = "cli.main:cli"` → `maestro = "maestro.cli:cli"`
- `known-first-party = ["AppName"]` → `known-first-party = ["maestro"]`
- `addopts = """... --cov=src/AppName ..."""` → `--cov=src/maestro`

Exact `pyproject.toml` after changes:

```toml
[build-system]
requires = ["setuptools>=65.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "maestro"
version = "1.0.0"
description = "Music organizer"
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
authors = [
    {name = "dev", email = "megalith01@gmail.com"}
]
keywords = ["music", "organizer", "file-management", "automation"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    "apscheduler",
    "backoff",
    "click",
    "loguru",
    "daemonize",
    "apprise",
    "pyyaml",
    "requests",
    "sqlalchemy",
    "urllib3",
]

[project.scripts]
maestro = "maestro.cli:cli"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
"*" = ["py.typed"]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # Pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "SIM", # flake8-simplify
    "TCH", # flake8-type-checking
]

ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # unused imports in __init__.py
"tests/*" = ["S101"]      # assert usage in tests

[tool.ruff.lint.isort]
known-first-party = ["maestro"]

[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
strict_equality = true
mypy_path = "src"

# Relax for tests
[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false

[tool.pytest.ini_options]
testpaths = ["tests"]
minversion = "7.0"
addopts = """
    -ra
    --strict-markers
    --strict-config
    --cov=src/maestro
    --cov-report=term-missing
    --cov-report=html
    --cov-report=xml
"""
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests",
    "unit: marks tests as unit tests",
]

[tool.coverage.run]
source = ["src"]
omit = ["tests/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "@abstractmethod",
]

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-cov>=7.1.0",
    "pytest-mock>=3.15.1",
    "pytest-crap @ git+https://github.com/binhex/pytest-crap.git@v0.3.1",
    "types-requests>=2.31.0",
    "types-pyyaml>=6.0.0",
    "pre-commit"
]
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/maestro/ src/appname/
git commit -m "chore: rename package from appname to maestro"
```

---

### Task 2: Update CLI module (`src/maestro/cli.py`)

**Files:**
- Modify: `src/maestro/cli.py`

- [ ] **Step 1: Rewrite the CLI module**

Replace the entire file content:

```python
"""Command-line interface for Maestro."""

from importlib.metadata import PackageNotFoundError, version

import click

from maestro.logger import create_logger
from maestro.utils import get_project_root

try:
    _VERSION = version("maestro")
except PackageNotFoundError:
    _VERSION = "unknown"

# Compute default database path (project_root/db/maestro.db)
_PROJECT_ROOT = get_project_root()
_DEFAULT_DB_PATH = f"{_PROJECT_ROOT}/db/maestro.db"
_DEFAULT_LOGS_PATH = f"{_PROJECT_ROOT}/logs/maestro.log"


@click.command()
@click.option(
    "--database-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=_DEFAULT_DB_PATH,
    show_default=True,
    metavar="<path>",
    help="Path to SQLite database file for tracking music library state.",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"], case_sensitive=False),
    metavar="<level>",
    show_default=True,
    help="Logging level for console output",
)
@click.option(
    "--log-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=_DEFAULT_LOGS_PATH,
    show_default=True,
    metavar="<path>",
    help="Path to log file for tracking application events.",
)

@click.version_option(version=_VERSION, prog_name="maestro")
def cli(
    database_path: str | None,
    log_level: str,
    log_path: str,
) -> None:
    """Maestro - Organise and manage your music library.

    Maestro scans your music directories, analyses metadata, and helps
    organise your collection by fixing tags, renaming files, and
    detecting duplicates.
    """

    # Logger format for consistent output styling
    log_format = "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"

    logger = create_logger(log_format=log_format, log_level=log_level, log_path=log_path)

    logger.info("WIP: CLI logic not yet implemented.")

if __name__ == "__main__":
    cli()
```

Key changes:
- Docstring: `AppName` → `Maestro`
- Imports: `from appname.` → `from maestro.`
- `version("AppName")` → `version("maestro")`
- `_DEFAULT_DB_PATH` uses `maestro.db` instead of `AppName.db`
- `_DEFAULT_LOGS_PATH` uses `maestro.log` instead of `trimarr.log`
- `prog_name="AppName"` → `prog_name="maestro"`
- CLI docstring describes Maestro as a music organiser instead of lorem ipsum
- `--database-path` help text updated to reflect music library context
- Added newlines between decorators for proper formatting (two decorators were on one line)

- [ ] **Step 2: Commit**

```bash
git add src/maestro/cli.py
git commit -m "chore: update CLI module for maestro"
```

---

### Task 3: Update logger module (`src/maestro/logger.py`)

**Files:**
- Modify: `src/maestro/logger.py`

- [ ] **Step 1: Fix module docstring**

Edit line 1:

```python
"""Logging utilities for maestro."""
```

(Was: `"""Logging utilities for trimarr."""` — leftover from previous template use.)

- [ ] **Step 2: Commit**

```bash
git add src/maestro/logger.py
git commit -m "chore: fix logger module docstring for maestro"
```

---

### Task 4: Rewrite README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write new README**

Replace the entire file:

```markdown
# Maestro

Organise and manage your music library.

This software is under *HEAVY* development right now, expect lack of documentation, major bugs and missing functionality.

## Description

Maestro scans your music directories, analyses metadata, and helps organise
your collection by fixing tags, renaming files, and detecting duplicates.

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [Astral uv](https://github.com/astral-sh/uv#installation)

## Quick start

### Installation

```bash
git clone https://github.com/binhex/maestro
cd maestro
uv venv --quiet
uv sync
```

### Usage

```bash
maestro --help
```

## Options

WIP

## Development

```bash
git clone https://github.com/binhex/maestro
cd maestro
uv venv --quiet
uv sync --extra dev
```

If you wish to perform linting on all files before committing (PR will not be
accepted if it does not pass all linting) then run `pre-commit run --all-files`.

## FAQ

WIP

___
If you appreciate my work, then please consider buying me a beer  :D

[![PayPal donation](https://www.paypal.com/en_US/i/btn/btn_donate_SM.gif)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=MM5E27UX6AUU4)
```

Key changes:
- Title: `AppName` → `Maestro`
- Description: from "WIP" to actual music organiser description
- Repo URL: `binhex/AppName` → `binhex/maestro`
- Commands: `AppName --help` → `maestro --help`
- Fixed typo: "nt be" → "not be"

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for maestro music organiser"
```

---

### Task 5: Verify everything works

**Files:** (none — verification only)

- [ ] **Step 1: Verify package can be imported**

Run:
```bash
cd /data/maestro
uv run python -c "import maestro; print('Package OK')"
```

Expected:
```
Package OK
```

- [ ] **Step 2: Verify CLI runs**

Run:
```bash
uv run maestro --help
```

Expected output showing the Maestro CLI with `--database-path`, `--log-level`, `--log-path`, `--version`, `--help` options.

- [ ] **Step 3: Run pre-commit on all files**

```bash
uv run pre-commit run --all-files
```

Expected: All hooks pass (or only pre-existing issues not related to our changes).

- [ ] **Step 4: Run linting**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: No errors.

- [ ] **Step 5: Run type checking**

```bash
uv run mypy .
```

Expected: No type errors.

- [ ] **Step 6: Commit verification pass**

If any fixes were made during verification:

```bash
git add -A
git commit -m "chore: fix lint and type issues after rename"
```

- [ ] **Step 7: Make initial project commit (if no commits exist yet)**

Since this is a fresh repo with no commits, verify the commit history:

```bash
git log --oneline
```

If there are no commits yet despite the earlier steps (because `main` has no commits), we need an initial commit that the subsequent commits can build on. Run:

```bash
git add -A
git commit -m "feat: initial scaffold for Maestro music organiser"
```
