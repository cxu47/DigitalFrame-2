"""Shared fixtures for the offline sync tests."""

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

from alibabacloud_oss_v2.crc import Crc64
from PIL import Image
from pillow_heif import register_heif_opener

from digitalframe.config import Settings
from digitalframe.storage import OssStorage


register_heif_opener()


def make_settings(root, **overrides):
    cache = root / "cache"
    values = dict(
        root=root,
        cache_dir=cache,
        secrets_dir=root / "secrets",
        oss_credentials_file="oss.env",
        network_timeout=10,
        cache_max_width=1600,
        cache_max_height=900,
        other_image_quality=85,
        iphone_jpeg_quality=75,
        log_level="INFO",
    )
    values.update(overrides)
    return Settings(**values)


def write_oss_env(root, *, endpoint="", prefix="photos/", secret="local-secret"):
    secrets = root / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    lines = [
        "OSS_ACCESS_KEY_ID=local-id",
        f"OSS_ACCESS_KEY_SECRET={secret}",
        "OSS_BUCKET_NAME=local-bucket",
        "OSS_REGION=cn-hongkong",
        f"OSS_ENDPOINT={endpoint}",
        f"OSS_PREFIX={prefix}",
    ]
    (secrets / "oss.env").write_text("\n".join(lines) + "\n", encoding="utf-8")


def jpeg_bytes(width, height, color=(20, 40, 60)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def heic_bytes(width=8, height=6, color=(1, 2, 3)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="HEIF")
    return buffer.getvalue()


def png_bytes(width, height, color=(4, 5, 6)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def oss_object(key, *, size=3, etag='"etag"', modified=None):
    return SimpleNamespace(
        key=key,
        size=size,
        etag=etag,
        last_modified=modified or datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def oss_prefix(value):
    return SimpleNamespace(prefix=value)


def oss_page(contents=(), prefixes=()):
    return SimpleNamespace(contents=list(contents), common_prefixes=list(prefixes))


def crc64(data):
    checksum = Crc64(0)
    checksum.update(data)
    return str(checksum.sum64())


class Body:
    def __init__(self, data):
        self.data = data
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        return False

    def iter_bytes(self, *, block_size):
        assert block_size > 0
        yield self.data


def fake_client(pages, bodies):
    class Paginator:
        def iter_page(self, request):
            return iter(pages[request.prefix])

    client = Mock()
    client.list_objects_v2_paginator.side_effect = Paginator

    def get_object(request):
        data = bodies[request.key]
        return SimpleNamespace(body=Body(data), hash_crc64=crc64(data))

    client.get_object.side_effect = get_object
    return client


def storage_for(client, prefix="photos/"):
    return OssStorage(client=client, bucket="local-bucket", prefix=prefix)
