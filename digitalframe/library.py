"""The photo list for one process. Pictures stay in OSS."""

import logging
import time
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


class Library:
    """One shared catalog. Each browser receives sealed ids, not object keys."""

    def __init__(self, storage, *, interval, jpeg_quality=75, clock=None, lister=list_albums):
        self.storage = storage
        self.interval = interval
        self.jpeg_quality = jpeg_quality
        self._clock = clock or time.monotonic
        self._lister = lister
        self.sync_problem = False
        self._lock = Lock()
        self._records = []
        self._names = {}
        self._albums = {}
        self._listed = None

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
        if session.mode == "months":
            selected = filter_photos(records, months=session.months)
        else:
            selected = filter_photos(records, folder=session.folder)
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

    def media(self, token, key):
        self.ensure()
        object_key = open_seal(key, token)
        if object_key is None or object_key not in self._names:
            return None
        data = read_photo(self.storage, object_key)
        name = self._names[object_key]
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
