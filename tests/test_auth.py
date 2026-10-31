"""Passcode file and login lockout. No web server and no photos."""

import pytest

from digitalframe.auth import (
    LoginLimiter, authenticate, ensure_session_key, load_users)


def _users(tmp_path, text):
    path = tmp_path / "users.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_users_rejects_a_missing_file(tmp_path):
    with pytest.raises(ValueError, match="Missing users file"):
        load_users(tmp_path / "users.yaml")


def test_load_users_rejects_blank_duplicate_and_non_text_passcodes(tmp_path):
    with pytest.raises(ValueError, match="without a passcode"):
        load_users(_users(tmp_path, "users:\n  - name: ada\n    passcode:\n"))
    with pytest.raises(ValueError, match="more than once"):
        load_users(_users(tmp_path, """
users:
  - {name: ada, passcode: "one"}
  - {name: ada, passcode: "two"}
"""))
    with pytest.raises(ValueError, match="Quote passcodes"):
        load_users(_users(tmp_path, "users:\n  - {name: ada, passcode: 1234}\n"))


def test_passcode_match_does_not_trim_or_accept_an_unknown_name(tmp_path):
    users = load_users(_users(tmp_path, """
users:
  - name: ada
    passcode: "correct-pass"
"""))
    assert authenticate(users, "ada", "correct-pass")
    assert not authenticate(users, "ada", "correct-pass ")
    assert not authenticate(users, "ada", "nope")
    assert not authenticate(users, "missing", "correct-pass")


def test_session_key_is_32_bytes_and_owner_readable(tmp_path):
    path = tmp_path / "secrets" / "session.key"
    first = ensure_session_key(path)
    assert len(first) == 32
    assert path.stat().st_mode & 0o777 == 0o600
    assert ensure_session_key(path) == first


def test_sixth_failure_from_one_address_is_blocked():
    limiter = LoginLimiter()
    for _ in range(5):
        assert not limiter.blocked("10.0.0.8")
        limiter.fail("10.0.0.8")
    assert limiter.blocked("10.0.0.8")
    assert not limiter.blocked("10.0.0.9")
    limiter.succeed("10.0.0.8")
    assert not limiter.blocked("10.0.0.8")
