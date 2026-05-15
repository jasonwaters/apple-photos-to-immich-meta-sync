"""Shared domain models for favorite sync."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FavoritePhoto:
    """Metadata for a favorite photo from a configured source."""

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
        """Serialize favorite metadata for local cache storage."""
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
    def from_dict(cls, data: dict) -> "FavoritePhoto":
        """Deserialize favorite metadata from local cache storage."""
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
