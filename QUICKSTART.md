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
uv run immich-favorite-sync --refresh-cache
```

Random deterministic sample:

```bash
uv run immich-favorite-sync --sample-size 100 --sample-seed 1 --refresh-cache
```

Single filename:

```bash
uv run immich-favorite-sync --only-filename IMG_5743.HEIC --refresh-cache
```

Docker:

```bash
docker-compose run --rm immich-favorite-sync --refresh-cache
```

## Apply

Only apply after reviewing the planned favorites table:

```bash
uv run immich-favorite-sync --apply
```

```bash
docker-compose run --rm immich-favorite-sync --apply
```

## Verify

```bash
uv run pytest
uv run ruff check .
uv run immich-favorite-sync --help
docker build -t immich-favorite-sync .
```

## GitHub Actions

- `CI` runs Ruff and pytest on pull requests and pushes to `main`.
- `Docker` builds images on pull requests and publishes multi-platform GHCR images on `main`, tags, and manual runs.

## Safety Notes

- Dry run is the default.
- The app only sets favorites in Immich.
- It never removes Immich favorites.
- `Photos.sqlite` is opened read-only.
- There is no Apple auth or iCloud web API code.
