# Maestro

Organise and manage your music library.

This software is under *HEAVY* development right now, expect lack of documentation, major bugs and missing functionality.

## Description

Maestro scans your music directories, analyses metadata, and helps organise
your collection by fixing tags, renaming files, and detecting duplicates.

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [Astral uv](https://github.com/astral-sh/uv#installation)

## Quick start

### Installation

```bash
git clone https://github.com/binhex/maestro
cd maestro
uv venv --quiet
uv sync
```

### Usage

```bash
maestro --help
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `maestro scan [roots...]` | Scan download roots, or `--library` to scan existing library |
| `maestro identify` | Identify albums via ID3 tags or folder heuristics |
| `maestro check` | Check download quality against library |
| `maestro import` | Import identified albums into library |
| `maestro tag [--clear]` | Write or clear ID3 tags |
| `maestro artwork` | Download album art and fanart (run `scan --library` first) |
| `maestro daemon` | Run scheduled pipeline in foreground |
| `maestro config` | Display current configuration |

### Configuration

Maestro can be configured via a YAML file at one of these locations:
- `$MAESTRO_CONFIG` environment variable
- `./configs/maestro.yaml` (project root)
- `~/.config/maestro/maestro.yaml`
- `~/.maestro.yaml`

### Path pattern variables

The `pattern` field in library and download roots supports these variables.
They are replaced with metadata from ID3 tags or extracted from folder/file names.

| Variable | Source | Example |
|----------|--------|--------|
| `{artist}` | ID3 tag or folder heuristic | `Amon Tobin` |
| `{album}` | ID3 tag or folder heuristic | `Bricolage` |
| `{title}` | ID3 tag | `Bricolage` |
| `{track}` | ID3 tag or parsed filename | `01` |
| `{year}` | ID3 tag | `1997` |
| `{genre}` | ID3 tag | `Electronic` |
| `{subgenre}` | ID3 tag or path-extracted | `Ambient` |
| `{filename}` | File basename (no extension) | `01 - Bricolage` |
| `{ext}` | File extension | `flac` |
| `{format}` | Normalised format | `FLAC` |
| `{bitrate}` | Audio bitrate (kbps) | `1411` |
| `{path}` | Full original path | `/downloads/user/Bricolage` |
| `{downloader}` | Extracted from download path | `user123` |
| `{owner}` | Extracted from library path | `Paul` |
| `{type}` | Extracted from library path | `Albums` |
| `{hash}` | File hash (hex) | `a1b2c3d4` |

Missing variables are silently collapsed from the resulting path.

```yaml
library_roots:
  - path: "/path/to/music/library"
    type: library
    pattern: "{artist}/{album}/{filename}.{ext}"

download_roots:
  - path: "/path/to/downloads"
    type: download
    pattern: "{downloader}/{album}"

quality:
  min_acceptable: 3
  delete_replaced: false

artwork:
  album_art: cover.jpg
  fanart: fanart.jpg
  skip_if_exists: true
  sources:
    - musicbrainz
    - lastfm
  width: 500
  height: 500

scheduler:
  schedule: "0 3 * * *"
  run_on_start: true
  max_retries: 3
```

### Artwork dimensions

The `artwork` section supports `width` and `height` to control image quality.
Downloaded artwork is validated against these settings before saving:

| Condition | Result |
|-----------|--------|
| Image is larger than `width`×`height` | Resized down using high-quality Lanczos filter |
| Either dimension is below ⅓ of target | Rejected (too small for album art) |
| Aspect ratio exceeds 3:1 | Rejected (wrong shape, would need stretching) |
| Image meets all criteria | Saved at original or resized size |

If an image fails validation, Maestro automatically tries the next source in
`sources` before giving up.

## Development

```bash
git clone https://github.com/binhex/maestro
cd maestro
uv venv --quiet
uv sync --extra dev
```

If you wish to perform linting on all files before committing (PR will not be
accepted if it does not pass all linting) then run `pre-commit run --all-files`.

## FAQ

WIP

___
If you appreciate my work, then please consider buying me a beer  :D

[![PayPal donation](https://www.paypal.com/en_US/i/btn/btn_donate_SM.gif)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=MM5E27UX6AUU4)
