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
