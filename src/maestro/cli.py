"""Command-line interface for Maestro."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING

import click

from maestro.config import Config, load_config
from maestro.db.core import create_session, get_engine, init_db
from maestro.logger import create_logger
from maestro.utils import get_project_root

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

try:
    _VERSION = version("maestro")
except PackageNotFoundError:
    _VERSION = "unknown"

_PROJECT_ROOT = get_project_root()
_DEFAULT_DB_PATH = f"{_PROJECT_ROOT}/db/maestro.db"
_DEFAULT_LOGS_PATH = f"{_PROJECT_ROOT}/logs/maestro.log"
_DEFAULT_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _lastfm_api_key(config: Config) -> str | None:
    """Return the Last.fm API key from environment or config.

    Priority: ``LASTFM_API_KEY`` environment variable.
    """
    del config  # reserved for future config-based key lookup
    return os.environ.get("LASTFM_API_KEY")


def _setup(
    ctx: click.Context,
    database_path: str | None = None,
    config_path: str | None = None,
) -> tuple[Config, Engine, Session]:
    """Load config, initialise logger, create engine and session.

    Args:
        ctx: Click context — group-level params are read from
            ``ctx.parent.params``.
        database_path: Override path to the SQLite database.  Falls back to
            ``MAESTRO_DB`` env var, then the default project path.
        config_path: Override path to the YAML config file.  ``None`` means
            auto-detect via :func:`~maestro.config.load_config`.

    Returns:
        Tuple of ``(config, engine, session)``.
    """
    config = load_config(config_path)

    if ctx.parent is None:
        raise click.UsageError("_setup must be called from a subcommand")
    log_level = ctx.parent.params.get("log_level", "INFO")
    log_path = ctx.parent.params.get("log_path") or _DEFAULT_LOGS_PATH
    database_path = database_path or ctx.parent.params.get("database_path")
    if not database_path:
        database_path = os.environ.get("MAESTRO_DB") or _DEFAULT_DB_PATH

    create_logger(
        log_format=_DEFAULT_LOG_FORMAT,
        log_level=log_level,
        log_path=log_path,
    )

    engine = get_engine(database_path)
    init_db(engine)
    session = create_session(engine)

    return config, engine, session


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group(invoke_without_command=True)
@click.option(
    "--database-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=None,
    metavar="<path>",
    help="Path to SQLite database file. Falls back to MAESTRO_DB env var or a default path under the project root.",
)
@click.option(
    "--config",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=None,
    metavar="<path>",
    help="Path to YAML configuration file.",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(
        ["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"],
        case_sensitive=False,
    ),
    metavar="<level>",
    show_default=True,
    help="Logging level for console output",
)
@click.option(
    "--log-path",
    type=click.Path(file_okay=True, dir_okay=False, resolve_path=True),
    required=False,
    default=None,
    metavar="<path>",
    help="Path to log file. Falls back to a default path under the project root.",
)
@click.pass_context
@click.version_option(version=_VERSION, prog_name="maestro")
def cli(ctx: click.Context, **kwargs: object) -> None:
    """Maestro - Organise and manage your music library.

    Maestro scans your music directories, analyses metadata, and helps
    organise your collection by fixing tags, renaming files, and
    detecting duplicates.
    """
    # All options are consumed by subcommands via _setup(); the **kwargs
    # catch-all is deliberate to avoid unused-argument warnings.
    del kwargs
    if ctx.invoked_subcommand is None:
        # Ensure default config file is created on first invocation
        load_config()
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "roots",
    nargs=-1,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
)
@click.pass_context
def scan(ctx: click.Context, roots: tuple[str, ...]) -> None:
    """Scan download directories for new music files.

    If ROOTS are provided, scan those directories.  Otherwise use the
    download roots from the configuration file.
    """
    from maestro.scanner import scan_download_root

    config, _engine, session = _setup(ctx)
    try:
        paths_to_scan = list(roots) if roots else [r.path for r in config.download_roots if r.enabled]

        if not paths_to_scan:
            click.echo("No download roots to scan.")
            return

        for root in paths_to_scan:
            click.echo(f"Scanning {root}...")
            result = scan_download_root(session, root)
            click.echo(
                f"  Result: created={result['created']} skipped={result['skipped']}",
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# identify
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def identify(ctx: click.Context) -> None:
    """Identify metadata for newly discovered downloads."""
    from maestro.identifier import identify_downloads

    _config, _engine, session = _setup(ctx)
    try:
        click.echo("Identifying downloads...")
        downloads = identify_downloads(session)
        click.echo(f"Identified {len(downloads)} download(s).")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def check(ctx: click.Context) -> None:
    """Show library statistics and quality information."""
    from maestro.db.models import Album, Artist, Download, Track
    from maestro.quality import get_quality_tier

    _config, _engine, session = _setup(ctx)
    try:
        artist_count = session.query(Artist).count()
        album_count = session.query(Album).count()
        track_count = session.query(Track).count()
        download_count = session.query(Download).count()
        new_dl = session.query(Download).filter(Download.status == "new").count()
        identified_dl = session.query(Download).filter(Download.status == "identified").count()
        imported_dl = session.query(Download).filter(Download.status == "imported").count()
        error_dl = session.query(Download).filter(Download.status == "error").count()

        click.echo("Maestro Library Status")
        click.echo(f"  Artists:     {artist_count}")
        click.echo(f"  Albums:      {album_count}")
        click.echo(f"  Tracks:      {track_count}")
        click.echo(f"  Downloads:   {download_count}")
        click.echo(f"    - new:         {new_dl}")
        click.echo(f"    - identified:  {identified_dl}")
        click.echo(f"    - imported:    {imported_dl}")
        click.echo(f"    - errors:      {error_dl}")

        if track_count:
            quality_counts: dict[str, int] = {}
            for track in session.query(Track).all():
                tier = get_quality_tier(
                    track.format or "unknown",
                    track.bitrate,
                )
                label = f"Tier {tier}"
                quality_counts[label] = quality_counts.get(label, 0) + 1
            click.echo("  Quality tiers:")
            for label, count in sorted(quality_counts.items()):
                click.echo(f"    {label}: {count} tracks")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


@cli.command(name="import")
@click.pass_context
def import_(ctx: click.Context) -> None:
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

        click.echo(f"Importing downloads into {lib_root.path}...")
        result = import_downloads(
            session=session,
            destination_root=lib_root.path,
            destination_pattern=dest_pattern,
            move=True,
            delete_replaced=config.quality.delete_replaced,
        )
        click.echo(
            f"  imported={result['imported']} "
            f"skipped={result['skipped']} "
            f"replaced={result['replaced']} "
            f"errors={result['errors']}",
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--clear",
    is_flag=True,
    default=False,
    help="Clear all tags instead of writing them.",
)
@click.pass_context
def tag(ctx: click.Context, clear: bool) -> None:
    """Write or clear metadata tags on imported tracks."""
    from maestro.db.models import Album, Artist, Track
    from maestro.tagger import clear_tags, write_tags

    _config, _engine, session = _setup(ctx)
    try:
        tracks = (
            session.query(Track)
            .join(Album, Track.album_id == Album.id, isouter=True)
            .join(Artist, Album.artist_id == Artist.id, isouter=True)
            .all()
        )

        if not tracks:
            click.echo("No tracks found to tag.")
            return

        if clear:
            click.echo(f"Clearing tags on {len(tracks)} track(s)...")
            for track in tracks:
                if clear_tags(track.file_path):
                    click.echo(f"  Cleared: {track.file_path}")
            return

        click.echo(f"Writing tags on {len(tracks)} track(s)...")
        for track in tracks:
            artist_name = track.album.artist.name if track.album and track.album.artist else None
            album_title = track.album.title if track.album else None
            year = track.album.year if track.album else None
            genre = track.album.genre if track.album else None
            ok = write_tags(
                file_path=track.file_path,
                artist=artist_name,
                album=album_title,
                title=track.title,
                track_number=track.track_number,
                year=year,
                genre=genre,
            )
            if ok:
                click.echo(f"  Tagged: {track.file_path}")
            else:
                click.echo(f"  Failed: {track.file_path}")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# artwork
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def artwork(ctx: click.Context) -> None:
    """Download album art and fanart for all albums in the library."""
    from maestro.artwork import download_artwork_for_album
    from maestro.db.models import Album, Artist

    config, _engine, session = _setup(ctx)
    try:
        albums = session.query(Album).join(Artist, Album.artist_id == Artist.id).all()

        if not albums:
            click.echo("No albums found to fetch artwork for.")
            return

        api_key = _lastfm_api_key(config)
        sources = config.artwork.sources

        for album in albums:
            if not album.artist:
                continue
            # Determine album directory from the first track's location
            if album.tracks:
                album_dir = str(Path(album.tracks[0].file_path).parent)
            else:
                click.echo(
                    f"Skipping '{album.title}' — no tracks in database.",
                )
                continue

            click.echo(
                f"Fetching artwork for '{album.artist.name} — {album.title}'...",
            )
            result = download_artwork_for_album(
                album_dir=album_dir,
                artist=album.artist.name,
                album=album.title,
                album_art_filename=config.artwork.album_art,
                fanart_filename=config.artwork.fanart,
                lastfm_api_key=api_key,
                sources=sources,
            )
            click.echo(
                f"  Album art: {'✓' if result['album_art'] else '✗'}",
            )
            click.echo(
                f"  Fanart:    {'✓' if result['fanart'] else '✗'}",
            )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# daemon
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Run the Maestro daemon (scheduled pipeline execution)."""
    from maestro.daemon import Daemon

    config, _engine, session = _setup(ctx)
    session.close()

    click.echo("Starting Maestro daemon...")
    db_path = ctx.obj.get("database_path") if ctx.obj else None
    daemon_instance = Daemon(config, db_path=db_path)
    daemon_instance.run()


# ---------------------------------------------------------------------------
# config (display)
# ---------------------------------------------------------------------------


@cli.command(name="config")
@click.pass_context
def show_config(ctx: click.Context) -> None:
    """Display the current configuration."""
    config, _engine, session = _setup(ctx)
    session.close()

    click.echo("Maestro Configuration")
    click.echo(f"  Library roots: {len(config.library_roots)}")
    for root in config.library_roots:
        click.echo(f"    - {root.path} (enabled={root.enabled})")
    click.echo(f"  Download roots: {len(config.download_roots)}")
    for root in config.download_roots:
        click.echo(f"    - {root.path} (enabled={root.enabled})")
    click.echo(
        f"  Quality min acceptable: {config.quality.min_acceptable}",
    )
    click.echo(
        f"  Quality delete replaced: {config.quality.delete_replaced}",
    )
    click.echo(f"  Artwork album art: {config.artwork.album_art}")
    click.echo(f"  Artwork fanart: {config.artwork.fanart}")
    click.echo(
        f"  Artwork skip if exists: {config.artwork.skip_if_exists}",
    )
    click.echo(f"  Artwork sources: {config.artwork.sources}")
    click.echo(f"  Scheduler schedule: {config.scheduler.schedule}")
    click.echo(
        f"  Scheduler run on start: {config.scheduler.run_on_start}",
    )
    click.echo(
        f"  Scheduler retry failed: {config.scheduler.retry_failed}",
    )
    click.echo(
        f"  Scheduler max retries: {config.scheduler.max_retries}",
    )
