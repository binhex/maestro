"""Tagger module — read/write/clear audio file metadata tags.

Uses mutagen to read and write ID3 (MP3) and Vorbis (FLAC) tags,
with a fallback to ``mutagen.File`` for other formats.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARTWORK_MIME_MAP: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _guess_mime(path: str | Path) -> str:
    """Guess the image MIME type from the file extension.

    Args:
        path: Path to the artwork file.

    Returns:
        A MIME type string (default ``"image/jpeg"`` if unknown).
    """
    ext = Path(path).suffix.lower()
    return _ARTWORK_MIME_MAP.get(ext, "image/jpeg")


# ---------------------------------------------------------------------------
# Artwork embedding helpers (called by write_tags)
# ---------------------------------------------------------------------------


def embed_artwork_id3(audio: Any, artwork_path: str | Path) -> None:
    """Embed artwork as an APIC frame in an MP3's ID3 tags.

    Args:
        audio: A ``mutagen.id3.ID3`` instance (or equivalent).
        artwork_path: Path to the image file to embed.
    """
    try:
        from mutagen.id3 import APIC  # noqa: PLC0415

        with open(artwork_path, "rb") as fh:
            data = fh.read()

        apic = APIC(
            encoding=3,  # UTF-8
            mime=_guess_mime(artwork_path),
            type=3,  # Front cover
            desc="",
            data=data,
        )
        audio["APIC"] = apic
        logger.debug("Embedded APIC artwork in ID3 tag")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to embed artwork in ID3 tag")


def embed_artwork_vorbis(audio: Any, artwork_path: str | Path) -> None:
    """Embed artwork as a picture block in a FLAC file.

    Args:
        audio: A ``mutagen.flac.FLAC`` instance.
        artwork_path: Path to the image file to embed.
    """
    try:
        from mutagen.flac import Picture  # noqa: PLC0415

        with open(artwork_path, "rb") as fh:
            data = fh.read()

        picture = Picture()
        picture.type = 3  # Front cover
        picture.desc = ""
        picture.mime = _guess_mime(artwork_path)
        picture.width = 0
        picture.height = 0
        picture.depth = 0
        picture.colors = 0
        picture.data = data

        audio.add_picture(picture)
        logger.debug("Embedded picture in FLAC Vorbis tag")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to embed artwork in FLAC Vorbis tag")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_tags(
    file_path: str | Path,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    track_number: int | None = None,
    year: int | None = None,
    genre: str | None = None,
    artwork_path: str | Path | None = None,
) -> bool:
    """Write metadata tags to an audio file.

    Supports MP3 (ID3), FLAC (VorbisComment), and falls back to
    ``mutagen.File`` for other formats.

    Args:
        file_path: Path to the audio file.
        artist: Track artist name.
        album: Album name.
        title: Track title.
        track_number: Track number.
        year: Release year.
        genre: Track genre.
        artwork_path: Optional path to artwork image to embed.

    Returns:
        ``True`` on success, ``False`` if the file does not exist or
        an error occurs during tag writing.
    """
    fpath = Path(file_path)
    if not fpath.is_file():
        logger.warning("File not found: {}", file_path)
        return False

    try:
        ext = fpath.suffix.lower()

        if ext == ".mp3":
            return _write_mp3_tags(fpath, artist, album, title, track_number, year, genre, artwork_path)
        if ext == ".flac":
            return _write_flac_tags(fpath, artist, album, title, track_number, year, genre, artwork_path)

        return _write_other_tags(fpath, artist, album, title, track_number, year, genre, artwork_path)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write tags to {}", file_path)
        return False


def clear_tags(file_path: str | Path) -> bool:
    """Remove all metadata tags from an audio file.

    Args:
        file_path: Path to the audio file.

    Returns:
        ``True`` on success, ``False`` if the file does not exist or
        an error occurs during tag clearing.
    """
    fpath = Path(file_path)
    if not fpath.is_file():
        logger.warning("File not found: {}", file_path)
        return False

    try:
        _clear_audio_tags(fpath)
        logger.debug("Cleared tags from {}", fpath)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to clear tags from {}", file_path)
        return False


def _clear_audio_tags(fpath: Path) -> None:
    """Clear tags from a single audio file (per-format dispatch).

    Raises:
        ValueError: If ``mutagen.File`` returns ``None`` (unsupported format).
    """
    ext = fpath.suffix.lower()
    audio: Any = None

    if ext == ".mp3":
        import mutagen.id3  # noqa: PLC0415

        audio = mutagen.id3.ID3(fpath)
        audio.delete()
    elif ext == ".flac":
        import mutagen.flac  # noqa: PLC0415

        audio = mutagen.flac.FLAC(fpath)
        audio.delete()
    else:
        import mutagen  # noqa: PLC0415

        audio = mutagen.File(fpath)
        if audio is None:
            logger.warning("Unsupported format or unreadable file: {}", fpath)
            msg = f"unsupported format or unreadable file: {fpath}"
            raise ValueError(msg)
        if hasattr(audio, "delete"):
            audio.delete()
        elif hasattr(audio, "clear"):
            audio.clear()  # fallback for some formats


# ---------------------------------------------------------------------------
# Internal helpers — per-format tag writing
# ---------------------------------------------------------------------------


def _set_id3_frames(
    audio: Any,
    artist: str | None,
    album: str | None,
    title: str | None,
    track_number: int | None,
    year: int | None,
    genre: str | None,
) -> None:
    """Set ID3 frames on *audio* for each non-None value."""
    import mutagen.id3  # noqa: PLC0415

    frames: list[tuple[str, str | None, Any]] = [
        ("TPE1", artist, mutagen.id3.TPE1),
        ("TALB", album, mutagen.id3.TALB),
        ("TIT2", title, mutagen.id3.TIT2),
        ("TRCK", track_number, mutagen.id3.TRCK),
        ("TDRC", year, mutagen.id3.TDRC),
        ("TCON", genre, mutagen.id3.TCON),
    ]
    for frame_id, val, cls in frames:
        if val is not None:
            text = str(val) if isinstance(val, int) else val
            audio[frame_id] = cls(encoding=3, text=text)


def _write_mp3_tags(
    fpath: Path,
    artist: str | None,
    album: str | None,
    title: str | None,
    track_number: int | None,
    year: int | None,
    genre: str | None,
    artwork_path: str | Path | None,
) -> bool:
    """Write ID3 tags to an MP3 file."""
    import mutagen.id3  # noqa: PLC0415

    try:
        audio = mutagen.id3.ID3(fpath)
    except mutagen.id3.ID3NoHeaderError:
        audio = mutagen.id3.ID3()

    _set_id3_frames(audio, artist, album, title, track_number, year, genre)

    if artwork_path is not None:
        embed_artwork_id3(audio, artwork_path)

    audio.save(fpath)
    logger.debug("Wrote ID3 tags to {}", fpath)
    return True


def _write_flac_tags(
    fpath: Path,
    artist: str | None,
    album: str | None,
    title: str | None,
    track_number: int | None,
    year: int | None,
    genre: str | None,
    artwork_path: str | Path | None,
) -> bool:
    """Write VorbisComment tags to a FLAC file."""
    import mutagen.flac  # noqa: PLC0415

    audio = mutagen.flac.FLAC(fpath)

    if artist is not None:
        audio["artist"] = artist
    if album is not None:
        audio["album"] = album
    if title is not None:
        audio["title"] = title
    if track_number is not None:
        audio["tracknumber"] = str(track_number)
    if year is not None:
        audio["date"] = str(year)
    if genre is not None:
        audio["genre"] = genre

    if artwork_path is not None:
        embed_artwork_vorbis(audio, artwork_path)

    audio.save()
    logger.debug("Wrote Vorbis tags to {}", fpath)
    return True


def _set_vorbis_dict_tags(
    tags: dict,
    artist: str | None,
    album: str | None,
    title: str | None,
    track_number: int | None,
    year: int | None,
    genre: str | None,
) -> None:
    """Set VorbisComment-style tags on *tags* dict for each non-None value."""
    entries: list[tuple[str, str | None]] = [
        ("artist", artist),
        ("album", album),
        ("title", title),
        ("tracknumber", track_number),
        ("date", year),
        ("genre", genre),
    ]
    for key, val in entries:
        if val is not None:
            tags[key] = [str(val)]


def _write_other_tags(
    fpath: Path,
    artist: str | None,
    album: str | None,
    title: str | None,
    track_number: int | None,
    year: int | None,
    genre: str | None,
    artwork_path: str | Path | None,
) -> bool:
    """Write tags to a non-MP3, non-FLAC audio file using ``mutagen.File``.

    Handles VorbisComment-style tag dictionaries (Ogg Vorbis, Opus, etc.).
    For other tag formats (MP4, ASF, etc.) the file is saved without
    modifications — those formats require format-specific key names.
    """
    import mutagen  # noqa: PLC0415

    audio = mutagen.File(fpath)
    if audio is None:
        logger.warning("Unsupported format or unreadable file: {}", fpath)
        return False

    tags = getattr(audio, "tags", None)

    if isinstance(tags, dict):
        _set_vorbis_dict_tags(tags, artist, album, title, track_number, year, genre)

    audio.save()
    logger.debug("Wrote tags to {} via generic mutagen.File", fpath)
    return True

    audio.save()
    logger.debug("Wrote tags to {} via generic mutagen.File", fpath)
    return True
