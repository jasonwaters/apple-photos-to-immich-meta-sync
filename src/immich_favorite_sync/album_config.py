"""Album mapping configuration persistence."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import PhotoAlbumMapping, PhotoAlbumSummary


@dataclass
class AlbumMappingConfig:
    """Config file containing saved Photos-to-Immich album mappings."""

    albums: list[PhotoAlbumMapping] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "AlbumMappingConfig":
        """Load mapping config from disk."""
        if not path.exists():
            return cls()

        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)

        return cls(
            albums=[
                PhotoAlbumMapping.from_dict(item)
                for item in data.get("albums", [])
            ]
        )

    def save(self, path: Path) -> None:
        """Write mapping config to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as config_file:
            json.dump(
                {"albums": [album.to_dict() for album in self.albums]},
                config_file,
                indent=2,
                sort_keys=True,
            )

    def upsert_album(
        self,
        album: PhotoAlbumSummary,
        immich_album_name: str | None = None,
        immich_album_id: str | None = None,
    ) -> PhotoAlbumMapping:
        """Insert or update one selected Photos album mapping."""
        mapping = PhotoAlbumMapping.from_album(album, immich_album_name=immich_album_name)
        mapping.immich_album_id = immich_album_id
        existing_index = self._find_mapping_index(mapping)

        if existing_index is None:
            self.albums.append(mapping)
            return mapping

        existing = self.albums[existing_index]
        existing.photos_album_uuid = mapping.photos_album_uuid
        existing.photos_album_path = mapping.photos_album_path
        existing.photos_album_name = mapping.photos_album_name
        existing.immich_album_name = immich_album_name or existing.immich_album_name or mapping.immich_album_name
        existing.immich_album_id = immich_album_id or existing.immich_album_id
        existing.last_seen_photos_album_name = mapping.last_seen_photos_album_name
        existing.last_seen_photos_album_path = mapping.last_seen_photos_album_path
        return existing

    def _find_mapping_index(self, mapping: PhotoAlbumMapping) -> int | None:
        """Find an existing mapping for the same Photos album."""
        for index, existing in enumerate(self.albums):
            if mapping.photos_album_uuid and existing.photos_album_uuid == mapping.photos_album_uuid:
                return index
            if (
                mapping.photos_album_path
                and existing.photos_album_path == mapping.photos_album_path
                and existing.photos_album_name == mapping.photos_album_name
                and (not mapping.photos_album_uuid or not existing.photos_album_uuid)
            ):
                return index

        return None
