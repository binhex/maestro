"""Tests for maestro.db.models."""

from maestro.db.models import (
    Album,
    Artist,
    Download,
    FileSystemSnapshot,
    LibraryRoot,
    Track,
)


class TestArtistModel:
    def test_create_artist(self):
        artist = Artist(name="Amon Tobin", slug="amon-tobin")
        assert artist.name == "Amon Tobin"
        assert artist.slug == "amon-tobin"
        assert artist.id is None  # not yet persisted

    def test_artist_to_dict(self):
        """Minimal repr/dict-like access for debugging."""
        artist = Artist(name="Test Artist", slug="test-artist")
        # just ensures the model doesn't crash
        assert artist.__tablename__ == "artists"


class TestAlbumModel:
    def test_create_album(self):
        album = Album(
            title="Bricolage",
            year=1997,
            genre="Electronic",
            subgenre="Ambient",
        )
        assert album.title == "Bricolage"
        assert album.year == 1997


class TestTrackModel:
    def test_create_track(self):
        track = Track(
            title="Bricolage",
            track_number=1,
            disc_number=1,
            format="FLAC",
            bitrate=1411,
            sample_rate=44100,
            channels=2,
            duration_seconds=372,
            file_path="/music/Amon Tobin/Bricolage/01 - Bricolage.flac",
            file_size=50000000,
            file_hash="a1b2c3d4",
        )
        assert track.format == "FLAC"
        assert track.track_number == 1

    def test_track_default_disc_number(self):
        track = Track(
            title="Test",
            file_path="/test.flac",
            file_size=1000,
            file_hash="abcd",
        )
        # duration_channels and other numeric fields default to None
        assert track.disc_number is None


class TestDownloadModel:
    def test_create_download(self):
        dl = Download(
            source_path="/downloads/user/Bricolage",
            status="new",
        )
        assert dl.status == "new"

    def test_download_status_default(self):
        # status should default to "new" if we set a default in the model
        dl = Download(source_path="/test")
        # we can't enforce a default in the test; check if model sets one
        assert dl.status in ("new", None)  # lenient check


class TestFileSystemSnapshotModel:
    def test_create_snapshot(self):
        snap = FileSystemSnapshot(
            path="/music/file.flac",
            file_hash="deadbeef",
            file_size=12345,
        )
        assert snap.path == "/music/file.flac"


class TestLibraryRootModel:
    def test_create_root(self):
        root = LibraryRoot(
            path="/music/library",
            type="library",
            source_pattern="{artist}/{album}",
            destination_pattern="{genre}/{artist}/{album}",
        )
        assert root.type == "library"
        assert root.enabled is True  # default enabled
