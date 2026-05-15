# AGENTS.md

Guidance for LLM coding agents working on `immich-favorite-sync`.

## Project Purpose

This project syncs favorites from a local macOS Photos library into Immich. The only supported favorite source is `Photos.sqlite`; do not add Apple web auth, `pyicloud`, or `icloudpd` integration back into the app.

## Core Invariants

- Default to dry-run behavior. `--apply` is the only mode that mutates Immich.
- Never remove existing Immich favorites. The sync is mark-only.
- Open `Photos.sqlite` read-only and do not write to the Photos library.
- Keep matching conservative. Ambiguous matches should be reported and skipped unless there is a deterministic, well-tested reason to choose one.
- Preserve detailed dry-run output so users can audit what will change.

## Development Commands

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run immich-favorite-sync --help
```

## Code Style

- Prefer small, focused functions with descriptive names.
- Keep source-specific behavior in `local_photos_client.py`; keep Immich API behavior in `immich_client.py`; keep matching decisions in `matcher.py`; keep orchestration in `sync.py`.
- Add regression tests for every matching bug or edge case.
- Use structured APIs for SQLite, JSON, and HTTP; avoid ad hoc string parsing when a typed or structured option exists.
- Keep docs aligned with the local-only workflow and current CLI flags.

## Safety Rules

- Do not commit, push, merge, rebase, or run destructive git commands.
- Do not log or expose real Immich API keys.
- Do not edit `.env` unless the user explicitly asks; prefer `.env.example` for documented defaults.
- Do not reintroduce dependencies that are not needed for local Photos SQLite support.
