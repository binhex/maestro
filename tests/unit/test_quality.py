"""Tests for maestro.quality."""

from maestro.quality import compare_tracks, get_quality_tier


class TestGetQualityTier:
    def test_flac_tier(self):
        assert get_quality_tier("FLAC") == 10
        assert get_quality_tier("flac") == 10
        assert get_quality_tier("Flac") == 10

    def test_wav_tier(self):
        assert get_quality_tier("WAV") == 9

    def test_aiff_tier(self):
        assert get_quality_tier("AIFF") == 8

    def test_mp3_320_tier(self):
        assert get_quality_tier("MP3", 320) == 7

    def test_mp3_v0_tier(self):
        assert get_quality_tier("MP3", 245) == 6

    def test_mp3_v2_tier(self):
        assert get_quality_tier("MP3", 190) == 5

    def test_mp3_192_tier(self):
        assert get_quality_tier("MP3", 192) == 3

    def test_mp3_128_tier(self):
        assert get_quality_tier("MP3", 128) == 1

    def test_aac_tier(self):
        assert get_quality_tier("M4A", 256) == 2

    def test_unknown_format(self):
        assert get_quality_tier("OGG") == 4
        assert get_quality_tier("UNKNOWN") == 0

    def test_ogg_tier(self):
        assert get_quality_tier("OGG", 192) == 4


class TestCompareTracks:
    def test_replace_download_higher_tier(self):
        result = compare_tracks(("MP3", 320), ("FLAC", 1411))
        assert result == "replace"

    def test_skip_library_higher_tier(self):
        result = compare_tracks(("FLAC", 1411), ("MP3", 320))
        assert result == "skip"

    def test_skip_equal_quality(self):
        result = compare_tracks(("FLAC", 1411), ("FLAC", 1411))
        assert result == "skip"

    def test_replace_same_tier_higher_bitrate(self):
        result = compare_tracks(("MP3", 128), ("MP3", 320))
        assert result == "replace"

    def test_skip_same_tier_lower_bitrate(self):
        result = compare_tracks(("MP3", 320), ("MP3", 128))
        assert result == "skip"

    def test_import_no_library_match(self):
        result = compare_tracks(None, ("FLAC", 1411))
        assert result == "import"

    def test_import_library_with_no_track_unknown(self):
        result = compare_tracks(("UNKNOWN", 0), ("FLAC", 1411))
        assert result == "replace"
