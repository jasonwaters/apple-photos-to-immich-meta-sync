"""Tests for asset matching logic."""

from datetime import datetime

from immich_favorite_sync.immich_client import ImmichAsset
from immich_favorite_sync.matcher import AssetMatcher, MatchConfidence, MatchResult
from immich_favorite_sync.models import FavoritePhoto


def test_match_result_creation():
    """Test creating a MatchResult."""
    photo = FavoritePhoto(
        id="test-id",
        filename="IMG_1234.JPG",
        asset_date=datetime(2024, 1, 15, 10, 30),
        added_date=datetime(2024, 1, 15, 10, 30),
        dimensions=(3024, 4032),
        size=1024000,
    )

    result = MatchResult(
        source_photo=photo,
        confidence=MatchConfidence.HIGH,
        reason="Test match",
    )

    assert result.source_photo == photo
    assert result.confidence == MatchConfidence.HIGH
    assert result.immich_asset is None
    assert result.candidates == []
    assert result.reason == "Test match"


def test_match_confidence_levels():
    """Test match confidence enum values."""
    assert MatchConfidence.HIGH.value == "high"
    assert MatchConfidence.MEDIUM.value == "medium"
    assert MatchConfidence.AMBIGUOUS.value == "ambiguous"
    assert MatchConfidence.NONE.value == "none"


def test_matcher_prefers_case_sensitive_filename_match():
    """Case-only duplicates should prefer the Photos filename spelling."""
    photo = _favorite_photo(filename="Blue Book-145.jpg", asset_date=None, dimensions=(1320, 1038), size=241631)
    expected_asset = _immich_asset(
        asset_id="lowercase",
        filename="Blue Book-145.jpg",
        dimensions=(1320, 1038),
        size=241631,
    )
    uppercase_asset = _immich_asset(
        asset_id="uppercase",
        filename="Blue Book-145.JPG",
        dimensions=(1320, 1038),
        size=241631,
    )
    immich_client = FakeImmichClient(search_by_filename_results={
        "Blue Book-145.jpg": [expected_asset, uppercase_asset],
    })

    result = AssetMatcher(immich_client).match(photo)

    assert result.immich_asset == expected_asset
    assert result.confidence == MatchConfidence.MEDIUM


def test_matcher_searches_adjusted_filename_variant():
    """Photos edited assets can land in Immich with an -adjusted suffix."""
    photo = _favorite_photo(
        filename="image000000.jpg",
        asset_date=datetime(2024, 6, 30, 20, 34, 55),
        dimensions=(821, 892),
        size=380632,
    )
    adjusted_asset = _immich_asset(
        asset_id="adjusted",
        filename="image000000-adjusted.JPG",
        created_at=datetime(2024, 6, 30, 20, 34, 55),
        dimensions=(821, 892),
    )
    immich_client = FakeImmichClient(metadata_results={
        "image000000-adjusted.JPG": [adjusted_asset],
    })

    result = AssetMatcher(immich_client).match(photo)

    assert result.immich_asset == adjusted_asset
    assert result.confidence == MatchConfidence.MEDIUM


def test_matcher_searches_size_suffixed_filename_variant():
    """Imported assets may add the byte size to common names like FullSizeRender."""
    photo = _favorite_photo(
        filename="FullSizeRender.heic",
        asset_date=datetime(2021, 7, 26, 17, 2, 28, 914000),
        dimensions=(2316, 3088),
        size=1372909,
        make="Apple",
        model="iPhone 11 Pro Max",
        lens_model="iPhone 11 Pro Max front camera 2.71mm f/2.2",
    )
    renamed_asset = _immich_asset(
        asset_id="renamed",
        filename="FullSizeRender-1372909.heic",
        created_at=datetime(2021, 7, 26, 17, 2, 28, 914000),
        dimensions=(2316, 3088),
        make="Apple",
        model="iPhone 11 Pro Max",
    )
    immich_client = FakeImmichClient(metadata_results={
        "FullSizeRender-1372909.heic": [renamed_asset],
    })

    result = AssetMatcher(immich_client).match(photo)

    assert result.immich_asset == renamed_asset
    assert result.confidence == MatchConfidence.HIGH


def _favorite_photo(
    filename: str,
    asset_date: datetime | None,
    dimensions: tuple[int, int],
    size: int,
    make: str | None = None,
    model: str | None = None,
    lens_model: str | None = None,
) -> FavoritePhoto:
    return FavoritePhoto(
        id="favorite-id",
        filename=filename,
        asset_date=asset_date,
        added_date=None,
        dimensions=dimensions,
        size=size,
        make=make,
        model=model,
        lens_model=lens_model,
    )


def _immich_asset(
    asset_id: str,
    filename: str,
    dimensions: tuple[int, int],
    created_at: datetime | None = None,
    size: int | None = None,
    make: str | None = None,
    model: str | None = None,
) -> ImmichAsset:
    return ImmichAsset(
        id=asset_id,
        original_file_name=filename,
        original_path=f"/photos/{filename}",
        file_created_at=created_at,
        local_date_time=created_at,
        checksum=None,
        is_favorite=False,
        width=dimensions[0],
        height=dimensions[1],
        file_size_in_byte=size,
        make=make,
        model=model,
    )


class FakeImmichClient:
    """Small fake covering the matcher-facing Immich client methods."""

    def __init__(
        self,
        metadata_results: dict[str, list[ImmichAsset]] | None = None,
        search_by_filename_results: dict[str, list[ImmichAsset]] | None = None,
    ):
        self.metadata_results = metadata_results or {}
        self.search_by_filename_results = search_by_filename_results or {}

    def search_metadata(self, payload: dict, description: str = "metadata") -> list[ImmichAsset]:
        return self.metadata_results.get(payload["originalFileName"], [])

    def search_by_filename(
        self,
        filename: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[ImmichAsset]:
        return self.search_by_filename_results.get(filename, [])

    def get_asset(self, asset_id: str) -> ImmichAsset:
        for assets in [*self.metadata_results.values(), *self.search_by_filename_results.values()]:
            for asset in assets:
                if asset.id == asset_id:
                    return asset

        raise KeyError(asset_id)
