"""Tests for sync orchestration."""

from immich_favorite_sync.immich_client import ImmichAsset
from immich_favorite_sync.matcher import MatchConfidence, MatchResult
from immich_favorite_sync.models import FavoritePhoto
from immich_favorite_sync.sync import FavoriteSyncer, SyncStats


def test_sync_stats_initialization():
    """Test SyncStats initialization."""
    stats = SyncStats()

    assert stats.total_source_favorites == 0
    assert stats.high_confidence_matches == 0
    assert stats.medium_confidence_matches == 0
    assert stats.ambiguous_matches == 0
    assert stats.no_matches == 0
    assert stats.already_favorited == 0
    assert stats.to_favorite == 0
    assert stats.favorited == 0
    assert stats.errors == 0
    assert stats.matched_asset_ids == []
    assert stats.ambiguous_photos == []
    assert stats.missing_photos == []
    assert stats.error_photos == []


def test_sync_stats_get_total_matches():
    """Test getting total matches from stats."""
    stats = SyncStats()
    stats.high_confidence_matches = 10
    stats.medium_confidence_matches = 3

    assert stats.get_total_matches() == 13


def test_sync_plans_each_asset_once_in_dry_run():
    """Test dry run deduplicates duplicate favorite plans for the same Immich asset."""
    photo = FavoritePhoto(
        id="favorite-id",
        filename="IMG_1234.JPG",
        asset_date=None,
        added_date=None,
        dimensions=None,
        size=None,
    )
    asset = ImmichAsset(
        id="asset-id",
        original_file_name="IMG_1234.JPG",
        original_path="/photos/IMG_1234.JPG",
        file_created_at=None,
        local_date_time=None,
        checksum=None,
        is_favorite=False,
    )
    syncer = FavoriteSyncer(
        favorite_source=FakeFavoriteSource([photo, photo]),
        immich_client=FakeImmichClient(),
        dry_run=True,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=photo,
        confidence=MatchConfidence.HIGH,
        immich_asset=asset,
        candidates=[asset],
        reason="test match",
    ))

    stats = syncer.sync()

    assert stats.to_favorite == 1
    assert stats.planned_favorites == [syncer.matcher.result]


class FakeFavoriteSource:
    def __init__(self, favorites: list[FavoritePhoto]):
        self.favorites = favorites

    def get_favorites(self) -> list[FavoritePhoto]:
        return self.favorites

    def close(self) -> None:
        return None


class FakeMatcher:
    def __init__(self, result: MatchResult):
        self.result = result

    def match(self, photo: FavoritePhoto) -> MatchResult:
        return self.result


class FakeImmichClient:
    def update_favorites(self, asset_ids: list[str], is_favorite: bool = True) -> None:
        return None
