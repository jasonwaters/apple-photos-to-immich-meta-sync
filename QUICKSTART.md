# Quickstart

## Local Setup

```bash
cp .env.example .env
uv sync --extra dev
```

Set `.env` for local execution:

```env
PHOTOS_SQLITE_PATH=/Users/you/Pictures/Photos Library.photoslibrary/database/Photos.sqlite
IMMICH_URL=https://your-immich.example.com
IMMICH_API_KEY=your-api-key
DRY_RUN=true
```

## Docker Setup

For Docker, keep `PHOTOS_SQLITE_PATH=/photos-library/Photos.sqlite` in `.env` and mount the host database read-only:

```yaml
image: ghcr.io/jasonwaters/apple-photos-to-immich-meta-sync:latest
volumes:
  - "/Users/you/Pictures/Photos Library.photoslibrary/database/Photos.sqlite:/photos-library/Photos.sqlite:ro"
  - ./.cache:/cache
```

Pull the published image:

```bash
docker pull ghcr.io/jasonwaters/apple-photos-to-immich-meta-sync:latest
```

## Dry Run First

All favorites:

```bash
uv run apple-photos-to-immich-meta-sync --refresh-cache
```

Random deterministic sample:

```bash
uv run apple-photos-to-immich-meta-sync --sample-size 100 --sample-seed 1 --refresh-cache
```

Single filename:

```bash
uv run apple-photos-to-immich-meta-sync --only-filename IMG_5743.HEIC --refresh-cache
```

Docker:

```bash
docker-compose run --rm apple-photos-to-immich-meta-sync --refresh-cache
```

## Album Sync

List available non-empty Apple Photos albums:

```bash
uv run apple-photos-to-immich-meta-sync albums --list
```

First run: select albums interactively and seed `.cache/album-sync.json`. When an Immich album is found or created, the config stores its ID so future runs still work after an Immich-side rename:

```bash
uv run apple-photos-to-immich-meta-sync albums --interactive
```

New Immich album names are derived from the Apple Photos path, such as `[Family Photos] 2017-03 - Lehi` or `[kelly] (Scott Kelly) All Scott`.
Duplicate Photos album rows with the same path are combined into one shared Immich album target.

Later runs: replay the saved config non-interactively:

```bash
uv run apple-photos-to-immich-meta-sync albums
```

Apply album changes:

```bash
uv run apple-photos-to-immich-meta-sync --apply albums
```

## Apply

Only apply after reviewing the planned favorites table:

```bash
uv run apple-photos-to-immich-meta-sync --apply
```

```bash
docker-compose run --rm apple-photos-to-immich-meta-sync --apply
```

## Verify

```bash
uv run pytest
uv run ruff check .
uv run apple-photos-to-immich-meta-sync --help
docker build -t apple-photos-to-immich-meta-sync .
```

## GitHub Actions

- `CI` runs Ruff and pytest on pull requests and pushes to `main`.
- `Docker` builds images on pull requests and publishes multi-platform GHCR images on `main`, tags, and manual runs.

## Safety Notes

- Dry run is the default.
- The app only sets favorites in Immich.
- It never removes Immich favorites.
- Album sync is add-only and never removes assets from Immich albums.
- `Photos.sqlite` is opened read-only.
- There is no Apple auth or iCloud web API code.
