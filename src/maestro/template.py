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


def _build_regex(
    tokens: list[tuple[str, str]],
    max_vars: int | None = None,
) -> tuple[str, list[str]]:
    """Build a regex pattern from tokens, optionally limiting variable count.

    Args:
        tokens: List of (type, value) pairs from :func:`_tokenize`.
        max_vars: Maximum number of variables to include. ``None`` means all.

    Returns:
        Tuple of (regex_string, variable_names).
    """
    parts: list[str] = []
    names: list[str] = []
    for token_type, value in tokens:
        if max_vars is not None and len(names) >= max_vars:
            break
        if token_type == "literal":
            parts.append(re.escape(value))
        else:
            parts.append(r"(.+)")
            names.append(value)
    return f"^{''.join(parts)}$", names


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

    # Full match -- all variables
    full_regex, var_names = _build_regex(tokens)
    match = re.match(full_regex, path)
    if match:
        return dict(zip(var_names, match.groups(), strict=False))

    # Partial match -- try matching as many leading variables as possible
    for end_idx in range(len(var_names) - 1, 0, -1):
        partial_regex, names = _build_regex(tokens, max_vars=end_idx)
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
    collapsed = re.sub(r"/{2,}", "/", result)
    # Use callable to avoid backslash-escaping issues in replacement
    collapsed = re.sub(r"\\{2,}", lambda m: "\\", collapsed)
    collapsed = collapsed.strip("/\\")
    return collapsed
