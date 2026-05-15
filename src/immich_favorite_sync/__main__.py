"""Command-line interface for immich-favorite-sync."""

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from .config import Config
from .immich_client import ImmichClient
from .local_photos_client import LocalPhotosLibraryClient
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
            "[bold cyan]Immich Favorite Sync[/bold cyan]\n"
            "Sync Photos favorites to Immich",
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


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Sync macOS Photos favorites to Immich",
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
