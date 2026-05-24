"""Quality comparison for audio files.

Provides tier-based ranking of audio formats and comparison logic to
determine whether a downloaded track should replace its library counterpart.
"""

_QUALITY_TIERS: dict[str, int] = {
    "FLAC": 10,
    "WAV": 9,
    "AIFF": 8,
    "MP3": 7,
    "OGG": 4,
    "AAC": 2,
    "M4A": 2,
}


_MP3_BITRATE_THRESHOLDS: list[tuple[int, int]] = [
    (320, 7),
    (245, 6),
    (191, 3),  # CBR 192+
    (190, 5),  # V2 (VBR, ~190 kbps avg) — higher quality than CBR at same bitrate
    (160, 3),  # CBR 160-189
    (128, 1),  # CBR 128-159
]


def get_quality_tier(format_name: str, bitrate: int | None = None) -> int:
    """Determine the quality tier for a given format and optional bitrate.

    Args:
        format_name: Audio format string (e.g. 'FLAC', 'MP3', 'AAC').
        bitrate: Bitrate in kbps. Used for MP3 sub-tier differentiation.

    Returns:
        Integer tier from 0 (lowest) to 10 (highest).
    """
    fmt = format_name.upper().strip()

    if fmt == "MP3" and bitrate is not None:
        for min_br, tier in _MP3_BITRATE_THRESHOLDS:
            if bitrate >= min_br:
                return tier
        return 1

    return _QUALITY_TIERS.get(fmt, 0)


def compare_tracks(
    library_track: tuple[str, int | None] | None,
    download_track: tuple[str, int | None],
) -> str:
    """Compare a library track against a downloaded track.

    Args:
        library_track: (format, bitrate) tuple from the library, or None.
        download_track: (format, bitrate) tuple from the download.

    Returns:
        'import' — no library match, always import.
        'skip' — library already has equal or better quality.
        'replace' — download has better quality than library.
    """
    if library_track is None:
        return "import"

    lib_fmt, lib_br = library_track
    dl_fmt, dl_br = download_track

    lib_tier = get_quality_tier(lib_fmt, lib_br)
    dl_tier = get_quality_tier(dl_fmt, dl_br)

    if dl_tier > lib_tier:
        return "replace"
    if dl_tier == lib_tier:
        if dl_br is not None and lib_br is not None and dl_br > lib_br:
            return "replace"
        return "skip"
    return "skip"
