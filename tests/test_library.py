"""Catalog listing without a disk cache."""

import threading

from digitalframe.library import Library


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
