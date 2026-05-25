# DuckDuckGo Artwork Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DuckDuckGo image search as an artwork source, tried before MusicBrainz and Last.fm.

**Architecture:** New `fetch_album_art_duckduckgo()` function in `artwork.py`. Searches DDG Images for `"{artist} {album} cover"`, downloads top results, validates through existing `validate_and_resize_image()` pipeline, returns first valid result. Default source list updated to `["duckduckgo", "musicbrainz", "lastfm"]`.

**Tech Stack:** Python 3.12, duckduckgo-search library, existing validation pipeline.

---

## Files to Create/Modify

### Modified files
- `pyproject.toml` — add `duckduckgo-search` dependency
- `src/maestro/artwork.py` — add `fetch_album_art_duckduckgo()`, integrate into source loop
- `src/maestro/config.py` — update default sources, update migration

### Test files
- `tests/unit/test_artwork.py` — add tests for new function
- `tests/unit/test_config.py` — update default sources test

---

### Task 1: Add dependency

**Files:**
- Modify: `pyproject.toml`
- Run: `uv sync`

- [ ] **Step 1: Add duckduckgo-search to dependencies**

Edit `pyproject.toml` dependencies section:

```toml
dependencies = [
    "backoff",
    "click",
    "loguru",
    "apprise",
    "pyyaml",
    "requests",
    "sqlalchemy",
    "urllib3",
    "mutagen",
    "croniter",
    "musicbrainzngs",
    "pillow",
    "duckduckgo-search",
]
```

- [ ] **Step 2: Install and verify**

```bash
cd /data/maestro && uv sync
uv run python3 -c "from duckduckgo_search import DDGS; print('ok')"
```

Expected: prints "ok"

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "chore: add duckduckgo-search dependency"
```

---

### Task 2: Update config defaults and migration

**Files:**
- Modify: `src/maestro/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Update ArtworkConfig default sources**

Change `sources` default in `ArtworkConfig`:

```python
class ArtworkConfig:
    """Artwork-related configuration."""
    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    skip_if_exists: bool = True
    sources: list[str] = field(default_factory=lambda: ["duckduckgo", "musicbrainz", "lastfm"])
    width: int = 500
    height: int = 500
    aspect_tolerance_percentage: int = 5
```

- [ ] **Step 2: Update `_default_config_dict()`**

Update the `sources` list in `_default_config_dict()` to `["duckduckgo", "musicbrainz", "lastfm"]`.

- [ ] **Step 3: Update `_migrate_v1_to_v2()`**

Ensure the migration sets `sources` to the new default if the key doesn't already exist. The current code already uses `setdefault` which preserves user customizations.

- [ ] **Step 4: Write failing test for config defaults**

Add to `tests/unit/test_config.py`:

```python
def test_default_sources_includes_duckduckgo(self) -> None:
    """Default ArtworkConfig should have duckduckgo as first source."""
    from maestro.config import ArtworkConfig
    config = ArtworkConfig()
    assert config.sources == ["duckduckgo", "musicbrainz", "lastfm"]
```

- [ ] **Step 5: Run test to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_config.py::TestConfigDataclass::test_default_config -v
```

If the test fails, verify the default is wrong. Otherwise, the test should pass after step 1.

- [ ] **Step 6: Commit**

```bash
git add src/maestro/config.py tests/unit/test_config.py
git commit -m "feat: update default artwork sources to include duckduckgo"
```

---

### Task 3: Implement fetch_album_art_duckduckgo

**Files:**
- Modify: `src/maestro/artwork.py`
- Modify: `tests/unit/test_artwork.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_artwork.py`:

```python
class TestFetchAlbumArtDuckDuckGo:
    """Tests for fetch_album_art_duckduckgo."""

    def test_returns_bytes_on_success(self, mocker) -> None:
        """A successful search and download should return image bytes."""
        from maestro.artwork import fetch_album_art_duckduckgo
        from PIL import Image
        import io
        from pathlib import Path

        # Create a test image
        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        fake_image = buf.getvalue()

        # Mock DDGS().images() to return results
        mock_results = [
            {"image": "https://example.com/cover1.jpg"},
            {"image": "https://example.com/cover2.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch(
            "maestro.artwork.DDGS",
            return_value=mock_ddgs,
        )

        # Mock requests.get to return the fake image
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_duckduckgo("Test Artist", "Test Album")
        assert result is not None
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_returns_none_on_empty_results(self, mocker) -> None:
        """No search results should return None."""
        from maestro.artwork import fetch_album_art_duckduckgo

        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = []
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        result = fetch_album_art_duckduckgo("Unknown", "Unknown")
        assert result is None

    def test_returns_none_when_all_fail_validation(self, mocker) -> None:
        """When all results fail validation, should return None."""
        from maestro.artwork import fetch_album_art_duckduckgo
        from PIL import Image
        import io

        # Create a tiny image that will fail validation
        img = Image.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        small_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/small1.jpg"},
            {"image": "https://example.com/small2.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = small_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is None

    def test_skips_invalid_urls_and_tries_next(self, mocker) -> None:
        """If one URL fails to download, the next should be tried."""
        from maestro.artwork import fetch_album_art_duckduckgo
        from PIL import Image
        import io

        img = Image.new("RGB", (500, 500), color="red")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        valid_image = buf.getvalue()

        mock_results = [
            {"image": "https://example.com/broken.jpg"},
            {"image": "https://example.com/valid.jpg"},
        ]
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = mock_results
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        # First request fails (status != 200), second succeeds
        mock_fail = mocker.MagicMock()
        mock_fail.status_code = 404
        mock_success = mocker.MagicMock()
        mock_success.status_code = 200
        mock_success.content = valid_image
        mocker.patch(
            "maestro.artwork.requests.get",
            side_effect=[mock_fail, mock_success],
        )

        result = fetch_album_art_duckduckgo("Test", "Album")
        assert result is not None
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd /data/maestro && uv run pytest tests/unit/test_artwork.py -k "TestFetchAlbumArtDuckDuckGo" -v
```

Expected: `ImportError: cannot import name 'fetch_album_art_duckduckgo'`

- [ ] **Step 3: Implement the function**

Add to `src/maestro/artwork.py` before `download_artwork_for_album`:

```python
def fetch_album_art_duckduckgo(
    artist: str,
    album: str,
    max_results: int = 5,
) -> bytes | None:
    """Fetch album art via DuckDuckGo image search.

    Searches for ``{artist} {album} cover``, downloads results in order,
    and returns the first image that passes validation.

    Args:
        artist: Artist name.
        album: Album title.
        max_results: Maximum number of search results to try.

    Returns:
        Raw image bytes, or ``None`` if not found or all fail validation.
    """
    try:
        from duckduckgo_search import DDGS  # noqa: PLC0415
    except ImportError:
        return None

    query = f"{artist} {album} cover"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results))
    except Exception:  # noqa: BLE001
        return None

    if not results:
        return None

    for result in results:
        url = result.get("image")
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            processed = validate_and_resize_image(
                resp.content,
                max_width=500,
                max_height=500,
                aspect_tolerance_percentage=5,
            )
            if processed is not None:
                return processed
        except Exception:  # noqa: BLE001
            continue

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /data/maestro && uv run pytest tests/unit/test_artwork.py -k "TestFetchAlbumArtDuckDuckGo" -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/maestro/artwork.py tests/unit/test_artwork.py
git commit -m "feat: add DuckDuckGo artwork source"
```

---

### Task 4: Wire duckduckgo into the artwork download pipeline

**Files:**
- Modify: `src/maestro/artwork.py`
- Modify: `tests/unit/test_artwork.py`

- [ ] **Step 1: Add duckduckgo case to download_artwork_for_album**

Find the source loop in `download_artwork_for_album()` and add the duckduckgo case:

Before the existing source loop, insert:

```python
        for source in sources:
            data: bytes | None = None
            if source == "duckduckgo":
                data = fetch_album_art_duckduckgo(artist, album)
            elif source == "musicbrainz":
                data = fetch_album_art_musicbrainz(artist, album)
            elif source == "lastfm":
                data = fetch_album_art_lastfm(artist, album, lastfm_api_key)
            # ... existing validation and write logic continues unchanged
```

The existing `if data is not None: processed = validate_and_resize_image(...)` logic
handles all sources uniformly — no additional changes needed.

- [ ] **Step 2: Write failing integration test**

Add to `tests/unit/test_artwork.py` in the `TestDownloadArtworkForAlbum` class:

```python
    def test_duckduckgo_is_tried_first(self, tmp_path, mocker) -> None:
        """When duckduckgo is first in sources, it's tried before others."""
        from maestro.artwork import download_artwork_for_album
        from PIL import Image
        import io

        album_dir = tmp_path / "DuckFirst"
        album_dir.mkdir()

        # Create valid image
        img = Image.new("RGB", (500, 500), color="green")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        fake_image = buf.getvalue()

        # Mock DDG search to return a result
        mock_ddgs = mocker.MagicMock()
        mock_ddgs.__enter__.return_value.images.return_value = [
            {"image": "https://example.com/ddg.jpg"},
        ]
        mocker.patch("maestro.artwork.DDGS", return_value=mock_ddgs)

        # Mock requests.get to return valid image
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_image
        mocker.patch("maestro.artwork.requests.get", return_value=mock_response)

        # Mock musicbrainzngs to ensure it's NOT called
        mock_mb = mocker.patch("musicbrainzngs.search_releases")

        result = download_artwork_for_album(
            album_dir=str(album_dir),
            artist="Test Artist",
            album="Test Album",
            sources=["duckduckgo", "musicbrainz"],
        )

        assert result["album_art"] is True
        assert result["source_used"] == "duckduckgo"
        # musicbrainz should NOT have been called (ddg succeeded first)
        mock_mb.assert_not_called()
```

- [ ] **Step 3: Run tests**

```bash
cd /data/maestro && uv run pytest tests/unit/test_artwork.py -v -k "duckduckgo or DuckDuckGo or TestFetch" --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/maestro/artwork.py tests/unit/test_artwork.py
git commit -m "feat: wire duckduckgo into artwork download pipeline"
```

---

### Task 5: Run full verification

**Files:** (no code changes)

- [ ] **Step 1: Run all QA gates**

```bash
cd /data/maestro && \
  rm -rf .coverage* htmlcov/ coverage.xml .mypy_cache && \
  uv run ruff check --fix . && \
  uv run ruff format . && \
  uv run mypy . --no-error-summary && \
  uv run pytest --cov=src/maestro --cov-fail-under=88 -q
```

Expected: all gates pass.

- [ ] **Step 2: Verify generated config**

```bash
cd /data/maestro && rm -f configs/maestro.yaml
uv run maestro scan --help > /dev/null 2>&1
grep -A 2 "sources:" configs/maestro.yaml
```

Expected: sources includes duckduckgo first.

- [ ] **Step 3: Commit plan**

```bash
git add docs/superpowers/plans/2026-05-25-duckduckgo-artwork-source.md
git commit -m "docs: add DuckDuckGo artwork source implementation plan"
```
