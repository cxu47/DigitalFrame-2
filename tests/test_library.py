"""Catalog listing without a disk cache."""

from io import BytesIO
import threading

from PIL import Image

from digitalframe.auth import Session
from digitalframe.library import Library
from tests.fakes import heic_bytes, jpeg_bytes


KEY = b"k" * 32


def _albums():
    return [{
        "id": "photos/kids/",
        "name": "kids",
        "photos": [{
            "id": "photos/kids/keep.jpg",
            "name": "keep.jpg",
            "size": 3,
            "modifiedTime": "2026-09-12T00:00:00Z",
            "etag": "keep",
        }],
    }]


def test_a_fresh_catalog_is_not_listed_again():
    calls = []

    def listing(_storage):
        calls.append(1)
        return _albums()

    library = Library(object(), interval=10, clock=lambda: 0, lister=listing)
    library.ensure()
    library.ensure()
    assert calls == [1]


def test_a_stale_catalog_is_listed_again():
    now = {"value": 0}
    calls = []

    def listing(_storage):
        calls.append(now["value"])
        return _albums()

    library = Library(object(), interval=10, clock=lambda: now["value"], lister=listing)
    library.ensure()
    now["value"] = 11
    library.ensure()
    assert calls == [0, 11]


def test_an_overlapping_list_waits_instead_of_starting_another():
    calls = []
    release = threading.Event()
    started = threading.Event()

    def listing(_storage):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(2)
        return _albums()

    library = Library(object(), interval=10, clock=lambda: 0, lister=listing)
    first = threading.Thread(target=library.ensure)
    first.start()
    assert started.wait(2)
    second = threading.Thread(target=library.ensure)
    second.start()
    release.set()
    first.join(2)
    second.join(2)
    assert calls == [1]


def _photo(album, name, modified):
    return {
        "id": f"photos/{album}/{name}",
        "name": name,
        "size": 3,
        "modifiedTime": modified,
        "etag": name,
    }


def _album(name, photos):
    return {"id": f"photos/{name}/", "name": name, "photos": photos}


def _library(albums, reader, **kwargs):
    return Library(
        object(), interval=3600, clock=lambda: 0, lister=lambda _storage: albums,
        reader=reader, **kwargs)


def test_the_current_queue_is_read_concurrently_and_then_from_memory():
    current = 0
    peak = 0
    calls = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def reader(_storage, key):
        nonlocal current, peak
        with lock:
            calls.append(key)
            current += 1
            peak = max(peak, current)
        try:
            barrier.wait(2)
        finally:
            with lock:
                current -= 1
        return b"pic"

    photos = [
        _photo("kids", "a.jpg", "2026-09-03T00:00:00Z"),
        _photo("kids", "b.jpg", "2026-09-02T00:00:00Z"),
        _photo("kids", "c.jpg", "2026-09-01T00:00:00Z"),
    ]
    library = _library([_album("kids", photos)], reader, queue_limit=8, queue_workers=3)
    session = Session("ada", 10**12, "folder", "kids", (), 5)
    catalog = library.catalog(session, KEY)
    library._queue.wait()
    assert peak == 3
    assert len(calls) == 3
    library.catalog(session, KEY)
    library._queue.wait()
    assert len(calls) == 3
    played = library.media(catalog["photos"][0]["id"], KEY, session)
    assert played == (b"pic", "image/jpeg")
    assert len(calls) == 3


def test_a_new_folder_or_month_drops_a_read_from_the_previous_queue():
    release = threading.Event()
    started = threading.Event()
    calls = []

    def reader(_storage, key):
        calls.append(key)
        if key.endswith("slow.jpg"):
            started.set()
            assert release.wait(2)
        return b"pic"

    albums = [
        _album("kids", [_photo("kids", "slow.jpg", "2026-09-12T00:00:00Z")]),
        _album("holidays", [_photo("holidays", "trip.jpg", "2024-01-02T00:00:00Z")]),
    ]
    library = _library(albums, reader, queue_workers=2)
    kids = Session("ada", 10**12, "folder", "kids", (), 5)
    listed = library.catalog(kids, KEY)
    slow_id = listed["photos"][0]["id"]
    assert started.wait(2)
    holidays = Session("ada", 10**12, "folder", "holidays", (), 5)
    switched = library.catalog(holidays, KEY)
    release.set()
    library._queue.wait()
    assert calls.count("photos/kids/slow.jpg") == 1
    library.media(slow_id, KEY, holidays)
    assert calls.count("photos/kids/slow.jpg") == 2
    trip_id = switched["photos"][0]["id"]
    before = calls.count("photos/holidays/trip.jpg")
    assert library.media(trip_id, KEY, holidays)[0] == b"pic"
    assert calls.count("photos/holidays/trip.jpg") == before
    months = Session("ada", 10**12, "months", None, ("2026-09",), 5)
    library.catalog(months, KEY)
    library._queue.wait()
    assert calls.count("photos/kids/slow.jpg") == 3
    library.media(trip_id, KEY, months)
    assert calls.count("photos/holidays/trip.jpg") == before + 1


def test_the_queue_stops_at_the_newest_photos():
    calls = []

    def reader(_storage, key):
        calls.append(key)
        return b"pic"

    photos = [
        _photo("kids", f"{day}.jpg", f"2026-09-{day:02d}T00:00:00Z") for day in range(1, 5)
    ]
    library = _library([_album("kids", photos)], reader, queue_limit=2, queue_workers=2)
    session = Session("ada", 10**12, "folder", None, (), 5)
    library.catalog(session, KEY)
    library._queue.wait()
    assert sorted(calls) == ["photos/kids/3.jpg", "photos/kids/4.jpg"]


def test_descale_shrinks_a_cached_photo_and_leaves_the_original_in_memory():
    payload = jpeg_bytes(2000, 1000)
    calls = []

    def reader(_storage, key):
        calls.append(key)
        return payload

    photos = [_photo("kids", "wide.jpg", "2026-09-03T00:00:00Z")]
    library = _library(
        [_album("kids", photos)], reader, max_width=1600, max_height=900, queue_workers=1)
    session = Session("ada", 10**12, "folder", "kids", (), 5)
    catalog = library.catalog(session, KEY)
    library._queue.wait()
    photo_id = catalog["photos"][0]["id"]
    assert library.media(photo_id, KEY, session)[0] == payload
    scaled = library.media(photo_id, KEY, session, descale=True)
    with Image.open(BytesIO(scaled[0])) as image:
        assert image.size == (1600, 800)
    assert library.media(photo_id, KEY, session)[0] == payload
    library.media(photo_id, KEY, session, descale=True)
    assert len(calls) == 1


def test_descale_shrinks_a_heic_photo_from_its_full_jpeg():
    payload = heic_bytes(80, 40)
    calls = []

    def reader(_storage, key):
        calls.append(key)
        return payload

    photos = [_photo("kids", "phone.heic", "2026-09-03T00:00:00Z")]
    library = _library(
        [_album("kids", photos)], reader, max_width=40, max_height=20,
        jpeg_quality=75, queue_workers=1)
    session = Session("ada", 10**12, "folder", "kids", (), 5)
    catalog = library.catalog(session, KEY)
    library._queue.wait()
    photo_id = catalog["photos"][0]["id"]
    full = library.media(photo_id, KEY, session)
    assert full[1] == "image/jpeg"
    with Image.open(BytesIO(full[0])) as image:
        assert image.size == (80, 40)
    scaled = library.media(photo_id, KEY, session, descale=True)
    with Image.open(BytesIO(scaled[0])) as image:
        assert image.format == "JPEG"
        assert image.size == (40, 20)
    assert len(calls) == 1
