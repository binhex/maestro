"""Tests for maestro.artwork."""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image as PilImage

from maestro.artwork import (
    download_artwork_for_album,
    fetch_album_art_lastfm,
    fetch_album_art_musicbrainz,
    fetch_fanart_lastfm,
    get_artwork_paths,
)


def _test_image(width: int = 300, height: int = 300) -> bytes:
    """Create a test image and return JPEG bytes."""
    img = PilImage.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


_TEST_IMAGE = _test_image()

if TYPE_CHECKING:
    import pytest_mock


# ===================================================================
# get_artwork_paths
# ===================================================================


class TestGetArtworkPaths:
    """get_artwork_paths returns correct paths in the album directory."""

    def test_returns_paths_in_album_dir_default(
        self,
        tmp_path: Path,
    ) -> None:
        """Default filenames yield paths ending in cover.jpg and fanart.jpg."""
        album_dir = tmp_path / "Artist" / "Album"
        album_dir.mkdir(parents=True)

        paths = get_artwork_paths(str(album_dir))

        assert "cover.jpg" in paths["album_art"]
        assert "fanart.jpg" in paths["fanart"]
        assert str(album_dir) in paths["album_art"]
        assert str(album_dir) in paths["fanart"]

    def test_returns_paths_custom_filenames(
        self,
        tmp_path: Path,
    ) -> None:
        """Custom filenames are reflected in the returned paths."""
        album_dir = tmp_path / "Album"
        album_dir.mkdir(parents=True)

        paths = get_artwork_paths(
            str(album_dir),
            album_art="folder.jpg",
            fanart="background.jpg",
        )

        assert paths["album_art"].endswith("folder.jpg")
        assert paths["fanart"].endswith("background.jpg")

    def test_returns_absolute_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """Returned paths are absolute (resolved from album_dir)."""
        album_dir = tmp_path / "Somewhere"
        album_dir.mkdir(parents=True)

        paths = get_artwork_paths(str(album_dir))

        assert Path(paths["album_art"]).is_absolute()
        assert Path(paths["fanart"]).is_absolute()

    def test_album_dir_does_not_need_to_exist(
        self,
        tmp_path: Path,
    ) -> None:
        """The function works even when the album directory does not exist."""
        album_dir = tmp_path / "NotYetCreated"

        paths = get_artwork_paths(str(album_dir))

        assert str(album_dir) in paths["album_art"]
        assert str(album_dir) in paths["fanart"]


# ===================================================================
# fetch_album_art_musicbrainz
# ===================================================================


class TestFetchAlbumArtMusicBrainz:
    """fetch_album_art_musicbrainz fetches from MusicBrainz / Cover Art Archive."""

    def test_returns_bytes_on_success(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """On successful search and image fetch, raw bytes are returned."""
        # Mock musicbrainzngs functions (imported inside the function body)
        mock_search = mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )
        mocker.patch("musicbrainzngs.set_useragent")

        # Mock the requests.get for the Cover Art Archive URL
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake_image_bytes"
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_musicbrainz("Test Artist", "Test Album")

        assert result == b"fake_image_bytes"
        mock_search.assert_called_once_with(
            artist="Test Artist",
            release="Test Album",
            limit=1,
        )

    def test_returns_none_when_no_release_found(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When MusicBrainz finds no releases, None is returned."""
        mocker.patch("musicbrainzngs.search_releases", return_value={"release-list": []})
        mocker.patch("musicbrainzngs.set_useragent")

        result = fetch_album_art_musicbrainz("Unknown Artist", "Unknown Album")

        assert result is None

    def test_returns_none_when_image_fetch_fails(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the Cover Art Archive request fails, None is returned."""
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )
        mocker.patch("musicbrainzngs.set_useragent")

        mock_response = mocker.MagicMock()
        mock_response.status_code = 404
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_musicbrainz("Test Artist", "Test Album")

        assert result is None

    def test_returns_none_on_exception(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When an exception occurs, None is returned (caught silently)."""
        mocker.patch(
            "musicbrainzngs.search_releases",
            side_effect=ConnectionError("network error"),
        )
        mocker.patch("musicbrainzngs.set_useragent")

        result = fetch_album_art_musicbrainz("Test Artist", "Test Album")

        assert result is None

    def test_release_list_missing_key(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the response dict lacks a 'release-list' key, None is returned."""
        mocker.patch("musicbrainzngs.search_releases", return_value={})
        mocker.patch("musicbrainzngs.set_useragent")

        result = fetch_album_art_musicbrainz("Test Artist", "Test Album")

        assert result is None


# ===================================================================
# fetch_album_art_lastfm
# ===================================================================


class TestFetchAlbumArtLastfm:
    """fetch_album_art_lastfm fetches album art from Last.fm."""

    def test_returns_none_without_api_key(self) -> None:
        """Without an API key, the function returns None immediately."""
        result = fetch_album_art_lastfm("Test Artist", "Test Album", api_key=None)

        assert result is None

    def test_returns_bytes_on_success(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """On successful API call and image fetch, raw bytes are returned."""
        # First requests.get: API call
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "album": {
                "image": [
                    {"#text": "https://example.com/small.jpg", "size": "small"},
                    {"#text": "https://example.com/large.jpg", "size": "large"},
                ],
            },
        }

        # Second requests.get: image download
        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b"fake_lastfm_art"

        mock_get = mocker.patch("maestro.artwork.requests.get")
        mock_get.side_effect = [mock_api_response, mock_img_response]

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result == b"fake_lastfm_art"
        # Verify the image URL used was the last (largest) one
        assert mock_get.call_args_list[1][0][0] == "https://example.com/large.jpg"

    def test_returns_none_on_api_error(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the API returns a non-200 status, None is returned."""
        mock_response = mocker.MagicMock()
        mock_response.status_code = 403
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result is None

    def test_returns_none_when_no_images(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the API response has no image list, None is returned."""
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"album": {"image": []}}
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result is None

    def test_returns_none_when_missing_image_text(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the image entry has an empty '#text', None is returned."""
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "album": {
                "image": [
                    {"#text": "", "size": "large"},
                ],
            },
        }
        mocker.patch("maestro.artwork.requests.get", return_value=mock_api_response)

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result is None

    def test_returns_none_on_image_download_failure(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the image download request fails, None is returned."""
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "album": {
                "image": [
                    {"#text": "https://example.com/art.jpg", "size": "large"},
                ],
            },
        }

        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 404

        mock_get = mocker.patch("maestro.artwork.requests.get")
        mock_get.side_effect = [mock_api_response, mock_img_response]

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result is None

    def test_returns_none_on_exception(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When an exception occurs, None is returned (caught silently)."""
        mocker.patch(
            "maestro.artwork.requests.get",
            side_effect=TimeoutError("timeout"),
        )

        result = fetch_album_art_lastfm(
            "Test Artist",
            "Test Album",
            api_key="test_key_123",
        )

        assert result is None


# ===================================================================
# fetch_fanart_lastfm
# ===================================================================


class TestFetchFanartLastfm:
    """fetch_fanart_lastfm fetches artist fanart from Last.fm."""

    def test_returns_none_without_api_key(self) -> None:
        """Without an API key, the function returns None immediately."""
        result = fetch_fanart_lastfm("Test Artist", api_key=None)

        assert result is None

    def test_returns_bytes_on_success(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """On successful API call and image fetch, raw bytes are returned."""
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "artist": {
                "image": [
                    {"#text": "https://example.com/small.jpg", "size": "small"},
                    {"#text": "https://example.com/mega.jpg", "size": "mega"},
                ],
            },
        }

        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = b"fake_lastfm_fanart"

        mock_get = mocker.patch("maestro.artwork.requests.get")
        mock_get.side_effect = [mock_api_response, mock_img_response]

        result = fetch_fanart_lastfm("Test Artist", api_key="test_key_123")

        assert result == b"fake_lastfm_fanart"
        # Verify the image URL used was the last (largest) one
        assert mock_get.call_args_list[1][0][0] == "https://example.com/mega.jpg"

    def test_returns_none_on_api_error(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the API returns a non-200 status, None is returned."""
        mock_response = mocker.MagicMock()
        mock_response.status_code = 500
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_fanart_lastfm("Test Artist", api_key="test_key_123")

        assert result is None

    def test_returns_none_when_no_images(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the API response has no image list, None is returned."""
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"artist": {"image": []}}
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_fanart_lastfm("Test Artist", api_key="test_key_123")

        assert result is None

    def test_returns_none_on_exception(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When an exception occurs, None is returned (caught silently)."""
        mocker.patch(
            "maestro.artwork.requests.get",
            side_effect=ConnectionError("reset"),
        )

        result = fetch_fanart_lastfm("Test Artist", api_key="test_key_123")

        assert result is None


# ===================================================================
# fetch_album_art_duckduckgo
# ===================================================================


class TestFetchAlbumArtDuckDuckGo:
    """Tests for fetch_album_art_duckduckgo."""

    def test_returns_bytes_on_success(self, mocker) -> None:
        """A successful search and download should return image bytes."""
        import io

        from PIL import Image

        from maestro.artwork import fetch_album_art_duckduckgo

        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        fake_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/cover1.jpg"},
            {"image": "https://example.com/cover2.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_duckduckgo("Test Artist", "Test Album")
        assert result is not None
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_returns_none_on_empty_results(self, mocker) -> None:
        """No search results should return None."""
        from maestro.artwork import fetch_album_art_duckduckgo

        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = []
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        result = fetch_album_art_duckduckgo("Unknown", "Unknown")
        assert result is None

    def test_returns_none_when_all_fail_validation(self, mocker) -> None:
        """When all results fail validation, should return None."""
        import io

        from PIL import Image

        from maestro.artwork import fetch_album_art_duckduckgo

        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        small_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/small1.jpg"},
            {"image": "https://example.com/small2.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = small_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is None

    def test_skips_invalid_urls_and_tries_next(self, mocker) -> None:
        """If one URL fails to download, the next should be tried."""
        import io

        from PIL import Image

        from maestro.artwork import fetch_album_art_duckduckgo

        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        valid_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/broken.jpg"},
            {"image": "https://example.com/valid.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_fail = mocker.MagicMock()
        mock_fail.status_code = 404
        mock_success = mocker.MagicMock()
        mock_success.status_code = 200
        mock_success.content = valid_image
        mocker.patch(
            "maestro.artwork.requests.get",
            side_effect=[mock_fail, mock_success],
        )

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is not None

    def test_returns_none_when_ddgs_exception(self, mocker) -> None:
        """When DDGS raises an exception, None is returned."""
        from maestro.artwork import fetch_album_art_duckduckgo

        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.side_effect = RuntimeError("search failed")
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is None

    def test_skips_results_without_url(self, mocker) -> None:
        """Results missing an 'image' key are skipped."""
        import io

        from PIL import Image

        from maestro.artwork import fetch_album_art_duckduckgo

        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        valid_image = buf.getvalue()

        mock_results = [
            {"image": None},  # no URL — should be skipped
            {"image": "https://example.com/valid.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = valid_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is not None

    def test_skips_on_download_exception(self, mocker) -> None:
        """When downloading an image raises an exception, next URL is tried."""
        import io

        from PIL import Image

        from maestro.artwork import fetch_album_art_duckduckgo

        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        valid_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/broken.jpg"},
            {"image": "https://example.com/valid.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_fail = mocker.MagicMock()
        mock_fail.status_code = 200
        mock_fail.content = b"garbage"
        # Make validate_and_resize_image raise an exception
        # Actually, let the request fail with an exception

        mock_success = mocker.MagicMock()
        mock_success.status_code = 200
        mock_success.content = valid_image

        # First request raises, second succeeds
        mocker.patch(
            "maestro.artwork.requests.get",
            side_effect=[ConnectionError("connection failed"), mock_success],
        )

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is not None


# ===================================================================
# download_artwork_for_album
# ===================================================================


class TestDownloadArtworkForAlbum:
    """download_artwork_for_album orchestrates artwork downloads."""

    def test_creates_files_and_returns_success(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """On success, files are created and the result dict shows True."""
        album_dir = tmp_path / "Artist" / "Album"
        # Do NOT create the directory — the function should do it

        # Mock MusicBrainz source
        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )

        # First requests.get (CAA) returns art bytes
        mock_caa_response = mocker.MagicMock()
        mock_caa_response.status_code = 200
        mock_caa_response.content = _TEST_IMAGE

        # API response for fanart
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "artist": {
                "image": [
                    {"#text": "https://example.com/fan.jpg", "size": "mega"},
                ],
            },
        }

        # Image download for fanart
        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = _TEST_IMAGE

        def mock_get_side_effect(url: str, **kwargs: Any) -> Any:
            if "coverartarchive" in url:
                return mock_caa_response
            if "ws.audioscrobbler.com" in url:
                return mock_api_response
            if "example.com" in url:
                return mock_img_response
            return mocker.MagicMock()

        mocker.patch("maestro.artwork.requests.get", side_effect=mock_get_side_effect)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            lastfm_api_key="test_key_123",
        )

        assert result == {"album_art": True, "fanart": True, "source_used": "musicbrainz"}
        assert (album_dir / "cover.jpg").exists()
        assert (album_dir / "fanart.jpg").exists()
        assert (album_dir / "cover.jpg").read_bytes() == _TEST_IMAGE
        assert (album_dir / "fanart.jpg").read_bytes() == _TEST_IMAGE

    def test_handles_missing_api_key(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Without a Last.fm API key, album art from MusicBrainz still works but fanart is skipped."""
        album_dir = tmp_path / "NoKey" / "Album"
        album_dir.mkdir(parents=True)

        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )

        mock_caa_response = mocker.MagicMock()
        mock_caa_response.status_code = 200
        mock_caa_response.content = _TEST_IMAGE

        mocker.patch("maestro.artwork.requests.get", return_value=mock_caa_response)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["musicbrainz", "lastfm"],
            lastfm_api_key=None,
        )

        assert result == {"album_art": True, "fanart": False, "source_used": "musicbrainz"}
        assert (album_dir / "cover.jpg").exists()
        assert not (album_dir / "fanart.jpg").exists()

    def test_skips_existing_album_art(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When album art already exists, it is not re-downloaded."""
        album_dir = tmp_path / "Skip" / "Existing"
        album_dir.mkdir(parents=True)
        (album_dir / "cover.jpg").write_bytes(b"existing_art")

        # Mock should not be called
        mock_search = mocker.patch("musicbrainzngs.search_releases")
        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch("maestro.artwork.requests.get")

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            lastfm_api_key="test_key_123",
        )

        assert result == {"album_art": True, "fanart": False, "source_used": "cached"}
        # mb search should not have been called since art exists
        mock_search.assert_not_called()
        # read the file — it should still be the original content
        assert (album_dir / "cover.jpg").read_bytes() == b"existing_art"

    def test_skips_existing_fanart(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When fanart already exists, it is not re-downloaded."""
        album_dir = tmp_path / "SkipFanart" / "Existing"
        album_dir.mkdir(parents=True)
        (album_dir / "fanart.jpg").write_bytes(b"existing_fanart")

        # We still need album art from MusicBrainz
        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )

        mock_caa_response = mocker.MagicMock()
        mock_caa_response.status_code = 200
        mock_caa_response.content = _TEST_IMAGE

        mocker.patch("maestro.artwork.requests.get", return_value=mock_caa_response)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["musicbrainz", "lastfm"],
            lastfm_api_key="test_key_123",
        )

        assert result == {"album_art": True, "fanart": True, "source_used": "musicbrainz"}
        assert (album_dir / "fanart.jpg").read_bytes() == b"existing_fanart"

    def test_creates_album_directory(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """The album directory is created if it does not exist."""
        album_dir = tmp_path / "BrandNew" / "Album"
        assert not album_dir.exists()

        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )

        mock_caa_response = mocker.MagicMock()
        mock_caa_response.status_code = 200
        mock_caa_response.content = _TEST_IMAGE

        mocker.patch("maestro.artwork.requests.get", return_value=mock_caa_response)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["musicbrainz", "lastfm"],
            lastfm_api_key=None,
        )

        assert result == {"album_art": True, "fanart": False, "source_used": "musicbrainz"}
        assert album_dir.is_dir()
        assert (album_dir / "cover.jpg").exists()

    def test_falls_through_all_sources(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When MusicBrainz returns None, the next source (Last.fm) is tried."""
        album_dir = tmp_path / "Fallthrough" / "Test"
        album_dir.mkdir(parents=True)

        # MusicBrainz returns no releases
        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={"release-list": []},
        )

        # Last.fm returns art
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "album": {
                "image": [
                    {"#text": "https://example.com/art.jpg", "size": "large"},
                ],
            },
        }

        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = _TEST_IMAGE

        def mock_get_side_effect(url: str, **kwargs: Any) -> Any:
            if "ws.audioscrobbler.com" in url:
                return mock_api_response
            if "example.com" in url:
                return mock_img_response
            return mocker.MagicMock()

        mocker.patch("maestro.artwork.requests.get", side_effect=mock_get_side_effect)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            lastfm_api_key="test_key_123",
        )

        assert result["album_art"] is True
        assert (album_dir / "cover.jpg").read_bytes() == _TEST_IMAGE

    def test_custom_filenames(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Custom filenames are used when specified."""
        album_dir = tmp_path / "Custom" / "Names"
        album_dir.mkdir(parents=True)

        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={
                "release-list": [
                    {"id": "abc-123", "title": "Test Album", "artist-credit": [{"artist": {"name": "Test Artist"}}]}
                ],
            },
        )

        mock_caa_response = mocker.MagicMock()
        mock_caa_response.status_code = 200
        mock_caa_response.content = _TEST_IMAGE

        mocker.patch("maestro.artwork.requests.get", return_value=mock_caa_response)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["musicbrainz", "lastfm"],
            album_art_filename="folder.jpg",
            fanart_filename="bg.jpg",
            lastfm_api_key=None,
        )

        assert result == {"album_art": True, "fanart": False, "source_used": "musicbrainz"}
        assert (album_dir / "folder.jpg").exists()
        assert not (album_dir / "cover.jpg").exists()

    def test_no_sources_match(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When no source can provide artwork, album_art remains False."""
        album_dir = tmp_path / "NoMatch"
        album_dir.mkdir(parents=True)

        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={"release-list": []},
        )

        # No Last.fm key, so that source is skipped
        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["musicbrainz", "lastfm"],
            lastfm_api_key=None,
        )

        assert result == {"album_art": False, "fanart": False, "source_used": None}

    def test_custom_sources_list(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A custom sources list is respected and tried in order."""
        album_dir = tmp_path / "CustomSources"
        album_dir.mkdir(parents=True)

        # With sources=["lastfm"] and a key, only Last.fm is tried
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = {
            "album": {
                "image": [
                    {"#text": "https://example.com/art.jpg", "size": "large"},
                ],
            },
        }

        mock_img_response = mocker.MagicMock()
        mock_img_response.status_code = 200
        mock_img_response.content = _TEST_IMAGE

        def mock_get_side_effect(url: str, **kwargs: Any) -> Any:
            if "ws.audioscrobbler.com" in url:
                return mock_api_response
            if "example.com" in url:
                return mock_img_response
            return mocker.MagicMock()

        mocker.patch("maestro.artwork.requests.get", side_effect=mock_get_side_effect)

        # MusicBrainz should NOT be called
        mock_search = mocker.patch("musicbrainzngs.search_releases")
        mocker.patch("musicbrainzngs.set_useragent")

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            lastfm_api_key="test_key_123",
            sources=["lastfm"],
        )

        assert result["album_art"] is True
        mock_search.assert_not_called()
        assert (album_dir / "cover.jpg").read_bytes() == _TEST_IMAGE

    def test_all_sources_fail_still_returns_false(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When all sources fail, album_art is False (no crash)."""
        album_dir = tmp_path / "AllFail"
        album_dir.mkdir(parents=True)

        # MusicBrainz returns no releases
        mocker.patch("musicbrainzngs.set_useragent")
        mocker.patch(
            "musicbrainzngs.search_releases",
            return_value={"release-list": []},
        )

        # Last.fm API returns error
        mock_api_response = mocker.MagicMock()
        mock_api_response.status_code = 500

        mocker.patch("maestro.artwork.requests.get", return_value=mock_api_response)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            lastfm_api_key="test_key_123",
        )

        assert result == {"album_art": False, "fanart": False, "source_used": None}

    def test_duckduckgo_is_tried_first(self, tmp_path, mocker) -> None:
        """When duckduckgo is first in sources, it's tried before musicbrainz."""
        import io

        from PIL import Image

        from maestro.artwork import download_artwork_for_album

        album_dir = tmp_path / "DuckFirst"
        album_dir.mkdir()

        img = Image.new("RGB", (500, 500), color="green")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        fake_image = buf.getvalue()

        # Mock DDG search to return a result
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = [
            {"image": "https://example.com/ddg.jpg"},
        ]
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        # Mock requests.get to return valid image
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        # Mock musicbrainzngs — should NOT be called
        mock_mb = mocker.patch("musicbrainzngs.search_releases")

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["duckduckgo", "musicbrainz"],
        )

        assert result["album_art"] is True
        assert result["source_used"] == "duckduckgo"
        mock_mb.assert_not_called()


# ===================================================================
# download_artwork_for_album — disable flags
# ===================================================================


class TestDownloadArtworkForAlbumDisable:
    """Tests for the download_album_art / download_fanart disable flags."""

    def test_disable_album_art_returns_none(self, tmp_path) -> None:
        """When download_album_art is False, album_art in result should be None."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=False,
            download_fanart=True,
        )

        assert result["album_art"] is None
        assert result["source_used"] is None

    def test_disable_fanart_returns_none(self, tmp_path) -> None:
        """When download_fanart is False, fanart in result should be None."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=True,
            download_fanart=False,
        )

        assert result["fanart"] is None

    def test_disable_both_returns_early(self, tmp_path) -> None:
        """When both are False, should log and return no artwork."""
        album_dir = tmp_path / "artist" / "album"
        album_dir.mkdir(parents=True)

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            download_album_art=False,
            download_fanart=False,
        )

        assert result["album_art"] is None
        assert result["fanart"] is None
        assert result["source_used"] is None

    def test_download_artwork_duckduckgo_source_skipped_when_missing(
        self,
        tmp_path,
        mocker,
    ) -> None:
        """When DDGS is not available and duckduckgo is a source, it's skipped gracefully."""
        import maestro.artwork as art_mod

        original = art_mod.DDGS
        art_mod.DDGS = None  # type: ignore[misc,assignment]
        try:
            album_dir = tmp_path / "artist" / "album"
            album_dir.mkdir(parents=True)

            result = art_mod.download_artwork_for_album(
                album_dir=str(album_dir),
                artist="Test Artist",
                album="Test Album",
                download_album_art=True,
                download_fanart=False,
                sources=["duckduckgo", "musicbrainz"],
            )
            # Should not crash; should try musicbrainz after duckduckgo skip
            assert isinstance(result, dict)
            assert "album_art" in result
        finally:
            art_mod.DDGS = original  # type: ignore[misc,assignment]
