# Maestro Core Design

> Music library organiser — CLI + daemon for scanning, identifying, organising, tagging,
> and managing music collections with quality-aware deduplication.

## Architecture

**Approach:** Modular pipeline (Approval — 24/05/2026)

Each subsystem is an independent module with a single responsibility. The SQLite database
serves as the central bus — modules read from and write to it rather than calling each
other directly. The daemon runs an orchestration loop: scan → identify → check → import
→ tag → artwork.

```
CLI ──► Scanner ──► DB ──► Identifier ──► Quality Check ──► Organizer ──► Tagger ──► Artwork
                                                                                │
                                    Daemon (croniter scheduler loop) ◄─────────┘
```

## Project Structure

```
src/maestro/
├── __init__.py
├── __main__.py
├── cli.py              # Click entry point with subcommands
├── daemon.py            # Daemon lifecycle + scheduler loop
├── config.py            # YAML config loading and validation
├── db/
│   ├── __init__.py
│   ├── models.py        # SQLAlchemy ORM models
│   ├── schema.py        # Table definitions, migrations
│   └── core.py          # Session management, connection
├── scanner.py           # Walk filesystem, extract metadata
├── identifier.py        # Match downloads → library entries
├── organizer.py         # Move/copy using path templates
├── tagger.py            # Read/write/delete ID3 tags
├── artwork.py           # Download album art + artist fanart
├── quality.py           # Format/bitrate comparison
├── template.py          # Path template engine
└── utils.py             # Shared helpers
```

## Database Schema

SQLite via SQLAlchemy ORM. All modules communicate through the DB. Primary use case is
deduplication — checking whether an album of equal/better quality already exists before
importing.

### Tables

**Artist**
- `id` (PK), `name`, `slug` (normalised), `created_at`

**Album**
- `id` (PK), `artist_id` (FK→Artist), `title`, `year`, `genre`, `subgenre`,
  `artwork_path`, `fanart_path`, `created_at`

**Track**
- `id` (PK), `album_id` (FK→Album), `title`, `track_number`, `disc_number`,
  `format`, `bitrate`, `sample_rate`, `channels`, `duration_seconds`,
  `file_path`, `file_size`, `file_hash`, `created_at`

**Download** — state machine for processing downloaded albums
- `id` (PK), `source_path`, `status` (new/identified/imported/skipped/error),
  `match_type` (id3_tag/folder_heuristic/unmatched),
  `identified_artist`, `identified_album`, `identified_year`, `identified_genre`,
  `identified_album_id` (FK→Album nullable — the library album it matched),
  `quality_score` (tier 0-10), `retry_count`, `error_message`, `created_at`, `processed_at`

**FileSystemSnapshot** — tracks known files for detecting new/changed/removed files
- `id` (PK), `path`, `file_hash`, `file_size`, `modified_at`, `first_seen_at`

**LibraryRoot** — configures path templates per directory root
- `id` (PK), `path`, `type` (library/download), `enabled`,
  `source_pattern` (for downloads), `destination_pattern` (for library),
  `created_at`

## Template Engine

A standalone module (`template.py`) that resolves path template variables. Has two modes:
- **Parse mode** — extract variable values from a real filesystem path using the pattern
- **Render mode** — construct a target path from variable values using the pattern

### Built-in Variables

| Variable | Source | Example |
|----------|--------|---------|
| `{artist}` | ID3 tag (or heuristic) | `Amon Tobin` |
| `{album}` | ID3 tag (or heuristic) | `Bricolage` |
| `{title}` | ID3 tag | `Bricolage` |
| `{track}` | ID3 tag (or parsed filename) | `01` |
| `{year}` | ID3 tag | `1997` |
| `{genre}` | ID3 tag | `Electronic` |
| `{subgenre}` | ID3 tag or path-extracted | `Ambient` |
| `{downloader}` | Path-extracted from source pattern | `user123` |
| `{owner}` | Path-extracted from source pattern | `Paul` |
| `{type}` | Path-extracted from source pattern | `Albums` |
| `{format}` | File extension (normalised) | `FLAC` |
| `{bitrate}` | Audio analysis | `1411` |
| `{sample_rate}` | Audio analysis | `44100` |
| `{filename}` | Basename without extension | `01 - Bricolage` |
| `{ext}` | File extension | `flac` |
| `{path}` | Full original path | `D:\dl\user\Bricolage` |
| `{hash}` | File hash (first 8 hex) | `a1b2c3d4` |

### Example Config

```yaml
library_roots:
  - path: "\\NAS\Music\Paul\Albums"
    type: library
    pattern: "{owner}/{type}/{genre}/{subgenre}/{artist}/{album}/{filename}.{ext}"

download_roots:
  - path: "D:\Downloads\Music"
    type: download
    pattern: "{downloader}/{album}"
  - path: "D:\Downloads\Music"
    type: download
    pattern: "{downloader}/{artist}/{album}"
```

## Pipeline Flow — End to End

### Step 1: Scan (`maestro scan [root...]`)
1. Walk download root directories recursively
2. For each directory containing audio files, create a Download record (status: `new`)
3. Record filesystem snapshot (path, size, hash, modified_at)
4. Mark directories no longer present as removed

### Step 2: Identify (`maestro identify [root...]`)
1. Read ID3 tags from files in each `new` Download
2. If tags present → extract artist, album, title, track, year, genre
3. If no tags → fall back to heuristic parsing of folder + filenames
   (e.g. `Amon Tobin - Bricolage` → split on ` - ` or common delimiters)
4. Match against existing library Albums via artist+album name
5. If matched → set `matched_library_album_id`; if unmatched → leave null
6. Set `match_type` to `id3_tag`, `folder_heuristic`, or `unmatched`
7. Mark Download as `identified`

### Step 3: Quality Check (`maestro check [album...]`)
1. Compare each track against library counterpart (if matched)
2. Quality tiers (highest→lowest): FLAC(10) > WAV(9) > AIFF(8) > 320 MP3(7) >
   V0 MP3(6) > V2 MP3(5) > Ogg Vorbis q10(4) > 192 MP3(3) > AAC 256(2) > 128 MP3(1)
3. If library has equal or better → mark Download as `skipped` with reason
4. If download is better → mark for replacement; queue old tracks for deletion
5. If unmatched in library → proceed to import

### Step 4: Organize / Import (`maestro import [album...]`)
1. For each `identified` Download that wasn't skipped:
2. Apply destination template to construct target path
3. Move (default) or copy files to target location
4. If replacing: move old files to `_replaced/` directory (or delete if `--delete-old-quality`)
5. Create/update Artist, Album, Track records in DB
6. Update filesystem snapshot

### Step 5: Tag (`maestro tag [album...]`)
1. For each imported/updated album, apply tag rules:
   - Optionally clear all existing ID3 tags
   - Write tags from: ID3 source data OR heuristic data
   - Write: track number, title, artist, album, year, genre
   - Optionally embed album art in the file

### Step 6: Artwork (`maestro artwork [album...]`)
1. For each imported/updated album, search artwork sources in order:
   - MusicBrainz → Cover Art Archive (no key needed)
   - Last.fm API for artist images (free API key)
   - Discogs API (free API token)
2. Download album art to album directory as `cover.jpg` (configurable)
3. Download artist fanart/background as `fanart.jpg` (configurable)
4. Store paths in Album table

## CLI Subcommands

```
maestro scan [root...]          Scan download roots for new albums
maestro identify [root...]      Identify downloaded albums via tags/heuristics
maestro check [album...]        Compare quality against library
maestro import [album...]       Import organised albums into library
maestro tag [album...]          Write/clear ID3 tags
maestro artwork [album...]      Download album art + fanart
maestro daemon                  Start scheduler, runs full pipeline
maestro config                  Show/edit config
```

## Daemon & Scheduler

**CLI:** `maestro daemon`

**Config:**
```yaml
scheduler:
  schedule: "0 3 * * *"         # cron expression — default daily at 3am
  run_on_start: true            # run full pipeline immediately when daemon starts
  retry_failed: true            # re-attempt failed downloads
  max_retries: 3
```

**Lifecycle:**
1. Load config, connect DB, set up logging
2. If `run_on_start` → run full pipeline immediately
3. Enter loop: every 60 seconds (configurable), check if cron expression matches
4. If match → run full pipeline (scan → identify → check → import → tag → artwork)
5. If no match → sleep
6. Handle SIGTERM/SIGINT gracefully (finish current album, exit)
7. Uses `croniter` for cron expression parsing
8. Runs in foreground — OS service manager (`systemd`, launchd) handles backgrounding

## Quality Comparator

### Quality Tiers

| Tier | Format | Threshold |
|------|--------|-----------|
| 10 | FLAC | ≥ 16-bit / 44.1kHz |
| 9 | WAV | ≥ 16-bit / 44.1kHz |
| 8 | AIFF | ≥ 16-bit / 44.1kHz |
| 7 | MP3 | ≥ 320 kbps CBR |
| 6 | MP3 | V0 (~245 kbps VBR) |
| 5 | MP3 | V2 (~190 kbps VBR) |
| 4 | Ogg Vorbis | q10 |
| 3 | MP3 | ~192 kbps CBR |
| 2 | AAC/M4A | ≥ 256 kbps |
| 1 | MP3 | ~128 kbps CBR |
| 0 | Other | Unknown/low |

### Rules
- Download tier > library tier → replace
- Equal tier AND higher bitrate → replace
- Lower tier → skip
- No library match → always import

### Config
```yaml
quality:
  min_acceptable: 3
  delete_replaced: false
```

## Artwork Sources

Multiple sources searched in configured priority order:

1. **MusicBrainz + Cover Art Archive** — no key, album art primary
2. **Last.fm API** — artist imagery (banners, backgrounds, photos)
3. **Discogs API** — album art fallback (free token required)

```yaml
artwork:
  album_art: cover.jpg
  fanart: fanart.jpg
  skip_if_exists: true
  sources:
    - musicbrainz
    - lastfm
    - discogs
```

## Error Handling Principles

- **Per-album granularity** — a failure on one album never blocks processing of others
- **Retry with backoff** — failed downloads get up to 3 retries with exponential backoff
- **Status tracking** — every Download record has `status` + `error_message` for auditing
- **Safe replacements** — old files are moved to `_replaced/` by default, never deleted
- **Graceful shutdown** — daemon completes current album before exiting on SIGTERM/SIGINT

## Testing Strategy

- **Unit tests** — each module tested in isolation with mocked DB/filesystem
- **Template engine** — extensive tests for parse + render, edge cases, missing variables
- **Quality comparator** — all tier combinations tested
- **Integration tests** — end-to-end pipeline with temp dirs and fake audio files
- **Target:** ≥ 95% coverage per module (following existing project standard)
