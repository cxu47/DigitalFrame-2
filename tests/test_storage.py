"""OSS prefix confinement. The client is a fake; nothing is sent to the network."""

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from digitalframe.config import load_oss_config, load_settings
from digitalframe.storage import download_photo, list_albums, normalize_prefix, open_storage
from tests.fakes import (
    fake_client, make_settings, oss_object, oss_page, oss_prefix, storage_for, write_oss_env)


@pytest.mark.parametrize("value", ["", "/photos", "photos/../secret", "..", "a/../../b", "photos\\kids"])
def test_prefix_rejects_empty_absolute_and_parent_segments(value):
    with pytest.raises(ValueError, match="OSS_PREFIX"):
        normalize_prefix(value)


def test_prefix_accepts_a_bucket_folder():
    assert normalize_prefix("photos") == "photos/"
    assert normalize_prefix("photos/") == "photos/"


def test_environment_oss_settings_are_used_instead_of_the_secrets_file(tmp_path, monkeypatch):
    write_oss_env(tmp_path, endpoint="https://from-file.example.invalid")
    (tmp_path / "secrets" / "oss.env").write_text(
        "OSS_ACCESS_KEY_ID=file-id\n"
        "OSS_ACCESS_KEY_SECRET=file-secret\n"
        "OSS_BUCKET_NAME=file-bucket\n"
        "OSS_REGION=cn-hangzhou\n"
        "OSS_ENDPOINT=https://from-file.example.invalid\n"
        "OSS_PREFIX=photos/\n",
        encoding="utf-8",
    )
    for name, value in {
        "OSS_ACCESS_KEY_ID": "env-id",
        "OSS_ACCESS_KEY_SECRET": "env-secret",
        "OSS_BUCKET_NAME": "env-bucket",
        "OSS_REGION": "cn-hongkong",
        "OSS_ENDPOINT": "https://oss-cn-hongkong-internal.aliyuncs.com",
        "OSS_PREFIX": "photos",
    }.items():
        monkeypatch.setenv(name, value)
    config = load_oss_config(make_settings(tmp_path))
    assert config.access_key_id == "env-id"
    assert config.access_key_secret == "env-secret"
    assert config.bucket == "env-bucket"
    assert config.region == "cn-hongkong"
    assert config.endpoint == "https://oss-cn-hongkong-internal.aliyuncs.com"
    assert config.prefix == "photos/"


def test_http_endpoint_is_rejected(tmp_path, monkeypatch):
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    write_oss_env(tmp_path, endpoint="http://oss.example.invalid")
    settings = make_settings(tmp_path)

    with pytest.raises(ValueError, match="https://"):
        load_oss_config(settings)


def test_missing_secret_does_not_echo_the_other_values_or_export_them(tmp_path, monkeypatch):
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    write_oss_env(tmp_path, secret="")
    settings = make_settings(tmp_path)
    before = os.environ.get("OSS_ACCESS_KEY_ID")

    with pytest.raises(ValueError, match="OSS_ACCESS_KEY_SECRET") as error:
        load_oss_config(settings)

    assert "local-id" not in str(error.value)
    assert os.environ.get("OSS_ACCESS_KEY_ID") == before


def test_open_storage_reads_the_secret_file_without_exporting_it(tmp_path, monkeypatch):
    write_oss_env(tmp_path, endpoint="https://oss.example.invalid")
    (tmp_path / ".env").write_text("NETWORK_TIMEOUT=2.5\n", encoding="utf-8")
    for name in ("NETWORK_TIMEOUT", "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(tmp_path)
    captured = {}

    def fake_client(sdk_config):
        captured["config"] = sdk_config
        return Mock()

    monkeypatch.setattr("digitalframe.storage.oss.config.load_default", lambda: SimpleNamespace())
    monkeypatch.setattr("digitalframe.storage.oss.Client", fake_client)

    config = load_oss_config(settings)
    storage = open_storage(config, settings.network_timeout)

    credentials = captured["config"].credentials_provider.get_credentials()
    assert credentials.access_key_id == "local-id"
    assert credentials.access_key_secret == "local-secret"
    assert captured["config"].region == "cn-hongkong"
    assert captured["config"].endpoint == "https://oss.example.invalid"
    assert captured["config"].connect_timeout == 2.5
    assert storage.bucket == "local-bucket"
    assert storage.prefix == "photos/"
    assert os.environ.get("OSS_ACCESS_KEY_SECRET") is None


def test_listing_keeps_an_empty_album_and_drops_loose_and_nested_keys():
    pages = {
        "photos/": [
            oss_page(contents=[oss_object("photos/loose.jpg", size=4)], prefixes=[
                oss_prefix("photos/kids/"),
            ]),
            oss_page(prefixes=[oss_prefix("photos/empty/"), oss_prefix("photos/summer/")]),
        ],
        "photos/empty/": [oss_page(contents=[oss_object("photos/empty/", size=0)])],
        "photos/kids/": [oss_page(contents=[
            oss_object("photos/kids/"),
            oss_object("photos/kids/one.jpg", size=3, etag='"one-etag"'),
            oss_object("photos/kids/readme.txt", size=3),
            oss_object("photos/kids/nested/deep.jpg", size=3),
        ], prefixes=[oss_prefix("photos/kids/nested/")])],
        "photos/summer/": [oss_page(contents=[
            oss_object("photos/summer/two.HEIC", size=8),
        ])],
    }
    client = fake_client(pages, {})
    albums = list_albums(storage_for(client))

    assert [album["name"] for album in albums] == ["empty", "kids", "summer"]
    assert albums[0]["photos"] == []
    assert albums[0]["modifiedTime"] == "2026-09-12T00:00:00Z"
    names = {album["name"]: [photo["name"] for photo in album["photos"]] for album in albums}
    assert names["kids"] == ["one.jpg"]
    assert names["summer"] == ["two.HEIC"]
    assert albums[1]["photos"][0]["etag"] == "one-etag"
    assert "photos/loose.jpg" not in {photo["id"] for album in albums for photo in album["photos"]}


def test_listing_rejects_an_album_outside_the_prefix():
    pages = {"photos/": [oss_page(prefixes=[oss_prefix("private/")])]}
    with pytest.raises(RuntimeError, match="outside"):
        list_albums(storage_for(fake_client(pages, {})))


def test_download_rejects_keys_outside_a_direct_album(tmp_path):
    payload = b"abcdef"
    client = fake_client(
        {},
        {"photos/kids/photo.jpg": payload},
    )
    storage = storage_for(client)
    destination = tmp_path / "photo.jpg.part"

    download_photo(storage, "photos/kids/photo.jpg", destination)

    assert destination.read_bytes() == payload
    request = client.get_object.call_args.args[0]
    assert request.bucket == "local-bucket"
    assert request.key == "photos/kids/photo.jpg"

    for key in ("private/photo.jpg", "photos/loose.jpg", "photos/kids/nested/photo.jpg"):
        with pytest.raises(ValueError):
            download_photo(storage, key, destination)
    assert client.get_object.call_count == 1


def test_download_rejects_a_crc_mismatch_and_removes_the_partial_file(tmp_path):
    destination = tmp_path / "photo.part"
    destination.write_bytes(b"stale")
    client = Mock()
    body = Mock()
    body.__enter__ = Mock(return_value=body)
    body.__exit__ = Mock(return_value=None)
    body.iter_bytes.return_value = iter([b"damaged"])
    client.get_object.return_value = SimpleNamespace(body=body, hash_crc64="1")

    with pytest.raises(Exception):
        download_photo(storage_for(client), "photos/kids/photo.jpg", destination)

    assert not destination.exists()
