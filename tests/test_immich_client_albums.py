"""Tests for Immich album API helpers."""

import pytest

from immich_favorite_sync.immich_client import ImmichClient


def test_immich_client_finds_album_by_name():
    """Test exact album lookup from Immich album list."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(get_payload=[
        {"id": "album-1", "albumName": "Hawaii", "assetCount": 0, "assets": []},
    ])

    album = client.find_album_by_name("Hawaii")

    assert album.id == "album-1"


def test_immich_client_finds_album_by_id():
    """Test ID lookup from Immich album list."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(get_payload=[
        {"id": "album-1", "albumName": "Renamed in Immich", "assetCount": 0, "assets": []},
    ])

    album = client.find_album_by_id("album-1")

    assert album.album_name == "Renamed in Immich"


def test_immich_client_rejects_ambiguous_album_names():
    """Duplicate album names should fail closed instead of choosing arbitrarily."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(get_payload=[
        {"id": "album-1", "albumName": "Hawaii", "assetCount": 0, "assets": []},
        {"id": "album-2", "albumName": "Hawaii", "assetCount": 0, "assets": []},
    ])

    with pytest.raises(RuntimeError, match="Multiple Immich albums named"):
        client.find_album_by_name("Hawaii")


def test_immich_client_rejects_invalid_album_list_payload():
    """Unexpected album list shapes should fail explicitly."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(get_payload={"albums": []})

    with pytest.raises(RuntimeError, match="invalid album list"):
        client.get_albums()


def test_immich_client_creates_album():
    """Test album creation request shape."""
    http_client = FakeHttpClient(post_payload={
        "id": "album-1",
        "albumName": "Hawaii",
        "assetCount": 0,
        "assets": [],
    })
    client = ImmichClient("http://immich", "key")
    client._client = http_client

    album = client.create_album("Hawaii")

    assert album.album_name == "Hawaii"
    assert http_client.post_json == {"albumName": "Hawaii"}


def test_immich_client_treats_duplicate_album_add_as_present():
    """Duplicate add responses are idempotent for add-only sync."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(put_payload=[
        {"id": "asset-1", "success": True},
        {"id": "asset-2", "success": False, "error": "duplicate"},
    ])

    added_count = client.add_assets_to_album("album-1", ["asset-1", "asset-2"])

    assert added_count == 2


def test_immich_client_ignores_failed_album_add_results():
    """Only successful or duplicate add results count as present."""
    client = ImmichClient("http://immich", "key")
    client._client = FakeHttpClient(put_payload=[
        {"id": "asset-1", "success": True},
        {"id": "asset-2", "success": False, "error": "not_found"},
        "unexpected",
    ])

    added_count = client.add_assets_to_album("album-1", ["asset-1", "asset-2", "asset-3"])

    assert added_count == 1


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeHttpClient:
    def __init__(self, get_payload=None, post_payload=None, put_payload=None):
        self.get_payload = get_payload
        self.post_payload = post_payload
        self.put_payload = put_payload
        self.post_json = None

    def get(self, url):
        return FakeResponse(self.get_payload)

    def post(self, url, json):
        self.post_json = json
        return FakeResponse(self.post_payload)

    def put(self, url, json):
        return FakeResponse(self.put_payload)
