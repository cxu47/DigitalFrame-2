"""Photo records, month buckets, and newest-first order.

This module does not sleep, start threads, or open sockets. Month buckets use
the OSS last-modified time, which is the only timestamp ListObjects provides.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path


SOURCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
PLAYBACK_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
IPHONE_SUFFIXES = {".heic", ".heif"}


@dataclass(frozen=True)
class PhotoRecord:
    id: str
    album: str
    path: str
    modified: str | None
    month: str | None


def parse_time(value):
    """Return a UTC datetime, or None when the value is missing or damaged."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_time(value):
    parsed = parse_time(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def photo_month(value):
    """Return the UTC YYYY-MM bucket for a timestamp, or None."""
    parsed = parse_time(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m")


def sort_photos(photos):
    """Newest modified time first. Equal times use the path. Missing times are last."""
    def key(photo):
        parsed = parse_time(photo.modified)
        if parsed is None:
            return (1, 0.0, photo.path)
        return (0, -parsed.timestamp(), photo.path)

    return sorted(photos, key=key)


def filter_photos(photos, *, folder=None, months=None):
    """Keep one album, or a set of months across every album.

    A month selection ignores album boundaries. An empty selection is valid.
    """
    if months is not None:
        selected = set(months)
        return [photo for photo in photos if photo.month in selected]
    if folder:
        return [photo for photo in photos if photo.album == folder]
    return list(photos)


def records_from_catalog(catalog):
    photos = catalog.get("photos") if isinstance(catalog, dict) else None
    if not isinstance(photos, dict):
        return []
    records = []
    for object_id, entry in photos.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        records.append(PhotoRecord(
            id=object_id,
            album=entry.get("album") or Path(entry["path"]).parent.name,
            path=entry["path"],
            modified=entry.get("modified"),
            month=entry.get("month"),
        ))
    return records


def build_catalog(albums, processing):
    """Map a confined listing to published album and playback names.

    HEIC and HEIF claim `<stem>.jpg`. A file that wants the same playback
    name gets a stable suffix from its object key.
    """
    album_names = _claim_names(
        [(album["id"], _safe_name(album["name"], "album")) for album in albums])
    photos = {}
    folder_metadata = {}
    for album in albums:
        album_name = album_names[album["id"]]
        folder_metadata[album_name] = {
            "created": album.get("createdTime"),
            "modified": album.get("modifiedTime"),
        }
        supported = [photo for photo in album.get("photos", [])
                     if _supported(photo.get("name", ""))]
        playback = _claim_names(_playback_requests(supported))
        for photo in supported:
            modified = photo.get("modifiedTime")
            photos[photo["id"]] = {
                "path": f"{album_name}/{playback[photo['id']]}",
                "album": album_name,
                "source_name": photo["name"],
                "etag": photo.get("etag"),
                "size": photo.get("size"),
                "modified": modified,
                "month": photo_month(modified),
                "converted": Path(photo["name"]).suffix.lower() in IPHONE_SUFFIXES,
                "processing": processing,
            }
    return {"albums": folder_metadata, "photos": photos}


def _supported(name):
    return Path(name).suffix.lower() in SOURCE_SUFFIXES


def _playback_requests(photos):
    """List HEIC and HEIF first so they keep the plain JPEG name."""
    iphone = []
    other = []
    for photo in photos:
        suffix = Path(photo["name"]).suffix.lower()
        if suffix in IPHONE_SUFFIXES:
            desired = _safe_name(f"{Path(photo['name']).stem}.jpg", "untitled.jpg")
            iphone.append((photo["id"], desired))
        else:
            other.append((photo["id"], _safe_name(photo["name"], "untitled")))
    iphone.sort()
    other.sort()
    return iphone + other


def _claim_names(requests):
    used = set()
    claimed = {}
    for object_id, desired in requests:
        name = desired
        index = 0
        while name.casefold() in used:
            index += 1
            tag = hashlib.sha256(object_id.encode()).hexdigest()[:12]
            path = Path(desired)
            name = f"{path.stem} ({tag}-{index}){path.suffix}"
        used.add(name.casefold())
        claimed[object_id] = name
    return claimed


def _safe_name(name, fallback):
    cleaned = str(name).replace("/", "_").replace("\\", "_").replace("\x00", "_").strip()
    cleaned = cleaned.lstrip(".") or fallback
    if cleaned in {".", ".."}:
        cleaned = fallback
    while len(cleaned.encode("utf-8")) > 180:
        stem, suffix = Path(cleaned).stem, Path(cleaned).suffix
        cleaned = stem[:-1] + suffix if stem else cleaned[:-1]
        if not cleaned:
            return fallback
    return cleaned
