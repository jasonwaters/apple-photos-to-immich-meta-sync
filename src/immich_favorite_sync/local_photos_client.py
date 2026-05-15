"""Read favorite metadata from the local macOS Photos library database."""

import logging
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .models import FavoritePhoto

logger = logging.getLogger(__name__)

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


class LocalPhotosLibraryClient:
    """Read favorites from a local Photos.sqlite database."""

    def __init__(self, photos_sqlite_path: Path):
        """Initialize the local Photos library reader."""
        self.photos_sqlite_path = photos_sqlite_path

    def get_favorites(self) -> Iterator[FavoritePhoto]:
        """Yield favorite photos from the local Photos SQLite database."""
        if not self.photos_sqlite_path.exists():
            raise FileNotFoundError(f"Photos SQLite database not found: {self.photos_sqlite_path}")

        logger.info("Reading favorites from local Photos database: %s", self.photos_sqlite_path)

        conn = sqlite3.connect(f"file:{self.photos_sqlite_path}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")

        try:
            for row in conn.execute(self._favorites_query()):
                favorite = self._row_to_favorite(row)
                if favorite is not None:
                    yield favorite
        finally:
            conn.close()

    def close(self) -> None:
        """Compatibility no-op for sync orchestration."""

    def _row_to_favorite(self, row: sqlite3.Row) -> FavoritePhoto | None:
        """Convert one SQLite result row into FavoritePhoto metadata."""
        filename = row["original_filename"] or row["additional_original_filename"]
        if not filename:
            logger.debug("Skipping favorite with no original filename: %s", row["uuid"])
            return None

        width = row["width"] or row["original_width"]
        height = row["height"] or row["original_height"]

        return FavoritePhoto(
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
