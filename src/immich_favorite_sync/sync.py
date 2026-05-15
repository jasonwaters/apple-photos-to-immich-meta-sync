"""Sync orchestration for Photos favorites to Immich favorites."""

import json
import logging
import random
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .immich_client import ImmichClient
from .matcher import AssetMatcher, MatchConfidence, MatchResult
from .models import FavoritePhoto

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics for a sync run."""

    total_source_favorites: int = 0
    high_confidence_matches: int = 0
    medium_confidence_matches: int = 0
    ambiguous_matches: int = 0
    no_matches: int = 0
    already_favorited: int = 0
    to_favorite: int = 0
    favorited: int = 0
    errors: int = 0

    matched_asset_ids: list[str] = field(default_factory=list)
    favorites_by_library: dict[str, int] = field(default_factory=dict)
    ambiguous_photos: list[FavoritePhoto] = field(default_factory=list)
    missing_photos: list[FavoritePhoto] = field(default_factory=list)
    error_photos: list[tuple[FavoritePhoto, str]] = field(default_factory=list)
    planned_favorites: list[MatchResult] = field(default_factory=list)

    def get_total_matches(self) -> int:
        """Get total number of successful matches."""
        return self.high_confidence_matches + self.medium_confidence_matches


class FavoriteSourceClient(Protocol):
    """Favorite metadata source interface."""

    def get_favorites(self) -> Iterable[FavoritePhoto]:
        """Return favorite photo metadata."""
        ...

    def close(self) -> None:
        """Close any resources held by the source."""
        ...


class FavoriteSyncer:
    """Orchestrates syncing Photos favorites to Immich."""

    def __init__(
        self,
        favorite_source: FavoriteSourceClient,
        immich_client: ImmichClient,
        batch_size: int = 50,
        dry_run: bool = True,
        sample_size: int | None = None,
        sample_seed: int = 1,
        only_filename: str | None = None,
        favorites_cache_path: Path | None = None,
        refresh_cache: bool = False,
    ):
        """Initialize syncer.

        Args:
            favorite_source: Favorite metadata source client
            immich_client: Immich API client
            batch_size: Number of assets to update per batch
            dry_run: If True, only report what would be done
        """
        self.favorite_source = favorite_source
        self.immich_client = immich_client
        self.matcher = AssetMatcher(immich_client)
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.sample_size = sample_size
        self.sample_seed = sample_seed
        self.only_filename = only_filename
        self.favorites_cache_path = favorites_cache_path
        self.refresh_cache = refresh_cache

    def sync(self) -> SyncStats:
        """Perform sync of favorite metadata to Immich.

        Returns:
            SyncStats with results
        """
        stats = SyncStats()

        logger.info("Starting favorite sync")
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'APPLY CHANGES'}")

        # Get all favorites from the configured source.
        try:
            favorites = self._load_or_fetch_favorites()
            stats.total_source_favorites = len(favorites)
            stats.favorites_by_library = self._count_favorites_by_library(favorites)
            logger.info(f"Found {stats.total_source_favorites} favorites")
            favorites = self._filter_favorites_for_run(favorites)
        except Exception as e:
            logger.error(f"Failed to fetch favorites: {e}")
            raise

        # Match each favorite to Immich assets
        match_results = []
        for photo in favorites:
            try:
                result = self.matcher.match(photo)
                match_results.append(result)
                self._update_stats_from_match(stats, result)
            except Exception as e:
                logger.error(f"Error matching {photo.filename}: {e}")
                stats.errors += 1
                stats.error_photos.append((photo, str(e)))

        # Log matching summary
        self._log_match_summary(stats)

        # Collect assets to favorite (excluding already favorited)
        assets_to_favorite = []
        planned_asset_ids = set()
        for result in match_results:
            if result.confidence in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]:
                matched_assets = self._get_matched_assets(result)

                for asset in matched_assets:
                    if not asset.is_favorite:
                        assets_to_favorite.append(asset.id)
                        stats.matched_asset_ids.append(asset.id)
                        if asset.id not in planned_asset_ids:
                            stats.planned_favorites.append(result)
                            planned_asset_ids.add(asset.id)
                    else:
                        stats.already_favorited += 1

        assets_to_favorite = list(dict.fromkeys(assets_to_favorite))
        stats.matched_asset_ids = list(dict.fromkeys(stats.matched_asset_ids))
        stats.to_favorite = len(assets_to_favorite)

        # Update favorites in batches
        if assets_to_favorite:
            if self.dry_run:
                logger.info(f"DRY RUN: Would mark {stats.to_favorite} assets as favorites")
            else:
                logger.info(f"Marking {stats.to_favorite} assets as favorites")
                try:
                    self._batch_update_favorites(assets_to_favorite, stats)
                except Exception as e:
                    logger.error(f"Failed to update favorites: {e}")
                    raise
        else:
            logger.info("No new assets to favorite")

        logger.info("Sync complete")
        return stats

    def _get_matched_assets(self, result: MatchResult):
        """Return all Immich assets accepted for a match result."""
        if result.immich_asset is not None:
            return [result.immich_asset]

        return result.candidates

    def _load_or_fetch_favorites(self) -> list[FavoritePhoto]:
        """Load favorites from cache or fetch them from the configured source."""
        if self.favorites_cache_path and self.favorites_cache_path.exists() and not self.refresh_cache:
            logger.info("Loading favorites from cache: %s", self.favorites_cache_path)
            with self.favorites_cache_path.open("r", encoding="utf-8") as cache_file:
                data = json.load(cache_file)
            return [FavoritePhoto.from_dict(item) for item in data["favorites"]]

        try:
            favorites = self._fetch_favorites_with_retries()
        except Exception:
            if self.favorites_cache_path and self.favorites_cache_path.exists():
                logger.warning("Refreshing favorites failed; falling back to existing cache")
                with self.favorites_cache_path.open("r", encoding="utf-8") as cache_file:
                    data = json.load(cache_file)
                return [FavoritePhoto.from_dict(item) for item in data["favorites"]]
            raise

        if self.favorites_cache_path:
            self.favorites_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.favorites_cache_path.open("w", encoding="utf-8") as cache_file:
                json.dump(
                    {"favorites": [favorite.to_dict() for favorite in favorites]},
                    cache_file,
                    indent=2,
                    sort_keys=True,
                )
            logger.info("Wrote favorites cache: %s", self.favorites_cache_path)

        return favorites

    def _fetch_favorites_with_retries(self, attempts: int = 3) -> list[FavoritePhoto]:
        """Fetch favorites with retries for transient source errors."""
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                return list(self.favorite_source.get_favorites())
            except Exception as e:
                last_error = e
                if attempt == attempts:
                    break

                wait_seconds = attempt * 5
                logger.warning(
                    "Favorites fetch failed on attempt %s/%s: %s. Retrying in %s seconds.",
                    attempt,
                    attempts,
                    e,
                    wait_seconds,
                )
                self.favorite_source.close()
                time.sleep(wait_seconds)

        raise RuntimeError(f"Failed to fetch favorites after {attempts} attempts: {last_error}") from last_error

    def _filter_favorites_for_run(self, favorites: list[FavoritePhoto]) -> list[FavoritePhoto]:
        """Apply optional test-run filters to the favorites list."""
        if self.only_filename:
            filtered = [favorite for favorite in favorites if favorite.filename == self.only_filename]
            logger.info("Filtered run to %s favorites named %s", len(filtered), self.only_filename)
            return filtered

        if self.sample_size is not None and self.sample_size < len(favorites):
            random_generator = random.Random(self.sample_seed)
            sampled = random_generator.sample(favorites, self.sample_size)
            logger.info(
                "Filtered run to deterministic sample of %s favorites with seed %s",
                self.sample_size,
                self.sample_seed,
            )
            return sampled

        return favorites

    def _update_stats_from_match(self, stats: SyncStats, result: MatchResult) -> None:
        """Update stats based on match result.

        Args:
            stats: Stats object to update
            result: Match result
        """
        if result.confidence == MatchConfidence.HIGH:
            stats.high_confidence_matches += 1
        elif result.confidence == MatchConfidence.MEDIUM:
            stats.medium_confidence_matches += 1
        elif result.confidence == MatchConfidence.AMBIGUOUS:
            stats.ambiguous_matches += 1
            stats.ambiguous_photos.append(result.source_photo)
        elif result.confidence == MatchConfidence.NONE:
            stats.no_matches += 1
            stats.missing_photos.append(result.source_photo)

    def _log_match_summary(self, stats: SyncStats) -> None:
        """Log summary of matching results.

        Args:
            stats: Stats object
        """
        logger.info("=" * 60)
        logger.info("MATCHING SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total favorites: {stats.total_source_favorites}")
        for library_name, count in sorted(stats.favorites_by_library.items()):
            logger.info(f"  {library_name}: {count}")
        logger.info(f"High confidence matches: {stats.high_confidence_matches}")
        logger.info(f"Medium confidence matches: {stats.medium_confidence_matches}")
        logger.info(f"Ambiguous matches (skipped): {stats.ambiguous_matches}")
        logger.info(f"No matches found: {stats.no_matches}")
        logger.info(f"Already favorited: {stats.already_favorited}")
        logger.info("=" * 60)

        if stats.ambiguous_photos:
            logger.warning(f"\nAmbiguous matches (skipped {len(stats.ambiguous_photos)}):")
            for photo in stats.ambiguous_photos[:10]:  # Show first 10
                logger.warning(f"  - {photo}")
            if len(stats.ambiguous_photos) > 10:
                logger.warning(f"  ... and {len(stats.ambiguous_photos) - 10} more")

        if stats.missing_photos:
            logger.warning(f"\nNot found in Immich ({len(stats.missing_photos)}):")
            for photo in stats.missing_photos[:10]:  # Show first 10
                logger.warning(f"  - {photo}")
            if len(stats.missing_photos) > 10:
                logger.warning(f"  ... and {len(stats.missing_photos) - 10} more")

    def _batch_update_favorites(self, asset_ids: list[str], stats: SyncStats) -> None:
        """Update favorites in batches.

        Args:
            asset_ids: List of asset IDs to favorite
            stats: Stats object to update
        """
        total = len(asset_ids)
        for i in range(0, total, self.batch_size):
            batch = asset_ids[i : i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} assets)")

            try:
                self.immich_client.update_favorites(batch, is_favorite=True)
                stats.favorited += len(batch)
            except Exception as e:
                logger.error(f"Failed to update batch {batch_num}: {e}")
                stats.errors += len(batch)
                raise

    def _count_favorites_by_library(self, favorites: list[FavoritePhoto]) -> dict[str, int]:
        """Count favorites by source library."""
        counts: dict[str, int] = {}
        for favorite in favorites:
            library_name = favorite.library or "unknown"
            counts[library_name] = counts.get(library_name, 0) + 1
        return counts
