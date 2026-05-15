"""Tests for CLI parsing helpers."""

import pytest

from immich_favorite_sync.__main__ import _duplicate_album_names, _parse_selection, build_parser
from immich_favorite_sync.models import PhotoAlbumSummary


def test_parse_selection_supports_ranges_and_dedupes_indexes():
    """Album selections should support comma-separated ranges."""
    selected_indexes = _parse_selection("1,3,3,5-7", max_index=10)

    assert selected_indexes == [1, 3, 5, 6, 7]


def test_parse_selection_rejects_out_of_range_indexes():
    """Invalid interactive selections should fail before syncing."""
    with pytest.raises(ValueError, match="out of range"):
        _parse_selection("1,4", max_index=3)


def test_duplicate_album_names_returns_repeated_leaf_names():
    """Album list notes should flag duplicate leaf names."""
    albums = [
        _album(name="Hawaii", path="Trips/Hawaii"),
        _album(name="Hawaii", path="Family/Hawaii"),
        _album(name="Instagram", path="Instagram"),
    ]

    duplicate_names = _duplicate_album_names(albums)

    assert duplicate_names == {"Hawaii"}


def test_albums_parser_exposes_supported_options_only():
    """The parser should expose the hardened album options."""
    parser = build_parser()

    args = parser.parse_args(["albums", "--interactive", "--no-save-config"])

    assert args.command == "albums"
    assert args.interactive is True
    assert args.no_save_config is True
    assert not hasattr(args, "immich_album_name_source")


def _album(name: str, path: str) -> PhotoAlbumSummary:
    return PhotoAlbumSummary(
        id="1",
        uuid=f"{path}-uuid",
        name=name,
        path=path,
        asset_count=1,
        photo_count=1,
        video_count=0,
    )
