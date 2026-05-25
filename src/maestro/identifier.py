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


def _extract_flac_tags(fpath: Path) -> dict[str, Any] | None:
    """Extract tags from a FLAC file."""
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
    return result if result.get("artist") or result.get("album") else None


def _extract_mp3_tags(fpath: Path) -> dict[str, Any] | None:
    """Extract tags from an MP3 file."""
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
    return result if result.get("artist") or result.get("album") else None


def _extract_id3like_tags(tags: Any) -> dict[str, Any] | None:
    """Extract tags from an ID3-like (getall) tag container."""
    if not hasattr(tags, "getall"):
        return None
    year_text = _id3_text(tags, "TDRC") or _id3_text(tags, "TYER")
    result = {
        "artist": _id3_text(tags, "TPE1"),
        "album": _id3_text(tags, "TALB"),
        "title": _id3_text(tags, "TIT2"),
        "track": _id3_track(tags, "TRCK"),
        "year": _parse_int(year_text),
        "genre": _id3_text(tags, "TCON"),
    }
    return result if result.get("artist") or result.get("album") else None


def _extract_vorbislike_tags(tags: Any) -> dict[str, Any] | None:
    """Extract tags from a VorbisComment-like (dict) tag container."""
    if not isinstance(tags, dict):
        return None
    result = {
        "artist": _vorbis_first(tags, "artist"),
        "album": _vorbis_first(tags, "album"),
        "title": _vorbis_first(tags, "title"),
        "track": _vorbis_int(tags, "tracknumber"),
        "year": _vorbis_int(tags, "date"),
        "genre": _vorbis_first(tags, "genre"),
    }
    return result if result.get("artist") or result.get("album") else None


def _extract_other_tags(audio: Any, fpath: Path) -> dict[str, Any] | None:
    """Extract tags from non-FLAC/MP3 audio via mutagen.File."""
    if not hasattr(audio, "tags") or audio.tags is None:
        return None
    tags = audio.tags
    result = _extract_id3like_tags(tags)
    if result is not None:
        return result
    result = _extract_vorbislike_tags(tags)
    if result is not None:
        return result
    return _extract_mp4_tags(tags)


def _extract_mp4_tags(tags: Any) -> dict[str, Any] | None:
    """Extract tags from an MP4/M4A file."""
    if not hasattr(tags, "__getitem__"):
        return None
    atoms_map: dict[str, list[str]] = {
        "artist": ["\xa9ART", "aART", "----:com.apple.iTunes:Artist"],
        "album": ["\xa9alb", "----:com.apple.iTunes:Album"],
        "title": ["\xa9nam", "----:com.apple.iTunes:Title"],
        "track": ["\xa9trkn", "----:com.apple.iTunes:TrackNumber"],
        "year": ["\xa9day", "----:com.apple.iTunes:Year"],
        "genre": ["\xa9gen", "----:com.apple.iTunes:Genre"],
    }
    result: dict[str, Any] = {}
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
    return result if result.get("artist") or result.get("album") else None


def _extract_tags_from_file(fpath: Path) -> dict[str, Any] | None:
    """Attempt to read metadata tags from a single audio file."""
    import mutagen  # noqa: PLC0415

    ext = fpath.suffix.lower()

    if ext == ".flac":
        return _extract_flac_tags(fpath)

    if ext == ".mp3":
        return _extract_mp3_tags(fpath)

    # --- Other formats via mutagen.File ---
    try:
        audio = mutagen.File(fpath)
    except Exception:  # noqa: BLE001
        return None
    if audio is None:
        return None

    return _extract_other_tags(audio, fpath)


# ---------------------------------------------------------------------------
# Library matching helper
# ---------------------------------------------------------------------------


def _match_to_library(
    session: Session,
    artist_name: str | None,
    album_title: str | None,
    year: int | None = None,
    genre: str | None = None,
) -> int | None:
    """Match identified metadata against existing library records.

    Returns the matched Album id, or None.
    """
    if not artist_name or not album_title:
        return None
    artist = session.query(Artist).filter(Artist.name == artist_name).first()
    if artist is None:
        return None
    album = (
        session.query(Album)
        .filter(
            Album.artist_id == artist.id,
            Album.title == album_title,
        )
        .first()
    )
    if album is None:
        return None
    if year is not None and album.year is None:
        album.year = year
    if genre is not None and album.genre is None:
        album.genre = genre
    return album.id


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


# ---------------------------------------------------------------------------
# Download identification
# ---------------------------------------------------------------------------


def _identify_tags_or_heuristic(
    download: Download,
) -> tuple:
    """Read tags or fall back to heuristic for a download.

    Returns:
        Tuple of (artist_name, album_title, year, genre, match_type).
    """
    dl_path = Path(download.source_path)
    tags = _read_id3_tags(download.source_path)

    if tags is not None:
        return (
            tags.get("artist"),
            tags.get("album"),
            tags.get("year"),
            tags.get("genre"),
            "exact",
        )

    folder_name = dl_path.name
    artist_name, album_title = parse_filename_heuristic(folder_name)
    return artist_name, album_title, None, None, None


def _resolve_identified_album(
    session: Session,
    artist_name: str | None,
    album_title: str | None,
    year: int | None,
    genre: str | None,
    match_type: str | None,
) -> tuple[int | None, int | None, str | None, str | None, str | None]:
    """Match against library and return updated values.

    Returns:
        Tuple of (identified_album_id, year, genre, artist_name, match_type).
    """
    identified_album_id = _match_to_library(session, artist_name, album_title, year, genre)
    if identified_album_id is not None:
        if match_type is None:
            match_type = "exact"
        if year is None or genre is None:
            lib_album = session.get(Album, identified_album_id)
            if lib_album is not None:
                if year is None:
                    year = lib_album.year
                if genre is None:
                    genre = lib_album.genre
    return identified_album_id, year, genre, artist_name, match_type


def identify_download(download: Download, session: Session) -> None:
    """Identify metadata for a single download."""
    dl_path = Path(download.source_path)
    if not dl_path.is_dir():
        logger.debug("Download path {} is not a directory — skipping", dl_path)
        return

    artist_name, album_title, year, genre, match_type = _identify_tags_or_heuristic(download)
    identified_album_id, year, genre, artist_name, match_type = _resolve_identified_album(
        session,
        artist_name,
        album_title,
        year,
        genre,
        match_type,
    )

    download.identified_artist = artist_name
    download.identified_album = album_title or None
    download.identified_year = year
    download.identified_genre = genre
    download.match_type = match_type
    download.identified_album_id = identified_album_id
    if artist_name or album_title:
        download.status = "identified"
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
