# Apple Photos to Immich Meta Sync

[![CI](https://github.com/jasonwaters/apple-photos-to-immich-meta-sync/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jasonwaters/apple-photos-to-immich-meta-sync/actions/workflows/ci.yml)
[![Docker](https://github.com/jasonwaters/apple-photos-to-immich-meta-sync/actions/workflows/docker.yml/badge.svg?branch=main)](https://github.com/jasonwaters/apple-photos-to-immich-meta-sync/actions/workflows/docker.yml)

Sync favorites and albums from a local macOS Photos library into Immich.

The app reads `Photos.sqlite` directly and marks matching Immich assets as favorites or adds them to albums. It never talks to Apple's web APIs, never manages Apple credentials, never removes existing Immich favorites, and never removes assets from Immich albums.

## What It Does

- Reads favorite metadata from a local macOS `Photos.sqlite` database in read-only mode.
- Searches Immich for matching assets using filename variants plus date, dimensions, file size, GPS, and camera metadata.
- Marks matched Immich assets as favorites in batches.
- Lists non-empty Apple Photos albums and syncs selected albums to flat Immich albums.
- Runs as a dry run by default and prints the assets it would favorite.
- Caches source favorite metadata in `.cache/local-photos-favorites.json` or `/cache/local-photos-favorites.json` in Docker.
- Saves album mappings in `.cache/album-sync.json` or `/cache/album-sync.json` for repeat non-interactive runs.

## Requirements

- Python 3.10+ for local development, or Docker for container runs.
- `uv` for local setup.
- An Immich API key.
- A readable macOS Photos database, usually:

```bash
~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite
```

If macOS blocks access with `authorization denied`, grant Full Disk Access to the process running the sync: your terminal, Cursor, or Docker Desktop.

## Configuration

Copy the examples:

```bash
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
```

For Docker, keep the container path in `.env` and mount your host database there:

```env
PHOTOS_SQLITE_PATH=/photos-library/Photos.sqlite
IMMICH_URL=https://your-immich.example.com
IMMICH_API_KEY=your-api-key
DRY_RUN=true
BATCH_SIZE=50
LOG_LEVEL=INFO
```

```yaml
volumes:
  - "/Users/you/Pictures/Photos Library.photoslibrary/database/Photos.sqlite:/photos-library/Photos.sqlite:ro"
  - ./.cache:/cache
```

For local runs without Docker, point `PHOTOS_SQLITE_PATH` at the host path directly.

## Docker Image

Published images are available from GitHub Container Registry:

```bash
docker pull ghcr.io/jasonwaters/apple-photos-to-immich-meta-sync:latest
```

Use the published image in `docker-compose.yml`:

```yaml
services:
  apple-photos-to-immich-meta-sync:
    image: ghcr.io/jasonwaters/apple-photos-to-immich-meta-sync:latest
    env_file:
      - .env
    volumes:
      - "/Users/you/Pictures/Photos Library.photoslibrary/database/Photos.sqlite:/photos-library/Photos.sqlite:ro"
      - ./.cache:/cache
```

Images are tagged with `latest` for the default branch, branch names, `sha-<commit>`, and semantic version tags such as `v0.1.0`.

## Usage

Dry run all favorites:

```bash
uv run apple-photos-to-immich-meta-sync --refresh-cache
```

Dry run a deterministic sample:

```bash
uv run apple-photos-to-immich-meta-sync --sample-size 100 --sample-seed 1 --refresh-cache
```

Dry run one filename:

```bash
uv run apple-photos-to-immich-meta-sync --only-filename IMG_5743.HEIC --refresh-cache
```

Apply changes after reviewing the dry-run output:

```bash
uv run apple-photos-to-immich-meta-sync --apply
```

Docker equivalents:

```bash
docker-compose run --rm apple-photos-to-immich-meta-sync --refresh-cache
docker-compose run --rm apple-photos-to-immich-meta-sync --apply
```

## Album Sync

List non-empty Apple Photos albums:

```bash
uv run apple-photos-to-immich-meta-sync albums --list
```

First-time album setup is interactive. Select one or more albums by index or range, such as `1,3,5-8`:

```bash
uv run apple-photos-to-immich-meta-sync albums --interactive
```

Newly seeded Immich album names are derived from the Apple Photos path. For example, `Family Photos/2017-03 - Lehi` becomes `[Family Photos] 2017-03 - Lehi`, `zac/7 Months` becomes `[zac] 7 Months`, and `kelly/Scott Kelly/All Scott` becomes `[kelly] (Scott Kelly) All Scott`.

Interactive selections are saved to `.cache/album-sync.json` by default, even during dry runs. This makes the first interactive pass a config-seeding step. When an Immich album is found or created, its ID is saved too, so later runs can find the same album even if the user renames it in Immich. Use `--no-save-config` for one-off exploration:

```bash
uv run apple-photos-to-immich-meta-sync albums --interactive --no-save-config
```

Later runs can replay the saved config non-interactively:

```bash
uv run apple-photos-to-immich-meta-sync albums
```

Apply album changes after reviewing the dry-run output:

```bash
uv run apple-photos-to-immich-meta-sync --apply albums
```

Album sync is add-only. It creates missing Immich albums and adds matched assets, but it never removes assets from Immich albums. Apple Photos album folders are flattened into readable Immich album names because Immich albums are top-level. Duplicate Apple Photos album rows with the same path, such as two `misc/Grandpa Waters` albums, are saved as separate Photos mappings that target one shared Immich album. Saved Immich album IDs are preferred over names on replay.

Example album config:

```json
{
  "albums": [
    {
      "photos_album_uuid": "3040977A-9CC8-4342-9541-AF815D13A8E9",
      "photos_album_path": "Trips/Hawaii",
      "photos_album_name": "Hawaii",
      "immich_album_name": "[Trips] Hawaii",
      "immich_album_id": "8f5b8f28-2df6-4f79-9c86-123456789abc",
      "last_seen_photos_album_name": "Hawaii",
      "last_seen_photos_album_path": "Trips/Hawaii",
      "last_synced_at": "2026-05-15T16:00:00Z"
    }
  ]
}
```

## CLI Options

```bash
apple-photos-to-immich-meta-sync [OPTIONS]

options:
  --apply
  --photos-sqlite-path PHOTOS_SQLITE_PATH
  --immich-url IMMICH_URL
  --immich-api-key IMMICH_API_KEY
  --batch-size BATCH_SIZE
  --log-level {DEBUG,INFO,WARNING,ERROR}
  --sample-size SAMPLE_SIZE
  --sample-seed SAMPLE_SEED
  --only-filename ONLY_FILENAME
  --favorites-cache FAVORITES_CACHE
  --refresh-cache

commands:
  favorites
  albums

album options:
  --list
  --interactive
  --config CONFIG
  --no-save-config
```

## Matching

Matching is intentionally conservative. The matcher searches Immich from most-specific to broadest query:

- Filename variants such as `image000000-adjusted.JPG` and `FullSizeRender-1372909.heic`.
- Tight and broad capture date windows when Photos has a creation date.
- Camera make, model, and lens metadata when available.
- Filename-only fallback when specific searches do not produce a confident match.

Candidates are then scored using date, dimensions, file size, path date, GPS, and camera agreement. Ambiguous or missing matches are reported and skipped.

## Safety

- Dry run is the default.
- The app only sets `isFavorite=true` in Immich.
- Existing Immich favorites are preserved.
- Existing Immich album membership is preserved.
- The Photos database is opened read-only with SQLite `query_only`.
- There is no Apple auth code or iCloud web API integration.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
docker build -t apple-photos-to-immich-meta-sync .
```

The test suite includes regression coverage for local Photos extraction, album listing, hidden/trashed filtering, filename variants, case-sensitive duplicate filenames, album mapping config replay, and dry-run planning.

## CI and Publishing

GitHub Actions runs lint and tests on pull requests and pushes to `main`. The Docker workflow builds images on pull requests and publishes multi-platform `linux/amd64` and `linux/arm64` images to GHCR on `main`, tags, and manual dispatches.

## Troubleshooting

### Photos Permission Errors

Grant Full Disk Access to the process running the sync, then rerun with `--refresh-cache`.

### No Matches Found

Verify the assets are imported into Immich and enable debug logging:

```bash
LOG_LEVEL=DEBUG uv run apple-photos-to-immich-meta-sync --refresh-cache
```

### Stale Favorite Cache

Use `--refresh-cache` after changing `PHOTOS_SQLITE_PATH`, Photos library contents, or Docker volume mounts.

## License

MIT
