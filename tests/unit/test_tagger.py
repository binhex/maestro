"""Tests for maestro.tagger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest_mock

from maestro.tagger import (
    _guess_mime,
    clear_tags,
    embed_artwork_id3,
    embed_artwork_vorbis,
    write_tags,
)

# ===================================================================
# _guess_mime
# ===================================================================


class TestGuessMime:
    """_guess_mime maps file extensions to MIME types."""

    def test_jpeg(self) -> None:
        assert _guess_mime("cover.jpg") == "image/jpeg"

    def test_png(self) -> None:
        assert _guess_mime("cover.png") == "image/png"

    def test_gif(self) -> None:
        assert _guess_mime("cover.gif") == "image/gif"

    def test_webp(self) -> None:
        assert _guess_mime("cover.webp") == "image/webp"

    def test_unknown_extension(self) -> None:
        assert _guess_mime("cover.tiff") == "image/jpeg"


# ===================================================================
# write_tags — non-existent file
# ===================================================================


class TestWriteTagsNonExistentFile:
    """write_tags returns False for non-existent files."""

    def test_returns_false_for_nonexistent_mp3(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Non-existent .mp3 path returns False without calling mutagen."""
        spy_id3 = mocker.patch("mutagen.id3.ID3")
        result = write_tags("/tmp/nonexistent_test_file.mp3", artist="Test")
        assert result is False
        spy_id3.assert_not_called()

    def test_returns_false_for_nonexistent_flac(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Non-existent .flac path returns False without calling mutagen."""
        spy_flac = mocker.patch("mutagen.flac.FLAC")
        result = write_tags("/tmp/nonexistent_test_file.flac", artist="Test")
        assert result is False
        spy_flac.assert_not_called()

    def test_returns_false_for_nonexistent_other(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Non-existent .ogg path returns False without calling mutagen."""
        spy_file = mocker.patch("mutagen.File")
        result = write_tags("/tmp/nonexistent_test_file.ogg", artist="Test")
        assert result is False
        spy_file.assert_not_called()

    def test_returns_false_no_mutagen_calls(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """No mutagen function is called for a non-existent file."""
        spys = [
            mocker.patch("mutagen.id3.ID3"),
            mocker.patch("mutagen.flac.FLAC"),
            mocker.patch("mutagen.File"),
        ]
        result = write_tags("/tmp/nonexistent_test_file.m4a")
        assert result is False
        for spy in spys:
            spy.assert_not_called()


# ===================================================================
# write_tags — MP3
# ===================================================================


class TestWriteTagsMp3:
    """write_tags for MP3 files (ID3 tags)."""

    @pytest.fixture
    def audio_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.mp3"
        fpath.write_bytes(b"fake mp3 content")
        return fpath

    def test_writes_artist_album_title(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Artist, album, and title frames are set on the audio object."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        # Patch frame classes to return identifiable mocks
        mock_tpe1 = mocker.patch("mutagen.id3.TPE1", return_value="mock_tpe1")
        mock_talb = mocker.patch("mutagen.id3.TALB", return_value="mock_talb")
        mock_tit2 = mocker.patch("mutagen.id3.TIT2", return_value="mock_tit2")

        result = write_tags(
            str(audio_file),
            artist="Test Artist",
            album="Test Album",
            title="Test Title",
        )

        assert result is True
        mock_tpe1.assert_called_once_with(encoding=3, text="Test Artist")
        mock_talb.assert_called_once_with(encoding=3, text="Test Album")
        mock_tit2.assert_called_once_with(encoding=3, text="Test Title")
        mock_audio.save.assert_called_once_with(audio_file)

    def test_writes_all_tag_fields(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """All ID3 frames are set when all values are provided."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        mocker.patch("mutagen.id3.TPE1", return_value="tpe1")
        mocker.patch("mutagen.id3.TALB", return_value="talb")
        mocker.patch("mutagen.id3.TIT2", return_value="tit2")
        mock_trck = mocker.patch("mutagen.id3.TRCK", return_value="trck")
        mock_tdrc = mocker.patch("mutagen.id3.TDRC", return_value="tdrc")
        mock_tcon = mocker.patch("mutagen.id3.TCON", return_value="tcon")

        result = write_tags(
            str(audio_file),
            artist="A",
            album="B",
            title="C",
            track_number=7,
            year=1999,
            genre="Rock",
        )

        assert result is True
        mock_trck.assert_called_once_with(encoding=3, text="7")
        mock_tdrc.assert_called_once_with(encoding=3, text="1999")
        mock_tcon.assert_called_once_with(encoding=3, text="Rock")
        mock_audio.save.assert_called_once()

    def test_handles_id3_no_header(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When ID3NoHeaderError is raised, an empty ID3 object is created."""
        # First call (with file path) raises, second call (no args) succeeds
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        mock_id3 = mocker.patch("mutagen.id3.ID3")
        mock_id3.side_effect = [RuntimeError("no header"), mocker.MagicMock()]

        result = write_tags(str(audio_file), artist="A")

        assert result is True
        # Called twice: once with path (raises), once without (empty)
        assert mock_id3.call_count == 2
        assert mock_id3.call_args_list[0] == mocker.call(audio_file)
        assert mock_id3.call_args_list[1] == mocker.call()

    def test_skips_none_fields(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tag values are None, the corresponding frames are not set."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        mocker.patch("mutagen.id3.TPE1", return_value="tpe1")
        mocker.patch("mutagen.id3.TALB", return_value="talb")
        mocker.patch("mutagen.id3.TIT2", return_value="tit2")
        mocker.patch("mutagen.id3.TRCK", return_value="trck")
        mocker.patch("mutagen.id3.TDRC", return_value="tdrc")
        mocker.patch("mutagen.id3.TCON", return_value="tcon")

        # Only pass artist — everything else is None (default)
        result = write_tags(str(audio_file), artist="Only Artist")

        assert result is True
        # __setitem__ should only be called for artist frame
        set_keys = [call[0][0] for call in mock_audio.__setitem__.call_args_list]
        assert set_keys == ["TPE1"]
        mock_audio.save.assert_called_once()

    def test_embeds_artwork_when_provided(
        self,
        audio_file: Path,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When artwork_path is provided, embed_artwork_id3 is called."""
        artwork = tmp_path / "cover.jpg"
        artwork.write_bytes(b"fake jpeg")

        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        mocker.patch("mutagen.id3.TPE1", return_value="tpe1")
        embed_spy = mocker.patch("maestro.tagger.embed_artwork_id3")

        result = write_tags(
            str(audio_file),
            artist="A",
            artwork_path=str(artwork),
        )

        assert result is True
        embed_spy.assert_called_once_with(mock_audio, str(artwork))

    def test_does_not_embed_artwork_when_not_provided(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When artwork_path is None, embed_artwork_id3 is not called."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)
        mocker.patch("mutagen.id3.TPE1", return_value="tpe1")
        embed_spy = mocker.patch("maestro.tagger.embed_artwork_id3")

        result = write_tags(str(audio_file), artist="A")

        assert result is True
        embed_spy.assert_not_called()

    def test_catches_mutagen_exception(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A mutagen exception during tag writing returns False."""
        mocker.patch("mutagen.id3.ID3", side_effect=ValueError("boom"))
        mocker.patch("mutagen.id3.ID3NoHeaderError", RuntimeError)

        result = write_tags(str(audio_file), artist="A")

        assert result is False


# ===================================================================
# write_tags — FLAC
# ===================================================================


class TestWriteTagsFlac:
    """write_tags for FLAC files (Vorbis comments)."""

    @pytest.fixture
    def audio_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.flac"
        fpath.write_bytes(b"fake flac content")
        return fpath

    def test_writes_vorbis_comments(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Vorbis comment tags are set on the FLAC audio object."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.flac.FLAC", return_value=mock_audio)

        result = write_tags(
            str(audio_file),
            artist="Artist",
            album="Album",
            title="Title",
            track_number=5,
            year=2020,
            genre="Jazz",
        )

        assert result is True
        # Vorbis tags are set via __setitem__ on the audio object
        assert mock_audio.__setitem__.call_args_list == [
            mocker.call("artist", "Artist"),
            mocker.call("album", "Album"),
            mocker.call("title", "Title"),
            mocker.call("tracknumber", "5"),
            mocker.call("date", "2020"),
            mocker.call("genre", "Jazz"),
        ]
        mock_audio.save.assert_called_once()

    def test_skips_none_fields(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tag values are None, they are not set on the audio object."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.flac.FLAC", return_value=mock_audio)

        result = write_tags(str(audio_file), album="Only Album")

        assert result is True
        set_keys = [call[0][0] for call in mock_audio.__setitem__.call_args_list]
        assert set_keys == ["album"]
        mock_audio.save.assert_called_once()

    def test_embeds_artwork_when_provided(
        self,
        audio_file: Path,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When artwork_path is provided, embed_artwork_vorbis is called."""
        artwork = tmp_path / "cover.png"
        artwork.write_bytes(b"fake png")

        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.flac.FLAC", return_value=mock_audio)
        embed_spy = mocker.patch("maestro.tagger.embed_artwork_vorbis")

        result = write_tags(
            str(audio_file),
            artist="A",
            artwork_path=str(artwork),
        )

        assert result is True
        embed_spy.assert_called_once_with(mock_audio, str(artwork))

    def test_catches_mutagen_exception(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A mutagen exception during FLAC tag writing returns False."""
        mocker.patch("mutagen.flac.FLAC", side_effect=OSError("permission denied"))

        result = write_tags(str(audio_file), artist="A")

        assert result is False


# ===================================================================
# write_tags — other formats (mutagen.File fallback)
# ===================================================================


class TestWriteTagsOtherFormats:
    """write_tags fallback for non-MP3, non-FLAC formats."""

    @pytest.fixture
    def audio_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.ogg"
        fpath.write_bytes(b"fake ogg content")
        return fpath

    def test_writes_to_vorbis_like_tags(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """VorbisComment dict tags are populated for .ogg files."""
        mock_tags: dict[str, Any] = {}
        mock_audio = mocker.MagicMock()
        mock_audio.tags = mock_tags
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = write_tags(
            str(audio_file),
            artist="Artist",
            album="Album",
            title="Title",
            track_number=2,
            year=2021,
            genre="Classical",
        )

        assert result is True
        assert mock_tags == {
            "artist": ["Artist"],
            "album": ["Album"],
            "title": ["Title"],
            "tracknumber": ["2"],
            "date": ["2021"],
            "genre": ["Classical"],
        }
        mock_audio.save.assert_called_once()

    def test_handles_none_return_from_mutagen_file(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When mutagen.File returns None, write_tags returns False."""
        mocker.patch("mutagen.File", return_value=None)

        result = write_tags(str(audio_file), artist="A")

        assert result is False

    def test_handles_audio_without_tags_attribute(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the audio object has no 'tags' attribute, save is still called."""
        mock_audio = mocker.MagicMock()
        # A MagicMock auto-creates attrs; it won't be a dict so isinstance check fails
        # and save is still called.
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = write_tags(str(audio_file), artist="A")

        assert result is True
        mock_audio.save.assert_called_once()

    def test_skips_non_dict_tags(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When tags is not a dict (e.g. MP4), save is still called."""
        mock_audio = mocker.MagicMock()
        mock_audio.tags = "stringy_tags"  # not a dict
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = write_tags(str(audio_file), artist="A")

        assert result is True
        mock_audio.save.assert_called_once()

    def test_catches_mutagen_exception(
        self,
        audio_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A mutagen exception during fallback tag writing returns False."""
        mocker.patch("mutagen.File", side_effect=RuntimeError("corrupt file"))

        result = write_tags(str(audio_file), artist="A")

        assert result is False


# ===================================================================
# clear_tags
# ===================================================================


class TestClearTags:
    """clear_tags removes all tags from audio files."""

    @pytest.fixture
    def mp3_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.mp3"
        fpath.write_bytes(b"fake mp3")
        return fpath

    @pytest.fixture
    def flac_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.flac"
        fpath.write_bytes(b"fake flac")
        return fpath

    @pytest.fixture
    def ogg_file(self, tmp_path: Path) -> Path:
        fpath = tmp_path / "track.ogg"
        fpath.write_bytes(b"fake ogg")
        return fpath

    def test_non_existent_file_returns_false(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Non-existent file returns False without calling mutagen."""
        spy = mocker.patch("mutagen.id3.ID3")
        result = clear_tags("/tmp/nonexistent_test_file.mp3")
        assert result is False
        spy.assert_not_called()

    def test_clears_mp3_tags(
        self,
        mp3_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """MP3 tags are cleared via ID3.delete()."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.id3.ID3", return_value=mock_audio)

        result = clear_tags(str(mp3_file))

        assert result is True
        mock_audio.delete.assert_called_once()

    def test_clears_flac_tags(
        self,
        flac_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """FLAC tags are cleared via FLAC.delete()."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.flac.FLAC", return_value=mock_audio)

        result = clear_tags(str(flac_file))

        assert result is True
        mock_audio.delete.assert_called_once()

    def test_clears_other_format_tags(
        self,
        ogg_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """Other-format tags are cleared via delete() on the mutagen.File result."""
        mock_audio = mocker.MagicMock()
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = clear_tags(str(ogg_file))

        assert result is True
        mock_audio.delete.assert_called_once()

    def test_other_format_without_delete_uses_clear(
        self,
        ogg_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When the audio object has no delete(), clear() is used instead."""
        mock_audio = mocker.MagicMock()
        # Remove delete method
        del mock_audio.delete
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = clear_tags(str(ogg_file))

        assert result is True
        mock_audio.clear.assert_called_once()

    def test_other_format_without_delete_or_clear(
        self,
        ogg_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When neither delete() nor clear() exists, the function still succeeds."""
        mock_audio = mocker.MagicMock(spec=["save"])  # only has save
        mocker.patch("mutagen.File", return_value=mock_audio)

        result = clear_tags(str(ogg_file))

        assert result is True

    def test_mutagen_file_returns_none(
        self,
        ogg_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """When mutagen.File returns None, clear_tags returns False."""
        mocker.patch("mutagen.File", return_value=None)

        result = clear_tags(str(ogg_file))

        assert result is False

    def test_catches_exception(
        self,
        mp3_file: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A mutagen exception during tag clearing returns False."""
        mocker.patch("mutagen.id3.ID3", side_effect=PermissionError("access denied"))

        result = clear_tags(str(mp3_file))

        assert result is False


# ===================================================================
# embed_artwork_id3
# ===================================================================


class TestEmbedArtworkId3:
    """embed_artwork_id3 embeds APIC frames."""

    def test_embeds_apic_frame(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """An APIC frame is added to the audio object."""
        artwork = tmp_path / "cover.jpg"
        artwork.write_bytes(b"\xff\xd8\xff\xe0")  # JPEG header

        mock_audio = mocker.MagicMock()
        mock_apic = mocker.patch("mutagen.id3.APIC", return_value="apic_instance")
        mocker.patch("builtins.open", mocker.mock_open(read_data=b"jpeg data"))

        embed_artwork_id3(mock_audio, str(artwork))

        mock_apic.assert_called_once()
        assert mock_apic.call_args[1]["mime"] == "image/jpeg"
        assert mock_apic.call_args[1]["type"] == 3
        mock_audio.__setitem__.assert_called_once_with("APIC", "apic_instance")

    def test_catches_exception(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """An exception during embedding is caught and logged."""
        mock_audio = mocker.MagicMock()
        mocker.patch(
            "builtins.open",
            side_effect=FileNotFoundError("no such file"),
        )

        # Should not raise
        embed_artwork_id3(mock_audio, "/tmp/nonexistent_artwork.jpg")
        mock_audio.__setitem__.assert_not_called()


# ===================================================================
# embed_artwork_vorbis
# ===================================================================


class TestEmbedArtworkVorbis:
    """embed_artwork_vorbis embeds picture blocks in FLAC."""

    def test_embeds_picture(
        self,
        tmp_path: Path,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """A Picture is created and added to the audio object."""
        artwork = tmp_path / "cover.png"
        artwork.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG header

        mock_audio = mocker.MagicMock()
        mock_picture_cls = mocker.patch("mutagen.flac.Picture", return_value=mocker.MagicMock())
        mocker.patch("builtins.open", mocker.mock_open(read_data=b"png data"))

        embed_artwork_vorbis(mock_audio, str(artwork))

        mock_picture_cls.assert_called_once()
        picture = mock_picture_cls.return_value
        assert picture.type == 3
        assert picture.mime == "image/png"
        assert picture.data == b"png data"
        mock_audio.add_picture.assert_called_once_with(picture)

    def test_catches_exception(
        self,
        mocker: pytest_mock.MockerFixture,
    ) -> None:
        """An exception during embedding is caught and logged."""
        mock_audio = mocker.MagicMock()
        mocker.patch(
            "mutagen.flac.Picture",
            side_effect=ValueError("invalid picture data"),
        )

        # Should not raise
        embed_artwork_vorbis(mock_audio, "/tmp/nonexistent.png")
        mock_audio.add_picture.assert_not_called()
