"""Identifier module — extract metadata from downloads and match against the library.

Provides functions to parse filename heuristics, read ID3/Vorbis audio tags,
and match downloads against existing library entries.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from maestro.db.models import Album, Artist, Download

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Audio file extensions recognised for tag reading
# ---------------------------------------------------------------------------
AUDIO_EXTENSIONS: set[str] = {
    ".mp3",
    ".flac",
    ".ogg",
    ".wav",
    ".aiff",
    ".aif",
    ".m4a",
    ".wma",
    ".opus",
    ".ape",
    ".wv",
}


# ---------------------------------------------------------------------------
# Heuristic filename parsing
# ---------------------------------------------------------------------------

# Matches "Artist - Album" or "Artist - Part - Album" — leftmost dash
_DASH_PATTERN = re.compile(r"^(.*?)\s*-\s*(.*)$")
# Fallback underscore separator
_UNDERSCORE_PATTERN = re.compile(r"^(.*?)_(.*)$")


def parse_filename_heuristic(name: str) -> tuple[str | None, str]:
    """Parse artist and album from a folder name using common separators.

    Tries, in order:

    1. `` - `` (space-dash-space) — returns ``(artist, album)`` on first
       match.  If multiple dashes exist the leftmost one is the boundary.
    2. ``_`` (underscore) — returns ``(artist, album)``.
    3. No separator — returns ``(None, name)``.

    Args:
        name: Raw folder name to parse.

    Returns:
        Tuple ``(artist | None, album)``.  *artist* is ``None`` when no
        separator was found.
    """
    if not name:
        return (None, "")

    m = _DASH_PATTERN.match(name)
    if m:
        return (m.group(1).strip() or None, m.group(2).strip())

    m = _UNDERSCORE_PATTERN.match(name)
    if m:
        return (m.group(1).strip() or None, m.group(2).strip())

    return (None, name.strip())


# ---------------------------------------------------------------------------
# ID3 / Vorbis tag reading helpers
# ---------------------------------------------------------------------------


def _vorbis_first(tags: Any, key: str) -> str | None:
    """Return the first value for a Vorbis comment *key*, or ``None``."""
    try:
        values = tags.get(key, [])
        return str(values[0]) if values else None
    except Exception:  # noqa: BLE001
        return None


def _vorbis_int(tags: Any, key: str) -> int | None:
    """Return the integer value of a Vorbis comment *key*, or ``None``."""
    text = _vorbis_first(tags, key)
    return _parse_int(text)


def _id3_text(tags: Any, frame_id: str) -> str | None:
    """Extract text from an ID3 *frame_id*, or ``None``."""
    try:
        frames = tags.getall(frame_id)
        if frames:
            return str(frames[0])
    except Exception:  # noqa: BLE001
        pass
    return None


def _id3_track(tags: Any, frame_id: str) -> int | None:
    """Extract a track number from an ID3 TRCK-like frame.

    Handles ``"3"`` and ``"3/12"`` formats.
    """
    text = _id3_text(tags, frame_id)
    if text is None:
        return None
    parts = text.split("/")
    return _parse_int(parts[0])


def _parse_int(value: str | None) -> int | None:
    """Parse an integer from *value*, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Tag extraction from a single file
# ---------------------------------------------------------------------------


def _extract_tags_from_file(fpath: Path) -> dict[str, Any] | None:
    """Attempt to read metadata tags from a single audio file.

    Args:
        fpath: Path to an audio file.

    Returns:
        A dict with keys ``artist``, ``album``, ``title``, ``track``,
        ``year``, ``genre``, or ``None``.
    """
    import mutagen  # noqa: PLC0415

    ext = fpath.suffix.lower()

    if ext == ".flac":
        from mutagen.flac import FLAC  # noqa: PLC0415

        try:
            flac_file = FLAC(fpath)
        except Exception:  # noqa: BLE001
            return None
        if flac_file.tags is None:
            return None
        result = {
            "artist": _vorbis_first(flac_file.tags, "artist"),
            "album": _vorbis_first(flac_file.tags, "album"),
            "title": _vorbis_first(flac_file.tags, "title"),
            "track": _vorbis_int(flac_file.tags, "tracknumber"),
            "year": _vorbis_int(flac_file.tags, "date"),
            "genre": _vorbis_first(flac_file.tags, "genre"),
        }
        if result.get("artist") or result.get("album"):
            return result
        return None

    if ext == ".mp3":
        from mutagen.id3 import ID3, ID3NoHeaderError  # noqa: PLC0415

        try:
            mp3_file = ID3(fpath)
        except ID3NoHeaderError:
            return None
        except Exception:  # noqa: BLE001
            return None

        year_text = _id3_text(mp3_file, "TDRC") or _id3_text(mp3_file, "TYER")
        result = {
            "artist": _id3_text(mp3_file, "TPE1"),
            "album": _id3_text(mp3_file, "TALB"),
            "title": _id3_text(mp3_file, "TIT2"),
            "track": _id3_track(mp3_file, "TRCK"),
            "year": _parse_int(year_text),
            "genre": _id3_text(mp3_file, "TCON"),
        }
        if result.get("artist") or result.get("album"):
            return result
        return None

    # --- Other formats via mutagen.File ---
    try:
        audio = mutagen.File(fpath)
    except Exception:  # noqa: BLE001
        return None
    if audio is None:
        return None

    if not hasattr(audio, "tags") or audio.tags is None:
        return None

    tags = audio.tags

    # EasyID3 / ID3-like
    if hasattr(tags, "getall"):
        year_text = _id3_text(tags, "TDRC") or _id3_text(tags, "TYER")
        result = {
            "artist": _id3_text(tags, "TPE1"),
            "album": _id3_text(tags, "TALB"),
            "title": _id3_text(tags, "TIT2"),
            "track": _id3_track(tags, "TRCK"),
            "year": _parse_int(year_text),
            "genre": _id3_text(tags, "TCON"),
        }
        if result.get("artist") or result.get("album"):
            return result
        return None

    # Vorbis-like (dict of lists)
    if isinstance(tags, dict):
        result = {
            "artist": _vorbis_first(tags, "artist"),
            "album": _vorbis_first(tags, "album"),
            "title": _vorbis_first(tags, "title"),
            "track": _vorbis_int(tags, "tracknumber"),
            "year": _vorbis_int(tags, "date"),
            "genre": _vorbis_first(tags, "genre"),
        }
        if result.get("artist") or result.get("album"):
            return result
        return None

    # MP4/M4A tags (mutagen.mp4.MP4Tags with __getitem__ atoms)
    if hasattr(tags, "__getitem__"):
        # MP4 atoms used for common metadata
        atoms_map: dict[str, list[str]] = {
            "artist": ["\xa9ART", "aART", "----:com.apple.iTunes:Artist"],
            "album": ["\xa9alb", "----:com.apple.iTunes:Album"],
            "title": ["\xa9nam", "----:com.apple.iTunes:Title"],
            "track": ["\xa9trkn", "----:com.apple.iTunes:TrackNumber"],
            "year": ["\xa9day", "----:com.apple.iTunes:Year"],
            "genre": ["\xa9gen", "----:com.apple.iTunes:Genre"],
        }
        result = {}
        for key, atoms in atoms_map.items():
            for atom in atoms:
                try:
                    val = tags[atom]
                    if val:
                        if isinstance(val, list):
                            result[key] = str(val[0])
                        else:
                            result[key] = str(val)
                        break
                except (KeyError, TypeError, IndexError):
                    continue
        if result.get("artist") or result.get("album"):
            return result

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _read_id3_tags(directory: str) -> dict[str, Any] | None:
    """Read ID3 / Vorbis tags from audio files in *directory*.

    Scans for audio files (MP3, FLAC, etc.) and attempts to extract
    metadata tags using mutagen.  Returns the first complete set of tags
    found.

    Args:
        directory: Path to the album directory.

    Returns:
        A dict with keys ``artist``, ``album``, ``title``, ``track``,
        ``year``, ``genre``, or ``None`` if no tags could be read.
    """
    import importlib.util as _util  # noqa: PLC0415

    if _util.find_spec("mutagen") is None:
        logger.warning("mutagen is not installed — skipping ID3 tag reading")
        return None

    dir_path = Path(directory)
    if not dir_path.is_dir():
        return None

    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            tags = _extract_tags_from_file(entry)
            if tags:
                return tags
        except Exception:  # noqa: BLE001
            logger.debug("Could not read tags from {}", entry)
            continue

    return None


def identify_download(download: Download, session: Session) -> None:
    """Identify metadata for a single download.

    Steps:

    1. Skip (return early) if ``download.source_path`` is not an existing
       directory.
    2. Attempt to read ID3 / Vorbis tags from audio files in the directory.
    3. If tags are present, extract ``artist``, ``album``, ``year``, and
       ``genre``.
    4. If no tags are found, fall back to :func:`parse_filename_heuristic`
       on the folder name.
    5. Query the library for a matching ``Artist`` + ``Album``.
    6. Update the ``Download`` record with identified metadata.

    Args:
        download: The ``Download`` record to update (modified in place).
        session: Active SQLAlchemy session.
    """
    dl_path = Path(download.source_path)

    if not dl_path.is_dir():
        logger.debug("Download path {} is not a directory — skipping", dl_path)
        return

    # --- Attempt tag reading ---
    tags = _read_id3_tags(download.source_path)

    if tags is not None:
        artist_name: str | None = tags.get("artist")
        album_title: str | None = tags.get("album")
        year: int | None = tags.get("year")
        genre: str | None = tags.get("genre")
        match_type: str | None = "exact"
        logger.debug(
            "Extracted tags from {}: artist={}, album={}",
            dl_path,
            artist_name,
            album_title,
        )
    else:
        # --- Fall back to heuristic ---
        folder_name = dl_path.name
        artist_name, album_title = parse_filename_heuristic(folder_name)
        year = None
        genre = None
        match_type = None
        logger.debug(
            "Heuristic parse of '{}': artist={}, album={}",
            folder_name,
            artist_name,
            album_title,
        )

    # --- Try to match against existing library ---
    identified_album_id: int | None = None
    if artist_name and album_title:
        artist = session.query(Artist).filter(Artist.name == artist_name).first()
        if artist is not None:
            album = session.query(Album).filter(Album.artist_id == artist.id, Album.title == album_title).first()
            if album is not None:
                identified_album_id = album.id
                if match_type is None:
                    match_type = "exact"
                # Fill in year / genre from the library match when missing
                if year is None:
                    year = album.year
                if genre is None:
                    genre = album.genre
                logger.debug("Matched to Album id={} in library", album.id)

    # --- Update the download record ---
    download.identified_artist = artist_name
    # Coerce empty string album title to None for DB consistency
    download.identified_album = album_title or None
    download.identified_year = year
    download.identified_genre = genre
    download.match_type = match_type
    download.identified_album_id = identified_album_id

    if artist_name or album_title:
        download.status = "identified"
    # else leave as "new"

    session.flush()


def identify_downloads(session: Session) -> list[Download]:
    """Identify all downloads with status ``"new"`` in *session*.

    Calls :func:`identify_download` on each matching record.

    Args:
        session: Active SQLAlchemy session.

    Returns:
        List of updated ``Download`` records.
    """
    downloads: list[Download] = session.query(Download).filter(Download.status == "new").all()

    for dl in downloads:
        try:
            identify_download(dl, session)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to identify download id={}", dl.id)
            dl.status = "error"
            continue

    session.commit()

    return downloads
