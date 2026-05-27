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
from typing import TYPE_CHECKING, Any

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


def _fs_safe(name: str) -> str:
    """Sanitise a filesystem component name (path separators, parent refs)."""
    return name.replace("/", "_").replace("\\", "_").replace("..", "_")


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


def _simulate_quality_skip(
    session: Session,
    download: Download,
    audio_files: list[Path],
) -> bool:
    """Check if all audio files should be skipped due to equal/better quality in library.

    Returns True if the entire album should be skipped.
    """
    if download.identified_album_id is None:
        return False

    existing_album = session.get(Album, download.identified_album_id)
    if not existing_album or not existing_album.tracks:
        return False

    skip_count = 0
    for afile in audio_files:
        track_key = afile.stem.lower()
        if _check_file_should_skip(existing_album.tracks, afile, track_key):
            skip_count += 1
    return skip_count == len(audio_files)


def _check_file_should_skip(
    tracks: list[Track],
    afile: Path,
    track_key: str,
) -> bool:
    """Check if a single audio file matches a track that should be skipped."""
    for t in tracks:
        if not t.file_path or not t.format:
            continue
        if Path(t.file_path).stem.lower() != track_key:
            continue
        decision = compare_tracks(
            (t.format, t.bitrate),
            (afile.suffix.lstrip(".").upper(), None),
        )
        if decision == "skip":
            return True
        break  # first matching track with format determines the result
    return False


def _dry_run_actions_for_files(
    audio_files: list[Path],
    artist_name: str,
    album_title: str,
    year: int | None,
    genre: str | None,
    dest_root: Path,
    destination_pattern: str,
) -> list[str]:
    """Generate dry-run action strings for a list of audio files."""
    actions: list[str] = []
    for afile in audio_files:
        stem = _fs_safe(afile.stem)
        ext = afile.suffix.lstrip(".")
        variables: dict[str, str] = {
            "artist": artist_name or "",
            "album": album_title or "",
            "filename": stem,
            "ext": ext,
            "year": str(year) if year else "",
            "genre": genre or "",
        }
        relative_path = render_path(variables, destination_pattern)
        full_target = (dest_root / relative_path).resolve()
        if full_target.exists():
            actions.append(f"Would replace: {afile} \u2192 {full_target}")
        else:
            actions.append(f"Would move: {afile} \u2192 {full_target}")
    return actions


def _list_audio_files(directory: Path) -> list[Path]:
    """Return sorted list of audio files in a directory."""
    return sorted(f for f in directory.iterdir() if f.is_file() and _is_audio_file(f))


def _process_dl_simulate(
    dl: Download,
    dest_root: Path,
    destination_pattern: str,
    session: Session,
) -> list[str]:
    """Process a single download in dry-run mode."""
    source = Path(dl.source_path)
    if not source.is_dir():
        return [f"Would skip: {source} (source directory missing)"]

    artist_name = dl.identified_artist or "Unknown Artist"
    album_title = dl.identified_album or source.name
    audio_files = _list_audio_files(source)
    if not audio_files:
        return [f"Would skip: {source} (no audio files)"]

    if _simulate_quality_skip(session, dl, audio_files):
        return [f"Would skip: {source.name} (all tracks equal/better quality in library)"]

    return _dry_run_actions_for_files(
        audio_files,
        artist_name,
        album_title,
        dl.identified_year,
        dl.identified_genre,
        dest_root,
        destination_pattern,
    )


def _simulate_imports(
    session: Session,
    downloads: list[Download],
    dest_root: Path,
    destination_pattern: str,
) -> dict[str, Any]:
    """Simulate imports for dry-run mode, returning action descriptions."""
    actions: list[str] = []
    for dl in downloads:
        actions.extend(_process_dl_simulate(dl, dest_root, destination_pattern, session))

    return {
        "imported": 0,
        "skipped": 0,
        "replaced": 0,
        "errors": 0,
        "dry_run": True,
        "actions": actions,
    }


def import_downloads(
    session: Session,
    destination_root: str,
    destination_pattern: str,
    move: bool = True,
    delete_replaced: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
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
        dry_run: If ``True``, simulate the import without mutating files
            or database records. Returns a dict with a ``"dry_run"`` flag
            and a list of action descriptions under ``"actions"``.

    Returns:
        A dictionary with counts: ``{"imported", "skipped", "replaced",
        "errors"}``. When ``dry_run=True``, the dict also contains
        ``{"dry_run": True, "actions": [str, ...]}``.
    """
    dest_root = Path(destination_root).resolve()
    counts: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "replaced": 0,
        "errors": 0,
    }

    downloads: list[Download] = session.query(Download).filter(Download.status == "identified").all()

    if not downloads:
        logger.info("No identified downloads to import")
        return {
            "imported": 0,
            "skipped": 0,
            "replaced": 0,
            "errors": 0,
            **({"dry_run": True, "actions": []} if dry_run else {}),
        }  # noqa: E501

    if dry_run:
        return _simulate_imports(session, downloads, dest_root, destination_pattern)

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


def _resolve_artist_and_album(
    session: Session,
    download: Download,
    source: Path,
) -> tuple[Artist, Album, str, str]:
    """Resolve or create Artist and Album for a download."""
    artist_name = download.identified_artist or "Unknown Artist"
    artist_name = _fs_safe(artist_name)
    artist = _get_or_create_artist(session, artist_name)

    album_title = _fs_safe(download.identified_album or source.name)

    if download.identified_album_id is not None:
        album = session.get(Album, download.identified_album_id)
        if album is None:
            album = _get_or_create_album(
                session,
                artist,
                album_title,
                year=download.identified_year,
                genre=download.identified_genre,
            )
    else:
        album = _get_or_create_album(
            session,
            artist,
            album_title,
            year=download.identified_year,
            genre=download.identified_genre,
        )
    return artist, album, artist_name, album_title


def _import_audio_files(
    session: Session,
    album: Album,
    source: Path,
    audio_files: list,
    dest_root: Path,
    pattern: str,
    move: bool,
    delete_replaced: bool,
    artist_name: str,
    album_title: str,
    counts: dict[str, Any],
) -> None:
    """Import audio files with quality comparison and file operations."""
    existing_tracks_by_name: dict[str, Track] = {}
    for t in album.tracks or []:
        if t.file_path:
            name = Path(t.file_path).stem.lower()
            existing_tracks_by_name[name] = t

    for afile in audio_files:
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
            counts=counts,
            artist_name=artist_name,
            album_title=album.title,
            year=album.year,
            genre=album.genre,
        )


def _process_download(
    session: Session,
    download: Download,
    dest_root: Path,
    pattern: str,
    move: bool,
    delete_replaced: bool,
    counts: dict[str, Any],
) -> None:
    """Process a single identified download record."""
    source = Path(download.source_path)

    if not source.is_dir():
        logger.warning("Source directory missing: {}", source)
        download.status = "error"
        download.error_message = "source directory does not exist"
        counts["errors"] += 1
        return

    artist, album, artist_name, album_title = _resolve_artist_and_album(
        session,
        download,
        source,
    )

    audio_files = _list_audio_files(source)
    if not audio_files:
        logger.warning("No audio files found in {}", source)
        download.status = "error"
        download.error_message = "no audio files found in source directory"
        counts["errors"] += 1
        return

    _import_audio_files(
        session=session,
        album=album,
        source=source,
        audio_files=audio_files,
        dest_root=dest_root,
        pattern=pattern,
        move=move,
        delete_replaced=delete_replaced,
        artist_name=artist_name,
        album_title=album_title,
        counts=counts,
    )

    # Update download status
    download.status = "imported"
    counts["imported"] += 1
    logger.info("Imported download id={} from {}", download.id, source)


def _ensure_target_within_root(full_target: Path, dest_root: Path) -> bool:
    """Return True if *full_target* is within *dest_root*."""
    try:
        full_target.relative_to(dest_root)
        return True
    except ValueError:
        return False


def _handle_target_replacement(
    full_target: Path,
    dest_root: Path,
    relative_path: str,
    delete_replaced: bool,
    counts: dict[str, Any],
) -> None:
    """Move an existing target to _replaced/ or delete it."""
    counts["replaced"] = counts.get("replaced", 0) + 1
    if delete_replaced:
        full_target.unlink()
        logger.debug("Deleted existing file: {}", full_target)
    else:
        replaced_dir = dest_root / _REPLACED_DIR
        replaced_target = replaced_dir / relative_path
        replaced_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(full_target), str(replaced_target))
        logger.debug("Moved existing file to {}", replaced_target)


def _build_target_variables(
    stem: str,
    ext: str,
    artist_name: str,
    album_title: str,
    year: int | None,
    genre: str | None,
) -> dict[str, str]:
    """Build the template variables dict for rendering a target path."""
    return {
        "artist": artist_name if artist_name else "",
        "album": album_title if album_title else "",
        "filename": stem,
        "ext": ext,
        "year": str(year) if year is not None else "",
        "genre": genre if genre else "",
    }


def _import_file(
    session: Session,
    source_file: Path,
    album: Album,
    dest_root: Path,
    pattern: str,
    move: bool,
    delete_replaced: bool,
    counts: dict[str, Any],
    artist_name: str,
    album_title: str,
    year: int | None,
    genre: str | None,
) -> None:
    """Move or copy a single audio file into the library.

    This function tracks replaced counts via *counts*.
    """
    stem = _fs_safe(source_file.stem)
    ext = source_file.suffix.lstrip(".")

    variables = _build_target_variables(stem, ext, artist_name, album_title, year, genre)
    relative_path = render_path(variables, pattern)
    full_target = (dest_root / relative_path).resolve()

    if not _ensure_target_within_root(full_target, dest_root):
        logger.warning("Rendered path escapes destination root: {}", full_target)
        return

    full_target.parent.mkdir(parents=True, exist_ok=True)

    if full_target.exists():
        _handle_target_replacement(full_target, dest_root, relative_path, delete_replaced, counts)

    if move:
        shutil.move(str(source_file), str(full_target))
    else:
        shutil.copy2(str(source_file), str(full_target))

    file_stat = full_target.stat()
    file_hash = _get_file_hash(full_target)

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
