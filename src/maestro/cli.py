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


def _resolve_db_path(database_path: str | None, ctx: click.Context) -> str:
    """Resolve the database path from options, env, or default."""
    if database_path is None and ctx.parent is not None:
        database_path = ctx.parent.params.get("database_path")
    assert ctx.parent is not None, "_resolve_db_path requires a parent context"
    if not database_path:
        database_path = os.environ.get("MAESTRO_DB") or _DEFAULT_DB_PATH
    db_p = Path(database_path)
    if db_p.is_dir() or not db_p.suffix:
        database_path = str(db_p / "maestro.db")
    return database_path


def _resolve_setup_config_path(ctx: click.Context, config_path: str | None) -> str | None:
    """Resolve the config path from the --config option or parameter."""
    if config_path is None and ctx.parent is not None:
        return ctx.parent.params.get("config")
    return config_path


def _setup(
    ctx: click.Context,
    database_path: str | None = None,
    config_path: str | None = None,
) -> tuple[Config, Engine, Session]:
    """Load config, initialise logger, create engine and session."""
    config = load_config(_resolve_setup_config_path(ctx, config_path))

    if ctx.parent is None:
        raise click.UsageError("_setup must be called from a subcommand")
    log_level = ctx.parent.params.get("log_level", "INFO")
    log_path = ctx.parent.params.get("log_path") or _DEFAULT_LOGS_PATH
    database_path = _resolve_db_path(database_path, ctx)

    create_logger(log_format=_DEFAULT_LOG_FORMAT, log_level=log_level, log_path=log_path)
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
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=True),
    required=False,
    default=None,
    metavar="<dir>",
    help="Directory for the SQLite database. The database file is created inside as 'maestro.db'. Falls back to MAESTRO_DB env var or a default project path.",
)
@click.option(
    "--config",
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=True),
    required=False,
    default=None,
    metavar="<dir>",
    help="Directory for the YAML configuration file. The config file is created inside as 'maestro.yaml'.",
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


def _run_library_scan(
    session: Session,
    config: Config,
    roots: tuple[str, ...],
) -> None:
    """Scan library roots and report results."""
    from maestro.scanner import scan_library_root

    paths = list(roots) if roots else [r.path for r in config.library_roots if r.enabled]
    if not paths:
        click.echo("No library roots to scan.")
        return
    for root in paths:
        click.echo(f"Scanning library {root}...")
        result = scan_library_root(session, root)
        click.echo(
            f"  Result: artists={result['artists']} albums={result['albums']} tracks={result['tracks']}",
        )
    click.echo("Library scan complete.")


def _run_download_scan(
    session: Session,
    config: Config,
    roots: tuple[str, ...],
) -> None:
    """Scan download roots and report results."""
    from maestro.scanner import scan_download_root

    paths = list(roots) if roots else [r.path for r in config.download_roots if r.enabled]
    if not paths:
        click.echo("No download roots to scan.")
        return
    for root in paths:
        click.echo(f"Scanning {root}...")
        result = scan_download_root(session, root)
        click.echo(
            f"  Result: created={result['created']} skipped={result['skipped']}",
        )


@cli.command()
@click.argument(
    "roots",
    nargs=-1,
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
)
@click.option(
    "--library",
    is_flag=True,
    default=False,
    help="Scan library roots instead of download roots.",
)
@click.pass_context
def scan(ctx: click.Context, roots: tuple[str, ...], library: bool) -> None:
    """Scan directories for music files.

    By default, scans download directories for new files to import.
    Use ``--library`` to scan an existing organised music library and
    populate the database with its Artist, Album, and Track records
    (required before running ``artwork`` or ``check``).
    """
    config, _engine, session = _setup(ctx)
    try:
        if library:
            _run_library_scan(session, config, roots)
        else:
            _run_download_scan(session, config, roots)
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


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------


def _write_tags_for_tracks(tracks: list) -> None:
    """Write metadata tags to all tracks in the list."""
    from maestro.tagger import write_tags

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
        click.echo(f"  {'Tagged' if ok else 'Failed'}: {track.file_path}")


def _clear_tags_for_tracks(tracks: list) -> None:
    """Clear all ID3 tags from tracks in the list."""
    from maestro.tagger import clear_tags

    click.echo(f"Clearing tags on {len(tracks)} track(s)...")
    for track in tracks:
        if clear_tags(track.file_path):
            click.echo(f"  Cleared: {track.file_path}")


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
    from maestro.db.models import Track

    _config, _engine, session = _setup(ctx)
    try:
        tracks = session.query(Track).all()

        if not tracks:
            click.echo("No tracks found to tag.")
            return

        if clear:
            _clear_tags_for_tracks(tracks)
        else:
            _write_tags_for_tracks(tracks)
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
                download_album_art=config.artwork.download_album_art,
                download_fanart=config.artwork.download_fanart,
                lastfm_api_key=api_key,
                sources=sources,
                max_width=config.artwork.width,
                max_height=config.artwork.height,
                aspect_tolerance_percentage=config.artwork.aspect_tolerance_percentage,
            )
            source = result.get("source_used") or "none"
            click.echo(
                f"  Album art: {'✓' if result['album_art'] else '✗'} ({source})",
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
    click.echo(f"  Artwork download album art: {config.artwork.download_album_art}")
    click.echo(f"  Artwork download fanart: {config.artwork.download_fanart}")
    click.echo(f"  Dry run: {config.dry_run}")
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
