"""Load app settings and OSS credentials.

The secrets file is read on each call. Its values are not written into the
process environment.
"""

from dataclasses import dataclass
import math
import os
from pathlib import Path

from dotenv import dotenv_values

from .storage import normalize_prefix


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path
    cache_dir: Path
    secrets_dir: Path
    oss_credentials_file: str
    network_timeout: float
    cache_max_width: int
    cache_max_height: int
    other_image_quality: int
    iphone_jpeg_quality: int
    log_level: str

    def processing_profile(self):
        return (
            f"fit-{self.cache_max_width}x{self.cache_max_height}"
            f"-other{self.other_image_quality}-iphone{self.iphone_jpeg_quality}"
        )


@dataclass(frozen=True)
class OssConfig:
    access_key_id: str
    access_key_secret: str
    session_token: str | None
    bucket: str
    region: str
    endpoint: str | None
    prefix: str


def load_settings(root=None):
    root = Path(root) if root is not None else ROOT
    get = _values(root / ".env")
    cache = _relative_dir(get, "CACHE_FOLDER", "cache")
    secrets = _relative_dir(get, "SECRETS_FOLDER", "secrets")
    credentials_name = get("OSS_CREDENTIALS_FILE", "oss.env")
    credentials_path = Path(credentials_name)
    if (credentials_path.is_absolute() or len(credentials_path.parts) != 1
            or credentials_path.name in {".", ".."}):
        raise ValueError("OSS_CREDENTIALS_FILE must be a filename inside SECRETS_FOLDER.")
    return Settings(
        root=root,
        cache_dir=root / cache,
        secrets_dir=root / secrets,
        oss_credentials_file=credentials_path.name,
        network_timeout=_timeout(get),
        cache_max_width=_integer(get, "CACHE_MAX_WIDTH", 1600, 1, 16384),
        cache_max_height=_integer(get, "CACHE_MAX_HEIGHT", 900, 1, 16384),
        other_image_quality=_integer(get, "OTHER_IMAGE_QUALITY", 85, 1, 95),
        iphone_jpeg_quality=_integer(get, "IPHONE_JPEG_QUALITY", 75, 1, 95),
        log_level=get("LOG_LEVEL", "INFO"),
    )


def load_oss_config(settings):
    path = settings.secrets_dir / settings.oss_credentials_file
    values = dotenv_values(path)

    def required(name):
        value = values.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Missing required OSS setting: {name}. Add it to {path.name}.")
        return value.strip()

    endpoint = str(values.get("OSS_ENDPOINT") or "").strip() or None
    if endpoint is not None and not endpoint.startswith("https://"):
        raise ValueError("OSS_ENDPOINT must use https://.")
    token = str(values.get("OSS_SESSION_TOKEN") or "").strip() or None
    return OssConfig(
        access_key_id=required("OSS_ACCESS_KEY_ID"),
        access_key_secret=required("OSS_ACCESS_KEY_SECRET"),
        session_token=token,
        bucket=required("OSS_BUCKET_NAME"),
        region=required("OSS_REGION"),
        endpoint=endpoint,
        prefix=normalize_prefix(values.get("OSS_PREFIX") or "photos"),
    )


def _values(env_file):
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def get(name, default=None):
        if name in os.environ:
            value = os.environ[name]
        else:
            value = file_values.get(name)
        if value is None or str(value).strip() == "":
            return default
        return str(value).strip()

    return get


def _relative_dir(get, name, default):
    raw = get(name, default)
    path = Path(raw)
    if path.is_absolute() or not raw or ".." in path.parts:
        raise ValueError(f"{name} must stay inside the repository.")
    return path


def _integer(get, name, default, minimum, maximum):
    raw = get(name, str(default))
    try:
        value = int(str(raw), 10)
        if not minimum <= value <= maximum:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} must be a whole number from {minimum} to {maximum}.") from None
    return value


def _timeout(get):
    raw = get("NETWORK_TIMEOUT", "10")
    try:
        value = float(raw)
        if not math.isfinite(value) or value < 0.001:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(
            "NETWORK_TIMEOUT must be a finite number of at least 0.001 seconds.") from None
    return value
