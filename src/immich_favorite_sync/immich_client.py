"""Immich API client for searching and updating assets."""

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ImmichAsset:
    """Metadata for an Immich asset."""

    id: str
    original_file_name: str
    original_path: str | None
    file_created_at: datetime | None
    local_date_time: datetime | None
    checksum: str | None
    is_favorite: bool
    width: int | None = None
    height: int | None = None
    file_size_in_byte: int | None = None
    date_time_original: datetime | None = None
    make: str | None = None
    model: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def __str__(self) -> str:
        """String representation."""
        return f"{self.original_file_name} (id: {self.id[:8]}...)"


class ImmichClient:
    """Client for Immich API operations."""

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        """Initialize Immich client.

        Args:
            base_url: Immich server URL
            api_key: Immich API key
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    def search_by_filename(
        self,
        filename: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[ImmichAsset]:
        """Search for assets by filename.

        Args:
            filename: Original filename to search for
            created_after: Optional date filter
            created_before: Optional date filter

        Returns:
            List of matching assets
        """
        logger.debug(f"Searching Immich for filename: {filename}")

        payload = {
            "originalFileName": filename,
        }

        if created_after:
            payload["takenAfter"] = created_after.isoformat()
        if created_before:
            payload["takenBefore"] = created_before.isoformat()

        return self.search_metadata(payload, f"filename: {filename}")

    def search_metadata(self, payload: dict, description: str = "metadata") -> list[ImmichAsset]:
        """Search for assets with an Immich metadata payload."""
        logger.debug("Searching Immich by %s", description)

        try:
            response = self._client.post(
                f"{self.base_url}/api/search/metadata",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            assets = data.get("assets", {}).get("items", [])

            results = []
            for asset_data in assets:
                asset = self._parse_asset(asset_data)
                if asset:
                    results.append(asset)

            logger.debug("Found %s assets matching %s", len(results), description)
            return results

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error searching by %s: %s", description, e.response.status_code)
            raise
        except Exception as e:
            logger.error("Error searching by %s: %s", description, e)
            raise

    def get_asset(self, asset_id: str) -> ImmichAsset:
        """Get full asset details by ID."""
        try:
            response = self._client.get(f"{self.base_url}/api/assets/{asset_id}")
            response.raise_for_status()

            asset = self._parse_asset(response.json())
            if asset is None:
                raise RuntimeError(f"Immich returned invalid asset details for {asset_id}")

            return asset

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching asset {asset_id}: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Error fetching asset {asset_id}: {e}")
            raise

    def update_favorites(self, asset_ids: list[str], is_favorite: bool = True) -> None:
        """Update favorite status for multiple assets.

        Args:
            asset_ids: List of asset IDs to update
            is_favorite: Whether to mark as favorite (default True)
        """
        if not asset_ids:
            return

        logger.info(f"Updating {len(asset_ids)} assets to favorite={is_favorite}")

        try:
            response = self._client.put(
                f"{self.base_url}/api/assets",
                json={
                    "ids": asset_ids,
                    "isFavorite": is_favorite,
                },
            )
            response.raise_for_status()

            logger.info(f"Successfully updated {len(asset_ids)} assets")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error updating favorites: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"Failed to update favorites in Immich: {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"Error updating favorites: {e}")
            raise RuntimeError(f"Failed to update favorites in Immich: {e}") from e

    def _parse_asset(self, asset_data: dict) -> ImmichAsset | None:
        """Parse asset data from API response.

        Args:
            asset_data: Raw asset data from API

        Returns:
            ImmichAsset or None if parsing fails
        """
        try:
            asset_id = asset_data.get("id")
            if not asset_id:
                return None

            original_file_name = asset_data.get("originalFileName", "")
            original_path = asset_data.get("originalPath")
            checksum = asset_data.get("checksum")
            is_favorite = asset_data.get("isFavorite", False)
            exif_info = asset_data.get("exifInfo") or {}

            file_created_at = self._parse_datetime(asset_data.get("fileCreatedAt"))
            local_date_time = self._parse_datetime(asset_data.get("localDateTime"))
            date_time_original = self._parse_datetime(exif_info.get("dateTimeOriginal"))

            width = asset_data.get("width") or exif_info.get("exifImageWidth")
            height = asset_data.get("height") or exif_info.get("exifImageHeight")

            return ImmichAsset(
                id=asset_id,
                original_file_name=original_file_name,
                original_path=original_path,
                file_created_at=file_created_at,
                local_date_time=local_date_time,
                checksum=checksum,
                is_favorite=is_favorite,
                width=width,
                height=height,
                file_size_in_byte=exif_info.get("fileSizeInByte"),
                date_time_original=date_time_original,
                make=exif_info.get("make"),
                model=exif_info.get("model"),
                latitude=exif_info.get("latitude"),
                longitude=exif_info.get("longitude"),
            )

        except Exception as e:
            logger.warning(f"Failed to parse asset data: {e}")
            return None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse an Immich API datetime string."""
        if not value:
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
        logger.debug("Closed Immich client")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
