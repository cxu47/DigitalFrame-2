"""Passcodes from users.yaml, and the in-memory sessions those passcodes open."""

from dataclasses import dataclass
import hmac
import hashlib
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
    def __init__(self, ttl=SESSION_SECONDS):
        self.ttl = ttl
        self._items = {}
        self._lock = Lock()

    def start(self, key, name, display_seconds):
        raw = secrets.token_urlsafe(32)
        token = f"{raw}.{_sign(key, raw)}"
        now = time.time()
        with self._lock:
            self._items[token] = Session(
                name=name, expires=now + self.ttl, mode="folder", folder=None,
                months=(), display_seconds=display_seconds)
        return token

    def get(self, key, token):
        if not _signed(key, token):
            return None
        now = time.time()
        with self._lock:
            session = self._items.get(token)
            if session is None or session.expires <= now:
                self._items.pop(token, None)
                return None
            session.expires = now + self.ttl
            return session

    def end(self, token):
        with self._lock:
            self._items.pop(token, None)

    def update(self, token, **changes):
        with self._lock:
            session = self._items.get(token)
            if session is None:
                return None
            for name, value in changes.items():
                setattr(session, name, value)
            return session


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


def _signed(key, token):
    if not isinstance(token, str) or "." not in token:
        return False
    raw, signature = token.rsplit(".", 1)
    if not raw or not signature:
        return False
    return hmac.compare_digest(_sign(key, raw), signature)
