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
