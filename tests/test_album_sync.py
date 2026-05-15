"""Tests for album sync orchestration."""

from immich_favorite_sync.album_config import AlbumMappingConfig
from immich_favorite_sync.album_sync import AlbumSyncer
from immich_favorite_sync.immich_client import ImmichAlbum, ImmichAsset
from immich_favorite_sync.matcher import MatchConfidence, MatchResult
from immich_favorite_sync.models import PhotoAlbumMapping, PhotoAlbumSummary, PhotoAsset


def test_album_sync_selected_upserts_config_for_later_replay(tmp_path):
    """Interactive selections should persist mappings for non-interactive runs."""
    album = _photo_album()
    asset = _photo_asset()
    immich_asset = _immich_asset()
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([album], [asset]),
        immich_client=FakeImmichClient(existing_album=None),
        config_path=tmp_path / "album-sync.json",
        dry_run=True,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=asset,
        confidence=MatchConfidence.HIGH,
        immich_asset=immich_asset,
    ))

    stats = syncer.sync_selected([album], save_config=True)
    config = AlbumMappingConfig.load(tmp_path / "album-sync.json")

    assert stats.assets_to_add == 1
    assert config.albums[0].photos_album_uuid == "photos-album-uuid"
    assert config.albums[0].immich_album_name == "[Trips] Hawaii"


def test_album_sync_selected_formats_photos_path_for_immich_album_name(tmp_path):
    """Interactive setup should seed readable path-based Immich album names."""
    album = _photo_album(path="kelly/Scott Kelly/All Scott", name="All Scott")
    asset = _photo_asset()
    immich_client = FakeImmichClient(existing_album=None)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([album], [asset]),
        immich_client=immich_client,
        config_path=tmp_path / "album-sync.json",
        dry_run=False,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=asset,
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    stats = syncer.sync_selected([album], save_config=True)
    config = AlbumMappingConfig.load(tmp_path / "album-sync.json")

    assert stats.albums_created == 1
    assert immich_client.created_album_names == ["[kelly] (Scott Kelly) All Scott"]
    assert config.albums[0].immich_album_name == "[kelly] (Scott Kelly) All Scott"


def test_album_sync_selected_formats_two_segment_photos_path(tmp_path):
    """Two-segment Photos paths should omit the middle-folder parentheses."""
    album = _photo_album(path="Family Photos/2017-03 - Lehi", name="2017-03 - Lehi")
    asset = _photo_asset()
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([album], [asset]),
        immich_client=FakeImmichClient(existing_album=None),
        config_path=tmp_path / "album-sync.json",
        dry_run=True,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=asset,
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    syncer.sync_selected([album], save_config=True)
    config = AlbumMappingConfig.load(tmp_path / "album-sync.json")

    assert config.albums[0].immich_album_name == "[Family Photos] 2017-03 - Lehi"


def test_album_sync_selected_combines_duplicate_photo_albums_into_one_immich_album(tmp_path):
    """Duplicate Photos albums with the same path should target one Immich album."""
    first_album = _photo_album(album_uuid="first", path="misc/Grandpa Waters", name="Grandpa Waters")
    second_album = _photo_album(album_uuid="second", path="misc/Grandpa Waters", name="Grandpa Waters")
    immich_client = FakeImmichClient(existing_album=None)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([first_album, second_album], [_photo_asset()]),
        immich_client=immich_client,
        config_path=tmp_path / "album-sync.json",
        dry_run=False,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=_photo_asset(),
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    stats = syncer.sync_selected([first_album, second_album], save_config=True)
    config = AlbumMappingConfig.load(tmp_path / "album-sync.json")

    assert stats.albums_created == 1
    assert stats.albums_found == 1
    assert immich_client.created_album_names == ["[misc] Grandpa Waters"]
    assert [album.photos_album_uuid for album in config.albums] == ["first", "second"]
    assert {album.immich_album_name for album in config.albums} == {"[misc] Grandpa Waters"}
    assert {album.immich_album_id for album in config.albums} == {"album-1"}


def test_album_sync_dry_run_plans_duplicate_immich_album_once(tmp_path):
    """Dry runs should not overcount one planned Immich album shared by mappings."""
    first_album = _photo_album(album_uuid="first", path="misc/Grandpa Waters", name="Grandpa Waters")
    second_album = _photo_album(album_uuid="second", path="misc/Grandpa Waters", name="Grandpa Waters")
    immich_client = FakeImmichClient(existing_album=None)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([first_album, second_album], [_photo_asset()]),
        immich_client=immich_client,
        config_path=tmp_path / "album-sync.json",
        dry_run=True,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=_photo_asset(),
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    stats = syncer.sync_selected([first_album, second_album], save_config=True)

    assert stats.albums_created == 1
    assert stats.albums_found == 0
    assert immich_client.created_album_names == []


def test_album_sync_configured_replays_saved_mapping(tmp_path):
    """Non-interactive runs should sync albums from config."""
    album = _photo_album()
    asset = _photo_asset()
    immich_album = ImmichAlbum(id="album-1", album_name="Hawaii", asset_count=0, assets=[])
    immich_client = FakeImmichClient(existing_album=immich_album)
    config = AlbumMappingConfig([
        PhotoAlbumMapping.from_album(album),
    ])
    config_path = tmp_path / "album-sync.json"
    config.save(config_path)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([album], [asset]),
        immich_client=immich_client,
        config_path=config_path,
        dry_run=False,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=asset,
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    stats = syncer.sync_configured()

    assert stats.assets_added == 1
    assert immich_client.added_asset_ids == ["asset-1"]


def test_album_sync_prefers_saved_immich_album_id_after_rename(tmp_path):
    """Saved Immich IDs should keep working after users rename albums."""
    album = _photo_album()
    asset = _photo_asset()
    renamed_album = ImmichAlbum(id="album-1", album_name="Renamed in Immich", asset_count=0, assets=[])
    immich_client = FakeImmichClient(existing_album=renamed_album)
    config = AlbumMappingConfig([
        PhotoAlbumMapping(
            photos_album_uuid=album.uuid,
            photos_album_path=album.path,
            photos_album_name=album.name,
            immich_album_name="Hawaii",
            immich_album_id="album-1",
        ),
    ])
    config_path = tmp_path / "album-sync.json"
    config.save(config_path)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([album], [asset]),
        immich_client=immich_client,
        config_path=config_path,
        dry_run=False,
    )
    syncer.matcher = FakeMatcher(MatchResult(
        source_photo=asset,
        confidence=MatchConfidence.HIGH,
        immich_asset=_immich_asset(),
    ))

    stats = syncer.sync_configured()
    updated_config = AlbumMappingConfig.load(config_path)

    assert stats.assets_added == 1
    assert immich_client.find_by_id_calls == ["album-1"]
    assert updated_config.albums[0].immich_album_name == "Renamed in Immich"
    assert updated_config.albums[0].immich_album_id == "album-1"


def test_album_sync_requires_disambiguated_duplicate_photo_album_names(tmp_path):
    """Duplicate leaf album names should require UUID or path-backed mappings."""
    mapping = PhotoAlbumMapping(
        photos_album_uuid=None,
        photos_album_path=None,
        photos_album_name="Hawaii",
        immich_album_name="Hawaii",
    )
    config_path = tmp_path / "album-sync.json"
    AlbumMappingConfig([mapping]).save(config_path)
    syncer = AlbumSyncer(
        photos_client=FakePhotosClient([
            _photo_album(album_uuid="first", path="Trips/Hawaii"),
            _photo_album(album_uuid="second", path="Family/Hawaii"),
        ], []),
        immich_client=FakeImmichClient(existing_album=None),
        config_path=config_path,
        dry_run=True,
    )

    stats = syncer.sync_configured()

    assert stats.errors == 1
    assert "Multiple Photos albums named" in stats.results[0].error


def _photo_album(
    album_uuid: str = "photos-album-uuid",
    path: str = "Trips/Hawaii",
    name: str = "Hawaii",
) -> PhotoAlbumSummary:
    return PhotoAlbumSummary(
        id="1",
        uuid=album_uuid,
        name=name,
        path=path,
        asset_count=1,
        photo_count=1,
        video_count=0,
    )


def _photo_asset() -> PhotoAsset:
    return PhotoAsset(
        id="photo-1",
        filename="IMG_0001.JPG",
        asset_date=None,
        added_date=None,
        dimensions=None,
        size=None,
    )


def _immich_asset() -> ImmichAsset:
    return ImmichAsset(
        id="asset-1",
        original_file_name="IMG_0001.JPG",
        original_path="/photos/IMG_0001.JPG",
        file_created_at=None,
        local_date_time=None,
        checksum=None,
        is_favorite=False,
    )


class FakePhotosClient:
    def __init__(self, albums: list[PhotoAlbumSummary], assets: list[PhotoAsset]):
        self.albums = albums
        self.assets = assets

    def list_albums(self) -> list[PhotoAlbumSummary]:
        return self.albums

    def get_album_assets(self, album_uuid: str) -> list[PhotoAsset]:
        return self.assets


class FakeImmichClient:
    def __init__(self, existing_album: ImmichAlbum | None):
        self.existing_album = existing_album
        self.added_asset_ids = []
        self.created_album_names = []
        self.find_by_id_calls = []
        self.find_by_name_calls = []

    def find_album_by_id(self, album_id: str) -> ImmichAlbum | None:
        self.find_by_id_calls.append(album_id)
        if self.existing_album and self.existing_album.id == album_id:
            return self.existing_album
        return None

    def find_album_by_name(self, album_name: str) -> ImmichAlbum | None:
        self.find_by_name_calls.append(album_name)
        return self.existing_album

    def create_album(self, album_name: str, asset_ids: list[str] | None = None) -> ImmichAlbum:
        self.created_album_names.append(album_name)
        self.existing_album = ImmichAlbum(id="album-1", album_name=album_name, asset_count=0, assets=[])
        return self.existing_album

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> int:
        self.added_asset_ids.extend(asset_ids)
        return len(asset_ids)


class FakeMatcher:
    def __init__(self, result: MatchResult):
        self.result = result

    def match(self, photo: PhotoAsset) -> MatchResult:
        return self.result
