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

## Options

WIP

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
