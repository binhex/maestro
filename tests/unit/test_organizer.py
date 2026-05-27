"""Tests for maestro.organizer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sqlalchemy import Engine

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Album, Artist, Download, Track
from maestro.organizer import import_downloads

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def engine(tmp_path: Path) -> Engine:  # type: ignore[misc]
    """Create a fresh SQLite engine and initialise tables."""
    db_path = str(tmp_path / "test.db")
    eng = get_engine(db_path, echo=False)
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def download_dir(tmp_path: Path) -> Path:
    """Create an identified download directory with audio files."""
    src = tmp_path / "downloads" / "Some Artist - Some Album"
    src.mkdir(parents=True, exist_ok=True)
    (src / "track01.flac").write_bytes(b"fake flac content 01")
    (src / "track02.flac").write_bytes(b"fake flac content 02")
    (src / "cover.jpg").write_bytes(b"cover image")  # non-audio — ignored
    return src


def _seed_identified_download(
    engine: Engine,
    source_path: str,
    artist: str | None = "Some Artist",
    album: str | None = "Some Album",
    album_id: int | None = None,
) -> int:
    """Insert a Download record with status 'identified' and return its id."""
    session = create_session(engine)
    dl = Download(
        source_path=source_path,
        status="identified",
        identified_artist=artist,
        identified_album=album,
        identified_album_id=album_id,
    )
    session.add(dl)
    session.flush()
    dl_id = dl.id
    session.commit()
    session.close()
    return dl_id


# ===================================================================
# import_downloads — basic move
# ===================================================================


class TestImportMovesFilesAndCreatesRecords:
    """Moving files into the library."""

    def test_import_moves_files_and_creates_records(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Move files, verify source gone, dest exists, DB records created."""
        dest_root = tmp_path / "music"
        pattern = "{artist}/{album}/{filename}.{ext}"

        dl_id = _seed_identified_download(engine, str(download_dir))

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=True,
        )
        session.close()

        # Assert counts
        assert result == {"imported": 1, "skipped": 0, "replaced": 0, "errors": 0}

        # --- Filesystem checks ---
        # Source files should be gone (moved)
        assert not (download_dir / "track01.flac").exists()
        assert not (download_dir / "track02.flac").exists()
        # Source directory itself still exists (only files moved)

        # Dest files should exist
        track1_dest = dest_root / "Some Artist" / "Some Album" / "track01.flac"
        track2_dest = dest_root / "Some Artist" / "Some Album" / "track02.flac"
        assert track1_dest.exists()
        assert track1_dest.read_bytes() == b"fake flac content 01"
        assert track2_dest.exists()
        assert track2_dest.read_bytes() == b"fake flac content 02"
        # cover.jpg should NOT have been moved
        assert not (dest_root / "Some Artist" / "Some Album" / "cover.jpg").exists()

        # --- DB checks ---
        session2 = create_session(engine)
        # Artist
        artist = session2.query(Artist).filter(Artist.name == "Some Artist").first()
        assert artist is not None
        assert artist.slug == "some-artist"

        # Album
        album = session2.query(Album).filter(Album.artist_id == artist.id, Album.title == "Some Album").first()
        assert album is not None

        # Tracks
        tracks = list(session2.query(Track).filter(Track.album_id == album.id).all())
        assert len(tracks) == 2
        track_titles = {t.title for t in tracks}
        assert track_titles == {"track01", "track02"}
        for t in tracks:
            assert t.format == "flac"
            assert t.file_size > 0
            assert t.file_hash is not None
            assert len(t.file_hash) == 16  # truncated SHA-256
            assert t.album_id == album.id

        # Download status updated
        dl = session2.query(Download).filter(Download.id == dl_id).first()
        assert dl is not None
        assert dl.status == "imported"

        session2.close()


# ===================================================================
# import_downloads — copy mode
# ===================================================================


class TestImportCopiesWhenMoveFalse:
    """Copying files into the library (move=False)."""

    def test_import_copies_files_when_move_false(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Copy files — source files still exist after import."""
        dest_root = tmp_path / "music_copy"
        pattern = "{artist}/{album}/{filename}.{ext}"

        dl_id = _seed_identified_download(engine, str(download_dir))

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=False,
        )
        session.close()

        assert result == {"imported": 1, "skipped": 0, "replaced": 0, "errors": 0}

        # Source files still exist
        assert (download_dir / "track01.flac").exists()
        assert (download_dir / "track02.flac").exists()

        # Dest files also exist
        track1_dest = dest_root / "Some Artist" / "Some Album" / "track01.flac"
        track2_dest = dest_root / "Some Artist" / "Some Album" / "track02.flac"
        assert track1_dest.exists()
        assert track2_dest.exists()

        # DB: download is imported
        session2 = create_session(engine)
        dl = session2.query(Download).filter(Download.id == dl_id).first()
        assert dl is not None
        assert dl.status == "imported"
        session2.close()


# ===================================================================
# import_downloads — replacement
# ===================================================================


class TestImportReplacedFilesMovedToReplaced:
    """Replacing existing files in the library."""

    def test_import_replaced_files_moved_to_replaced(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When target exists, old file is moved to _replaced/."""
        dest_root = tmp_path / "music_replace"
        pattern = "{artist}/{album}/{filename}.{ext}"

        # Pre-seed the destination with an existing file
        existing_target = dest_root / "Some Artist" / "Some Album" / "track01.flac"
        existing_target.parent.mkdir(parents=True, exist_ok=True)
        existing_target.write_bytes(b"old content")

        _seed_identified_download(engine, str(download_dir))

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=True,
        )
        session.close()

        # The key check is that the old file ended up in _replaced/.
        assert result["imported"] == 1
        assert result["errors"] == 0

        # The new file was written to the target
        assert existing_target.exists()
        assert existing_target.read_bytes() == b"fake flac content 01"

        # The old file was moved to _replaced/ mirroring the sub-path
        replaced_file = dest_root / "_replaced" / "Some Artist" / "Some Album" / "track01.flac"
        assert replaced_file.exists()
        assert replaced_file.read_bytes() == b"old content"

        # track02 did not exist before, so no replaced file for it
        replaced_track2 = dest_root / "_replaced" / "Some Artist" / "Some Album" / "track02.flac"
        assert not replaced_track2.exists()

        # DB records created as expected
        session2 = create_session(engine)
        artist = session2.query(Artist).filter(Artist.name == "Some Artist").first()
        assert artist is not None
        album = session2.query(Album).filter(Album.artist_id == artist.id, Album.title == "Some Album").first()
        assert album is not None
        tracks = list(session2.query(Track).filter(Track.album_id == album.id).all())
        assert len(tracks) == 2
        session2.close()

    def test_import_replaced_files_delete_when_flag_set(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When delete_replaced=True, old file is deleted, not moved."""
        dest_root = tmp_path / "music_delete"
        pattern = "{artist}/{album}/{filename}.{ext}"

        # Pre-seed the destination
        existing_target = dest_root / "Some Artist" / "Some Album" / "track01.flac"
        existing_target.parent.mkdir(parents=True, exist_ok=True)
        existing_target.write_bytes(b"old content to delete")

        _seed_identified_download(engine, str(download_dir))

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=True,
            delete_replaced=True,
        )
        session.close()

        assert result["imported"] == 1
        assert result["errors"] == 0

        # New content is in place
        assert existing_target.read_bytes() == b"fake flac content 01"

        # No _replaced/ directory was created
        assert not (dest_root / "_replaced").exists()

        # Old file is gone
        # (the new file was moved in its place, so the old content is simply lost)

    def test_import_replaced_files_replaced_count_increments(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When replacing, count reflects how many files were replaced."""
        dest_root = tmp_path / "music_count"
        pattern = "{artist}/{album}/{filename}.{ext}"

        # Pre-seed only track01
        existing_target = dest_root / "Some Artist" / "Some Album" / "track01.flac"
        existing_target.parent.mkdir(parents=True, exist_ok=True)
        existing_target.write_bytes(b"old")

        _seed_identified_download(engine, str(download_dir))

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=True,
            delete_replaced=True,
        )
        session.close()

        # track01 was replaced (1), track02 was new import (2 total)
        assert result["imported"] == 1  # one album imported
        assert result["replaced"] == 1  # one file replaced


# ===================================================================
# import_downloads — edge cases
# ===================================================================


class TestImportEdgeCases:
    """Edge cases and error handling."""

    def test_missing_source_directory(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """A non-existent source directory sets status to error."""
        missing_dir = tmp_path / "downloads" / "nonexistent"
        dl_id = _seed_identified_download(engine, str(missing_dir))

        dest_root = tmp_path / "music"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session.close()

        assert result == {"imported": 0, "skipped": 0, "replaced": 0, "errors": 1}

        session2 = create_session(engine)
        dl = session2.query(Download).filter(Download.id == dl_id).first()
        assert dl is not None
        assert dl.status == "error"
        assert dl.error_message is not None
        session2.close()

    def test_unknown_artist_fallback(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """When identified_artist is None, 'Unknown Artist' is used."""
        src = tmp_path / "downloads" / "Some Album Only"
        src.mkdir(parents=True, exist_ok=True)
        (src / "track.flac").write_bytes(b"content")

        _seed_identified_download(
            engine,
            str(src),
            artist=None,
            album="Some Album Only",
        )

        dest_root = tmp_path / "music_fallback"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session.close()

        assert result["imported"] == 1
        assert result["errors"] == 0

        # Artist should be "Unknown Artist"
        session2 = create_session(engine)
        artist = session2.query(Artist).filter(Artist.name == "Unknown Artist").first()
        assert artist is not None
        assert artist.slug == "unknown-artist"
        session2.close()

        target = dest_root / "Unknown Artist" / "Some Album Only" / "track.flac"
        assert target.exists()

    def test_no_audio_files_marks_error(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """A download directory with no audio files produces an error."""
        src = tmp_path / "downloads" / "No Audio"
        src.mkdir(parents=True, exist_ok=True)
        (src / "readme.txt").write_bytes(b"just text")

        dl_id = _seed_identified_download(engine, str(src))

        dest_root = tmp_path / "music_no_audio"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session.close()

        assert result == {"imported": 0, "skipped": 0, "replaced": 0, "errors": 1}

        session2 = create_session(engine)
        dl = session2.query(Download).filter(Download.id == dl_id).first()
        assert dl is not None
        assert dl.status == "error"
        assert "no audio files" in (dl.error_message or "").lower()
        session2.close()

    def test_identified_album_id_uses_existing_album(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When identified_album_id is set, that album is used directly."""
        session = create_session(engine)

        artist = Artist(name="Some Artist", slug="some-artist")
        session.add(artist)
        session.flush()

        album = Album(
            title="Some Album",
            artist_id=artist.id,
            year=2000,
            genre="Rock",
        )
        session.add(album)
        session.flush()
        album_id = album.id

        dl = Download(
            source_path=str(download_dir),
            status="identified",
            identified_artist="Some Artist",
            identified_album="Some Album",
            identified_album_id=album_id,
            identified_year=2000,
            identified_genre="Rock",
        )
        session.add(dl)
        session.commit()
        session.close()

        dest_root = tmp_path / "music_existing_album"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session2 = create_session(engine)
        result = import_downloads(
            session=session2,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session2.close()

        assert result["imported"] == 1

        # Verify only one album exists (no duplicate created)
        session3 = create_session(engine)
        albums = list(session3.query(Album).all())
        assert len(albums) == 1
        assert albums[0].id == album_id
        session3.close()

    def test_empty_downloads_list(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """No identified downloads returns zero counts."""
        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(tmp_path / "music"),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
        )
        session.close()

        assert result == {"imported": 0, "skipped": 0, "replaced": 0, "errors": 0}

    def test_album_update_fills_missing_year_genre(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When an existing album has missing year/genre, they are filled from the download."""
        session = create_session(engine)
        artist = Artist(name="Some Artist", slug="some-artist")
        session.add(artist)
        session.flush()

        # Create album without year and genre (both None)
        album = Album(
            title="Some Album",
            artist_id=artist.id,
            year=None,
            genre=None,
        )
        session.add(album)
        session.commit()
        session.close()

        # Do NOT set identified_album_id so that _get_or_create_album is called,
        # which will find the existing album by (artist_id, title) and update year/genre
        # Create the download manually with year and genre set
        session2 = create_session(engine)
        dl = Download(
            source_path=str(download_dir),
            status="identified",
            identified_artist="Some Artist",
            identified_album="Some Album",
            identified_year=1999,
            identified_genre="Electronic",
        )
        session2.add(dl)
        session2.commit()
        session2.close()

        dest_root = tmp_path / "music_update"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session3 = create_session(engine)
        result = import_downloads(
            session=session3,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session3.close()

        assert result["imported"] == 1

        # Verify year and genre were updated on the existing album
        session4 = create_session(engine)
        updated_album = session4.query(Album).filter(Album.title == "Some Album").first()
        assert updated_album is not None
        assert updated_album.year == 1999, f"Expected 1999, got {updated_album.year}"
        assert updated_album.genre == "Electronic", f"Expected Electronic, got {updated_album.genre}"
        session4.close()

    def test_non_existent_album_id_creates_new_album(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When identified_album_id points to a non-existent album, a new album is created."""
        _seed_identified_download(engine, str(download_dir), album_id=99999)

        dest_root = tmp_path / "music_new_album"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session.close()

        assert result["imported"] == 1

        session2 = create_session(engine)
        albums = list(session2.query(Album).all())
        assert len(albums) == 1
        assert albums[0].title == "Some Album"
        session2.close()

    def test_import_skip_existing_higher_quality_track(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When library has equal or better quality, existing tracks are skipped."""
        session = create_session(engine)
        artist = Artist(name="Some Artist", slug="some-artist")
        session.add(artist)
        session.flush()

        # Create an album with existing tracks that have the same names
        album = Album(title="Some Album", artist_id=artist.id, year=2020, genre="Test")
        session.add(album)
        session.flush()

        # Existing track at same quality tier as download (FLAC → compare_tracks returns "skip")
        track1 = Track(
            album_id=album.id,
            title="track01",
            format="FLAC",
            bitrate=None,
            file_path=str(download_dir / "track01.flac"),
            file_size=100,
            file_hash="aabbccddeeff0011",
        )
        session.add(track1)
        track2 = Track(
            album_id=album.id,
            title="track02",
            format="FLAC",
            bitrate=None,
            file_path=str(download_dir / "track02.flac"),
            file_size=100,
            file_hash="1122334455667788",
        )
        session.add(track2)
        session.commit()
        album_id = album.id
        session.close()

        # Seed download with album_id pointing to the album with existing tracks
        _seed_identified_download(engine, str(download_dir), album_id=album_id)

        dest_root = tmp_path / "music_skip"
        pattern = "{artist}/{album}/{filename}.{ext}"

        session2 = create_session(engine)
        result = import_downloads(
            session=session2,
            destination_root=str(dest_root),
            destination_pattern=pattern,
            move=True,
        )
        session2.close()

        # Both tracks should be skipped (FLAC vs FLAC → same tier)
        # The album is still imported with 1 count, but tracks are skipped
        assert result["imported"] == 1
        assert result["skipped"] == 2
        assert result["errors"] == 0

    def test_path_traversal_guard_skips_escaping_path(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """When a rendered path escapes destination root, it is skipped silently."""
        # Use a pattern with .. segment so the resolved path escapes dest_root
        src = tmp_path / "downloads" / "Traversal"
        src.mkdir(parents=True, exist_ok=True)
        (src / "track.flac").write_bytes(b"content")

        _seed_identified_download(engine, str(src), artist="Some Artist", album="Album")

        dest_root = tmp_path / "music_traversal"
        # Pattern starting with ../ will cause rendered path to escape
        pattern = "../../{artist}/{album}/{filename}.{ext}"

        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(dest_root),
            destination_pattern=pattern,
        )
        session.close()

        # The import succeeds (album is created, but file is skipped due to traversal)
        assert result["imported"] == 1

        # The file should not exist at the escaped location
        escaped = dest_root.parent.parent / "Some Artist" / "Album" / "track.flac"
        assert not escaped.exists()

        # File should also not exist within dest_root
        within = dest_root / ".." / ".." / "Some Artist" / "Album" / "track.flac"
        assert not within.exists()

    def test_import_exception_sets_error_status(
        self,
        engine: Engine,
        download_dir: Path,
        tmp_path: Path,
    ) -> None:
        """When processing a download raises, status is set to error."""
        from unittest.mock import patch

        _seed_identified_download(engine, str(download_dir))

        with patch("maestro.organizer._process_download", side_effect=RuntimeError("Unexpected error")):
            session = create_session(engine)
            result = import_downloads(
                session=session,
                destination_root=str(tmp_path / "music"),
                destination_pattern="{artist}/{album}/{filename}.{ext}",
            )
            session.close()

        assert result["imported"] == 0
        assert result["errors"] == 1

        session2 = create_session(engine)
        dl = session2.query(Download).first()
        assert dl is not None
        assert dl.status == "error"
        assert dl.error_message is not None
        session2.close()


# ===================================================================
# import_downloads — dry-run
# ===================================================================


class TestImportDownloadsDryRun:
    """Tests for dry-run mode in import_downloads."""

    def test_import_downloads_dry_run_returns_actions(
        self,
        engine,
        download_dir,
    ) -> None:
        """Dry run should return actions list instead of mutating files."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        assert result["dry_run"] is True
        assert isinstance(result["actions"], list)
        # Should have at least one "Would move:" action for the track(s)
        move_actions = [a for a in result["actions"] if a.startswith("Would move")]
        assert len(move_actions) > 0

    def test_import_downloads_dry_run_does_not_mutate_db(
        self,
        engine,
        download_dir,
    ) -> None:
        """Dry run must NOT create Artist/Album/Track records or change download status."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        # Count records before
        artist_count_before = session.query(Artist).count()
        album_count_before = session.query(Album).count()
        track_count_before = session.query(Track).count()
        dl = session.query(Download).first()
        assert dl is not None
        dl_status_before = dl.status

        lib_root = str(download_dir.parent.parent / "library")
        import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        # No new records
        assert session.query(Artist).count() == artist_count_before
        assert session.query(Album).count() == album_count_before
        assert session.query(Track).count() == track_count_before

        # Download status unchanged
        session.refresh(dl)
        assert dl.status == dl_status_before

    def test_import_downloads_dry_run_does_not_create_files(
        self,
        engine,
        download_dir,
    ) -> None:
        """Dry run must not create any files or directories in the library root."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        lib_path = Path(lib_root)

        import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        # Library root should not exist (was never created)
        assert not lib_path.exists()

    def test_import_downloads_dry_run_returns_zero_import_count(
        self,
        engine,
        download_dir,
    ) -> None:
        """Dry run must return imported=0 regardless of what would happen."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        lib_root = str(download_dir.parent.parent / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        assert result["imported"] == 0

    def test_import_downloads_dry_run_reports_replacement(
        self,
        engine,
        download_dir,
        tmp_path,
    ) -> None:
        """When the target library file already exists, dry-run should say 'Would replace:'."""
        _seed_identified_download(engine, str(download_dir))
        session = create_session(engine)

        # Create a library root with a pre-existing file at the target path
        lib_root = tmp_path / "library"
        # Expected target path: {artist}/{album}/{filename}.{ext}
        target_dir = lib_root / "Some Artist" / "Some Album"
        target_dir.mkdir(parents=True)
        (target_dir / "track01.flac").write_bytes(b"existing")
        (target_dir / "track02.flac").write_bytes(b"existing")

        lib_root_str = str(lib_root)
        result = import_downloads(
            session=session,
            destination_root=lib_root_str,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )

        replace_actions = [a for a in result.get("actions", []) if a.startswith("Would replace")]
        assert len(replace_actions) > 0, f"Expected 'Would replace' actions, got: {result.get('actions', [])}"

    def test_import_downloads_dry_run_quality_skip(
        self,
        engine,
        download_dir,
        tmp_path,
    ) -> None:
        """When a better-quality library version exists, dry-run says 'Would skip:'."""
        from maestro.db.models import Album, Artist, Track

        # First, create a library album with existing tracks
        session = create_session(engine)
        artist = Artist(name="Some Artist", slug="some-artist")
        session.add(artist)
        session.flush()

        album = Album(title="Some Album", artist_id=artist.id, year=2020, genre="Test")
        session.add(album)
        session.flush()
        album_id = album.id

        # Existing tracks at higher quality (FLAC) — same stems as download files
        for name in ("track01", "track02"):
            track = Track(
                album_id=album_id,
                title=name,
                format="FLAC",
                bitrate=1411,
                file_path=str(download_dir / f"{name}.flac"),
                file_size=100,
                file_hash="aabbccddeeff0011",
            )
            session.add(track)
        session.commit()
        session.close()

        # Now seed the download with a reference to this album
        _seed_identified_download(engine, str(download_dir), album_id=album_id)

        session2 = create_session(engine)
        lib_root = str(tmp_path / "library")
        result = import_downloads(
            session=session2,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )
        session2.close()

        assert result["dry_run"] is True
        skip_actions = [a for a in result.get("actions", []) if a.startswith("Would skip")]
        assert len(skip_actions) > 0, f"Expected quality skip actions, got: {result.get('actions', [])}"

    def test_import_downloads_dry_run_empty_downloads(
        self,
        engine,
        tmp_path,
    ) -> None:
        """Dry-run with no identified downloads returns empty actions."""
        session = create_session(engine)
        result = import_downloads(
            session=session,
            destination_root=str(tmp_path / "library"),
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )
        session.close()

        assert result["dry_run"] is True
        assert result["actions"] == []
        assert result["imported"] == 0

    def test_import_downloads_dry_run_skip_missing_source(
        self,
        engine,
        tmp_path,
    ) -> None:
        """Dry-run with a missing source directory says 'Would skip'."""
        missing_dir = tmp_path / "downloads" / "nonexistent"
        _seed_identified_download(engine, str(missing_dir))

        session = create_session(engine)
        lib_root = str(tmp_path / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )
        session.close()

        assert result["dry_run"] is True
        skip_actions = [a for a in result.get("actions", []) if a.startswith("Would skip")]
        assert len(skip_actions) > 0

    def test_import_downloads_dry_run_skip_no_audio(
        self,
        engine,
        tmp_path,
    ) -> None:
        """Dry-run with no audio files says 'Would skip'."""
        src = tmp_path / "downloads" / "No Audio"
        src.mkdir(parents=True, exist_ok=True)
        (src / "readme.txt").write_bytes(b"just text")
        _seed_identified_download(engine, str(src))

        session = create_session(engine)
        lib_root = str(tmp_path / "library")
        result = import_downloads(
            session=session,
            destination_root=lib_root,
            destination_pattern="{artist}/{album}/{filename}.{ext}",
            move=True,
            dry_run=True,
        )
        session.close()

        assert result["dry_run"] is True
        skip_actions = [a for a in result.get("actions", []) if a.startswith("Would skip")]
        assert len(skip_actions) > 0
