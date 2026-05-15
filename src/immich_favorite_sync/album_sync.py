"""Sync Photos albums to Immich albums."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .album_config import AlbumMappingConfig
from .immich_client import ImmichAlbum, ImmichClient
from .local_photos_client import LocalPhotosLibraryClient
from .matcher import AssetMatcher, MatchConfidence, MatchResult
from .models import PhotoAlbumMapping, PhotoAlbumSummary

logger = logging.getLogger(__name__)


@dataclass
class AlbumSyncResult:
    """Sync result for one album mapping."""

    mapping: PhotoAlbumMapping
    photos_album: PhotoAlbumSummary | None
    immich_album: ImmichAlbum | None = None
    matched_asset_ids: list[str] = field(default_factory=list)
    planned_asset_ids: list[str] = field(default_factory=list)
    skipped_matches: list[MatchResult] = field(default_factory=list)
    created_album: bool = False
    added_assets: int = 0
    error: str | None = None


@dataclass
class AlbumSyncStats:
    """Statistics for an album sync run."""

    total_mappings: int = 0
    albums_created: int = 0
    albums_found: int = 0
    photos_assets_seen: int = 0
    matched_assets: int = 0
    assets_to_add: int = 0
    assets_added: int = 0
    skipped_assets: int = 0
    errors: int = 0
    results: list[AlbumSyncResult] = field(default_factory=list)


@dataclass
class AlbumSyncContext:
    """Shared state for one album sync run."""

    resolved_immich_albums: dict[str, ImmichAlbum] = field(default_factory=dict)
    planned_album_names: set[str] = field(default_factory=set)


class AlbumSyncer:
    """Orchestrates add-only Photos album sync to Immich."""

    def __init__(
        self,
        photos_client: LocalPhotosLibraryClient,
        immich_client: ImmichClient,
        config_path: Path,
        batch_size: int = 50,
        dry_run: bool = True,
    ):
        self.photos_client = photos_client
        self.immich_client = immich_client
        self.config_path = config_path
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.matcher = AssetMatcher(immich_client)

    def sync_configured(self) -> AlbumSyncStats:
        """Sync albums from the saved mapping config."""
        config = AlbumMappingConfig.load(self.config_path)
        if not config.albums:
            raise ValueError(f"No album mappings found in {self.config_path}. Run albums --interactive first.")

        return self._sync_mappings(config.albums, config, save_config=True)

    def sync_selected(
        self,
        selected_albums: list[PhotoAlbumSummary],
        save_config: bool = True,
    ) -> AlbumSyncStats:
        """Sync interactively selected albums and optionally persist mappings."""
        config = AlbumMappingConfig.load(self.config_path)
        mappings = [
            PhotoAlbumMapping.from_album(
                album,
                immich_album_name=self._target_album_name(album),
            )
            for album in selected_albums
        ]
        return self._sync_mappings(mappings, config, save_config=save_config)

    def _sync_mappings(
        self,
        mappings: list[PhotoAlbumMapping],
        config: AlbumMappingConfig,
        save_config: bool,
    ) -> AlbumSyncStats:
        """Sync a set of album mappings."""
        photos_albums = self.photos_client.list_albums()
        stats = AlbumSyncStats(total_mappings=len(mappings))

        context = AlbumSyncContext()
        for mapping in mappings:
            result = self._sync_mapping(mapping, photos_albums, context)
            stats.results.append(result)
            self._update_stats(stats, result)

        if save_config:
            synced_at = self._timestamp()
            for result in stats.results:
                if result.error is None and result.photos_album is not None:
                    mapping = config.upsert_album(
                        result.photos_album,
                        result.immich_album.album_name if result.immich_album else result.mapping.immich_album_name,
                        result.immich_album.id if result.immich_album else result.mapping.immich_album_id,
                    )
                    mapping.last_synced_at = synced_at if not self.dry_run else mapping.last_synced_at
            config.save(self.config_path)

        return stats

    def _sync_mapping(
        self,
        mapping: PhotoAlbumMapping,
        photos_albums: list[PhotoAlbumSummary],
        context: AlbumSyncContext,
    ) -> AlbumSyncResult:
        """Sync one album mapping."""
        try:
            photos_album = self._resolve_photos_album(mapping, photos_albums)
            result = AlbumSyncResult(mapping=mapping, photos_album=photos_album)

            immich_album = self._resolve_immich_album(mapping, context)
            if immich_album is None:
                result.created_album = self._mark_album_creation_planned(mapping, context)
                if not self.dry_run:
                    immich_album = self.immich_client.create_album(mapping.immich_album_name)
                    self._remember_immich_album(immich_album, context)
            result.immich_album = immich_album

            match_results = [self.matcher.match(asset) for asset in self.photos_client.get_album_assets(photos_album.uuid)]
            result.matched_asset_ids = self._accepted_asset_ids(match_results)
            result.skipped_matches = [
                match
                for match in match_results
                if match.confidence not in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]
            ]
            result.planned_asset_ids = self._assets_missing_from_album(result.matched_asset_ids, immich_album)

            if result.planned_asset_ids and not self.dry_run:
                result.added_assets = self._add_assets_in_batches(immich_album.id, result.planned_asset_ids)

            return result

        except Exception as e:
            logger.error("Failed to sync album mapping %s: %s", mapping.immich_album_name, e)
            return AlbumSyncResult(
                mapping=mapping,
                photos_album=None,
                error=str(e),
            )

    def _resolve_photos_album(
        self,
        mapping: PhotoAlbumMapping,
        photos_albums: list[PhotoAlbumSummary],
    ) -> PhotoAlbumSummary:
        """Resolve a mapping to exactly one Photos album."""
        if mapping.photos_album_uuid:
            uuid_matches = [album for album in photos_albums if album.uuid == mapping.photos_album_uuid]
            if uuid_matches:
                return uuid_matches[0]

        if mapping.photos_album_path:
            path_matches = [
                album
                for album in photos_albums
                if album.path == mapping.photos_album_path and album.name == mapping.photos_album_name
            ]
            if len(path_matches) == 1:
                return path_matches[0]

        name_matches = [album for album in photos_albums if album.name == mapping.photos_album_name]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            raise ValueError(f"Multiple Photos albums named {mapping.photos_album_name!r}; use UUID or path mapping")

        raise ValueError(f"Photos album not found: {mapping.photos_album_name}")

    def _resolve_immich_album(
        self,
        mapping: PhotoAlbumMapping,
        context: AlbumSyncContext,
    ) -> ImmichAlbum | None:
        """Resolve the target Immich album, preferring saved IDs over names."""
        cached_album = self._cached_immich_album(mapping, context)
        if cached_album is not None:
            return cached_album

        if mapping.immich_album_id:
            album = self.immich_client.find_album_by_id(mapping.immich_album_id)
            if album is not None:
                self._remember_immich_album(album, context)
                return album

            logger.warning(
                "Saved Immich album ID %s was not found; falling back to album name %s",
                mapping.immich_album_id,
                mapping.immich_album_name,
            )

        album = self.immich_client.find_album_by_name(mapping.immich_album_name)
        if album is not None:
            self._remember_immich_album(album, context)

        return album

    def _cached_immich_album(
        self,
        mapping: PhotoAlbumMapping,
        context: AlbumSyncContext,
    ) -> ImmichAlbum | None:
        """Return an Immich album already resolved in this sync run."""
        for cache_key in self._album_cache_keys(mapping):
            album = context.resolved_immich_albums.get(cache_key)
            if album is not None:
                return album

        return None

    def _remember_immich_album(self, album: ImmichAlbum, context: AlbumSyncContext) -> None:
        """Cache resolved Immich album identifiers for the current run."""
        context.resolved_immich_albums[f"id:{album.id}"] = album
        context.resolved_immich_albums[f"name:{album.album_name.casefold()}"] = album

    def _mark_album_creation_planned(
        self,
        mapping: PhotoAlbumMapping,
        context: AlbumSyncContext,
    ) -> bool:
        """Record whether this run already planned the missing Immich album."""
        album_name_key = f"name:{mapping.immich_album_name.casefold()}"
        if album_name_key in context.planned_album_names:
            return False

        context.planned_album_names.add(album_name_key)
        return True

    def _album_cache_keys(self, mapping: PhotoAlbumMapping) -> list[str]:
        """Return cache keys that can identify a mapped Immich album."""
        cache_keys = []
        if mapping.immich_album_id:
            cache_keys.append(f"id:{mapping.immich_album_id}")
        cache_keys.append(f"name:{mapping.immich_album_name.casefold()}")
        return cache_keys

    def _accepted_asset_ids(self, match_results: list[MatchResult]) -> list[str]:
        """Return deduplicated Immich asset IDs accepted for album sync."""
        asset_ids = []
        for match in match_results:
            if match.confidence not in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]:
                continue

            matched_assets = [match.immich_asset] if match.immich_asset is not None else match.candidates
            asset_ids.extend(asset.id for asset in matched_assets if asset is not None)

        return list(dict.fromkeys(asset_ids))

    def _assets_missing_from_album(
        self,
        matched_asset_ids: list[str],
        immich_album: ImmichAlbum | None,
    ) -> list[str]:
        """Return matched asset IDs not already visible in the Immich album payload."""
        if immich_album is None:
            return matched_asset_ids

        existing_asset_ids = {asset.id for asset in immich_album.assets}
        return [asset_id for asset_id in matched_asset_ids if asset_id not in existing_asset_ids]

    def _add_assets_in_batches(self, album_id: str, asset_ids: list[str]) -> int:
        """Add assets to an Immich album in batches."""
        added_count = 0
        for start in range(0, len(asset_ids), self.batch_size):
            batch = asset_ids[start : start + self.batch_size]
            added_count += self.immich_client.add_assets_to_album(album_id, batch)

        return added_count

    def _update_stats(self, stats: AlbumSyncStats, result: AlbumSyncResult) -> None:
        """Update aggregate album sync stats."""
        if result.error:
            stats.errors += 1
            return

        if result.created_album:
            stats.albums_created += 1
        elif result.immich_album is not None:
            stats.albums_found += 1

        stats.photos_assets_seen += result.photos_album.asset_count if result.photos_album else 0
        stats.matched_assets += len(result.matched_asset_ids)
        stats.assets_to_add += len(result.planned_asset_ids)
        stats.assets_added += result.added_assets
        stats.skipped_assets += len(result.skipped_matches)

    def _timestamp(self) -> str:
        """Return an ISO UTC timestamp."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _target_album_name(self, album: PhotoAlbumSummary) -> str:
        """Return the Immich album name for a selected Photos album."""
        path_parts = [part.strip() for part in album.path.split("/") if part.strip()]
        if len(path_parts) <= 1:
            return album.name

        if len(path_parts) == 2:
            return f"[{path_parts[0]}] {path_parts[1]}"

        middle_path = " / ".join(path_parts[1:-1])
        return f"[{path_parts[0]}] ({middle_path}) {path_parts[-1]}"
