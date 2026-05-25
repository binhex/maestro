# DuckDuckGo Artwork Source

> Add DuckDuckGo image search as a primary artwork source for Maestro, improving
> coverage when MusicBrainz and Last.fm fail to find album art.

## Motivation

The current artwork sources (MusicBrainz Cover Art Archive, Last.fm) fail to find
artwork for a significant portion of albums. DuckDuckGo image search provides a
broad web search that can find album art from any website, filling these gaps.

## Priority Order

Default sources order: `["duckduckgo", "musicbrainz", "lastfm"]`

DuckDuckGo is tried first because:
- It searches the open web (highest chance of finding something)
- MusicBrainz and Last.fm serve as fallbacks with more authoritative results

## Search Query

Format: `"{artist} {album} cover"`

Examples:
- `"Amon Tobin Bricolage cover"`
- `"Classic FM Music For Studying cover"`

The word `"cover"` is appended to filter out unrelated images and increase the
likelihood of getting actual album cover art.

## Data Flow

```
download_artwork_for_album()
  → for source in sources:
    → if source == "duckduckgo":
      call fetch_album_art_duckduckgo(artist, album)
        → DuckDuckGo images search for "{artist} {album} cover"
        → Get top 5 image result URLs
        → For each URL (in order):
          → Download image bytes
          → validate_and_resize_image(bytes, max_width, max_height, tolerance)
          → If valid → return bytes
          → If invalid → try next URL
        → Return None (no valid image found)
    → if source == "musicbrainz": (existing, unchanged)
    → if source == "lastfm": (existing, unchanged)
```

## Component Changes

### `artwork.py` — New function

```python
def fetch_album_art_duckduckgo(
    artist: str,
    album: str,
    max_results: int = 5,
) -> bytes | None:
```

- Uses `duckduckgo_search` library's `DDGS().images()` method
- Searches for `"{artist} {album} cover"`
- Iterates results, downloads each image URL
- Passes downloaded bytes through `validate_and_resize_image()`
- Returns first valid image bytes, or None

### `artwork.py` — Integration in `download_artwork_for_album()`

Add a `"duckduckgo"` case in the source loop:

```python
for source in sources:
    if source == "duckduckgo":
        data = fetch_album_art_duckduckgo(artist, album)
    elif source == "musicbrainz":
        data = fetch_album_art_musicbrainz(artist, album)
    elif source == "lastfm":
        data = fetch_album_art_lastfm(artist, album, lastfm_api_key)
    # ... existing validation and write logic
```

No other changes needed — the existing `validate_and_resize_image()` call and
`album_art_path.write_bytes()` logic already handle validation and saving.

### `config.py` — Default source list

```python
class ArtworkConfig:
    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    skip_if_exists: bool = True
    sources: list[str] = field(default_factory=lambda: ["duckduckgo", "musicbrainz", "lastfm"])
    width: int = 500
    height: int = 500
    aspect_tolerance_percentage: int = 5
```

### `config.py` — Migration update

Update `_migrate_v1_to_v2()` to set sources to `["duckduckgo", "musicbrainz", "lastfm"]`
if the `sources` key doesn't already exist (existing configs with custom source
lists are preserved).

### Dependencies

Add `duckduckgo-search` to `pyproject.toml`.

## Error Handling

- Network errors in DuckDuckGo search or image download → caught, logged, returns None
- No search results → returns None
- All results fail validation (wrong size, aspect ratio, corrupt) → returns None
- On None return, the next source in the list is tried automatically

## Testing

- Unit test `fetch_album_art_duckduckgo` with mocked `DDGS().images()`
- Test: returns bytes on successful search + download
- Test: returns None on empty search results
- Test: returns None when all results fail validation
- Test: integration with `download_artwork_for_album` when duckduckgo is first source
- Test: config default sources updated
- Test: migration preserves existing custom source lists
