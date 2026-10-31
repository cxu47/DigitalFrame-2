"""List and download photos confined to one OSS prefix."""

from dataclasses import dataclass
from pathlib import Path

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.crc import Crc64

from .catalog import SOURCE_SUFFIXES, format_time


DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class OssStorage:
    client: object
    bucket: str
    prefix: str


def normalize_prefix(value):
    """Return a folder prefix such as `photos/`.

    Empty, absolute, and `..` prefixes are rejected so a secrets file cannot
    point the sync at the bucket root or another prefix by accident.
    """
    raw = str(value or "").strip()
    if not raw or raw.startswith("/") or "\\" in raw:
        raise ValueError("OSS_PREFIX must name a folder inside the bucket.")
    parts = raw.strip("/").split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("OSS_PREFIX must name a folder inside the bucket.")
    return "/".join(parts) + "/"


def open_storage(config, timeout):
    credentials = oss.credentials.StaticCredentialsProvider(
        config.access_key_id,
        config.access_key_secret,
        config.session_token,
    )
    sdk_config = oss.config.load_default()
    sdk_config.credentials_provider = credentials
    sdk_config.region = config.region
    sdk_config.connect_timeout = timeout
    sdk_config.readwrite_timeout = timeout
    if config.endpoint is not None:
        sdk_config.endpoint = config.endpoint
    return OssStorage(
        client=oss.Client(sdk_config),
        bucket=config.bucket,
        prefix=config.prefix,
    )


def list_albums(storage):
    """Return immediate albums and the supported photos directly inside them."""
    prefixes = []
    root = oss.ListObjectsV2Request(
        bucket=storage.bucket, prefix=storage.prefix, delimiter="/")
    for page in _pages(storage.client, root):
        for item in page.common_prefixes or ():
            _album_name(item.prefix, storage.prefix)
            prefixes.append(item.prefix)

    albums = []
    for album_prefix in sorted(set(prefixes)):
        album = {
            "id": album_prefix,
            "name": _album_name(album_prefix, storage.prefix),
            "photos": [],
        }
        request = oss.ListObjectsV2Request(
            bucket=storage.bucket, prefix=album_prefix, delimiter="/")
        for page in _pages(storage.client, request):
            for item in page.contents or ():
                if item.key == album_prefix:
                    modified = format_time(item.last_modified)
                    album["createdTime"] = modified
                    album["modifiedTime"] = modified
                    continue
                name = _object_name(item.key, album_prefix)
                if name is not None and Path(name).suffix.lower() in SOURCE_SUFFIXES:
                    album["photos"].append(_photo(item, name))
        albums.append(album)
    return albums


def download_photo(storage, object_key, destination):
    """Stream one confined photo into `destination`. Remove it if the read fails."""
    object_key = confined_key(object_key, storage.prefix)
    destination = Path(destination)
    result = storage.client.get_object(oss.GetObjectRequest(
        bucket=storage.bucket, key=object_key))
    checksum = Crc64(0)
    try:
        with result.body as body, destination.open("wb") as output:
            for chunk in body.iter_bytes(block_size=DOWNLOAD_CHUNK_SIZE):
                output.write(chunk)
                checksum.update(chunk)
        server_checksum = getattr(result, "hash_crc64", None)
        if server_checksum is not None and checksum.sum64() != int(server_checksum):
            raise oss.exceptions.InconsistentError(
                client_crc=str(checksum.sum64()), server_crc=str(server_checksum))
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def read_photo(storage, object_key):
    """Read one confined photo into memory. Nothing is written to disk."""
    object_key = confined_key(object_key, storage.prefix)
    result = storage.client.get_object(oss.GetObjectRequest(
        bucket=storage.bucket, key=object_key))
    checksum = Crc64(0)
    chunks = []
    with result.body as body:
        for chunk in body.iter_bytes(block_size=DOWNLOAD_CHUNK_SIZE):
            chunks.append(chunk)
            checksum.update(chunk)
    server_checksum = getattr(result, "hash_crc64", None)
    if server_checksum is not None and checksum.sum64() != int(server_checksum):
        raise oss.exceptions.InconsistentError(
            client_crc=str(checksum.sum64()), server_crc=str(server_checksum))
    return b"".join(chunks)


def confined_key(object_key, prefix):
    if not isinstance(object_key, str) or not object_key.startswith(prefix):
        raise ValueError("OSS object key is outside the configured photos prefix")
    parts = object_key[len(prefix):].split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("OSS photo key must be directly inside an album")
    return object_key


def _pages(client, request):
    paginator = client.list_objects_v2_paginator()
    yield from paginator.iter_page(request)


def _album_name(album_prefix, photos_prefix):
    if not album_prefix.startswith(photos_prefix) or not album_prefix.endswith("/"):
        raise RuntimeError("OSS returned an album outside the configured photos prefix")
    relative = album_prefix[len(photos_prefix):-1]
    if not relative or "/" in relative or relative in {".", ".."}:
        raise RuntimeError("OSS returned an invalid immediate album prefix")
    return relative


def _object_name(object_key, album_prefix):
    if not isinstance(object_key, str) or not object_key.startswith(album_prefix):
        raise RuntimeError("OSS returned an object outside its requested album prefix")
    relative = object_key[len(album_prefix):]
    if not relative or "/" in relative:
        return None
    return relative


def _photo(item, name):
    modified = format_time(item.last_modified)
    etag = getattr(item, "etag", None)
    if isinstance(etag, str):
        etag = etag.strip('"')
    return {
        "id": item.key,
        "name": name,
        "size": getattr(item, "size", None),
        "createdTime": modified,
        "modifiedTime": modified,
        "etag": etag,
    }
