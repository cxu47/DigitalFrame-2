"""One sync pass against a fake bucket."""

import fcntl
import json

from PIL import Image
from typer.testing import CliRunner

from digitalframe.catalog import build_catalog
from digitalframe.cli import app
from digitalframe.sync import MANIFEST_NAME, sync_once
from tests.fakes import (
    fake_client, heic_bytes, jpeg_bytes, make_settings, oss_object, oss_page,
    oss_prefix, storage_for,
)


def _pages_for(objects_by_album):
    prefixes = [oss_prefix(f"photos/{album}/") for album in objects_by_album]
    pages = {"photos/": [oss_page(prefixes=prefixes)]}
    for album, objects in objects_by_album.items():
        pages[f"photos/{album}/"] = [oss_page(contents=[
            oss_object(f"photos/{album}/"), *objects,
        ])]
    return pages


def test_sync_publishes_heic_as_the_jpeg_and_gives_the_collision_a_suffix(tmp_path):
    settings = make_settings(tmp_path)
    heic = heic_bytes()
    original = jpeg_bytes(40, 30, color=(200, 10, 10))
    objects = [
        oss_object("photos/kids/portrait.heic", size=len(heic), etag='"heic"'),
        oss_object("photos/kids/portrait.jpg", size=len(original), etag='"jpeg"'),
    ]
    client = fake_client(
        _pages_for({"kids": objects}),
        {
            "photos/kids/portrait.heic": heic,
            "photos/kids/portrait.jpg": original,
        },
    )

    result = sync_once(settings.cache_dir, storage_for(client), settings)

    assert result.success
    assert result.downloaded == 2
    published = settings.cache_dir / "kids" / "portrait.jpg"
    with Image.open(published) as image:
        assert image.format == "JPEG"
        assert image.size == (8, 6)
    catalog = build_catalog([{
        "id": "photos/kids/",
        "name": "kids",
        "photos": [
            {"id": "photos/kids/portrait.heic", "name": "portrait.heic",
             "size": len(heic), "modifiedTime": "2026-09-12T00:00:00Z", "etag": "heic"},
            {"id": "photos/kids/portrait.jpg", "name": "portrait.jpg",
             "size": len(original), "modifiedTime": "2026-09-12T00:00:00Z", "etag": "jpeg"},
        ],
    }], settings.processing_profile())
    collision = settings.cache_dir / catalog["photos"]["photos/kids/portrait.jpg"]["path"]
    assert collision.name != "portrait.jpg"
    assert collision.read_bytes() == original


def test_second_sync_removes_a_deleted_photo_and_does_not_download_the_kept_one(tmp_path):
    settings = make_settings(tmp_path)
    keep = jpeg_bytes(30, 20, color=(1, 1, 1))
    gone = jpeg_bytes(30, 20, color=(2, 2, 2))
    first = fake_client(
        _pages_for({
            "kids": [oss_object("photos/kids/keep.jpg", size=len(keep), etag='"keep"')],
            "holidays": [oss_object("photos/holidays/gone.jpg", size=len(gone), etag='"gone"')],
        }),
        {
            "photos/kids/keep.jpg": keep,
            "photos/holidays/gone.jpg": gone,
        },
    )
    assert sync_once(settings.cache_dir, storage_for(first), settings).success
    assert (settings.cache_dir / "holidays" / "gone.jpg").read_bytes() == gone

    second = fake_client(
        _pages_for({
            "kids": [oss_object("photos/kids/keep.jpg", size=len(keep), etag='"keep"')],
        }),
        {"photos/kids/keep.jpg": keep},
    )
    result = sync_once(settings.cache_dir, storage_for(second), settings)

    assert result.success
    assert result.downloaded == 0
    assert second.get_object.call_count == 0
    assert (settings.cache_dir / "kids" / "keep.jpg").read_bytes() == keep
    assert not (settings.cache_dir / "holidays").exists()
    manifest = json.loads((settings.cache_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert list(manifest["photos"]) == ["photos/kids/keep.jpg"]
    assert manifest["photos"]["photos/kids/keep.jpg"]["month"] == "2026-09"


def test_failed_download_leaves_the_previous_file_and_manifest(tmp_path):
    settings = make_settings(tmp_path)
    original = jpeg_bytes(24, 16)
    client = fake_client(
        _pages_for({
            "kids": [oss_object("photos/kids/keep.jpg", size=len(original), etag='"keep"')],
        }),
        {"photos/kids/keep.jpg": original},
    )
    assert sync_once(settings.cache_dir, storage_for(client), settings).success
    manifest_before = (settings.cache_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    broken = fake_client(
        _pages_for({
            "kids": [oss_object("photos/kids/keep.jpg", size=len(original), etag='"changed"')],
        }),
        {},
    )
    broken.get_object.side_effect = RuntimeError("offline")

    result = sync_once(settings.cache_dir, storage_for(broken), settings)

    assert not result.success
    assert (settings.cache_dir / "kids" / "keep.jpg").read_bytes() == original
    assert (settings.cache_dir / MANIFEST_NAME).read_text(encoding="utf-8") == manifest_before


def test_listing_failure_does_not_change_the_cache(tmp_path):
    settings = make_settings(tmp_path)
    photo = settings.cache_dir / "kids" / "keep.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"original")
    manifest = settings.cache_dir / MANIFEST_NAME
    manifest.write_text("{}\n", encoding="utf-8")
    client = fake_client({}, {})
    client.list_objects_v2_paginator.side_effect = RuntimeError("offline")

    result = sync_once(settings.cache_dir, storage_for(client), settings)

    assert not result.success
    assert photo.read_bytes() == b"original"
    assert manifest.read_text(encoding="utf-8") == "{}\n"


def test_a_second_sync_process_exits_nonzero(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    settings.cache_dir.mkdir()
    held = (settings.cache_dir / ".sync.lock").open("a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr("digitalframe.cli.load_settings", lambda: settings)
    monkeypatch.setattr("digitalframe.cli.load_oss_config", lambda _settings: object())
    monkeypatch.setattr("digitalframe.cli.open_storage", lambda *_args: object())

    result = CliRunner().invoke(app, ["sync"])

    assert result.exit_code == 1
    assert "already using this cache" in result.output
    held.close()
