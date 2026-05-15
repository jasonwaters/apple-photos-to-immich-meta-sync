"""Shared domain models for Photos-to-Immich sync."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PhotoAsset:
    """Metadata for a photo asset from the local Photos library."""

    id: str
    filename: str
    asset_date: datetime | None
    added_date: datetime | None
    dimensions: tuple[int, int] | None
    size: int | None
    library: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    make: str | None = None
    model: str | None = None
    lens_model: str | None = None
    cloud_master_guid: str | None = None
    uti: str | None = None

    def __str__(self) -> str:
        """String representation."""
        date_str = self.asset_date.strftime("%Y-%m-%d") if self.asset_date else "unknown date"
        library = f", {self.library}" if self.library else ""
        return f"{self.filename} ({date_str}{library})"

    def to_dict(self) -> dict:
        """Serialize photo metadata for local cache storage."""
        return {
            "id": self.id,
            "filename": self.filename,
            "asset_date": self.asset_date.isoformat() if self.asset_date else None,
            "added_date": self.added_date.isoformat() if self.added_date else None,
            "dimensions": list(self.dimensions) if self.dimensions else None,
            "size": self.size,
            "library": self.library,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "make": self.make,
            "model": self.model,
            "lens_model": self.lens_model,
            "cloud_master_guid": self.cloud_master_guid,
            "uti": self.uti,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhotoAsset":
        """Deserialize photo metadata from local cache storage."""
        dimensions = data.get("dimensions")

        return cls(
            id=data["id"],
            filename=data["filename"],
            asset_date=datetime.fromisoformat(data["asset_date"]) if data.get("asset_date") else None,
            added_date=datetime.fromisoformat(data["added_date"]) if data.get("added_date") else None,
            dimensions=tuple(dimensions) if dimensions else None,
            size=data.get("size"),
            library=data.get("library"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            make=data.get("make"),
            model=data.get("model"),
            lens_model=data.get("lens_model"),
            cloud_master_guid=data.get("cloud_master_guid"),
            uti=data.get("uti"),
        )


class FavoritePhoto(PhotoAsset):
    """Backward-compatible name for favorite sync assets."""


@dataclass
class PhotoAlbumSummary:
    """A non-empty album from the local Photos library."""

    id: str
    uuid: str
    name: str
    path: str
    asset_count: int
    photo_count: int
    video_count: int

    @property
    def display_name(self) -> str:
        """Return the most helpful human-readable album name."""
        return self.path or self.name


@dataclass
class PhotoAlbumMapping:
    """Mapping from a Photos album to an Immich album."""

    photos_album_uuid: str | None
    photos_album_path: str | None
    photos_album_name: str
    immich_album_name: str
    immich_album_id: str | None = None
    last_seen_photos_album_name: str | None = None
    last_seen_photos_album_path: str | None = None
    last_synced_at: str | None = None

    def to_dict(self) -> dict:
        """Serialize album mapping for config storage."""
        return {
            "photos_album_uuid": self.photos_album_uuid,
            "photos_album_path": self.photos_album_path,
            "photos_album_name": self.photos_album_name,
            "immich_album_name": self.immich_album_name,
            "immich_album_id": self.immich_album_id,
            "last_seen_photos_album_name": self.last_seen_photos_album_name,
            "last_seen_photos_album_path": self.last_seen_photos_album_path,
            "last_synced_at": self.last_synced_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhotoAlbumMapping":
        """Deserialize album mapping from config storage."""
        return cls(
            photos_album_uuid=data.get("photos_album_uuid"),
            photos_album_path=data.get("photos_album_path"),
            photos_album_name=data["photos_album_name"],
            immich_album_name=data["immich_album_name"],
            immich_album_id=data.get("immich_album_id"),
            last_seen_photos_album_name=data.get("last_seen_photos_album_name"),
            last_seen_photos_album_path=data.get("last_seen_photos_album_path"),
            last_synced_at=data.get("last_synced_at"),
        )

    @classmethod
    def from_album(cls, album: PhotoAlbumSummary, immich_album_name: str | None = None) -> "PhotoAlbumMapping":
        """Create a mapping from a selected Photos album."""
        return cls(
            photos_album_uuid=album.uuid,
            photos_album_path=album.path,
            photos_album_name=album.name,
            immich_album_name=immich_album_name or album.name,
            last_seen_photos_album_name=album.name,
            last_seen_photos_album_path=album.path,
        )
