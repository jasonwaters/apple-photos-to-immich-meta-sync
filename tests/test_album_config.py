"""Tests for album mapping config persistence."""

from immich_favorite_sync.album_config import AlbumMappingConfig
from immich_favorite_sync.models import PhotoAlbumMapping, PhotoAlbumSummary


def test_album_mapping_config_upserts_selected_album(tmp_path):
    """Interactive selections should seed reusable album mappings."""
    config_path = tmp_path / "album-sync.json"
    album = PhotoAlbumSummary(
        id="1",
        uuid="album-uuid",
        name="Hawaii",
        path="Trips/Hawaii",
        asset_count=10,
        photo_count=9,
        video_count=1,
    )
    config = AlbumMappingConfig()

    config.upsert_album(album)
    config.upsert_album(album)
    config.save(config_path)
    loaded = AlbumMappingConfig.load(config_path)

    assert len(loaded.albums) == 1
    assert loaded.albums[0].photos_album_uuid == "album-uuid"
    assert loaded.albums[0].immich_album_name == "Hawaii"


def test_album_mapping_config_persists_immich_album_id(tmp_path):
    """Saved mappings should retain the Immich album ID for rename-safe replay."""
    config_path = tmp_path / "album-sync.json"
    album = PhotoAlbumSummary(
        id="1",
        uuid="album-uuid",
        name="Hawaii",
        path="Trips/Hawaii",
        asset_count=10,
        photo_count=9,
        video_count=1,
    )
    config = AlbumMappingConfig()

    config.upsert_album(album, immich_album_name="Renamed in Immich", immich_album_id="immich-album-id")
    config.save(config_path)
    loaded = AlbumMappingConfig.load(config_path)

    assert loaded.albums[0].immich_album_id == "immich-album-id"


def test_album_mapping_config_keeps_duplicate_albums_with_distinct_uuids(tmp_path):
    """Duplicate Photos album rows should not overwrite each other in config."""
    config_path = tmp_path / "album-sync.json"
    first_album = PhotoAlbumSummary(
        id="1",
        uuid="first-album-uuid",
        name="Grandpa Waters",
        path="misc/Grandpa Waters",
        asset_count=302,
        photo_count=302,
        video_count=0,
    )
    second_album = PhotoAlbumSummary(
        id="2",
        uuid="second-album-uuid",
        name="Grandpa Waters",
        path="misc/Grandpa Waters",
        asset_count=8,
        photo_count=8,
        video_count=0,
    )
    config = AlbumMappingConfig()

    config.upsert_album(first_album, immich_album_name="[misc] Grandpa Waters")
    config.upsert_album(second_album, immich_album_name="[misc] Grandpa Waters")
    config.save(config_path)
    loaded = AlbumMappingConfig.load(config_path)

    assert [album.photos_album_uuid for album in loaded.albums] == ["first-album-uuid", "second-album-uuid"]
    assert {album.immich_album_name for album in loaded.albums} == {"[misc] Grandpa Waters"}


def test_album_mapping_config_upgrades_legacy_path_mapping_with_uuid(tmp_path):
    """Legacy path-only mappings should be updated once Photos UUIDs are known."""
    config_path = tmp_path / "album-sync.json"
    config = AlbumMappingConfig([
        PhotoAlbumMapping(
            photos_album_uuid=None,
            photos_album_path="Trips/Hawaii",
            photos_album_name="Hawaii",
            immich_album_name="[Trips] Hawaii",
        ),
    ])
    album = PhotoAlbumSummary(
        id="1",
        uuid="album-uuid",
        name="Hawaii",
        path="Trips/Hawaii",
        asset_count=10,
        photo_count=9,
        video_count=1,
    )

    config.upsert_album(album, immich_album_name="[Trips] Hawaii")
    config.save(config_path)
    loaded = AlbumMappingConfig.load(config_path)

    assert len(loaded.albums) == 1
    assert loaded.albums[0].photos_album_uuid == "album-uuid"


def test_album_mapping_config_loads_missing_file_as_empty(tmp_path):
    """Missing config files should load as empty for interactive first runs."""
    config = AlbumMappingConfig.load(tmp_path / "missing.json")

    assert config.albums == []
