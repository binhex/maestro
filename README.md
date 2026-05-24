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
| `maestro scan [roots...]` | Scan download roots for new music |
| `maestro identify` | Identify albums via ID3 tags or folder heuristics |
| `maestro check` | Check download quality against library |
| `maestro import` | Import identified albums into library |
| `maestro tag [--clear]` | Write or clear ID3 tags |
| `maestro artwork` | Download album art and fanart |
| `maestro daemon` | Run scheduled pipeline in foreground |
| `maestro config` | Display current configuration |

### Configuration

Maestro can be configured via a YAML file at one of these locations:
- `$MAESTRO_CONFIG` environment variable
- `./maestro.yaml` (project root)
- `~/.config/maestro/maestro.yaml`
- `~/.maestro.yaml`

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
  sources:
    - musicbrainz
    - lastfm
    - discogs

scheduler:
  schedule: "0 3 * * *"
  run_on_start: true
  max_retries: 3
```

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
