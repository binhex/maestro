"""Path template engine — parse source paths and render destination paths.

Supports variables like {artist}, {album}, {genre}, {filename}, {ext}, etc.
Parse mode extracts values from a real path using a pattern.
Render mode constructs a target path from variable values using a pattern.
"""

import re

_VARIABLE_RE = re.compile(r"\{(\w+)\}")


def _tokenize(pattern: str) -> list[tuple[str, str]]:
    """Split a pattern into a list of (type, value) tokens.

    Type is either 'var' for a variable or 'literal' for a static segment.
    """
    tokens: list[tuple[str, str]] = []
    last_end = 0
    for match in _VARIABLE_RE.finditer(pattern):
        start, end = match.start(), match.end()
        if start > last_end:
            tokens.append(("literal", pattern[last_end:start]))
        tokens.append(("var", match.group(1)))
        last_end = end
    if last_end < len(pattern):
        tokens.append(("literal", pattern[last_end:]))
    return tokens


def parse_variables(path: str, pattern: str) -> dict[str, str]:
    """Extract variable values from a real filesystem path using a pattern.

    The pattern is split on forward slashes and backslashes to match path
    components.

    Args:
        path: The actual filesystem path (e.g. 'Amon Tobin/Bricolage').
        pattern: The template pattern (e.g. '{artist}/{album}').

    Returns:
        A dictionary of variable name to extracted value.
        Only variables that could be matched are included.
    """
    tokens = _tokenize(pattern)

    # Build regex from pattern
    regex_parts: list[str] = []
    var_names: list[str] = []
    for token_type, value in tokens:
        if token_type == "literal":
            regex_parts.append(re.escape(value))
        else:
            regex_parts.append(r"(.+)")
            var_names.append(value)

    full_regex = f"^{''.join(regex_parts)}$"
    match = re.match(full_regex, path)
    if match:
        return dict(zip(var_names, match.groups(), strict=False))

    # Partial match — try matching as many leading variables as possible
    for end_idx in range(len(var_names) - 1, 0, -1):
        parts: list[str] = []
        names: list[str] = []
        for token_type, value in tokens:
            if token_type == "literal":
                if len(names) >= end_idx:
                    break
                parts.append(re.escape(value))
            else:
                if len(names) >= end_idx:
                    break
                parts.append(r"(.+)")
                names.append(value)
        partial_regex = f"^{''.join(parts)}$"
        m = re.match(partial_regex, path)
        if m:
            return dict(zip(names, m.groups(), strict=False))

    return {}


def render_path(variables: dict[str, str], pattern: str) -> str:
    """Construct a path from variable values using the pattern.

    Variables missing from the dictionary are replaced with an empty string,
    causing the corresponding path segment to be collapsed.

    Args:
        variables: Dict of variable name to string value.
        pattern: The template pattern (e.g. '{artist}/{album}').

    Returns:
        The rendered path string.
    """
    result = _VARIABLE_RE.sub(lambda m: variables.get(m.group(1), ""), pattern)
    # Collapse double separators from empty variables
    # Collapse double separators from empty variables
    collapsed = re.sub(r"/{2,}", "/", result)
    # Use callable to avoid backslash-escaping issues in replacement
    collapsed = re.sub(r"\\{2,}", lambda m: "\\", collapsed)
    collapsed = collapsed.strip("/\\")
    return collapsed
