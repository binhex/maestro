# Maestro Config Options — Dry Run & Artwork Disable

> Three new configuration options: a global dry-run mode that simulates imports
> without modifying files, and per-feature toggles to disable album art and/or
> fanart downloading.

## Overview

Add three configuration knobs to Maestro. All are optional — default values
preserve current behaviour.

| Option | Type | Default | Scope |
|--------|------|---------|-------|
| `dry_run` | `bool` | `false` | Global (affects import pipeline) |
| `download_album_art` | `bool` | `true` | Under `artwork` section |
| `download_fanart` | `bool` | `true` | Under `artwork` section |

Dry run also gets a `--dry-run` CLI flag on both `maestro import` and
`maestro daemon`, which overrides the config value.

---

## 1. Config Schema

### Changes to `config.py`

**`CONFIG_VERSION` bumped to `3`** with a `_migrate_v2_to_v3` migration.

```python
CONFIG_VERSION = 3

@dataclass
class ArtworkConfig:
    download_album_art: bool = True     # NEW — false = skip album art
    download_fanart: bool = True        # NEW — false = skip fanart
    album_art: str = "cover.jpg"
    fanart: str = "fanart.jpg"
    skip_if_exists: bool = True
    sources: list[str] = field(default_factory=lambda: [...])
    # width, height, aspect_tolerance_percentage unchanged

@dataclass
class Config:
    dry_run: bool = False               # NEW — top-level field
    library_roots: list[RootEntry] = ...
    download_roots: list[RootEntry] = ...
    quality: QualityConfig = ...
    artwork: ArtworkConfig = ...
    scheduler: SchedulerConfig = ...
```

### Migration `v2 → v3`

```python
_MIGRATIONS: dict[int, Any] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,  # registered
}

def _migrate_v2_to_v3(data: dict) -> None:
    """Add dry_run at root, download_album_art/fanart under artwork."""
    data.setdefault("dry_run", False)
    artwork = data.setdefault("artwork", {})
    artwork.setdefault("download_album_art", True)
    artwork.setdefault("download_fanart", True)
```

### Default YAML additions

```yaml
# Top-level
dry_run: false

# Under artwork:
artwork:
  download_album_art: true
  download_fanart: true
  album_art: cover.jpg
  fanart: fanart.jpg
  skip_if_exists: true
  sources: [duckduckgo, musicbrainz, lastfm]
```

### `show_config` display

The `maestro config` command gains lines for the new fields:

```
Dry run: false
Artwork download album art: true
Artwork download fanart: true
```

---

## 2. Organizer — Dry Run Support

**File:** `src/maestro/organizer.py` — function `import_downloads()`

### Signature change

```python
def import_downloads(
    session: Session,
    destination_root: str,
    destination_pattern: str,
    move: bool = True,
    delete_replaced: bool = False,
    dry_run: bool = False,            # NEW
) -> dict[str, Any]:
```

### Behaviour when `dry_run=True`

1. Iterate through all `identified` downloads (same as real run)
2. For each download:
   - Construct destination path via `render_path()` (same as real run)
   - Compare quality against existing library album (same as real run)
   - If better quality or new → log `"Would move: {src} → {dst}"`
   - If replacing existing → log `"Would replace: {old_path} → {dst}"`
   - If better AND `delete_replaced` → log `"Would delete: {old_path}"`
   - If quality equal/worse → log `"Would skip: {path} (quality tie/worse)"`
3. **Never** calls `shutil.move()`, `shutil.copy2()`, `Path.unlink()`, `os.remove()`, or any filesystem-mutating operation
4. **Never** creates or modifies DB records (no Artist, Album, Track, or Download status changes)
5. Returns a result dict with extra `dry_run` and `actions` keys:

```python
{
    "imported": 0,          # always 0
    "skipped": 5,
    "replaced": 3,
    "errors": 0,
    "dry_run": True,
    "actions": [
        "Would skip: /dl/foo/bar (quality tie/worse)",
        "Would move: /dl/artist/album → /lib/Artist/Album",
        "Would replace: /lib/Artist/Album/old.flac",
    ],
}
```

---

## 3. CLI — `--dry-run` Flag

**File:** `src/maestro/cli.py`

### `import` command

```python
@cli.command(name="import")
@click.option("--dry-run", is_flag=True, default=False,
              help="Simulate import without making changes.")
@click.pass_context
def import_(ctx: click.Context, dry_run: bool) -> None:
    config, _engine, session = _setup(ctx)
    try:
        effective_dry_run = dry_run or config.dry_run
        result = import_downloads(
            session=session,
            destination_root=...,
            destination_pattern=...,
            move=True,
            delete_replaced=config.quality.delete_replaced,
            dry_run=effective_dry_run,
        )
        if effective_dry_run:
            click.echo("--- DRY RUN --- No files were changed ---")
            for action in result.get("actions", []):
                click.echo(f"  {action}")
            click.echo(f"Summary: would import={result['imported']} "
                       f"would skip={result['skipped']} "
                       f"would replace={result['replaced']}")
        else:
            click.echo(f"imported={result['imported']} ...")
    finally:
        session.close()
```

### `daemon` command

```python
@cli.command()
@click.option("--dry-run", is_flag=True, default=False,
              help="Run daemon pipeline in dry-run mode.")
@click.pass_context
def daemon(ctx: click.Context, dry_run: bool) -> None:
    config, _engine, session = _setup(ctx)
    session.close()
    if dry_run:
        config.dry_run = True  # override config value
    daemon_instance = Daemon(config, db_path=...)
    daemon_instance.run()
```

### Precedence

```
CLI --dry-run flag → overrides all
                    ↓
           config.dry_run → used if flag not set
                    ↓
           default (false) → used if nothing set
```

---

## 4. Daemon / Pipeline — Threading `dry_run`

**File:** `src/maestro/daemon.py`

### `run_pipeline()` change

```python
def run_pipeline(config, session):
    # ... scan phase unchanged ...
    # ... identify phase unchanged ...

    # Import phase
    import_result = import_downloads(
        session=session,
        destination_root=lib_root.path,
        destination_pattern=dest_pattern,
        move=True,
        delete_replaced=config.quality.delete_replaced,
        dry_run=config.dry_run,          # NEW — read from config
    )
    result["imported"] = import_result
    logger.info("Import: {}", import_result)
```

The `Daemon` class itself doesn't need structural changes — it already passes `config` through to `run_pipeline()`. The only addition is the CLI `--dry-run` override in the `daemon` command (section 3), which mutates `config.dry_run` before constructing the `Daemon`.

---

## 5. Artwork — Disable Album Art / Fanart

**File:** `src/maestro/artwork.py`

### `download_artwork_for_album()` signature change

```python
def download_artwork_for_album(
    album_dir: str,
    artist: str,
    album: str,
    album_art_filename: str = "cover.jpg",
    fanart_filename: str = "fanart.jpg",
    download_album_art: bool = True,       # NEW
    download_fanart: bool = True,          # NEW
    lastfm_api_key: str | None = None,
    sources: list[str] | None = None,
    max_width: int = 500,
    max_height: int = 500,
    aspect_tolerance_percentage: int = 5,
) -> dict[str, Any]:
```

### Behaviour

- If `download_album_art` is `False`: skip all album art source lookups. Returned dict has `album_art: None` and `source_used: None` (unless fanart still runs).
- If `download_fanart` is `False`: skip all fanart source lookups. Returned dict has `fanart: None`.
- If both are `False`: log a single info-level message and return early.

### CLI `artwork` command wiring

```python
@cli.command()
@click.pass_context
def artwork(ctx: click.Context) -> None:
    config, _engine, session = _setup(ctx)
    try:
        if not config.artwork.download_album_art and not config.artwork.download_fanart:
            click.echo("Artwork downloading is disabled in config.")
            return

        for album in albums:
            result = download_artwork_for_album(
                album_dir=album_dir,
                artist=album.artist.name,
                album=album.title,
                album_art_filename=config.artwork.album_art,
                fanart_filename=config.artwork.fanart,
                download_album_art=config.artwork.download_album_art,   # NEW
                download_fanart=config.artwork.download_fanart,         # NEW
                lastfm_api_key=api_key,
                sources=sources,
                # ... rest unchanged
            )
    finally:
        session.close()
```

---

## 6. Files Changed

| File | Change |
|------|--------|
| `src/maestro/config.py` | Add `dry_run` field, `download_album_art`/`download_fanart` fields, bump version, add migration |
| `src/maestro/organizer.py` | Add `dry_run` parameter to `import_downloads()`, conditional skip of file ops |
| `src/maestro/artwork.py` | Add `download_album_art`/`download_fanart` params, conditional skip |
| `src/maestro/daemon.py` | Pass `config.dry_run` to `import_downloads()` in pipeline |
| `src/maestro/cli.py` | `--dry-run` flag on `import` and `daemon`; wire artwork toggles; show in `config` |
| `tests/unit/test_config.py` | Tests for new config fields and migration |
| `tests/unit/test_organizer.py` | Tests for `dry_run` behaviour |
| `tests/unit/test_artwork.py` | Tests for disable flags |
| `tests/unit/test_cli.py` | Tests for `--dry-run` CLI flag |
