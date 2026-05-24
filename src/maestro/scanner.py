"""Filesystem scanner — walk directories, detect audio files, create records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maestro.db.models import Download, FileSystemSnapshot

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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

_CD_SUBDIR_PREFIXES: tuple[str, ...] = ("cd", "disc", "disk", "cdrom")


def _is_audio_file(path: Path) -> bool:
    """Return True if *path* has an audio-file extension (case-insensitive)."""
    return path.suffix.lower() in AUDIO_EXTENSIONS


def _get_file_hash(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 digest of *path* and return the first 16 hex characters."""
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _is_cd_subdirectory(dir_name: str) -> bool:
    """Return True if *dir_name* matches a CD / disc subdirectory pattern."""
    normalised = dir_name.lower().replace(" ", "").replace("_", "").replace("-", "")
    return any(normalised.startswith(p) for p in _CD_SUBDIR_PREFIXES)


def _album_dir_for_file(file_path: Path) -> Path:
    """Determine the album directory for an audio file.

    If the file lies inside a CD subdirectory the grandparent is returned;
    otherwise the immediate parent is returned.
    """
    parent = file_path.parent
    if parent.name and _is_cd_subdirectory(parent.name):
        return parent.parent
    return parent


def scan_download_root(
    session: Session,
    root_path: str | Path,
    pattern: str | None = None,
) -> dict[str, int]:
    """Walk *root_path*, find audio files, and create Download / Snapshot records.

    Audio files are grouped by album directory (parent folder, or grandparent
    when inside a CD subdirectory).  One ``Download`` record is created per
    unique album directory if one does not already exist.  A
    ``FileSystemSnapshot`` record is created for every audio file discovered.

    Parameters
    ----------
    session:
        An active SQLAlchemy ``Session`` bound to the Maestro database.
    root_path:
        The top-level download directory to scan.
    pattern:
        Reserved for future use (e.g. glob pattern filtering).  Currently
        ignored — all audio files are scanned.

    Returns
    -------
    dict[str, int]
        ``{"created": N, "skipped": N, "removed": 0}``
    """
    del pattern  # reserved for future use

    root = Path(root_path).resolve()
    if not root.is_dir():
        return {"created": 0, "skipped": 0, "removed": 0}

    # Gather all audio files, grouped by album directory
    album_files: dict[Path, list[Path]] = {}
    for fpath in root.rglob("*"):
        if not fpath.is_file() or not _is_audio_file(fpath):
            continue
        album_dir = _album_dir_for_file(fpath)
        # Skip files whose album directory is the scan root itself (no
        # meaningful album grouping).
        if album_dir == root:
            continue
        album_files.setdefault(album_dir, []).append(fpath)

    created = 0
    skipped = 0

    existing_paths: set[str] = {row[0] for row in session.query(Download.source_path).distinct().all()}

    for album_dir, files in album_files.items():
        album_path_str = str(album_dir)

        if album_path_str in existing_paths:
            skipped += 1
        else:
            dl = Download(source_path=album_path_str, status="new")
            session.add(dl)
            session.flush()
            existing_paths.add(album_path_str)
            created += 1

        for afile in files:
            # Skip duplicate snapshots on re-scan
            existing_snap = (
                session.query(FileSystemSnapshot)
                .filter(
                    FileSystemSnapshot.path == str(afile),
                )
                .first()
            )
            if existing_snap is not None:
                continue
            file_stat = afile.stat()
            snapshot = FileSystemSnapshot(
                path=str(afile),
                file_hash=_get_file_hash(afile),
                file_size=file_stat.st_size,
                modified_at=datetime.fromtimestamp(file_stat.st_mtime, tz=UTC),
            )
            session.add(snapshot)

    session.commit()

    # Count new snapshots (those created this session)
    return {"created": created, "skipped": skipped, "removed": 0}


def _create_artist_album_track(
    session: Session,
    artist_name: str,
    album_title: str,
    track_path: Path,
    **track_meta: Any,
) -> None:
    """Create or retrieve Artist, Album, and Track records.

    This is an internal helper for :func:`scan_library_root` and is not
    intended to be called directly.
    """
    # TODO: implement library scanning logic when scan_library_root is built
    raise NotImplementedError  # pragma: no cover


def scan_library_root(
    session: Session,
    root_path: str | Path,
) -> dict[str, int]:
    """Walk *root_path* following an artist/album/track structure.

    .. warning::
       Not yet implemented.
    """
    raise NotImplementedError  # pragma: no cover
