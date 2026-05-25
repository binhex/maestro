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

        release_id = releases[0]["id"]

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
            if source == "musicbrainz":
                data = fetch_album_art_musicbrainz(artist, album)
            elif source == "lastfm":
                data = fetch_album_art_lastfm(artist, album, lastfm_api_key)
            else:
                data = None

            if data is not None:
                album_art_path.write_bytes(data)
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
