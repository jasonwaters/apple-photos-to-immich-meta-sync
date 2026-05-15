"""Configuration management for immich-favorite-sync."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Photos Library Configuration
    photos_sqlite_path: Path = Field(
        default=Path("/photos-library/Photos.sqlite"),
        description="Path to local Photos.sqlite database",
    )

    # Immich Configuration
    immich_url: str = Field(
        ...,
        description="Immich server URL",
    )
    immich_api_key: str = Field(
        ...,
        description="Immich API key",
    )

    # Sync Configuration
    dry_run: bool = Field(
        default=True,
        description="Dry run mode - only report what would be done",
    )
    batch_size: int = Field(
        default=50,
        description="Batch size for Immich API updates",
        ge=1,
        le=1000,
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Log level (DEBUG, INFO, WARNING, ERROR)",
    )

    def validate_paths(self) -> None:
        """Validate that required paths exist."""
        if not self.photos_sqlite_path.exists():
            raise ValueError(f"Photos SQLite database not found: {self.photos_sqlite_path}")

    @property
    def immich_base_url(self) -> str:
        """Get Immich base URL without trailing slash."""
        return self.immich_url.rstrip("/")
