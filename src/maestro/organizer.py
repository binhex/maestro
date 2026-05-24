"""Organizer module — move/copy identified downloads into the library.

Processes downloads that have been identified (status ``"identified"``),
creates or updates Artist, Album, and Track records, and moves (or copies)
audio files into the library tree according to a configurable path pattern.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from maestro.db.models import Album, Artist, Download, Track
from maestro.quality import compare_tracks
from maestro.scanner import AUDIO_EXTENSIONS
from maestro.template import render_path

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_REPLACED_DIR = "_replaced"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert *text* to a filesystem-safe slug.

    Lowercases the input, collapses whitespace to hyphens, and removes
    everything except ASCII letters, digits, hyphens, and underscores.
    Consecutive hyphens are collapsed to a single hyphen.
    """
    lower = text.lower().strip()
    # Replace whitespace runs with hyphens
    slug = re.sub(r"\s+", "-", lower)
    # Remove any character that is not alphanumeric, hyphen, or underscore
    slug = re.sub(r"[^a-z0-9\-_]", "", slug)
    # Collapse consecutive hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug if slug else "unknown"


def _get_file_hash(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 digest of *path* and return the first 16 hex characters.

    Args:
        path: File to hash.
        chunk_size: Read chunk size in bytes.

    Returns:
        First 16 hex characters of the SHA-256 digest.
    """
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _get_or_create_artist(session: Session, name: str) -> Artist:
    """Return an existing Artist by *name*, or create one.

    Args:
        session: Active SQLAlchemy session.
        name: Artist name.

    Returns:
        The matching or newly created ``Artist`` record.
    """
    artist = session.query(Artist).filter(Artist.name == name).first()
    if artist is not None:
        return artist

    artist = Artist(name=name, slug=_slugify(name))
    session.add(artist)
    session.flush()
    logger.debug("Created Artist id={} name={!r}", artist.id, name)
    return artist


def _get_or_create_album(
    session: Session,
    artist: Artist,
    title: str,
    year: int | None = None,
    genre: str | None = None,
) -> Album:
    """Return an existing Album by *artist* and *title*, or create one.

    Args:
        session: Active SQLAlchemy session.
        artist: The owning ``Artist`` record.
        title: Album title.
        year: Optional release year (set only on creation).
        genre: Optional genre (set only on creation).

    Returns:
        The matching or newly created ``Album`` record.
    """
    album = session.query(Album).filter(Album.artist_id == artist.id, Album.title == title).first()
    if album is not None:
        # Update year/genre if currently missing on the existing record
        changed = False
        if album.year is None and year is not None:
            album.year = year
            changed = True
        if album.genre is None and genre is not None:
            album.genre = genre
            changed = True
        if changed:
            session.flush()
        return album

    album = Album(
        artist_id=artist.id,
        title=title,
        year=year,
        genre=genre,
    )
    session.add(album)
    session.flush()
    logger.debug("Created Album id={} title={!r}", album.id, title)
    return album


def _is_audio_file(path: Path) -> bool:
    """Return True if *path* has an audio-file extension (case-insensitive).

    Uses the same extension set as :mod:`maestro.scanner`.
    """
    return path.suffix.lower() in AUDIO_EXTENSIONS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_downloads(
    session: Session,
    destination_root: str,
    destination_pattern: str,
    move: bool = True,
    delete_replaced: bool = False,
) -> dict[str, int]:
    """Process identified downloads and import them into the library.

    For each download with status ``"identified"``:

    1. Check that the source directory exists (skip with error if not).
    2. Get or create the ``Artist`` record.
    3. Get or create the ``Album`` record.
    4. For every audio file in the source directory:
       a. Build a variables dict for the template engine.
       b. Render the target path via :func:`~maestro.template.render_path`.
       c. Create parent directories.
       d. If the target file already exists, move the old file to
          ``_replaced/`` (mirroring the same sub-path under *destination_root*)
          or delete it if *delete_replaced* is ``True``.
       e. Move (or ``copy2``) the new file to the target.
       f. Create a ``Track`` record for the imported file.
    5. Set the download status to ``"imported"``.
    6. On any exception, set the download status to ``"error"`` and
       store the error message.

    Args:
        session: Active SQLAlchemy session.
        destination_root: Root directory of the music library.
        destination_pattern: Template pattern for file paths
            (e.g. ``{artist}/{album}/{filename}.{ext}``).
        move: If ``True`` (default), move files; otherwise copy.
        delete_replaced: If ``True``, permanently delete replaced files
            instead of moving them to ``_replaced/``.

    Returns:
        A dictionary with counts: ``{"imported", "skipped", "replaced",
        "errors"}``.
    """
    dest_root = Path(destination_root).resolve()
    counts: dict[str, int] = {
        "imported": 0,
        "skipped": 0,
        "replaced": 0,
        "errors": 0,
    }

    downloads: list[Download] = session.query(Download).filter(Download.status == "identified").all()

    if not downloads:
        logger.info("No identified downloads to import")
        return counts

    for dl in downloads:
        try:
            _process_download(
                session=session,
                download=dl,
                dest_root=dest_root,
                pattern=destination_pattern,
                move=move,
                delete_replaced=delete_replaced,
                counts=counts,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to import download id={}", dl.id)
            dl.status = "error"
            dl.error_message = "import failed: an unexpected error occurred"
            counts["errors"] += 1

    session.commit()
    return counts


def _process_download(
    session: Session,
    download: Download,
    dest_root: Path,
    pattern: str,
    move: bool,
    delete_replaced: bool,
    counts: dict[str, int],
) -> None:
    """Process a single identified download record."""
    source = Path(download.source_path)

    # 1. Source directory exists?
    if not source.is_dir():
        logger.warning("Source directory missing: {}", source)
        download.status = "error"
        download.error_message = "source directory does not exist"
        counts["errors"] += 1
        return

    # 2. Get or create Artist
    artist_name = download.identified_artist or "Unknown Artist"
    # Sanitise artist name for filesystem safety (path separators)
    artist_name = artist_name.replace("/", "_").replace("\\", "_")
    artist = _get_or_create_artist(session, artist_name)

    # 3. Get or create Album
    if download.identified_album_id is not None:
        album = session.get(Album, download.identified_album_id)
        if album is None:
            # Referenced album was deleted — fall back to creating one
            album_title = download.identified_album or source.name
            album = _get_or_create_album(
                session,
                artist,
                album_title,
                year=download.identified_year,
                genre=download.identified_genre,
            )
    else:
        album_title = download.identified_album or source.name
        album = _get_or_create_album(
            session,
            artist,
            album_title,
            year=download.identified_year,
            genre=download.identified_genre,
        )

    # 4. Process each audio file
    audio_files = sorted(f for f in source.iterdir() if f.is_file() and _is_audio_file(f))
    if not audio_files:
        logger.warning("No audio files found in {}", source)
        download.status = "error"
        download.error_message = "no audio files found in source directory"
        counts["errors"] += 1
        return

    # Build a lookup of existing tracks by filename for quality comparison
    existing_tracks_by_name: dict[str, Track] = {}
    for t in album.tracks or []:
        if t.file_path:
            name = Path(t.file_path).stem.lower()
            existing_tracks_by_name[name] = t

    for afile in audio_files:
        # Quality check: skip if library has equal or better quality
        source_ext = afile.suffix.lstrip(".").upper()
        track_key = afile.stem.lower()
        existing = existing_tracks_by_name.get(track_key)
        if existing is not None and existing.format:
            decision = compare_tracks(
                (existing.format, existing.bitrate),
                (source_ext, None),
            )
            if decision in ("skip",):
                logger.info(
                    "Skipping {} — library has equal or better quality ({})",
                    afile.name,
                    existing.format,
                )
                counts["skipped"] += 1
                continue

        _import_file(
            session=session,
            source_file=afile,
            album=album,
            dest_root=dest_root,
            pattern=pattern,
            move=move,
            delete_replaced=delete_replaced,
            artist_name=artist_name,
            album_title=album.title,
            year=album.year,
            genre=album.genre,
        )

    # 5. Update download status
    download.status = "imported"
    counts["imported"] += 1
    logger.info("Imported download id={} from {}", download.id, source)


def _import_file(
    session: Session,
    source_file: Path,
    album: Album,
    dest_root: Path,
    pattern: str,
    move: bool,
    delete_replaced: bool,
    artist_name: str,
    album_title: str,
    year: int | None,
    genre: str | None,
) -> None:
    """Move or copy a single audio file into the library.

    This function does **not** track replaced / imported counts — those
    are managed by the caller (:func:`_process_download`).
    """
    stem = source_file.stem
    # Sanitise filename stem: replace path separators and parent-dir refs
    stem = stem.replace("/", "_").replace("\\", "_").replace("..", "_")
    ext = source_file.suffix.lstrip(".")

    variables: dict[str, str] = {
        "artist": artist_name or "",
        "album": album_title or "",
        "filename": stem,
        "ext": ext,
        "year": str(year) if year is not None else "",
        "genre": genre or "",
    }

    relative_path = render_path(variables, pattern)
    full_target = (dest_root / relative_path).resolve()

    # Ensure the full_target is within dest_root (path traversal check)
    try:
        full_target.relative_to(dest_root)
    except ValueError:
        logger.warning("Rendered path escapes destination root: {}", full_target)
        return

    # Create parent directories
    full_target.parent.mkdir(parents=True, exist_ok=True)

    # Handle replacement if target already exists
    if full_target.exists():
        if delete_replaced:
            full_target.unlink()
            logger.debug("Deleted existing file: {}", full_target)
        else:
            # Move to _replaced/ mirroring the same relative sub-path
            replaced_dir = dest_root / _REPLACED_DIR
            replaced_target = replaced_dir / relative_path
            replaced_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(full_target), str(replaced_target))
            logger.debug("Moved existing file to {}", replaced_target)

    # Move or copy the new file
    if move:
        shutil.move(str(source_file), str(full_target))
    else:
        shutil.copy2(str(source_file), str(full_target))

    # Get file stats after the move/copy
    file_stat = full_target.stat()
    file_hash = _get_file_hash(full_target)

    # Create Track record
    track = Track(
        album_id=album.id,
        title=stem,
        format=ext,
        file_path=str(full_target),
        file_size=file_stat.st_size,
        file_hash=file_hash,
    )
    session.add(track)
    session.flush()
