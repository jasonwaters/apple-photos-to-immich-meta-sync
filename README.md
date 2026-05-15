# Immich Favorite Sync

Sync favorites from a local macOS Photos library into Immich.

The app reads `Photos.sqlite` directly and marks matching Immich assets as favorites. It never talks to Apple's web APIs, never manages Apple credentials, and never removes existing Immich favorites.

## What It Does

- Reads favorite metadata from a local macOS `Photos.sqlite` database in read-only mode.
- Searches Immich for matching assets using filename variants plus date, dimensions, file size, GPS, and camera metadata.
- Marks matched Immich assets as favorites in batches.
- Runs as a dry run by default and prints the assets it would favorite.
- Caches source favorite metadata in `.cache/local-photos-favorites.json` or `/cache/local-photos-favorites.json` in Docker.

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

## Usage

Dry run all favorites:

```bash
uv run immich-favorite-sync --refresh-cache
```

Dry run a deterministic sample:

```bash
uv run immich-favorite-sync --sample-size 100 --sample-seed 1 --refresh-cache
```

Dry run one filename:

```bash
uv run immich-favorite-sync --only-filename IMG_5743.HEIC --refresh-cache
```

Apply changes after reviewing the dry-run output:

```bash
uv run immich-favorite-sync --apply
```

Docker equivalents:

```bash
docker-compose run --rm immich-favorite-sync --refresh-cache
docker-compose run --rm immich-favorite-sync --apply
```

## CLI Options

```bash
immich-favorite-sync [OPTIONS]

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
- The Photos database is opened read-only with SQLite `query_only`.
- There is no Apple auth code or iCloud web API integration.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

The test suite includes regression coverage for local Photos extraction, hidden/trashed filtering, filename variants, case-sensitive duplicate filenames, and dry-run planning.

## Troubleshooting

### Photos Permission Errors

Grant Full Disk Access to the process running the sync, then rerun with `--refresh-cache`.

### No Matches Found

Verify the assets are imported into Immich and enable debug logging:

```bash
LOG_LEVEL=DEBUG uv run immich-favorite-sync --refresh-cache
```

### Stale Favorite Cache

Use `--refresh-cache` after changing `PHOTOS_SQLITE_PATH`, Photos library contents, or Docker volume mounts.

## License

MIT
