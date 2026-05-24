"""Tests for maestro.template."""

from maestro.template import parse_variables, render_path


class TestParseVariables:
    def test_simple_pattern(self):
        result = parse_variables(
            path="Amon Tobin/Bricolage",
            pattern="{artist}/{album}",
        )
        assert result == {"artist": "Amon Tobin", "album": "Bricolage"}

    def test_deep_pattern(self):
        result = parse_variables(
            path="Paul/Albums/Dance/Ambient/Amon Tobin/Bricolage",
            pattern="{owner}/{type}/{genre}/{subgenre}/{artist}/{album}",
        )
        assert result["owner"] == "Paul"
        assert result["type"] == "Albums"
        assert result["genre"] == "Dance"
        assert result["subgenre"] == "Ambient"
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage"

    def test_pattern_with_filename_and_ext(self):
        result = parse_variables(
            path="music/01 - Track.flac",
            pattern="{path}/{filename}.{ext}",
        )
        assert result["filename"] == "01 - Track"
        assert result["ext"] == "flac"

    def test_windows_backslash_path(self):
        result = parse_variables(
            path=r"D:\Music\Amon Tobin\Bricolage",
            pattern="{path}\\{artist}\\{album}",
        )
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage"

    def test_pattern_mismatch_returns_partial(self):
        result = parse_variables(
            path="Amon Tobin",
            pattern="{artist}/{album}",
        )
        assert result == {"artist": "Amon Tobin"}

    def test_pattern_with_spaces_in_names(self):
        result = parse_variables(
            path="Dance/Electronic/Amon Tobin/Bricolage (1997)",
            pattern="{genre}/{subgenre}/{artist}/{album}",
        )
        assert result["artist"] == "Amon Tobin"
        assert result["album"] == "Bricolage (1997)"


class TestRenderPath:
    def test_simple_render(self):
        result = render_path(
            variables={"artist": "Amon Tobin", "album": "Bricolage"},
            pattern="{artist}/{album}",
        )
        assert result == "Amon Tobin/Bricolage"

    def test_render_with_filename(self):
        result = render_path(
            variables={"filename": "01 - Bricolage", "ext": "flac"},
            pattern="{filename}.{ext}",
        )
        assert result == "01 - Bricolage.flac"

    def test_render_full_library_pattern(self):
        result = render_path(
            variables={
                "owner": "Paul",
                "type": "Albums",
                "genre": "Dance",
                "subgenre": "Ambient",
                "artist": "Amon Tobin",
                "album": "Bricolage",
                "filename": "01 - Bricolage",
                "ext": "flac",
            },
            pattern="{owner}/{type}/{genre}/{subgenre}/{artist}/{album}/{filename}.{ext}",
        )
        assert result == "Paul/Albums/Dance/Ambient/Amon Tobin/Bricolage/01 - Bricolage.flac"

    def test_missing_variable_skips_segment(self):
        result = render_path(
            variables={"artist": "Amon Tobin"},
            pattern="{artist}/{album}/file.flac",
        )
        assert result == "Amon Tobin/file.flac"

    def test_all_variables_missing_returns_empty(self):
        result = render_path(
            variables={},
            pattern="{artist}/{album}",
        )
        assert result == ""

    def test_render_no_variables_in_pattern(self):
        result = render_path(
            variables={"ignored": "value"},
            pattern="static/path/file.flac",
        )
        assert result == "static/path/file.flac"
