"""Slideshow routes against a temporary cache. No browser and no OSS."""

import json

from fastapi.testclient import TestClient

from digitalframe.auth import LoginLimiter, Session, Sessions, ensure_session_key, load_users
from digitalframe.web import TEMPLATE, Library, create_app, run_sync
from tests.fakes import jpeg_bytes, make_settings


def _app(tmp_path):
    cache = tmp_path / "cache"
    kids = cache / "kids"
    holidays = cache / "holidays"
    kids.mkdir(parents=True)
    holidays.mkdir()
    newer = jpeg_bytes(20, 10, color=(1, 2, 3))
    older = jpeg_bytes(20, 10, color=(4, 5, 6))
    (kids / "keep.jpg").write_bytes(newer)
    (holidays / "old.jpg").write_bytes(older)
    manifest = {
        "albums": {
            "kids": {"modified": "2026-09-12T00:00:00Z"},
            "holidays": {"modified": "2024-01-02T00:00:00Z"},
        },
        "photos": {
            "photos/kids/keep.jpg": {
                "path": "kids/keep.jpg",
                "album": "kids",
                "modified": "2026-09-12T00:00:00Z",
                "month": "2026-09",
                "etag": "oss-cn-hongkong.aliyuncs.com",
            },
            "photos/holidays/old.jpg": {
                "path": "holidays/old.jpg",
                "album": "holidays",
                "modified": "2024-01-02T00:00:00Z",
                "month": "2024-01",
                "etag": "oss-cn-hongkong.aliyuncs.com",
            },
        },
    }
    (cache / ".photos.json").write_text(json.dumps(manifest), encoding="utf-8")
    users_file = tmp_path / "users.yaml"
    users_file.write_text(
        "users:\n  - name: ada\n    passcode: \"correct-pass\"\n", encoding="utf-8")
    settings = make_settings(tmp_path, cookie_secure=False)
    library = Library(cache)
    app = create_app(
        settings, library, load_users(users_file), Sessions(), LoginLimiter(),
        ensure_session_key(tmp_path / "secrets" / "session.key"))
    return app, newer


def _login(client, name="ada", passcode="correct-pass"):
    return client.post("/login", data={"name": name, "passcode": passcode},
                        follow_redirects=False)


def test_missing_and_wrong_passcodes_match_and_set_no_cookie(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    missing = _login(client, "", "")
    wrong = _login(client, "ada", "nope")

    assert missing.status_code == wrong.status_code == 401
    assert missing.text == wrong.text
    assert "That name or passcode is not recognized." in missing.text
    assert "set-cookie" not in missing.headers
    assert "set-cookie" not in wrong.headers


def test_a_correct_passcode_sets_a_cookie_and_media_requires_it(tmp_path):
    app, _newer = _app(tmp_path)
    anonymous = TestClient(app)
    assert anonymous.get("/media/anything").status_code == 401
    assert anonymous.get("/catalog").status_code == 401

    client = TestClient(app)
    signed_in = _login(client)
    assert signed_in.status_code == 303
    assert "digitalframe_session" in signed_in.cookies
    assert client.get("/media/missing").status_code == 404


def test_catalog_and_media_hide_object_keys_and_send_private_headers(tmp_path):
    app, newer = _app(tmp_path)
    client = TestClient(app)
    _login(client)
    catalog = client.get("/catalog")
    body = catalog.text
    assert catalog.status_code == 200
    assert "photos/" not in body
    assert "oss-" not in body
    assert "aliyuncs" not in body
    photo_id = catalog.json()["photos"][0]["id"]
    assert catalog.json()["photos"][0]["modified"].startswith("2026-09-12")

    media = client.get(f"/media/{photo_id}")
    assert media.status_code == 200
    assert media.content == newer
    assert "no-store" in media.headers["cache-control"]
    assert media.headers["content-disposition"] == "inline"
    assert b"photos/" not in media.content
    assert b"oss-" not in media.content
    assert b"aliyuncs" not in media.content


def test_the_sixth_failure_is_rejected(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    for _ in range(5):
        assert _login(client, "ada", "nope").status_code == 401
    assert _login(client, "ada", "correct-pass").status_code == 429


def test_the_template_and_the_page_have_no_image_tag(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "<img" not in text.lower()
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    assert "<img" not in client.get("/").text.lower()
    _login(client)
    page = client.get("/")
    assert page.status_code == 200
    assert "<img" not in page.text.lower()
    assert "canvas" in page.text


def test_invalid_display_seconds_do_not_change_the_session(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    _login(client)
    rejected = client.post("/view", data={"action": "seconds", "display_seconds": "5.0"},
                            follow_redirects=False)
    assert rejected.status_code == 422
    assert "positive whole number" in rejected.text
    assert client.get("/catalog").json()["display_seconds"] == 5
    accepted = client.post("/view", data={"action": "seconds", "display_seconds": "8"},
                            follow_redirects=False)
    assert accepted.status_code == 303
    assert client.get("/catalog").json()["display_seconds"] == 8


def test_folder_selection_narrows_the_catalog(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    _login(client)
    assert len(client.get("/catalog").json()["photos"]) == 2
    response = client.post("/view", data={"action": "folder", "folder": "holidays"},
                            follow_redirects=False)
    assert response.status_code == 303
    catalog = client.get("/catalog").json()
    assert catalog["mode"] == "folder"
    assert catalog["folder"] == "holidays"
    assert len(catalog["photos"]) == 1
    assert catalog["photos"][0]["modified"].startswith("2024-01-02")


def test_a_failed_sync_sets_a_flag_and_hides_the_exception(tmp_path):
    library = Library(tmp_path / "cache")

    def explode(_settings):
        raise RuntimeError("https://oss-cn-hongkong.aliyuncs.com/photos/secret.jpg")

    run_sync(make_settings(tmp_path), library, lambda *_args: None, explode, lambda *_args: None)
    session = Session("ada", 9_999_999_999, "folder", None, (), 5)
    body = json.dumps(library.catalog(session))
    assert library.sync_problem is True
    assert "aliyuncs" not in body
    assert "photos/" not in body
    assert body.find("sync_problem") != -1
