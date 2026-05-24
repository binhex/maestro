"""Tests for maestro.scanner."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Download, FileSystemSnapshot
from maestro.scanner import scan_download_root


def _make_audio_file(base_dir: Path, rel_path: str) -> Path:
    """Create a dummy audio file and return its path."""
    path = base_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake audio content")
    return path


class TestScannerCreatesDownloadRecords:
    """Scan a download root with audio files creates Download records."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:  # type: ignore[misc]
        """Create a fresh SQLite engine and initialise tables."""
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_creates_download_for_album_dir(self, engine: Engine, tmp_path: Path) -> None:
        """Audio files in a subdirectory produce one Download with status 'new'."""
        root = tmp_path / "downloads"
        album_dir = root / "Some Album"
        _make_audio_file(album_dir, "track01.flac")
        _make_audio_file(album_dir, "track02.flac")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 1

        session2 = create_session(engine)
        downloads = list(session2.query(Download))
        session2.close()

        assert len(downloads) == 1
        assert downloads[0].status == "new"
        assert downloads[0].source_path == str(album_dir)

    def test_creates_separate_downloads_for_multiple_dirs(self, engine: Engine, tmp_path: Path) -> None:
        """Two album directories each get their own Download."""
        root = tmp_path / "downloads2"
        _make_audio_file(root / "Album A", "track.flac")
        _make_audio_file(root / "Album B", "track.flac")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 2

        session2 = create_session(engine)
        count = session2.query(Download).count()
        session2.close()
        assert count == 2


class TestScannerSkipsNonAudioFiles:
    """Non-audio files are ignored by the scanner."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:  # type: ignore[misc]
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_txt_files_produce_no_downloads(self, engine: Engine, tmp_path: Path) -> None:
        root = tmp_path / "no_audio"
        album_dir = root / "Notes"
        album_dir.mkdir(parents=True, exist_ok=True)
        (album_dir / "readme.txt").write_bytes(b"hello")
        (album_dir / "cover.jpg").write_bytes(b"image")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 0

        session2 = create_session(engine)
        count = session2.query(Download).count()
        session2.close()
        assert count == 0


class TestScannerCreatesSnapshots:
    """FileSystemSnapshot records are created for each audio file."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:  # type: ignore[misc]
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_snapshot_per_file(self, engine: Engine, tmp_path: Path) -> None:
        root = tmp_path / "snap_test"
        _make_audio_file(root / "Album", "track01.flac")
        _make_audio_file(root / "Album", "track02.ogg")
        _make_audio_file(root / "Album", "track03.mp3")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 1  # one album dir → one Download

        session2 = create_session(engine)
        snapshots = list(session2.query(FileSystemSnapshot))
        session2.close()

        assert len(snapshots) == 3
        paths = {s.path for s in snapshots}
        assert any(p.endswith("track01.flac") for p in paths)
        assert any(p.endswith("track02.ogg") for p in paths)
        assert any(p.endswith("track03.mp3") for p in paths)

    def test_snapshot_has_hash_and_size(self, engine: Engine, tmp_path: Path) -> None:
        """Each snapshot has a non-empty file_hash and correct file_size."""
        root = tmp_path / "snap_meta"
        _make_audio_file(root / "Album", "track.flac")

        session = create_session(engine)
        scan_download_root(session, root)
        session.close()

        session2 = create_session(engine)
        snap = session2.query(FileSystemSnapshot).one()
        session2.close()

        assert snap.file_hash is not None
        assert len(snap.file_hash) > 0
        assert snap.file_size > 0


class TestScannerSkipsExistingOnRescan:
    """Re-scanning the same directory skips already-tracked albums."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:  # type: ignore[misc]
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_second_scan_skips_existing(self, engine: Engine, tmp_path: Path) -> None:
        root = tmp_path / "rescan"
        _make_audio_file(root / "Album", "track.flac")

        session = create_session(engine)
        r1 = scan_download_root(session, root)
        session.close()
        assert r1["created"] == 1

        session2 = create_session(engine)
        r2 = scan_download_root(session2, root)
        session2.close()

        assert r2["created"] == 0
        assert r2["skipped"] >= 1

        # Total Download count stays at 1
        session3 = create_session(engine)
        count = session3.query(Download).count()
        session3.close()
        assert count == 1


class TestScannerDetectsCdSubdirectories:
    """CD subdirectories are collapsed into a single album directory."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Engine:  # type: ignore[misc]
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    @pytest.mark.parametrize(
        "subdir_name",
        ["CD1", "CD 2", "disc1", "Disc 1", "disk1", "cdrom", "CD_01"],
    )
    def test_cd_subdir_collapses_to_one_download(self, engine: Engine, tmp_path: Path, subdir_name: str) -> None:
        """Files under CD subdirectories produce one Download for the parent."""
        root = tmp_path / "cd_test"
        album_dir = root / "Greatest Hits"
        _make_audio_file(album_dir / subdir_name, "track01.flac")
        _make_audio_file(album_dir / subdir_name, "track02.flac")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 1

        session2 = create_session(engine)
        dl = session2.query(Download).one()
        session2.close()

        assert dl.source_path == str(album_dir)

    def test_two_cd_subdirs_one_album(self, engine: Engine, tmp_path: Path) -> None:
        """Audio in CD1 and CD2 of the same album yields one Download."""
        root = tmp_path / "two_cds"
        album_dir = root / "Double Album"
        _make_audio_file(album_dir / "CD1", "track01.flac")
        _make_audio_file(album_dir / "CD2", "track01.flac")

        session = create_session(engine)
        result = scan_download_root(session, root)
        session.close()

        assert result["created"] == 1

        session2 = create_session(engine)
        count = session2.query(Download).count()
        session2.close()
        assert count == 1
        snap_count = session2.query(FileSystemSnapshot).count()
        assert snap_count == 2
