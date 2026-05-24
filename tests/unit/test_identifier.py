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
