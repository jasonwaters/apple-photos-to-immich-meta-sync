"""Read favorite metadata from the local macOS Photos library database."""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .models import FavoritePhoto, PhotoAlbumSummary, PhotoAsset

logger = logging.getLogger(__name__)

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class LocalPhotosLibraryClient:
    """Read metadata from a local Photos.sqlite database."""

    def __init__(self, photos_sqlite_path: Path):
        """Initialize the local Photos library reader."""
        self.photos_sqlite_path = photos_sqlite_path

    def get_favorites(self) -> Iterator[FavoritePhoto]:
        """Yield favorite photos from the local Photos SQLite database."""
        logger.info("Reading favorites from local Photos database: %s", self.photos_sqlite_path)

        with closing(self._connect()) as conn:
            for row in conn.execute(self._favorites_query()):
                asset = self._row_to_asset(row, asset_class=FavoritePhoto)
                if asset is not None:
                    yield asset

    def list_albums(self) -> list[PhotoAlbumSummary]:
        """Return non-empty user albums from the local Photos library."""
        logger.info("Reading albums from local Photos database: %s", self.photos_sqlite_path)

        with closing(self._connect()) as conn:
            folders_by_id = self._folders_by_id(conn)
            albums = []
            for row in conn.execute(self._albums_query()):
                name = row["name"]
                path = self._album_path(name, row["parent_folder"], folders_by_id)
                albums.append(
                    PhotoAlbumSummary(
                        id=str(row["album_pk"]),
                        uuid=row["uuid"],
                        name=name,
                        path=path,
                        asset_count=row["asset_count"],
                        photo_count=row["photo_count"],
                        video_count=row["video_count"],
                    )
                )

            return albums

    def get_album_assets(self, album_uuid: str) -> list[PhotoAsset]:
        """Return visible, non-trashed assets for a Photos album UUID."""
        logger.info("Reading album assets from local Photos database: %s", album_uuid)

        with closing(self._connect()) as conn:
            assets = []
            for row in conn.execute(self._album_assets_query(), {"album_uuid": album_uuid}):
                asset = self._row_to_asset(row, asset_class=PhotoAsset)
                if asset is not None:
                    assets.append(asset)

            return assets

    def close(self) -> None:
        """Compatibility no-op for sync orchestration."""

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only SQLite connection."""
        if not self.photos_sqlite_path.exists():
            raise FileNotFoundError(f"Photos SQLite database not found: {self.photos_sqlite_path}")

        conn = sqlite3.connect(f"file:{self.photos_sqlite_path}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _row_to_asset(self, row: sqlite3.Row, asset_class: type[PhotoAsset]) -> PhotoAsset | None:
        """Convert one SQLite result row into Photos asset metadata."""
        filename = row["original_filename"] or row["additional_original_filename"]
        if not filename:
            logger.debug("Skipping asset with no original filename: %s", row["uuid"])
            return None

        width = row["width"] or row["original_width"]
        height = row["height"] or row["original_height"]

        return asset_class(
            id=row["uuid"] or str(row["asset_pk"]),
            filename=filename,
            asset_date=self._photos_datetime(row["date_created"]),
            added_date=self._photos_datetime(row["added_date"]),
            dimensions=(width, height) if width and height else None,
            size=row["original_file_size"],
            library=str(row["library_scope"]) if row["library_scope"] is not None else "local",
            latitude=self._valid_coordinate(row["latitude"]),
            longitude=self._valid_coordinate(row["longitude"]),
            make=row["camera_make"],
            model=row["camera_model"],
            lens_model=row["lens_model"],
            cloud_master_guid=row["cloud_master_guid"],
            uti=row["uti"],
        )

    def _photos_datetime(self, value: float | None) -> datetime | None:
        """Convert Photos' 2001-based timestamp to UTC datetime."""
        if value is None:
            return None

        # Photos uses the Unix epoch as a sentinel for some imported/scanned
        # assets with unknown creation dates.
        if value <= -APPLE_EPOCH.timestamp():
            return None

        return datetime.fromtimestamp(APPLE_EPOCH.timestamp() + value, tz=timezone.utc)

    def _valid_coordinate(self, value: float | None) -> float | None:
        """Normalize Photos' sentinel missing coordinate values."""
        if value is None or value <= -180:
            return None

        return value

    def _folders_by_id(self, conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
        """Return Photos folder rows keyed by primary key."""
        return {
            row["folder_pk"]: row
            for row in conn.execute(
                """
                select
                    Z_PK as folder_pk,
                    ZTITLE as name,
                    ZPARENTFOLDER as parent_folder
                from ZGENERICALBUM
                where Z_ENT = 41
                  and coalesce(ZTRASHEDSTATE, 0) = 0
                """
            )
        }

    def _album_path(self, album_name: str, parent_folder: int | None, folders_by_id: dict[int, sqlite3.Row]) -> str:
        """Build a slash-delimited Photos folder path for an album."""
        path_parts = [album_name]
        current_folder = parent_folder
        seen_folders = set()

        while current_folder and current_folder in folders_by_id and current_folder not in seen_folders:
            seen_folders.add(current_folder)
            folder = folders_by_id[current_folder]
            folder_name = folder["name"]
            if folder_name:
                path_parts.append(folder_name)
            current_folder = folder["parent_folder"]

        return "/".join(reversed(path_parts))

    def _favorites_query(self) -> str:
        """Return SQL that extracts favorite assets and matching metadata."""
        return """
            select
                a.Z_PK as asset_pk,
                a.ZUUID as uuid,
                a.ZDATECREATED as date_created,
                a.ZADDEDDATE as added_date,
                a.ZWIDTH as width,
                a.ZHEIGHT as height,
                a.ZLATITUDE as latitude,
                a.ZLONGITUDE as longitude,
                a.ZLIBRARYSCOPE as library_scope,
                cm.ZORIGINALFILENAME as original_filename,
                cm.ZCLOUDMASTERGUID as cloud_master_guid,
                cm.ZUNIFORMTYPEIDENTIFIER as uti,
                aaa.ZORIGINALFILENAME as additional_original_filename,
                aaa.ZORIGINALFILESIZE as original_file_size,
                aaa.ZORIGINALWIDTH as original_width,
                aaa.ZORIGINALHEIGHT as original_height,
                ea.ZCAMERAMAKE as camera_make,
                ea.ZCAMERAMODEL as camera_model,
                ea.ZLENSMODEL as lens_model
            from ZASSET a
            left join ZCLOUDMASTER cm on cm.Z_PK = a.ZMASTER
            left join ZADDITIONALASSETATTRIBUTES aaa on aaa.ZASSET = a.Z_PK
            left join ZEXTENDEDATTRIBUTES ea on ea.ZASSET = a.Z_PK
            where a.ZFAVORITE = 1
              and coalesce(a.ZTRASHEDSTATE, 0) = 0
              and coalesce(a.ZHIDDEN, 0) = 0
        """

    def _albums_query(self) -> str:
        """Return SQL that extracts non-empty user albums."""
        return """
            select
                ga.Z_PK as album_pk,
                ga.ZUUID as uuid,
                ga.ZTITLE as name,
                ga.ZPARENTFOLDER as parent_folder,
                count(a.Z_PK) as asset_count,
                sum(case when coalesce(a.ZKIND, 0) = 1 then 1 else 0 end) as photo_count,
                sum(case when coalesce(a.ZKIND, 0) = 2 then 1 else 0 end) as video_count
            from ZGENERICALBUM ga
            join Z_33ASSETS album_assets on album_assets.Z_33ALBUMS = ga.Z_PK
            join ZASSET a on a.Z_PK = album_assets.Z_3ASSETS
            where ga.Z_ENT = 33
              and ga.ZTITLE is not null
              and coalesce(ga.ZTRASHEDSTATE, 0) = 0
              and coalesce(a.ZTRASHEDSTATE, 0) = 0
              and coalesce(a.ZHIDDEN, 0) = 0
            group by ga.Z_PK
            having asset_count > 0
            order by lower(name), ga.ZPARENTFOLDER
        """

    def _album_assets_query(self) -> str:
        """Return SQL that extracts assets for one Photos album UUID."""
        return """
            select
                a.Z_PK as asset_pk,
                a.ZUUID as uuid,
                a.ZDATECREATED as date_created,
                a.ZADDEDDATE as added_date,
                a.ZWIDTH as width,
                a.ZHEIGHT as height,
                a.ZLATITUDE as latitude,
                a.ZLONGITUDE as longitude,
                a.ZLIBRARYSCOPE as library_scope,
                cm.ZORIGINALFILENAME as original_filename,
                cm.ZCLOUDMASTERGUID as cloud_master_guid,
                cm.ZUNIFORMTYPEIDENTIFIER as uti,
                aaa.ZORIGINALFILENAME as additional_original_filename,
                aaa.ZORIGINALFILESIZE as original_file_size,
                aaa.ZORIGINALWIDTH as original_width,
                aaa.ZORIGINALHEIGHT as original_height,
                ea.ZCAMERAMAKE as camera_make,
                ea.ZCAMERAMODEL as camera_model,
                ea.ZLENSMODEL as lens_model
            from ZGENERICALBUM ga
            join Z_33ASSETS album_assets on album_assets.Z_33ALBUMS = ga.Z_PK
            join ZASSET a on a.Z_PK = album_assets.Z_3ASSETS
            left join ZCLOUDMASTER cm on cm.Z_PK = a.ZMASTER
            left join ZADDITIONALASSETATTRIBUTES aaa on aaa.ZASSET = a.Z_PK
            left join ZEXTENDEDATTRIBUTES ea on ea.ZASSET = a.Z_PK
            where ga.ZUUID = :album_uuid
              and coalesce(ga.ZTRASHEDSTATE, 0) = 0
              and coalesce(a.ZTRASHEDSTATE, 0) = 0
              and coalesce(a.ZHIDDEN, 0) = 0
        """
