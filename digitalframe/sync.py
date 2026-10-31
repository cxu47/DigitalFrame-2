"""Fill a local cache from one confined OSS listing."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import shutil

from .catalog import PLAYBACK_SUFFIXES, build_catalog
from .images import publish_derivative
from .storage import download_photo, list_albums


logger = logging.getLogger(__name__)
MANIFEST_NAME = ".photos.json"


@dataclass
class SyncResult:
    success: bool
    downloaded: int = 0
    failed: int = 0
    error: str = ""


@contextmanager
def cache_lock(cache):
    """Hold the cache lock without removing the lock file.

    Unlinking it would let two processes lock two different inodes.
    """
    cache.mkdir(parents=True, exist_ok=True)
    handle = (cache / ".sync.lock").open("a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another sync process is already using this cache.") from None
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def sync_once(cache, storage, settings):
    """Download, publish, and clean one cache. A failed pass does not delete."""
    cache = Path(cache)
    downloaded = 0
    try:
        with cache_lock(cache):
            _clear_abandoned_staging(cache)
            catalog = build_catalog(list_albums(storage), settings.processing_profile())
            downloaded, failed, error = _publish(cache, storage, catalog, settings)
            if failed:
                return SyncResult(False, downloaded, failed, error)
            _remove_absent(cache, catalog)
            _write_manifest(cache, catalog)
    except Exception as exc:
        logger.exception("Photo sync failed")
        return SyncResult(False, downloaded, 0, f"{type(exc).__name__}: {exc}")
    return SyncResult(True, downloaded, 0, "")


def _publish(cache, storage, catalog, settings):
    previous = _read_manifest(cache).get("photos", {})
    if not isinstance(previous, dict):
        previous = {}
    downloaded = 0
    failed = 0
    error = ""
    for album in catalog["albums"]:
        album_dir = cache / album
        if album_dir.is_symlink():
            return downloaded, 1, f"{album}: symlinks are not supported in the photo cache"
        album_dir.mkdir(exist_ok=True)
    staging = cache / ".sync-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        for object_id, entry in catalog["photos"].items():
            temporary = staging / "download.part"
            publication = staging / f"publication{Path(entry['path']).suffix}"
            try:
                if _reuse(cache, previous.get(object_id), entry):
                    entry["sha256"] = previous[object_id]["sha256"]
                    continue
                temporary.unlink(missing_ok=True)
                publication.unlink(missing_ok=True)
                download_photo(storage, object_id, temporary)
                downloaded += 1
                if entry["size"] is not None and temporary.stat().st_size != entry["size"]:
                    raise ValueError("Downloaded size does not match OSS")
                destination = _destination(cache, entry["path"])
                wrote_derivative = publish_derivative(
                    temporary, publication,
                    converted=entry["converted"],
                    max_width=settings.cache_max_width,
                    max_height=settings.cache_max_height,
                    other_quality=settings.other_image_quality,
                    iphone_quality=settings.iphone_jpeg_quality,
                )
                published = publication if wrote_derivative else temporary
                entry["sha256"] = _sha256(published)
                published.replace(destination)
            except Exception as exc:
                failed += 1
                error = f"{entry['path']}: {type(exc).__name__}: {exc}"
                logger.exception("Unable to refresh %s", entry["path"])
            finally:
                temporary.unlink(missing_ok=True)
                publication.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return downloaded, failed, error


def _reuse(cache, old, entry):
    if not isinstance(old, dict):
        return False
    if not old.get("etag") or old.get("etag") != entry.get("etag"):
        return False
    if old.get("processing") != entry.get("processing"):
        return False
    expected = old.get("sha256")
    if not isinstance(expected, str) or not expected:
        return False
    try:
        old_path = _destination(cache, old.get("path"))
        destination = _destination(cache, entry["path"])
    except ValueError:
        return False
    if not old_path.is_file() or old_path.is_symlink() or _sha256(old_path) != expected:
        return False
    if old_path != destination:
        destination.parent.mkdir(exist_ok=True)
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        old_path.replace(destination)
    return True


def _remove_absent(cache, catalog):
    wanted = {entry["path"] for entry in catalog["photos"].values()}
    albums = set(catalog["albums"])
    for folder in list(cache.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith("."):
            continue
        for child in list(folder.iterdir()):
            if child.is_symlink() or not child.is_file():
                continue
            if child.suffix.lower() not in PLAYBACK_SUFFIXES:
                continue
            relative = f"{folder.name}/{child.name}"
            if relative not in wanted:
                child.unlink()
        if folder.name not in albums:
            try:
                folder.rmdir()
            except OSError:
                pass


def _write_manifest(cache, catalog):
    for entry in catalog["photos"].values():
        if "sha256" not in entry:
            raise RuntimeError("A published photo is missing its SHA-256")
    payload = {"albums": catalog["albums"], "photos": catalog["photos"]}
    temporary = cache / f"{MANIFEST_NAME}.part"
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(cache / MANIFEST_NAME)


def _read_manifest(cache):
    try:
        value = json.loads((cache / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _destination(cache, relative):
    path = Path(relative)
    if (not isinstance(relative, str) or path.is_absolute() or len(path.parts) != 2
            or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)):
        raise ValueError("Invalid cached photo path")
    destination = cache / path
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("Symlinks are not supported in the photo cache")
    parent = destination.parent.resolve()
    if cache.resolve() not in parent.parents:
        raise ValueError("Invalid cached photo path")
    return destination


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clear_abandoned_staging(cache):
    for abandoned in cache.glob(".sync-*"):
        if abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)
