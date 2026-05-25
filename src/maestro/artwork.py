"""Artwork downloader — fetch album art and fanart from multiple sources.

Supported sources:
- MusicBrainz → Cover Art Archive (free, no key needed)
- Last.fm (free API key needed)

Configurable source priority order.
"""

from __future__ import annotations

from pathlib import Path

import requests  # type: ignore[import-untyped]

# Default headers for HTTP requests
_HEADERS = {
    "User-Agent": "Maestro/1.0 (music organizer; https://github.com/binhex/maestro)",
}


def get_artwork_paths(
    album_dir: str,
    album_art: str = "cover.jpg",
    fanart: str = "fanart.jpg",
) -> dict[str, str]:
    """Get the expected file paths for artwork in an album directory.

    Args:
        album_dir: Path to the album directory.
        album_art: Filename for album art (e.g. ``'cover.jpg'``, ``'folder.jpg'``).
        fanart: Filename for fanart (e.g. ``'fanart.jpg'``, ``'background.jpg'``).

    Returns:
        Dict with keys ``'album_art'`` and ``'fanart'`` mapping to full paths.
    """
    base = Path(album_dir)
    return {
        "album_art": str(base / album_art),
        "fanart": str(base / fanart),
    }


def _get_mb_artist_name(release: dict) -> str:
    """Extract the artist name from a MusicBrainz release dict."""
    artist_credit: list = release.get("artist-credit", [])
    if artist_credit:
        first = artist_credit[0]
        if isinstance(first, dict) and "artist" in first:
            artist_info = first["artist"]
            if isinstance(artist_info, dict):
                name_val = artist_info.get("name", "")
                return str(name_val) if name_val else ""
        return str(first) if first else ""
    return ""


def _artists_match(query: str, result: str) -> bool:
    """Check if the queried artist matches the returned artist name."""
    return query.lower().strip() == result.lower().strip()


def _titles_match(query: str, result: str) -> bool:
    """Check if the queried album title matches the returned title."""
    q = " ".join(query.lower().split())
    r = " ".join(result.lower().split())
    return q == r


def fetch_album_art_musicbrainz(artist: str, album: str) -> bytes | None:
    """Fetch album art from MusicBrainz via the Cover Art Archive.

    Searches MusicBrainz for the release matching *artist* and *album*,
    then fetches the front cover image from the Cover Art Archive.

    Args:
        artist: Artist name.
        album: Album title.

    Returns:
        Raw image bytes, or ``None`` if not found or an error occurs.
    """
    try:
        import musicbrainzngs  # type: ignore[import-not-found]

        musicbrainzngs.set_useragent(
            "maestro",
            "1.0",
            "https://github.com/binhex/maestro",
        )

        result = musicbrainzngs.search_releases(
            artist=artist,
            release=album,
            limit=1,
        )
        releases = result.get("release-list", [])
        if not releases:
            return None

        # Verify the returned release actually matches what we searched for.
        # MusicBrainz may return a compilation or misattributed release.
        release = releases[0]
        release_title = (release.get("title") or "").lower()
        release_artist = _get_mb_artist_name(release)

        if not _artists_match(artist, release_artist) or not _titles_match(album, release_title):
            return None

        release_id = release["id"]

        url = f"https://coverartarchive.org/release/{release_id}/front"
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.content  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        pass

    return None


def fetch_album_art_lastfm(
    artist: str,
    album: str,
    api_key: str | None = None,
) -> bytes | None:
    """Fetch album art from the Last.fm API.

    Args:
        artist: Artist name.
        album: Album title.
        api_key: Last.fm API key. If ``None`` the function returns ``None``.

    Returns:
        Raw image bytes, or ``None`` if not found or an error occurs.
    """
    if not api_key:
        return None

    try:
        url = "https://ws.audioscrobbler.com/2.0/"
        params: dict[str, str] = {
            "method": "album.getinfo",
            "api_key": api_key,
            "artist": artist,
            "album": album,
            "format": "json",
        }
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        images = data.get("album", {}).get("image", [])
        if not images:
            return None

        # Get the largest image (last entry)
        largest = images[-1].get("#text", "")
        if not largest:
            return None

        img_resp = requests.get(largest, headers=_HEADERS, timeout=15)
        if img_resp.status_code == 200:
            return img_resp.content  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        pass

    return None


def fetch_fanart_lastfm(artist: str, api_key: str | None = None) -> bytes | None:
    """Fetch artist fanart/background image from the Last.fm API.

    Args:
        artist: Artist name.
        api_key: Last.fm API key. If ``None`` the function returns ``None``.

    Returns:
        Raw image bytes, or ``None`` if not found or an error occurs.
    """
    if not api_key:
        return None

    try:
        url = "https://ws.audioscrobbler.com/2.0/"
        params: dict[str, str] = {
            "method": "artist.getinfo",
            "api_key": api_key,
            "artist": artist,
            "format": "json",
        }
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        images = data.get("artist", {}).get("image", [])
        if not images:
            return None

        # Get the largest image (last entry)
        largest = images[-1].get("#text", "")
        if not largest:
            return None

        img_resp = requests.get(largest, headers=_HEADERS, timeout=15)
        if img_resp.status_code == 200:
            return img_resp.content  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        pass

    return None


def download_artwork_for_album(
    album_dir: str,
    artist: str,
    album: str,
    album_art_filename: str = "cover.jpg",
    fanart_filename: str = "fanart.jpg",
    lastfm_api_key: str | None = None,
    sources: list[str] | None = None,
    max_width: int = 500,
    max_height: int = 500,
    aspect_tolerance_percentage: int = 5,
) -> dict[str, bool | str | None]:
    """Download album art and fanart for a given album.

    Creates the album directory if it does not exist. Tries each configured
    source in order for album art, stopping at the first success. Fanart is
    fetched from Last.fm only.

    Args:
        album_dir: Path to the album directory.
        artist: Artist name.
        album: Album title.
        album_art_filename: Output filename for album art.
        fanart_filename: Output filename for fanart.
        lastfm_api_key: Last.fm API key (optional).
        sources: Ordered list of source names to try.
            Default: ``['musicbrainz', 'lastfm']``.
        max_width: Target width for resizing (images too small or wrong
            aspect ratio are rejected).
        max_height: Target height for resizing.

    Returns:
        Dict with keys ``'album_art'`` (bool), ``'fanart'`` (bool),
        and ``'source_used'`` (str or None) indicating which source
        provided the album art.
    """
    result: dict[str, bool | str | None] = {
        "album_art": False,
        "fanart": False,
        "source_used": None,
    }

    album_path = Path(album_dir)
    album_path.mkdir(parents=True, exist_ok=True)

    album_art_path = album_path / album_art_filename
    fanart_path = album_path / fanart_filename

    if sources is None:
        sources = ["musicbrainz", "lastfm"]

    # Try to fetch album art from configured sources in order
    if album_art_path.exists():
        result["album_art"] = True
        result["source_used"] = "cached"
    else:
        for source in sources:
            data: bytes | None = None
            if source == "musicbrainz":
                data = fetch_album_art_musicbrainz(artist, album)
            elif source == "lastfm":
                data = fetch_album_art_lastfm(artist, album, lastfm_api_key)

            if data is not None:
                # Validate and resize before saving
                processed = validate_and_resize_image(data, max_width, max_height, aspect_tolerance_percentage)
                if processed is not None:
                    album_art_path.write_bytes(processed)
                    result["album_art"] = True
                    result["source_used"] = source
                    break

    # Try to fetch fanart from Last.fm (only if API key is available)
    if fanart_path.exists():
        result["fanart"] = True
    elif lastfm_api_key:
        data = fetch_fanart_lastfm(artist, lastfm_api_key)
        if data is not None:
            fanart_path.write_bytes(data)
            result["fanart"] = True

    return result


_MIN_SIDE_RATIO = 3  # minimum dimension = max_dim / _MIN_SIDE_RATIO
_ASPECT_TOLERANCE = 0.15  # max allowed deviation from target aspect ratio (15%)


def _aspect_ratio_match(width: int, height: int, target_w: int, target_h: int, tolerance: float = 0.15) -> bool:
    """Check if an image's aspect ratio is close enough to the target.

    Returns True if the ratio deviation is within ``_ASPECT_TOLERANCE``.
    For example, with a 500x500 target (1:1 ratio), a 600x500 image
    (1.2:1) is accepted, but a 1000x500 image (2:1) is rejected.
    """
    if target_w == 0 or target_h == 0:
        return True
    target_ratio = target_w / target_h
    image_ratio = width / height
    if image_ratio == 0:
        return False
    deviation = abs(image_ratio - target_ratio) / target_ratio
    return deviation <= tolerance


def validate_and_resize_image(
    data: bytes,
    max_width: int = 500,
    max_height: int = 500,
    aspect_tolerance_percentage: int = 15,
) -> bytes | None:
    """Validate an image's dimensions and resize if needed.

    Rules:
    - If either dimension is below ``max_width / _MIN_SIDE_RATIO`` or
      ``max_height / _MIN_SIDE_RATIO``, the image is rejected (too small).
    - If the aspect ratio deviates from the target ``max_width/max_height``
      by more than ``aspect_tolerance_percentage``, the image is rejected (wrong shape).
    - If the image is larger than ``(max_width, max_height)``, it is resized
      down proportionally using high-quality Lanczos filtering.
    - Otherwise the image is returned unchanged.

    Args:
        data: Raw image bytes (JPEG, PNG, etc.).
        max_width: Maximum target width in pixels.
        max_height: Maximum target height in pixels.

    Returns:
        Processed image bytes, or ``None`` if the image was rejected.
    """
    try:
        import io

        from PIL import Image as PilImage

        img = PilImage.open(io.BytesIO(data))
        width, height = img.size
    except Exception:  # noqa: BLE001
        return None

    # Ensure both dimensions meet the minimum size threshold
    min_w = max_width // _MIN_SIDE_RATIO
    min_h = max_height // _MIN_SIDE_RATIO
    if width < min_w or height < min_h:
        return None

    # Check aspect ratio matches target within tolerance
    tolerance = aspect_tolerance_percentage / 100.0
    if not _aspect_ratio_match(width, height, max_width, max_height, tolerance):
        return None

    # Resize if larger than target, maintaining aspect ratio
    resized = False
    if width > max_width or height > max_height:
        img.thumbnail((max_width, max_height), PilImage.LANCZOS)
        resized = True

    if not resized:
        return data

    output = io.BytesIO()
    fmt = img.format or "JPEG"
    img.save(output, fmt, quality=95)
    return output.getvalue()
