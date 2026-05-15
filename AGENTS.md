# AGENTS.md

Guidance for LLM coding agents working on `apple-photos-to-immich-meta-sync`.

## Project Purpose

This project syncs favorites and albums from a local macOS Photos library into Immich. The only supported source is `Photos.sqlite`; do not add Apple web auth, `pyicloud`, or `icloudpd` integration back into the app.

## Core Invariants

- Default to dry-run behavior. `--apply` is the only mode that mutates Immich.
- Never remove existing Immich favorites. The sync is mark-only.
- Never remove assets from Immich albums. Album sync is add-only.
- Open `Photos.sqlite` read-only and do not write to the Photos library.
- Keep matching conservative. Ambiguous matches should be reported and skipped unless there is a deterministic, well-tested reason to choose one.
- Preserve detailed dry-run output so users can audit what will change.
- Interactive album sync should seed or update the album mapping config; non-interactive album sync should replay saved mappings.
- Persist `immich_album_id` when an Immich album is found or created, and prefer ID lookup over name lookup on replay.
- New interactive album mappings should derive Immich album names from the Photos path, e.g. `Family Photos/2017-03 - Lehi` becomes `[Family Photos] 2017-03 - Lehi`.
- Preserve duplicate Photos album UUIDs in config, but let duplicate albums with the same formatted target name share one Immich album.
- Duplicate Apple Photos album leaf names require UUID/path-backed mappings.

## Development Commands

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run apple-photos-to-immich-meta-sync --help
docker build -t apple-photos-to-immich-meta-sync .
```

## Code Style

- Prefer small, focused functions with descriptive names.
- Keep source-specific behavior in `local_photos_client.py`; keep Immich API behavior in `immich_client.py`; keep matching decisions in `matcher.py`; keep favorite orchestration in `sync.py`; keep album orchestration in `album_sync.py`.
- Add regression tests for every matching bug or edge case.
- Use structured APIs for SQLite, JSON, and HTTP; avoid ad hoc string parsing when a typed or structured option exists.
- Keep docs aligned with the local-only workflow and current CLI flags.
- Keep GitHub Actions aligned with local verification: CI should run Ruff and pytest; Docker publishing should build PRs and publish GHCR images only on trusted events.

## Safety Rules

- Do not commit, push, merge, rebase, or run destructive git commands.
- Do not log or expose real Immich API keys.
- Do not edit `.env` unless the user explicitly asks; prefer `.env.example` for documented defaults.
- Do not reintroduce dependencies that are not needed for local Photos SQLite support.
