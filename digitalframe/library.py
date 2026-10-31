"""The photo list for one process. Pictures stay in OSS."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .auth import open_seal, seal
from .catalog import build_catalog, filter_photos, records_from_catalog, sort_photos
from .images import jpeg_from_heic
from .storage import list_albums, read_photo


logger = logging.getLogger(__name__)
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/jpeg",
    ".heif": "image/jpeg",
}
QUEUE_LIMIT = 32
QUEUE_WORKERS = 4


class PhotoQueue:
    """Compressed photos for one folder or month selection, read concurrently."""

    def __init__(self, limit, workers):
        self.limit = limit
        self._workers = workers
        self._pool = None
        self._lock = Lock()
        self._selection = None
        self._generation = 0
        self._kept = set()
        self._ready = {}
        self._futures = {}
        self._running = set()

    def prepare(self, selection, keys, read):
        """Keep `keys` for this selection. A different selection drops the previous queue."""
        wanted = list(dict.fromkeys(keys))[: self.limit]
        started = []
        with self._lock:
            if selection != self._selection:
                self._generation += 1
                self._selection = selection
                self._ready.clear()
                self._futures.clear()
            self._kept = set(wanted)
            for key in list(self._ready):
                if key not in self._kept:
                    del self._ready[key]
            for key in list(self._futures):
                if key not in self._kept:
                    del self._futures[key]
            generation = self._generation
            missing = [key for key in wanted if key not in self._ready and key not in self._futures]
            for key in missing:
                slot = []
                future = self._executor().submit(self._finish, generation, key, read, slot)
                slot.append(future)
                self._futures[key] = future
                self._running.add(future)
                started.append(future)
        for future in started:
            future.add_done_callback(self._finished)

    def get(self, key):
        """Return a queued photo, waiting for a read that is already running."""
        with self._lock:
            played = self._ready.get(key)
            future = None if played is not None else self._futures.get(key)
        if played is not None:
            return played
        if future is None:
            return None
        try:
            future.result()
        except Exception:
            logger.exception("Queued photo read failed")
            return None
        with self._lock:
            return self._ready.get(key)

    def wait(self, timeout=2):
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                pending = list(self._running)
            if not pending:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("photo queue did not finish")
            for future in pending:
                future.result(remaining)

    def _finished(self, future):
        with self._lock:
            self._running.discard(future)

    def _executor(self):
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="photo-queue")
        return self._pool

    def _finish(self, generation, key, read, slot):
        try:
            played = read(key)
        except Exception:
            logger.exception("Queued photo could not be read")
            played = None
        with self._lock:
            if slot and self._futures.get(key) is slot[0]:
                self._futures.pop(key, None)
            if generation != self._generation or played is None or key not in self._kept:
                return None
            self._ready[key] = played
            return played


class Library:
    """One shared catalog. Each browser receives sealed ids, not object keys."""

    def __init__(self, storage, *, interval, jpeg_quality=75, clock=None, lister=list_albums,
                 reader=read_photo, queue_limit=QUEUE_LIMIT, queue_workers=QUEUE_WORKERS):
        self.storage = storage
        self.interval = interval
        self.jpeg_quality = jpeg_quality
        self._clock = clock or time.monotonic
        self._lister = lister
        self._reader = reader
        self.sync_problem = False
        self._lock = Lock()
        self._records = []
        self._names = {}
        self._albums = {}
        self._listed = None
        self._queue = PhotoQueue(queue_limit, queue_workers)

    def ensure(self):
        """List when the catalog is missing or stale. Wait if a list is running."""
        with self._lock:
            if self.storage is None:
                self.sync_problem = True
                return
            if self._listed is not None and self._clock() - self._listed < self.interval:
                return
            try:
                albums = self._lister(self.storage)
            except Exception:
                logger.exception("Photo list failed")
                self.sync_problem = True
                return
            self._replace(albums)
            self._listed = self._clock()
            self.sync_problem = False

    def catalog(self, session, key):
        self.ensure()
        records = sort_photos(self._records)
        selected = self._selected(session, records)
        self._warm(session, selected)
        return {
            "mode": session.mode,
            "folder": session.folder,
            "selected_months": list(session.months),
            "display_seconds": session.display_seconds,
            "sync_problem": self.sync_problem,
            "albums": _albums(records, self._albums),
            "months": _months(records),
            "photos": [{"id": seal(key, record.id), "modified": record.modified}
                       for record in selected],
        }

    def media(self, token, key, session):
        self.ensure()
        object_key = open_seal(key, token)
        if object_key is None or object_key not in self._names:
            return None
        self._warm(session)
        cached = self._queue.get(object_key)
        if cached is not None:
            return cached
        return self._bytes_for(object_key)

    def _selected(self, session, records=None):
        records = sort_photos(self._records if records is None else records)
        if session.mode == "months":
            return filter_photos(records, months=session.months)
        return filter_photos(records, folder=session.folder)

    def _warm(self, session, selected=None):
        if selected is None:
            selected = self._selected(session)
        self._queue.prepare(_selection_key(session), [record.id for record in selected], self._bytes_for)

    def _bytes_for(self, object_key):
        name = self._names.get(object_key)
        if name is None:
            return None
        data = self._reader(self.storage, object_key)
        suffix = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
        if suffix in {".heic", ".heif"}:
            return jpeg_from_heic(data, quality=self.jpeg_quality), "image/jpeg"
        media_type = CONTENT_TYPES.get(suffix)
        if media_type is None:
            return None
        return data, media_type

    def _replace(self, albums):
        catalog = build_catalog(albums, "original")
        self._records = records_from_catalog(catalog)
        self._albums = catalog["albums"]
        self._names = {
            object_id: entry["source_name"]
            for object_id, entry in catalog["photos"].items()
            if isinstance(entry, dict) and isinstance(entry.get("source_name"), str)
        }


def _selection_key(session):
    if session.mode == "months":
        return ("months", tuple(sorted(session.months)))
    return ("folder", session.folder or "")


def _albums(records, extra):
    counts = {}
    modified = {}
    for record in records:
        counts[record.album] = counts.get(record.album, 0) + 1
        if record.modified and (record.album not in modified or record.modified > modified[record.album]):
            modified[record.album] = record.modified
    for name, entry in extra.items():
        counts.setdefault(name, 0)
        if isinstance(entry, dict) and entry.get("modified") and name not in modified:
            modified[name] = entry["modified"]
    return [{"name": name, "count": counts[name], "modified": modified.get(name)}
            for name in sorted(counts)]


def _months(records):
    counts = {}
    for record in records:
        if record.month:
            counts[record.month] = counts.get(record.month, 0) + 1
    return [{"month": month, "count": counts[month]} for month in sorted(counts, reverse=True)]
