"""Tests for maestro.identifier."""

from collections.abc import Generator
from pathlib import Path

import pytest
import pytest_mock
from sqlalchemy import Engine

from maestro import identifier as mid
from maestro.db.core import create_session, get_engine, init_db
from maestro.db.models import Album, Artist, Download
from maestro.identifier import (
    identify_download,
    identify_downloads,
    parse_filename_heuristic,
)


def _test_path(p: Path) -> str:
    return str(p)


# ===================================================================
# parse_filename_heuristic
# ===================================================================


class TestParseFilenameHeuristic:
    """parse_filename_heuristic extracts artist/album from folder names."""

    def test_dash_separator(self) -> None:
        """Space-dash-space split yields artist and album."""
        artist, album = parse_filename_heuristic("Artist - Album")
        assert artist == "Artist"
        assert album == "Album"

    def test_underscore_separator(self) -> None:
        """Underscore split yields artist and album."""
        artist, album = parse_filename_heuristic("Artist_Album")
        assert artist == "Artist"
        assert album == "Album"

    def test_no_separator(self) -> None:
        """No separator returns None for artist and full name as album."""
        artist, album = parse_filename_heuristic("NoSeparator")
        assert artist is None
        assert album == "NoSeparator"

    def test_empty_string(self) -> None:
        """Empty string returns (None, '')."""
        artist, album = parse_filename_heuristic("")
        assert artist is None
        assert album == ""

    def test_multiple_dashes(self) -> None:
        """Multiple dashes — leftmost dash is the artist/album boundary."""
        artist, album = parse_filename_heuristic("Artist - Part - Album")
        assert artist == "Artist"
        assert album == "Part - Album"

    def test_dash_whitespace_stripped(self) -> None:
        """Extra whitespace around the dash separator is stripped."""
        artist, album = parse_filename_heuristic("  Artist   -   Album  ")
        assert artist == "Artist"
        assert album == "Album"

    def test_underscore_multiple_parts(self) -> None:
        """Underscore — leftmost separator wins."""
        artist, album = parse_filename_heuristic("Artist_Album_Suffix")
        assert artist == "Artist"
        assert album == "Album_Suffix"

    def test_only_dash_no_spaces(self) -> None:
        """Dash without spaces is still matched by the dash pattern.

        The pattern ``^(.*?)\\s*-\\s*(.*)$`` requires optional whitespace
        around the dash, so ``"A-B"`` with no spaces still matches because
        ``\\s*`` matches zero spaces.
        """
        artist, album = parse_filename_heuristic("A-B")
        assert artist == "A"
        assert album == "B"

    def test_artist_none_for_only_dash(self) -> None:
        """A string that is just '-' yields artist None, album ''."""
        artist, album = parse_filename_heuristic("-")
        assert artist is None
        assert album == ""


# ===================================================================
# identify_download — tag path
# ===================================================================


class TestIdentifyDownloadWithTags:
    """identify_download with mocked ID3 tags."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Generator[Engine, None, None]:
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    # ---- tag extraction sets fields ----

    def test_tags_set_fields(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tags are found the identified fields are populated from them."""
        dl_dir = tmp_path / "Some Artist - Some Album"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch(
            "maestro.identifier._read_id3_tags",
            return_value={
                "artist": "Some Artist",
                "album": "Some Album",
                "title": "Some Title",
                "track": 1,
                "year": 1999,
                "genre": "Rock",
            },
        )

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist == "Some Artist"
        assert dl.identified_album == "Some Album"
        assert dl.identified_year == 1999
        assert dl.identified_genre == "Rock"
        assert dl.match_type == "exact"
        assert dl.status == "identified"

    # ---- tag fields carry through without library match ----

    def test_tags_no_library_match(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Tags without a library match still have fields set, no album_id."""
        dl_dir = tmp_path / "Unknown Artist - Unknown Album"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch(
            "maestro.identifier._read_id3_tags",
            return_value={
                "artist": "Unknown Artist",
                "album": "Unknown Album",
                "title": "Song",
                "track": 3,
                "year": 2020,
                "genre": "Jazz",
            },
        )

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist == "Unknown Artist"
        assert dl.identified_album == "Unknown Album"
        assert dl.identified_year == 2020
        assert dl.identified_genre == "Jazz"
        assert dl.match_type == "exact"
        assert dl.identified_album_id is None

    # ---- tags match existing library album ----

    def test_tags_matches_library_album(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tags match a library Artist+Album, album_id is set."""
        dl_dir = tmp_path / "Known - Album2025"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)

        artist = Artist(name="Known", slug="known")
        session.add(artist)
        session.flush()

        album = Album(title="Album2025", artist_id=artist.id, year=2025, genre="Pop")
        session.add(album)
        session.flush()

        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch(
            "maestro.identifier._read_id3_tags",
            return_value={
                "artist": "Known",
                "album": "Album2025",
                "title": "Hit",
                "track": 1,
                "year": 2025,
                "genre": "Pop",
            },
        )

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist == "Known"
        assert dl.identified_album == "Album2025"
        assert dl.identified_year == 2025
        assert dl.identified_genre == "Pop"
        assert dl.match_type == "exact"
        assert dl.identified_album_id == album.id

    # ---- tags missing year/genre fills from library ----

    def test_tags_fills_year_genre_from_library(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tags lack year/genre, values from the matched album are used."""
        dl_dir = tmp_path / "Fill - Me"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)

        artist = Artist(name="Fill", slug="fill")
        session.add(artist)
        session.flush()

        album = Album(title="Me", artist_id=artist.id, year=2000, genre="Classical")
        session.add(album)
        session.flush()

        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        # Tags with no year or genre
        mocker.patch(
            "maestro.identifier._read_id3_tags",
            return_value={
                "artist": "Fill",
                "album": "Me",
                "title": "Track 1",
                "track": 1,
                "year": None,
                "genre": None,
            },
        )

        identify_download(dl, session)
        session.close()

        assert dl.identified_year == 2000
        assert dl.identified_genre == "Classical"

    # ---- missing directory returns early ----

    def test_missing_directory_returns_early(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """If the source_path directory does not exist, the function returns."""
        nonexistent = tmp_path / "does-not-exist"
        session = create_session(engine)
        dl = Download(source_path=str(nonexistent), status="new")
        session.add(dl)
        session.flush()

        spy = mocker.spy(mid, "_read_id3_tags")
        identify_download(dl, session)
        session.close()

        spy.assert_not_called()
        assert dl.status == "new"  # unchanged
        assert dl.identified_artist is None

    def test_directory_with_only_nonexistent_path(
        self,
        engine: Engine,
        tmp_path: Path,
    ) -> None:
        """The path doesn't exist — nothing changes."""
        session = create_session(engine)
        dl = Download(source_path="/tmp/nonexistent_maestro_test_dir_xyz", status="new")
        session.add(dl)
        session.flush()

        identify_download(dl, session)
        session.close()

        assert dl.status == "new"
        assert dl.identified_artist is None
        assert dl.identified_album is None


# ===================================================================
# identify_download — heuristic path (no tags)
# ===================================================================


class TestIdentifyDownloadNoTags:
    """identify_download falls back to heuristic when no tags exist."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Generator[Engine, None, None]:
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_no_tags_uses_heuristic(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When _read_id3_tags returns None, the heuristic is used."""
        dl_dir = tmp_path / "Test Artist - Test Album"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch("maestro.identifier._read_id3_tags", return_value=None)

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist == "Test Artist"
        assert dl.identified_album == "Test Album"
        assert dl.match_type is None
        assert dl.status == "identified"

    def test_heuristic_no_separator(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When heuristic finds no separator, album is the folder name."""
        dl_dir = tmp_path / "JustAlbumName"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch("maestro.identifier._read_id3_tags", return_value=None)

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist is None
        assert dl.identified_album == "JustAlbumName"
        assert dl.match_type is None

    def test_heuristic_with_library_match(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Heuristic match can also resolve against the library."""
        dl_dir = tmp_path / "KnownArtist - KnownAlbum"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)

        artist = Artist(name="KnownArtist", slug="knownartist")
        session.add(artist)
        session.flush()
        album = Album(title="KnownAlbum", artist_id=artist.id, year=2010, genre="Electronic")
        session.add(album)
        session.flush()

        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.flush()

        mocker.patch("maestro.identifier._read_id3_tags", return_value=None)

        identify_download(dl, session)
        session.close()

        assert dl.identified_artist == "KnownArtist"
        assert dl.identified_album == "KnownAlbum"
        assert dl.match_type == "exact"
        assert dl.identified_album_id == album.id
        # Year/genre filled from library match
        assert dl.identified_year == 2010
        assert dl.identified_genre == "Electronic"


# ===================================================================
# identify_downloads
# ===================================================================


class TestIdentifyDownloads:
    """identify_downloads processes all new downloads."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Generator[Engine, None, None]:
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_processes_new_downloads(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """All 'new' downloads are identified."""
        dl_dir = tmp_path / "Artist - Album"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.commit()
        session.close()

        mocker.patch("maestro.identifier._read_id3_tags", return_value=None)

        session2 = create_session(engine)
        results = identify_downloads(session2)

        # Access attributes before closing (commit expires objects)
        assert len(results) == 1
        assert results[0].identified_artist == "Artist"
        assert results[0].identified_album == "Album"
        assert results[0].status == "identified"
        session2.close()

    def test_skips_non_new_downloads(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Only 'new' downloads are identified."""
        dl_dir1 = tmp_path / "Artist1 - Album1"
        dl_dir1.mkdir(parents=True, exist_ok=True)
        dl_dir2 = tmp_path / "Artist2 - Album2"
        dl_dir2.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl1 = Download(source_path=str(dl_dir1), status="new")
        dl2 = Download(source_path=str(dl_dir2), status="imported")
        session.add_all([dl1, dl2])
        session.commit()
        session.close()

        mocker.patch("maestro.identifier._read_id3_tags", return_value=None)

        session2 = create_session(engine)
        results = identify_downloads(session2)

        # Access attributes before closing (commit expires objects)
        assert len(results) == 1
        assert results[0].source_path == str(dl_dir1)
        session2.close()

    def test_error_sets_status_to_error(
        self,
        engine: Engine,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """If identify_download raises, status is set to 'error'."""
        dl_dir = tmp_path / "Artist - Album"
        dl_dir.mkdir(parents=True, exist_ok=True)

        session = create_session(engine)
        dl = Download(source_path=str(dl_dir), status="new")
        session.add(dl)
        session.commit()
        session.close()

        mocker.patch(
            "maestro.identifier.identify_download",
            side_effect=RuntimeError("test error"),
        )

        session2 = create_session(engine)
        results = identify_downloads(session2)

        # Access attributes before closing (commit expires objects)
        assert len(results) == 1
        assert results[0].status == "error"
        session2.close()


# ===================================================================
# Tag-reading helper functions
# ===================================================================


class TestVorbisFirst:
    """Tests for _vorbis_first."""

    def test_returns_first_value(self) -> None:
        result = mid._vorbis_first({"artist": ["Amon Tobin", "Other"]}, "artist")
        assert result == "Amon Tobin"

    def test_returns_none_for_missing_key(self) -> None:
        result = mid._vorbis_first({"album": ["Test"]}, "artist")
        assert result is None

    def test_returns_none_for_empty_list(self) -> None:
        result = mid._vorbis_first({"artist": []}, "artist")
        assert result is None

    def test_returns_none_on_exception(self) -> None:
        result = mid._vorbis_first(None, "artist")
        assert result is None


class TestId3Text:
    """Tests for _id3_text."""

    def test_returns_text_from_frame(self) -> None:
        class MockFrame:
            def __str__(self) -> str:
                return "Test Value"

        class MockTags:
            def getall(self, frame_id: str) -> list:
                return [MockFrame()]

        result = mid._id3_text(MockTags(), "TPE1")
        assert result == "Test Value"

    def test_returns_none_for_missing_frame(self) -> None:
        class MockTags:
            def getall(self, frame_id: str) -> list:
                return []

        result = mid._id3_text(MockTags(), "TPE1")
        assert result is None

    def test_returns_none_on_exception(self) -> None:
        class MockTags:
            def getall(self, frame_id: str) -> list:
                raise RuntimeError

        result = mid._id3_text(MockTags(), "TPE1")
        assert result is None


class TestParseInt:
    """Tests for _parse_int."""

    def test_parses_valid_int(self) -> None:
        assert mid._parse_int("42") == 42

    def test_handles_whitespace(self) -> None:
        assert mid._parse_int("  42  ") == 42

    def test_returns_none_for_none(self) -> None:
        assert mid._parse_int(None) is None

    def test_returns_none_for_invalid(self) -> None:
        assert mid._parse_int("not-a-number") is None


class TestId3Track:
    """Tests for _id3_track."""

    def test_simple_track_number(self) -> None:
        class MockFrame:
            def __str__(self) -> str:
                return "3"

        class MockTags:
            def getall(self, frame_id: str) -> list:
                return [MockFrame()]

        result = mid._id3_track(MockTags(), "TRCK")
        assert result == 3

    def test_track_with_total(self) -> None:
        class MockFrame:
            def __str__(self) -> str:
                return "3/12"

        class MockTags:
            def getall(self, frame_id: str) -> list:
                return [MockFrame()]

        result = mid._id3_track(MockTags(), "TRCK")
        assert result == 3

    def test_returns_none_when_missing(self) -> None:
        class MockTags:
            def getall(self, frame_id: str) -> list:
                return []

        result = mid._id3_track(MockTags(), "TRCK")
        assert result is None


class TestReadId3Tags:
    """Tests for _read_id3_tags with mocked extraction."""

    def test_returns_none_for_empty_dir(self, tmp_path: Path, mocker) -> None:
        """A directory with no audio files returns None."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = mid._read_id3_tags(empty_dir)
        assert result is None

    def test_returns_none_when_extract_returns_none(self, tmp_path: Path, mocker) -> None:
        """When _extract_tags_from_file returns None, _read_id3_tags returns None."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        (dl_dir / "track.flac").write_text("data")
        mocker.patch("maestro.identifier._extract_tags_from_file", return_value=None)
        result = mid._read_id3_tags(dl_dir)
        assert result is None

    def test_returns_tags_when_found(self, tmp_path: Path, mocker) -> None:
        """When a file has tags, they are returned."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        (dl_dir / "track.flac").write_text("data")
        expected = {"artist": "Test", "album": "Album", "title": "Track"}
        mocker.patch("maestro.identifier._extract_tags_from_file", return_value=expected)
        result = mid._read_id3_tags(dl_dir)
        assert result == expected

    def test_returns_tags_from_first_file_with_tags(self, tmp_path: Path, mocker) -> None:
        """Skips files without tags, returns first with tags."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        (dl_dir / "track1.flac").write_text("data")
        (dl_dir / "track2.flac").write_text("data")
        mocker.patch(
            "maestro.identifier._extract_tags_from_file",
            side_effect=[None, {"artist": "Found"}],
        )
        result = mid._read_id3_tags(dl_dir)
        assert result == {"artist": "Found"}


class TestExtractTagsFromFile:
    """Tests for _extract_tags_from_file with mocked mutagen."""

    def test_extract_flac_tags(self, tmp_path: Path, mocker) -> None:
        """Extract tags from a FLAC file with mocked mutagen."""
        fpath = tmp_path / "track.flac"
        fpath.write_text("dummy")

        mock_flac = mocker.MagicMock()
        mock_flac.tags = {
            "artist": ["Artist"],
            "album": ["Album"],
            "title": ["Title"],
            "tracknumber": ["3"],
            "date": ["2024"],
            "genre": ["Electronic"],
        }
        mocker.patch("mutagen.flac.FLAC", return_value=mock_flac)

        result = mid._extract_tags_from_file(fpath)
        assert result is not None
        assert result["artist"] == "Artist"
        assert result["album"] == "Album"
        assert result["title"] == "Title"
        assert result["track"] == 3
        assert result["year"] == 2024

    def test_extract_flac_no_tags(self, tmp_path: Path, mocker) -> None:
        """FLAC file with no tags returns None."""
        fpath = tmp_path / "track.flac"
        fpath.write_text("dummy")

        mock_flac = mocker.MagicMock()
        mock_flac.tags = None
        mocker.patch("mutagen.flac.FLAC", return_value=mock_flac)

        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_extract_non_audio_returns_none(self, tmp_path: Path, mocker) -> None:
        """Non-audio file returns None."""
        fpath = tmp_path / "readme.txt"
        fpath.write_text("hello")
        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_extract_flac_exception_returns_none(self, tmp_path: Path, mocker) -> None:
        """FLAC extraction exception returns None."""
        fpath = tmp_path / "track.flac"
        fpath.write_text("dummy")
        mocker.patch("mutagen.flac.FLAC", side_effect=RuntimeError("corrupt"))

        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_extract_mp3_tags(self, tmp_path: Path, mocker) -> None:
        """Extract tags from an MP3 file with mocked ID3."""
        fpath = tmp_path / "track.mp3"
        fpath.write_text("dummy")

        class MockFrame:
            """Mock ID3 frame."""

            def __str__(self) -> str:
                return "Value"

        class MockID3:
            """Mock ID3 tags."""

            def getall(self, frame_id: str):
                return [MockFrame()]

        # MP3 files use mutagen.id3.ID3, not mutagen.mp3.MP3
        mocker.patch("mutagen.id3.ID3", return_value=MockID3())

        result = mid._extract_tags_from_file(fpath)
        assert result is not None


class TestExtractId3likeTags:
    """Tests for _extract_id3like_tags."""

    def test_id3like_with_getall(self) -> None:
        """ID3-like tags with getall should extract metadata."""
        from maestro import identifier as mid

        class MockFrame:
            def __str__(self) -> str:
                return "Artist"

        class MockTags:
            def getall(self, frame_id: str) -> list:
                return [MockFrame()]

        result = mid._extract_id3like_tags(MockTags())
        assert result is not None
        assert result["artist"] == "Artist"

    def test_id3like_no_getall_returns_none(self) -> None:
        """Without getall, _extract_id3like_tags returns None."""
        from maestro import identifier as mid

        result = mid._extract_id3like_tags(None)
        assert result is None

    def test_id3like_no_artist_or_album_returns_none(self) -> None:
        """When artist and album are both missing, returns None."""
        from maestro import identifier as mid

        class MockTags:
            def getall(self, frame_id: str) -> list:
                return []

        result = mid._extract_id3like_tags(MockTags())
        assert result is None


class TestExtractVorbislikeTags:
    """Tests for _extract_vorbislike_tags."""

    def test_vorbislike_with_dict(self) -> None:
        """Vorbis-like dict tags should extract metadata."""
        from maestro import identifier as mid

        result = mid._extract_vorbislike_tags({"artist": ["A"], "album": ["B"]})
        assert result is not None
        assert result["artist"] == "A"

    def test_vorbislike_not_dict_returns_none(self) -> None:
        """Non-dict tags return None."""
        from maestro import identifier as mid

        result = mid._extract_vorbislike_tags(None)
        assert result is None

    def test_extract_other_audio(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        """Non-FLAC/MP3 audio uses generic mutagen.File."""
        fpath = tmp_path / "track.ogg"
        fpath.write_text("dummy")

        mock_file = mocker.MagicMock()
        mock_file.tags = {"artist": ["Artist"]}
        mocker.patch("mutagen.File", return_value=mock_file)

        result = mid._extract_tags_from_file(fpath)
        assert result is not None

    def test_extract_mp4_tags(self, tmp_path: Path, mocker: pytest_mock.MockerFixture) -> None:
        """MP4/M4A files use __getitem__ atom access."""
        fpath = tmp_path / "track.m4a"
        fpath.write_text("dummy")

        class MockAtomTags:
            """Simulates mutagen.mp4.MP4Tags."""

            def __getitem__(self, key: str) -> list[str]:
                if key == "\xa9ART":
                    return ["MP4 Artist"]
                if key == "\xa9alb":
                    return ["MP4 Album"]
                raise KeyError(key)

        mock_file = mocker.MagicMock()
        mock_file.tags = MockAtomTags()
        mocker.patch("mutagen.File", return_value=mock_file)

        result = mid._extract_tags_from_file(fpath)
        assert result is not None
        assert result["artist"] == "MP4 Artist"
        assert result["album"] == "MP4 Album"


class TestReadId3TagsExtended:
    """Additional edge cases for _read_id3_tags."""

    def test_mutagen_not_installed(self, mocker) -> None:
        """When mutagen is not installed, return None."""
        mocker.patch("importlib.util.find_spec", return_value=None)
        result = mid._read_id3_tags("/some/path")
        assert result is None

    def test_path_not_a_directory(self, tmp_path: Path) -> None:
        """When path is not a directory, return None."""
        non_dir = tmp_path / "nonexistent"
        result = mid._read_id3_tags(str(non_dir))
        assert result is None

    def test_non_file_entries_skipped(self, tmp_path: Path, mocker) -> None:
        """Subdirectories (non-file entries) are skipped."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        subdir = dl_dir / "subdir"
        subdir.mkdir()
        (dl_dir / "track.flac").write_text("data")
        mocker.patch(
            "maestro.identifier._extract_tags_from_file",
            return_value={"artist": "A"},
        )
        result = mid._read_id3_tags(str(dl_dir))
        assert result == {"artist": "A"}

    def test_non_audio_extensions_skipped(self, tmp_path: Path, mocker) -> None:
        """Non-audio file extensions are skipped."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        (dl_dir / "cover.jpg").write_text("not audio")
        (dl_dir / "track.flac").write_text("data")
        mocker.patch(
            "maestro.identifier._extract_tags_from_file",
            return_value={"artist": "A"},
        )
        result = mid._read_id3_tags(str(dl_dir))
        assert result == {"artist": "A"}

    def test_exception_during_extraction_skipped(self, tmp_path: Path, mocker) -> None:
        """Exception during tag extraction is caught and skipped."""
        dl_dir = tmp_path / "album"
        dl_dir.mkdir()
        (dl_dir / "corrupt.mp3").write_text("garbage")
        (dl_dir / "good.flac").write_text("data")
        mocker.patch(
            "maestro.identifier._extract_tags_from_file",
            side_effect=[RuntimeError("corrupt"), {"artist": "Good"}],
        )
        result = mid._read_id3_tags(str(dl_dir))
        assert result == {"artist": "Good"}


class TestMatchToLibraryExtended:
    """Additional edge cases for _match_to_library."""

    @pytest.fixture
    def engine(self, tmp_path: Path) -> Generator[Engine, None, None]:
        db_path = str(tmp_path / "test.db")
        eng = get_engine(db_path, echo=False)
        init_db(eng)
        yield eng
        eng.dispose()

    def test_match_no_album_in_library(self, engine, mocker) -> None:
        """Artist exists but album does not — return None."""
        from maestro.db.core import create_session

        session = create_session(engine)
        artist = Artist(name="TestArtist", slug="testartist")
        session.add(artist)
        session.flush()

        # Existing album has different title
        album = Album(title="DifferentAlbum", artist_id=artist.id)
        session.add(album)
        session.flush()

        result = mid._match_to_library(
            session,
            artist_name="TestArtist",
            album_title="NonExistentAlbum",
        )
        assert result is None
        session.close()

    def test_match_sets_year_when_album_missing(self, engine, mocker) -> None:
        """When year is provided and album.year is None, year is set."""
        from maestro.db.core import create_session

        session = create_session(engine)
        artist = Artist(name="YearArtist", slug="yearartist")
        session.add(artist)
        session.flush()

        album = Album(title="YearAlbum", artist_id=artist.id, year=None)
        session.add(album)
        session.flush()

        result = mid._match_to_library(
            session,
            artist_name="YearArtist",
            album_title="YearAlbum",
            year=1999,
        )
        assert result == album.id
        # The in-memory object should be updated
        assert album.year == 1999
        session.close()

    def test_match_sets_genre_when_album_missing(self, engine, mocker) -> None:
        """When genre is provided and album.genre is None, genre is set."""
        from maestro.db.core import create_session

        session = create_session(engine)
        artist = Artist(name="GenreArtist", slug="genreartist")
        session.add(artist)
        session.flush()

        album = Album(title="GenreAlbum", artist_id=artist.id, genre=None)
        session.add(album)
        session.flush()

        result = mid._match_to_library(
            session,
            artist_name="GenreArtist",
            album_title="GenreAlbum",
            genre="Electronic",
        )
        assert result == album.id
        # The in-memory object should be updated
        assert album.genre == "Electronic"
        session.close()


class TestExtractMp4TagsExtended:
    """Additional edge cases for _extract_mp4_tags."""

    def test_no_getitem_returns_none(self) -> None:
        """An object without __getitem__ returns None."""
        result = mid._extract_mp4_tags(None)
        assert result is None

    def test_non_list_atom_value(self) -> None:
        """When an atom value is a string (not list), it is converted via str()."""

        class MockTags:
            """Mock MP4 tags with string values instead of lists."""

            def __getitem__(self, key: str) -> str:
                if key == "\xa9ART":
                    return "Artist Name"
                if key == "\xa9alb":
                    return "Album Name"
                raise KeyError(key)

        result = mid._extract_mp4_tags(MockTags())
        assert result is not None
        assert result["artist"] == "Artist Name"
        assert result["album"] == "Album Name"


class TestExtractTagsFromFileExtended:
    """Additional edge cases for _extract_tags_from_file."""

    def test_mp3_id3_no_header_error(self, tmp_path: Path, mocker) -> None:
        """MP3 file with ID3NoHeaderError returns None."""
        from mutagen.id3 import ID3NoHeaderError

        fpath = tmp_path / "track.mp3"
        fpath.write_text("dummy")
        mocker.patch("mutagen.id3.ID3", side_effect=ID3NoHeaderError)
        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_mp3_exception_returns_none(self, tmp_path: Path, mocker) -> None:
        """MP3 file with generic Exception returns None."""
        fpath = tmp_path / "track.mp3"
        fpath.write_text("dummy")
        mocker.patch("mutagen.id3.ID3", side_effect=RuntimeError("corrupt"))
        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_other_audio_tags_none_returns_none(self, tmp_path: Path, mocker) -> None:
        """Non-FLAC/MP3 audio with tags=None returns None."""
        fpath = tmp_path / "track.ogg"
        fpath.write_text("dummy")
        mock_file = mocker.MagicMock()
        mock_file.tags = None
        mocker.patch("mutagen.File", return_value=mock_file)
        result = mid._extract_tags_from_file(fpath)
        assert result is None

    def test_other_audio_id3like_tags(self, tmp_path: Path, mocker) -> None:
        """Non-FLAC/MP3 audio with ID3-like tags (getall) extracts correctly."""
        fpath = tmp_path / "track.ogg"
        fpath.write_text("dummy")

        class MockFrame:
            def __str__(self) -> str:
                return "Artist"

        class MockId3Tags:
            """Simulates ID3-like tags with getall."""

            def getall(self, frame_id: str) -> list:
                if frame_id in ("TPE1", "TALB"):
                    return [MockFrame()]
                return []

        mock_file = mocker.MagicMock()
        mock_file.tags = MockId3Tags()
        mocker.patch("mutagen.File", return_value=mock_file)
        result = mid._extract_tags_from_file(fpath)
        assert result is not None
        assert result["artist"] == "Artist"

    def test_mutagen_file_exception_returns_none(self, tmp_path: Path, mocker) -> None:
        """When mutagen.File raises an exception, None is returned."""
        fpath = tmp_path / "track.ogg"
        fpath.write_text("dummy")
        mocker.patch("mutagen.File", side_effect=RuntimeError("corrupt file"))
        result = mid._extract_tags_from_file(fpath)
        assert result is None
