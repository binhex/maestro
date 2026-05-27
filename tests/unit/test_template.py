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

    def test_render_with_special_chars(self):
        result = render_path({"artist": "AC/DC"}, "{artist}/file.flac")
        # Slash in variable value is handled by _fs_safe in organizer but
        # render_path just inserts it, which may produce double separators
        assert "AC/DC" in result or "AC_DC" in result


class TestTemplateEdgeCases:
    """Additional edge cases for template module."""

    def test_parse_empty_string(self) -> None:
        result = parse_variables("", "{artist}/{album}")
        assert result == {}

    def test_parse_pattern_ending_with_literal(self) -> None:
        """A pattern that ends with a literal suffix (no final variable)."""
        result = parse_variables(
            path="Some Artist/Some Album/track01.flac",
            pattern="{artist}/{album}/{filename}.{ext}",
        )
        assert result["artist"] == "Some Artist"
        assert result["album"] == "Some Album"
        assert result["filename"] == "track01"
        assert result["ext"] == "flac"

    def test_parse_partial_match_returns_leading_vars(self) -> None:
        """When the path is shorter than the pattern, leading variables are returned."""
        result = parse_variables(
            path="Some Artist",
            pattern="{artist}/{album}",
        )
        assert result == {"artist": "Some Artist"}

    def test_parse_partial_with_literal_prefix(self) -> None:
        """Partial match with a literal prefix before variables."""
        result = parse_variables(
            path="music/Some Artist",
            pattern="music/{artist}/{album}",
        )
        assert result == {"artist": "Some Artist"}

    def test_parse_no_match_returns_empty(self) -> None:
        """When pattern cannot be matched at all, empty dict is returned."""
        # With a literal prefix that doesn't appear in the path, nothing matches
        result = parse_variables(
            path="nope",
            pattern="prefix/{artist}",
        )
        assert result == {}

    def test_parse_partial_inner_variable_not_matched(self) -> None:
        """When only 1 of 3 vars can match, returns only the matching one."""
        # Pattern: {genre}/{artist}/{album}, path: "Rock"
        # Only genre can match
        result = parse_variables(
            path="Rock",
            pattern="{genre}/{artist}/{album}",
        )
        assert result == {"genre": "Rock"}

    def test_parse_pattern_ending_with_literal_no_var(self) -> None:
        """A pattern that ends with a non-variable literal suffix."""
        # Pattern ends with "/foo" — no final variable, triggers line 27.
        result = parse_variables(
            path="SomeValue/foo",
            pattern="{var}/foo",
        )
        assert result == {"var": "SomeValue"}

    def test_parse_consecutive_vars_no_separator(self) -> None:
        """Variables with no literal separator between them."""
        result = parse_variables(
            path="ab",
            pattern="{a}{b}",
        )
        assert result == {"a": "a", "b": "b"}

    def test_parse_partial_consecutive_vars_break(self) -> None:
        """Partial match stops at correct var boundary with consecutive vars."""
        # Pattern with 3 consecutive vars, path with only 2 segments
        # Partial match should collect {a}{b} with var break at {c}
        result = parse_variables(
            path="ab",
            pattern="{a}{b}{c}",
        )
        assert result == {"a": "a", "b": "b"}
