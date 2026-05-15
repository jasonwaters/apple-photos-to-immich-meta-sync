"""Tests for configuration module."""

from pathlib import Path

import pytest

from immich_favorite_sync.config import Config


def test_config_defaults():
    """Test default configuration values."""
    config = Config(
        photos_sqlite_path=Path("/tmp/Photos.sqlite"),
        immich_url="http://localhost:2283",
        immich_api_key="test-key",
    )

    assert config.photos_sqlite_path == Path("/tmp/Photos.sqlite")
    assert config.dry_run is True
    assert config.batch_size == 50
    assert config.log_level == "INFO"


def test_config_immich_base_url():
    """Test Immich base URL normalization."""
    config = Config(
        photos_sqlite_path=Path("/tmp/Photos.sqlite"),
        immich_url="http://localhost:2283/",
        immich_api_key="test-key",
    )

    assert config.immich_base_url == "http://localhost:2283"


def test_config_validate_paths_accepts_existing_photos_database(tmp_path):
    """Test Photos database path validation succeeds for an existing file."""
    photos_sqlite_path = tmp_path / "Photos.sqlite"
    photos_sqlite_path.touch()
    config = Config(
        photos_sqlite_path=photos_sqlite_path,
        immich_url="http://localhost:2283",
        immich_api_key="test-key",
    )

    config.validate_paths()


def test_config_validate_paths_rejects_missing_photos_database(tmp_path):
    """Test Photos database path validation fails for a missing file."""
    config = Config(
        photos_sqlite_path=tmp_path / "missing.sqlite",
        immich_url="http://localhost:2283",
        immich_api_key="test-key",
    )

    with pytest.raises(ValueError, match="Photos SQLite database not found"):
        config.validate_paths()
