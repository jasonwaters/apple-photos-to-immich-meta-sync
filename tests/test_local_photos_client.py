"""Tests for local macOS Photos SQLite reader."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from immich_favorite_sync.local_photos_client import LocalPhotosLibraryClient


def test_local_photos_client_reads_favorites(tmp_path: Path):
    """Test extracting favorite metadata from a Photos.sqlite-shaped database."""
    database_path = tmp_path / "Photos.sqlite"
    _create_photos_database(database_path)

    client = LocalPhotosLibraryClient(database_path)
    favorites = list(client.get_favorites())

    assert len(favorites) == 1
    favorite = favorites[0]
    assert favorite.id == "asset-uuid"
    assert favorite.filename == "IMG_5743.HEIC"
    assert favorite.asset_date == datetime(2023, 6, 28, 22, 22, 3, tzinfo=timezone.utc)
    assert favorite.dimensions == (4032, 3024)
    assert favorite.size == 1823773
    assert favorite.latitude == 21.660238333333332
    assert favorite.longitude == -157.95877
    assert favorite.make == "Apple"
    assert favorite.model == "iPhone 14 Pro"
    assert favorite.cloud_master_guid == "cloud-master-guid"


def test_local_photos_client_ignores_unknown_creation_date(tmp_path: Path):
    """Test Photos' Unix epoch sentinel does not become a real match date."""
    database_path = tmp_path / "Photos.sqlite"
    _create_photos_database(database_path, date_created=-978307200)

    favorite = next(LocalPhotosLibraryClient(database_path).get_favorites())

    assert favorite.asset_date is None


def test_local_photos_client_falls_back_to_additional_original_filename(tmp_path: Path):
    """Test local reader uses additional attributes when Cloud Master lacks filename."""
    database_path = tmp_path / "Photos.sqlite"
    _create_photos_database(database_path, cloud_master_filename=None, additional_filename="fallback.JPG")

    favorite = next(LocalPhotosLibraryClient(database_path).get_favorites())

    assert favorite.filename == "fallback.JPG"


def test_local_photos_client_skips_hidden_and_trashed_favorites(tmp_path: Path):
    """Test hidden and trashed favorites are excluded."""
    database_path = tmp_path / "Photos.sqlite"
    _create_photos_database(database_path, trashed_state=1)

    favorites = list(LocalPhotosLibraryClient(database_path).get_favorites())

    assert favorites == []


def _create_photos_database(
    database_path: Path,
    date_created: int = 709683723,
    cloud_master_filename: str | None = "IMG_5743.HEIC",
    additional_filename: str | None = None,
    trashed_state: int = 0,
    hidden: int = 0,
) -> None:
    """Create the subset of Photos tables used by the local reader."""
    conn = sqlite3.connect(database_path)
    try:
        conn.executescript(
            """
            create table ZASSET (
                Z_PK integer primary key,
                ZMASTER integer,
                ZADDITIONALATTRIBUTES integer,
                ZEXTENDEDATTRIBUTES integer,
                ZUUID text,
                ZFAVORITE integer,
                ZTRASHEDSTATE integer,
                ZHIDDEN integer,
                ZDATECREATED real,
                ZADDEDDATE real,
                ZWIDTH integer,
                ZHEIGHT integer,
                ZLATITUDE real,
                ZLONGITUDE real,
                ZLIBRARYSCOPE integer
            );

            create table ZCLOUDMASTER (
                Z_PK integer primary key,
                ZORIGINALFILENAME text,
                ZCLOUDMASTERGUID text,
                ZUNIFORMTYPEIDENTIFIER text
            );

            create table ZADDITIONALASSETATTRIBUTES (
                ZASSET integer,
                ZORIGINALFILENAME text,
                ZORIGINALFILESIZE integer,
                ZORIGINALWIDTH integer,
                ZORIGINALHEIGHT integer
            );

            create table ZEXTENDEDATTRIBUTES (
                ZASSET integer,
                ZCAMERAMAKE text,
                ZCAMERAMODEL text,
                ZLENSMODEL text
            );
            """
        )
        conn.execute(
            """
            insert into ZASSET values (
                1, 1, 1, 1, 'asset-uuid', 1, ?, ?, ?, 709769523.849945,
                4032, 3024, 21.660238333333332, -157.95877, 1
            )
            """,
            (trashed_state, hidden, date_created),
        )
        conn.execute(
            "insert into ZCLOUDMASTER values (1, ?, 'cloud-master-guid', 'public.heic')",
            (cloud_master_filename,),
        )
        conn.execute(
            "insert into ZADDITIONALASSETATTRIBUTES values (1, ?, 1823773, 4032, 3024)",
            (additional_filename,),
        )
        conn.execute(
            "insert into ZEXTENDEDATTRIBUTES values (1, 'Apple', 'iPhone 14 Pro', 'iPhone lens')"
        )
        conn.commit()
    finally:
        conn.close()
