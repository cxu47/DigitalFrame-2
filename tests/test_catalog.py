"""Ordering, month buckets, and playback names. No files and no network."""

from digitalframe.catalog import (
    PhotoRecord, build_catalog, filter_photos, photo_month, sort_photos)


def _photo(object_id, album, path, modified, month):
    return PhotoRecord(object_id, album, path, modified, month)


def test_month_bucket_uses_utc():
    assert photo_month("2026-01-01T00:30:00+08:00") == "2025-12"
    assert photo_month("2026-09-12T00:00:00Z") == "2026-09"
    assert photo_month(None) is None
    assert photo_month("not-a-date") is None


def test_newest_first_breaks_ties_by_path_and_puts_missing_times_last():
    photos = [
        _photo("a", "kids", "kids/a.jpg", "2024-01-15T00:00:00Z", "2024-01"),
        _photo("b", "kids", "kids/b.jpg", "2025-06-01T00:00:00Z", "2025-06"),
        _photo("c", "holidays", "holidays/c.jpg", "2025-06-01T00:00:00Z", "2025-06"),
        _photo("d", "kids", "kids/d.jpg", None, None),
    ]

    assert [photo.id for photo in sort_photos(photos)] == ["c", "b", "a", "d"]


def test_month_filter_ignores_albums_and_empty_selection_is_empty():
    photos = sort_photos([
        _photo("b", "kids", "kids/b.jpg", "2025-06-01T00:00:00Z", "2025-06"),
        _photo("c", "holidays", "holidays/c.jpg", "2025-06-01T00:00:00Z", "2025-06"),
        _photo("a", "kids", "kids/a.jpg", "2024-01-15T00:00:00Z", "2024-01"),
    ])

    chosen = filter_photos(photos, folder="kids", months={"2025-06"})
    assert [photo.id for photo in chosen] == ["c", "b"]
    assert [photo.id for photo in filter_photos(photos, folder="kids")] == ["b", "a"]
    assert filter_photos(photos, months=set()) == []
    assert filter_photos([], folder="missing") == []


def test_heic_claims_the_jpeg_name_and_the_collision_gets_a_stable_suffix():
    catalog = build_catalog([{
        "id": "photos/kids/",
        "name": "kids",
        "createdTime": "2026-09-12T00:00:00Z",
        "modifiedTime": "2026-09-12T00:00:00Z",
        "photos": [
            {
                "id": "photos/kids/portrait.jpg",
                "name": "portrait.jpg",
                "size": 2,
                "modifiedTime": "2026-08-01T00:00:00Z",
                "etag": "jpeg",
            },
            {
                "id": "photos/kids/portrait.heic",
                "name": "portrait.heic",
                "size": 1,
                "modifiedTime": "2026-09-12T00:00:00Z",
                "etag": "heic",
            },
        ],
    }], "fit-test")

    heic = catalog["photos"]["photos/kids/portrait.heic"]
    jpeg = catalog["photos"]["photos/kids/portrait.jpg"]
    assert heic["path"] == "kids/portrait.jpg"
    assert heic["converted"] is True
    assert heic["month"] == "2026-09"
    assert jpeg["path"] != "kids/portrait.jpg"
    assert jpeg["path"].startswith("kids/portrait (")
    assert jpeg["path"].endswith(".jpg")
    assert jpeg["converted"] is False
    assert catalog["albums"]["kids"]["modified"] == "2026-09-12T00:00:00Z"
