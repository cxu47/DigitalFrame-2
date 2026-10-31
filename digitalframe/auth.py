"""Passcodes from users.yaml, and the in-memory sessions those passcodes open."""

import base64
from dataclasses import dataclass
import hmac
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from threading import Lock

import yaml


SESSION_SECONDS = 12 * 60 * 60
LOGIN_LIMIT = 5
LOGIN_WINDOW = 15 * 60
COOKIE_NAME = "digitalframe_session"


@dataclass(frozen=True)
class User:
    name: str
    passcode: str

    def __repr__(self):
        return f"User(name={self.name!r})"


@dataclass
class Session:
    name: str
    expires: float
    mode: str
    folder: str | None
    months: tuple
    display_seconds: int


def load_users(path):
    """Read the gitignored user file. The error text never includes a passcode."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Missing users file: {path.name}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ValueError(f"Could not read {path.name}.") from None
    entries = loaded.get("users") if isinstance(loaded, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path.name} must list at least one user.")
    users = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{path.name} has an invalid user entry.")
        name = entry.get("name")
        passcode = entry.get("passcode")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path.name} has a user without a name.")
        name = name.strip()
        if not isinstance(passcode, str) or passcode == "":
            raise ValueError(
                f"{path.name} has a user without a passcode. Quote passcodes so they stay text.")
        if name in users:
            raise ValueError(f"{path.name} lists {name} more than once.")
        if any(existing.passcode == passcode for existing in users.values()):
            raise ValueError(f"{path.name} uses the same passcode more than once.")
        users[name] = User(name, passcode)
    return users


def authenticate(users, passcode):
    """Return the user whose passcode matches. The passcode is not trimmed.

    The name in the YAML file is a label. It is not part of the check.
    """
    if not isinstance(passcode, str):
        return None
    given = passcode.encode("utf-8")
    matched = None
    records = list(users.values()) or [None]
    for record in records:
        expected = record.passcode.encode("utf-8") if record is not None else b""
        if len(given) != len(expected):
            hmac.compare_digest(given, given)
            continue
        if hmac.compare_digest(expected, given) and record is not None:
            matched = record
    return matched


def load_session_key(settings):
    """Use SESSION_KEY when set, so another instance can read the same cookies.

    Local and ECS runs keep using secrets/session.key when the variable is absent.
    """
    encoded = os.environ.get("SESSION_KEY", "").strip()
    if encoded:
        try:
            data = bytes.fromhex(encoded)
        except ValueError:
            data = b""
        if len(data) != 32:
            raise ValueError("SESSION_KEY must be 64 hex characters.")
        return data
    return ensure_session_key(settings.secrets_dir / "session.key")


def ensure_session_key(path):
    """Create a 32-byte key on first run. The file mode is owner-read only."""
    path = Path(path)
    if path.exists():
        data = path.read_bytes()
        if len(data) != 32:
            raise ValueError("session.key must contain 32 bytes.")
        return data
    path.parent.mkdir(parents=True, exist_ok=True)
    data = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        data = path.read_bytes()
        if len(data) != 32:
            raise ValueError("session.key must contain 32 bytes.")
        return data
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    return data


class Sessions:
    """Signed cookies. Nothing about the view is kept in process memory."""

    def __init__(self, ttl=SESSION_SECONDS):
        self.ttl = ttl

    def start(self, key, name, display_seconds):
        session = Session(
            name=name, expires=time.time() + self.ttl, mode="folder", folder=None,
            months=(), display_seconds=display_seconds)
        return _pack(key, session)

    def get(self, key, token):
        return _unpack(key, token)

    def update(self, key, token, **changes):
        session = _unpack(key, token)
        if session is None:
            return None
        for name, value in changes.items():
            setattr(session, name, value)
        return _pack(key, session)


class LoginLimiter:
    """Five failures from one address, then no further attempts for 15 minutes."""

    def __init__(self, limit=LOGIN_LIMIT, window=LOGIN_WINDOW):
        self.limit = limit
        self.window = window
        self._failures = {}
        self._lock = Lock()

    def blocked(self, address):
        with self._lock:
            return len(self._recent(address)) >= self.limit

    def fail(self, address):
        with self._lock:
            recent = self._recent(address)
            recent.append(time.monotonic())
            self._failures[address] = recent

    def succeed(self, address):
        with self._lock:
            self._failures.pop(address, None)

    def _recent(self, address):
        now = time.monotonic()
        recent = [stamp for stamp in self._failures.get(address, [])
                  if now - stamp < self.window]
        if recent:
            self._failures[address] = recent
        else:
            self._failures.pop(address, None)
        return recent


def _sign(key, raw):
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _pack(key, session):
    payload = {
        "name": session.name,
        "exp": session.expires,
        "mode": session.mode,
        "folder": session.folder,
        "months": list(session.months),
        "seconds": session.display_seconds,
    }
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{body}.{_sign(key, 'session:' + body)}"


def _unpack(key, token):
    if not isinstance(token, str) or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    if not body or not hmac.compare_digest(_sign(key, "session:" + body), signature):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    expires = payload.get("exp")
    mode = payload.get("mode")
    months = payload.get("months")
    seconds = payload.get("seconds")
    folder = payload.get("folder")
    name = payload.get("name")
    if (not isinstance(expires, (int, float)) or expires <= time.time()
            or mode not in {"folder", "months"}
            or not isinstance(name, str)
            or not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0
            or not isinstance(months, list)
            or any(not _month(item) for item in months)
            or (folder is not None and not isinstance(folder, str))):
        return None
    return Session(
        name=name, expires=expires, mode=mode, folder=folder or None,
        months=tuple(months), display_seconds=seconds)


def seal(key, text):
    """Hide an object key inside a token any instance with the key can open."""
    data = text.encode("utf-8")
    nonce = hmac.new(key, b"media:" + data, hashlib.sha256).digest()[:16]
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(left ^ right for left, right in zip(data, stream))
    body = base64.urlsafe_b64encode(nonce + cipher).decode("ascii").rstrip("=")
    return f"{body}.{_sign(key, 'media:' + body)}"


def open_seal(key, token):
    if not isinstance(token, str) or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not body or not hmac.compare_digest(_sign(key, "media:" + body), signature):
        return None
    try:
        padded = body + "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeError):
        return None
    if len(raw) < 16:
        return None
    nonce, cipher = raw[:16], raw[16:]
    stream = _keystream(key, nonce, len(cipher))
    try:
        return bytes(left ^ right for left, right in zip(cipher, stream)).decode("utf-8")
    except UnicodeError:
        return None


def _month(value):
    return (isinstance(value, str) and len(value) == 7 and value[4] == "-"
            and value[:4].isdigit() and value[5:].isdigit()
            and 1 <= int(value[5:]) <= 12)


def _keystream(key, nonce, size):
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < size:
        blocks.append(hmac.new(
            key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:size]
