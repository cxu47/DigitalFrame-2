"""Slideshow routes against a fake bucket. No browser and no network."""

from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient

from digitalframe.auth import LoginLimiter, Session, Sessions, ensure_session_key, load_users
from digitalframe.library import Library
from digitalframe.web import TEMPLATE, create_app, run_sync
from tests.fakes import (
    fake_client, heic_bytes, jpeg_bytes, make_settings, oss_object, oss_page,
    oss_prefix, storage_for,
)


def _storage(objects):
    pages = {"photos/": [oss_page(prefixes=[
        oss_prefix(f"photos/{album}/") for album in {key.split("/")[1] for key in objects}
    ])]}
    for key, payload in objects.items():
        album = key.split("/")[1]
        prefix = f"photos/{album}/"
        pages.setdefault(prefix, [oss_page(contents=[oss_object(prefix)])])
        pages[prefix][0].contents.append(oss_object(
            key, size=len(payload["body"]), etag=payload["etag"], modified=payload["modified"]))
    client = fake_client(pages, {key: payload["body"] for key, payload in objects.items()})
    return storage_for(client), client


def _app(tmp_path):
    newer = jpeg_bytes(20, 10, color=(1, 2, 3))
    older = jpeg_bytes(20, 10, color=(4, 5, 6))
    objects = {
        "photos/kids/keep.jpg": {
            "body": newer, "etag": '"keep"',
            "modified": datetime(2026, 9, 12, tzinfo=timezone.utc),
        },
        "photos/holidays/old.jpg": {
            "body": older, "etag": '"old"',
            "modified": datetime(2024, 1, 2, tzinfo=timezone.utc),
        },
    }
    storage, _client = _storage(objects)
    users_file = tmp_path / "users.yaml"
    users_file.write_text(
        "users:\n  - name: ada\n    passcode: \"correct-pass\"\n", encoding="utf-8")
    settings = make_settings(tmp_path, cookie_secure=False)
    library = Library(storage, interval=3600, jpeg_quality=75)
    app = create_app(
        settings, library, load_users(users_file), Sessions(), LoginLimiter(),
        ensure_session_key(tmp_path / "secrets" / "session.key"))
    return app, newer


def _login(client, passcode="correct-pass"):
    return client.post("/login", data={"passcode": passcode}, follow_redirects=False)


def test_missing_and_wrong_passcodes_match_and_set_no_cookie(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    missing = _login(client, "")
    wrong = _login(client, "nope")

    assert missing.status_code == wrong.status_code == 401
    assert missing.text == wrong.text
    assert "That passcode is not recognized." in missing.text
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
        assert _login(client, "nope").status_code == 401
    assert _login(client, "correct-pass").status_code == 429


def test_translations_come_from_a_dictionary_file(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    dictionary = client.get("/translations.json")
    assert dictionary.status_code == 200
    words = dictionary.json()
    assert words["en"]["enter"] == "Enter"
    assert words["zh"]["enter"] == "进入"
    assert words["pl"]["enter"] == "Wejdź"
    page = client.get("/").text
    assert 'data-i18n="enter"' in page
    assert "进入" not in page
    assert "Wejdź" not in page


def test_the_template_and_the_page_have_no_image_tag(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "<img" not in text.lower()
    assert "Log out" not in text
    assert "Reset" in text
    assert 'id="previous"' in text
    assert 'id="next"' in text
    assert 'id="pause"' in text
    assert 'id="shuffle"' in text
    assert 'id="month-picker"' in text
    assert 'id="month-checks"' in text
    assert 'data-lang="zh"' in text
    assert 'data-lang="pl"' in text
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    login = client.get("/")
    assert 'id="playback" hidden' in login.text
    assert "<img" not in login.text.lower()
    _login(client)
    page = client.get("/")
    assert page.status_code == 200
    assert "<img" not in page.text.lower()
    assert "canvas" in page.text


def test_invalid_display_seconds_do_not_change_the_session(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    _login(client)
    rejected = client.post("/view", data={"apply": "seconds", "display_seconds": "5.0"},
                            follow_redirects=False)
    assert rejected.status_code == 422
    assert "positive whole number" in rejected.text
    assert client.get("/catalog").json()["display_seconds"] == 5
    accepted = client.post("/view", data={"apply": "seconds", "display_seconds": "8"},
                            follow_redirects=False)
    assert accepted.status_code == 303
    assert client.get("/catalog").json()["display_seconds"] == 8


def test_folder_selection_narrows_the_catalog(tmp_path):
    app, _newer = _app(tmp_path)
    client = TestClient(app)
    _login(client)
    assert len(client.get("/catalog").json()["photos"]) == 2
    response = client.post("/view", data={"apply": "folder", "folder": "holidays"},
                            follow_redirects=False)
    assert response.status_code == 303
    catalog = client.get("/catalog").json()
    assert catalog["mode"] == "folder"
    assert catalog["folder"] == "holidays"
    assert len(catalog["photos"]) == 1
    assert catalog["photos"][0]["modified"].startswith("2024-01-02")
    months = client.post("/view", data={"apply": "months", "months": "2026-09"},
                          follow_redirects=False)
    assert months.status_code == 303
    by_month = client.get("/catalog").json()
    assert by_month["mode"] == "months"
    assert by_month["photos"][0]["modified"].startswith("2026-09-12")
    reset = client.post("/reset", follow_redirects=False)
    assert reset.status_code == 303
    restored = client.get("/catalog").json()
    assert restored["mode"] == "folder"
    assert restored["folder"] is None
    assert len(restored["photos"]) == 2


def test_a_failed_list_sets_a_flag_and_hides_the_exception(tmp_path):
    def explode(_storage):
        raise RuntimeError("https://oss-cn-hongkong.aliyuncs.com/photos/secret.jpg")

    library = Library(object(), interval=0, lister=explode)
    run_sync(library)
    session = Session("ada", 9_999_999_999, "folder", None, (), 5)
    body = json.dumps(library.catalog(session, b"k" * 32))
    assert library.sync_problem is True
    assert "aliyuncs" not in body
    assert "photos/" not in body
    assert "sync_problem" in body


def test_a_cookie_works_on_another_instance(tmp_path):
    app, _newer = _app(tmp_path)
    first = TestClient(app)
    signed_in = _login(first)
    token = signed_in.cookies["digitalframe_session"]
    first.post("/view", data={"apply": "folder", "folder": "holidays"}, follow_redirects=False)
    shared = first.cookies["digitalframe_session"]
    assert shared != token

    other, _again = _app(tmp_path)
    second = TestClient(other)
    second.cookies.set("digitalframe_session", shared)
    catalog = second.get("/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["folder"] == "holidays"
    photo_id = catalog.json()["photos"][0]["id"]
    assert "photos/" not in photo_id
    assert second.get(f"/media/{photo_id}").status_code == 200


def test_heic_is_converted_in_memory_and_not_stored(tmp_path):
    from PIL import Image
    from io import BytesIO

    payload = heic_bytes()
    storage, client = _storage({
        "photos/kids/portrait.heic": {
            "body": payload, "etag": '"heic"',
            "modified": datetime(2026, 9, 12, tzinfo=timezone.utc),
        },
    })
    users_file = tmp_path / "users.yaml"
    users_file.write_text(
        "users:\n  - name: ada\n    passcode: \"correct-pass\"\n", encoding="utf-8")
    settings = make_settings(tmp_path, cookie_secure=False)
    library = Library(storage, interval=3600, jpeg_quality=75)
    app = create_app(
        settings, library, load_users(users_file), Sessions(), LoginLimiter(),
        ensure_session_key(tmp_path / "secrets" / "session.key"))
    browser = TestClient(app)
    _login(browser)
    photo_id = browser.get("/catalog").json()["photos"][0]["id"]
    media = browser.get(f"/media/{photo_id}")
    assert media.headers["content-type"].startswith("image/jpeg")
    assert media.content != payload
    with Image.open(BytesIO(media.content)) as image:
        assert image.format == "JPEG"
    assert client.put_object.call_count == 0
