"""Command-line interface for apple-photos-to-immich-meta-sync."""

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from .album_sync import AlbumSyncer, AlbumSyncStats
from .config import Config
from .immich_client import ImmichClient
from .local_photos_client import LocalPhotosLibraryClient
from .models import PhotoAlbumSummary
from .sync import FavoriteSyncer, SyncStats

console = Console()


def setup_logging(level: str) -> None:
    """Setup logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )
    if level.upper() != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def print_banner() -> None:
    """Print application banner."""
    console.print(
        Panel.fit(
            "[bold cyan]Apple Photos to Immich Meta Sync[/bold cyan]\n"
            "Sync Photos favorites and albums to Immich",
            border_style="cyan",
        )
    )


def print_summary(stats: SyncStats, dry_run: bool) -> None:
    """Print sync summary.

    Args:
        stats: Sync statistics
        dry_run: Whether this was a dry run
    """
    console.print()
    console.rule("[bold]Sync Summary", style="cyan")

    # Create summary table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")

    table.add_row("Source favorites found", str(stats.total_source_favorites))
    table.add_row("", "")
    table.add_row("High confidence matches", f"[green]{stats.high_confidence_matches}[/green]")
    table.add_row("Medium confidence matches", f"[yellow]{stats.medium_confidence_matches}[/yellow]")
    table.add_row("Already favorited", f"[dim]{stats.already_favorited}[/dim]")
    table.add_row("", "")
    table.add_row("Ambiguous (skipped)", f"[yellow]{stats.ambiguous_matches}[/yellow]")
    table.add_row("Not found (skipped)", f"[red]{stats.no_matches}[/red]")

    if not dry_run:
        table.add_row("", "")
        table.add_row("New favorites marked", f"[bold green]{stats.favorited}[/bold green]")

    if stats.errors > 0:
        table.add_row("", "")
        table.add_row("Errors", f"[bold red]{stats.errors}[/bold red]")

    console.print(table)
    console.print()

    if dry_run:
        console.print(
            f"[bold yellow]DRY RUN:[/bold yellow] Would mark {stats.to_favorite} assets as favorites",
            style="yellow",
        )
        print_planned_favorites(stats)
        console.print("[dim]Run with --apply to make changes[/dim]")
    else:
        if stats.favorited > 0:
            console.print(f"[bold green]✓[/bold green] Successfully favorited {stats.favorited} assets")
        else:
            console.print("[dim]No new assets to favorite[/dim]")


def print_planned_favorites(stats: SyncStats) -> None:
    """Print dry-run detail rows for assets that would be favorited."""
    if not stats.planned_favorites:
        return

    console.print()
    console.rule("[bold]Planned Favorites", style="yellow")

    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("Source Favorite", style="cyan")
    table.add_column("Confidence", style="bold")
    table.add_column("Immich Asset")
    table.add_column("Reason")

    for result in stats.planned_favorites[:25]:
        asset = result.immich_asset or (result.candidates[0] if result.candidates else None)
        if asset is None:
            continue

        asset_detail = "\n".join(
            part for part in [
                asset.id,
                asset.original_path,
                _format_asset_metadata(asset),
            ] if part
        )

        table.add_row(
            str(result.source_photo),
            result.confidence.value,
            asset_detail,
            result.reason,
        )

    console.print(table)

    if len(stats.planned_favorites) > 25:
        console.print(f"[dim]... and {len(stats.planned_favorites) - 25} more planned favorites[/dim]")


def _format_asset_metadata(asset) -> str:
    """Return compact asset metadata for review output."""
    details = []

    if asset.width and asset.height:
        details.append(f"{asset.width}x{asset.height}")
    if asset.file_size_in_byte:
        details.append(f"{asset.file_size_in_byte} bytes")
    if asset.make or asset.model:
        details.append(" ".join(part for part in [asset.make, asset.model] if part))

    return " | ".join(details)


def default_favorites_cache_path() -> Path:
    """Choose a cache path that works in Docker and local development."""
    cache_dir = Path("/cache") if Path("/cache").exists() else Path(".cache")
    return cache_dir / "local-photos-favorites.json"


def default_album_config_path() -> Path:
    """Choose an album mapping config path that works in Docker and local development."""
    cache_dir = Path("/cache") if Path("/cache").exists() else Path(".cache")
    return cache_dir / "album-sync.json"


def print_album_list(albums: list[PhotoAlbumSummary]) -> None:
    """Print available Photos albums for selection."""
    duplicates = _duplicate_album_names(albums)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("Album")
    table.add_column("Path")
    table.add_column("Assets", justify="right")
    table.add_column("Notes")

    for index, album in enumerate(albums, start=1):
        notes = "duplicate name" if album.name in duplicates else ""
        table.add_row(str(index), album.name, album.path, str(album.asset_count), notes)

    console.print(table)


def print_album_summary(stats: AlbumSyncStats, dry_run: bool) -> None:
    """Print album sync summary."""
    console.print()
    console.rule("[bold]Album Sync Summary", style="cyan")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold")
    table.add_row("Album mappings", str(stats.total_mappings))
    table.add_row("Albums found", str(stats.albums_found))
    table.add_row("Albums created/planned", str(stats.albums_created))
    table.add_row("Photos assets seen", str(stats.photos_assets_seen))
    table.add_row("Matched assets", str(stats.matched_assets))
    table.add_row("Assets to add", str(stats.assets_to_add))
    if not dry_run:
        table.add_row("Assets added", str(stats.assets_added))
    table.add_row("Skipped assets", str(stats.skipped_assets))
    table.add_row("Errors", str(stats.errors))
    console.print(table)

    if dry_run:
        console.print("[bold yellow]DRY RUN:[/bold yellow] No Immich album changes were applied", style="yellow")
        console.print("[dim]Run with --apply to create albums and add assets[/dim]")


def select_albums_interactively(albums: list[PhotoAlbumSummary]) -> list[PhotoAlbumSummary]:
    """Prompt the user to select Photos albums by index."""
    if not albums:
        return []

    print_album_list(albums)
    selection = console.input("\nSelect album numbers or ranges (example: 1,3,5-8): ").strip()
    selected_indices = _parse_selection(selection, len(albums))
    return [albums[index - 1] for index in selected_indices]


def _parse_selection(selection: str, max_index: int) -> list[int]:
    """Parse comma-separated indexes and ranges."""
    indexes = []
    for raw_part in selection.split(","):
        part = raw_part.strip()
        if not part:
            continue

        if "-" in part:
            start_text, end_text = part.split("-", maxsplit=1)
            start = int(start_text)
            end = int(end_text)
            indexes.extend(range(start, end + 1))
        else:
            indexes.append(int(part))

    deduped = list(dict.fromkeys(indexes))
    invalid = [index for index in deduped if index < 1 or index > max_index]
    if invalid:
        raise ValueError(f"Album selection out of range: {invalid}")

    return deduped


def _duplicate_album_names(albums: list[PhotoAlbumSummary]) -> set[str]:
    """Return album leaf names that appear more than once."""
    counts: dict[str, int] = {}
    for album in albums:
        counts[album.name] = counts.get(album.name, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Sync macOS Photos favorites and albums to Immich",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run only)",
    )
    parser.add_argument(
        "--photos-sqlite-path",
        type=Path,
        help="Path to local Photos.sqlite database (overrides PHOTOS_SQLITE_PATH)",
    )
    parser.add_argument(
        "--immich-url",
        help="Immich server URL (overrides IMMICH_URL)",
    )
    parser.add_argument(
        "--immich-api-key",
        help="Immich API key (overrides IMMICH_API_KEY)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Batch size for updates (overrides BATCH_SIZE)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (overrides LOG_LEVEL)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        help="Match only a deterministic random sample of favorites",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=1,
        help="Random seed for --sample-size (default: 1)",
    )
    parser.add_argument(
        "--only-filename",
        help="Match only favorites with this exact filename",
    )
    parser.add_argument(
        "--favorites-cache",
        type=Path,
        help="Local cache path for favorite metadata",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Refresh the favorites cache before matching",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("favorites", help="Sync Photos favorites to Immich favorites")
    albums_parser = subparsers.add_parser("albums", help="Sync Photos albums to Immich albums")
    albums_parser.add_argument(
        "--list",
        action="store_true",
        help="List non-empty Photos albums and exit",
    )
    albums_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactively select Photos albums to sync and save mappings",
    )
    albums_parser.add_argument(
        "--config",
        type=Path,
        help="Album mapping config path (default: .cache/album-sync.json or /cache/album-sync.json)",
    )
    albums_parser.add_argument(
        "--no-save-config",
        action="store_true",
        help="Do not save interactive album selections to the mapping config",
    )

    return parser


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = build_parser()
    args = parser.parse_args()

    # Load configuration
    try:
        config = Config()

        # Apply CLI overrides
        if args.photos_sqlite_path:
            config.photos_sqlite_path = args.photos_sqlite_path
        if args.immich_url:
            config.immich_url = args.immich_url
        if args.immich_api_key:
            config.immich_api_key = args.immich_api_key
        if args.batch_size:
            config.batch_size = args.batch_size
        if args.log_level:
            config.log_level = args.log_level
        if args.apply:
            config.dry_run = False

        favorites_cache_path = args.favorites_cache
        if favorites_cache_path is None:
            favorites_cache_path = default_favorites_cache_path()
        album_config_path = args.config if args.command == "albums" and args.config else default_album_config_path()

    except Exception as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        return 1

    # Setup logging
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    # Print banner
    print_banner()

    # Validate configuration
    try:
        config.validate_paths()
    except Exception as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        return 1

    logger.info(f"Photos SQLite path: {config.photos_sqlite_path}")
    logger.info(f"Immich URL: {config.immich_base_url}")
    logger.info(f"Mode: {'DRY RUN' if config.dry_run else 'APPLY CHANGES'}")

    # Initialize clients
    photos_library_client = None
    immich_client = None
    try:
        logger.info("Initializing clients...")

        photos_library_client = LocalPhotosLibraryClient(config.photos_sqlite_path)
        immich_client = ImmichClient(
            base_url=config.immich_base_url,
            api_key=config.immich_api_key,
        )

        if args.command == "albums":
            syncer = AlbumSyncer(
                photos_client=photos_library_client,
                immich_client=immich_client,
                config_path=album_config_path,
                batch_size=config.batch_size,
                dry_run=config.dry_run,
            )
        else:
            syncer = FavoriteSyncer(
                favorite_source=photos_library_client,
                immich_client=immich_client,
                batch_size=config.batch_size,
                dry_run=config.dry_run,
                sample_size=args.sample_size,
                sample_seed=args.sample_seed,
                only_filename=args.only_filename,
                favorites_cache_path=favorites_cache_path,
                refresh_cache=args.refresh_cache,
            )

    except Exception as e:
        console.print(f"[bold red]Initialization error:[/bold red] {e}")
        logger.exception("Failed to initialize")
        return 1

    # Perform sync
    try:
        if args.command == "albums":
            if args.list:
                albums = photos_library_client.list_albums()
                print_album_list(albums)
                return 0

            if args.interactive:
                albums = photos_library_client.list_albums()
                selected_albums = select_albums_interactively(albums)
                if not selected_albums:
                    console.print("[yellow]No albums selected[/yellow]")
                    return 0
                stats = syncer.sync_selected(
                    selected_albums,
                    save_config=not args.no_save_config,
                )
            else:
                stats = syncer.sync_configured()
            print_album_summary(stats, config.dry_run)
        else:
            stats = syncer.sync()
            print_summary(stats, config.dry_run)

        # Return error if there were failures
        if stats.errors > 0:
            return 1

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        return 130
    except Exception as e:
        console.print(f"\n[bold red]Sync failed:[/bold red] {e}")
        logger.exception("Sync failed")
        return 1
    finally:
        if photos_library_client is not None:
            photos_library_client.close()
        if immich_client is not None:
            immich_client.close()


if __name__ == "__main__":
    sys.exit(main())
