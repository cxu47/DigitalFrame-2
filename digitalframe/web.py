"""The slideshow site. Photo bytes stay behind the session cookie."""

from html import escape
import json
import logging
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .auth import COOKIE_NAME, authenticate
from .catalog import filter_photos, photo_month, records_from_catalog, sort_photos
from .config import parse_display_seconds
from .sync import MANIFEST_NAME


logger = logging.getLogger(__name__)
ERRORS = {
    "passcode": "That passcode is not recognized.",
    "seconds": "Enter a positive whole number of seconds, such as 5.",
    "months": "Choose months as YYYY-MM.",
    "folder": "Choose a photo folder.",
    "locked": "Too many attempts. Try again later.",
}
TEMPLATE = Path(__file__).resolve().parent / "templates" / "slideshow.html"
TRANSLATIONS = Path(__file__).resolve().parent / "translations.json"
MEDIA_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Disposition": "inline",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'",
}
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class Library:
    """Playback ids for the current cache. Ids are random and are not object keys."""

    def __init__(self, cache):
        self.cache = Path(cache)
        self.sync_problem = False
        self._lock = Lock()
        self._token_by_path = {}
        self._path_by_token = {}

    def set_sync_problem(self, failed):
        with self._lock:
            self.sync_problem = failed

    def catalog(self, session):
        records = sort_photos(self._records())
        if session.mode == "months":
            selected = filter_photos(records, months=session.months)
        else:
            selected = filter_photos(records, folder=session.folder)
        with self._lock:
            photos = [{"id": self._token(record.path), "modified": record.modified}
                      for record in selected]
            sync_problem = self.sync_problem
        return {
            "mode": session.mode,
            "folder": session.folder,
            "selected_months": list(session.months),
            "display_seconds": session.display_seconds,
            "sync_problem": sync_problem,
            "albums": _albums(records),
            "months": _months(records),
            "photos": photos,
        }

    def file(self, token):
        with self._lock:
            relative = self._path_by_token.get(token)
        if relative is None:
            return None
        return _playback_file(self.cache, relative)

    def _records(self):
        catalog = _read_manifest(self.cache)
        records = []
        for record in records_from_catalog(catalog):
            if _playback_file(self.cache, record.path) is None:
                continue
            month = record.month if _valid_month(record.month) else photo_month(record.modified)
            records.append(record if month == record.month
                           else type(record)(record.id, record.album, record.path, record.modified, month))
        return records

    def _token(self, relative):
        token = self._token_by_path.get(relative)
        if token is None:
            from secrets import token_urlsafe
            token = token_urlsafe(18)
            self._token_by_path[relative] = token
            self._path_by_token[token] = relative
        return token


def create_app(settings, library, users, sessions, limiter, session_key):
    page = TEMPLATE.read_text(encoding="utf-8")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def current(request):
        return sessions.get(session_key, request.cookies.get(COOKIE_NAME))

    def require(request):
        session = current(request)
        if session is None:
            return None, JSONResponse({"detail": "Sign in."}, status_code=401)
        return session, None

    @app.get("/translations.json")
    def translations():
        return Response(TRANSLATIONS.read_bytes(), media_type="application/json")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        session = current(request)
        if session is None:
            return HTMLResponse(_render(page, signed_in=False))
        return HTMLResponse(_render(page, signed_in=True))

    @app.post("/login")
    def login(request: Request, passcode: str = Form("")):
        address = request.client.host if request.client is not None else "unknown"
        if limiter.blocked(address):
            return HTMLResponse(
                _render(page, signed_in=False, error_code="locked"), status_code=429)
        user = authenticate(users, passcode)
        if user is None:
            limiter.fail(address)
            return HTMLResponse(
                _render(page, signed_in=False, error_code="passcode"), status_code=401)
        limiter.succeed(address)
        token = sessions.start(session_key, user.name, settings.display_seconds)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE_NAME, token, httponly=True, samesite="strict", path="/",
            secure=settings.cookie_secure, max_age=sessions.ttl)
        return response

    @app.get("/catalog")
    def catalog(request: Request):
        session, denial = require(request)
        if denial is not None:
            return denial
        return library.catalog(session)

    @app.get("/media/{token}")
    def media(token: str, request: Request):
        session, denial = require(request)
        if denial is not None:
            return denial
        path = library.file(token)
        if path is None:
            return Response(status_code=404)
        return Response(path.read_bytes(), media_type=CONTENT_TYPES[path.suffix.lower()],
                        headers=MEDIA_HEADERS)

    @app.post("/reset")
    def reset(request: Request):
        session, denial = require(request)
        if denial is not None:
            return denial
        sessions.update(
            request.cookies.get(COOKIE_NAME), mode="folder", folder=None, months=(),
            display_seconds=settings.display_seconds)
        return RedirectResponse("/", status_code=303)

    @app.post("/view")
    def view(request: Request, apply: str = Form(""), folder: str = Form(""),
             display_seconds: str = Form(""), months: list[str] = Form(default=[])):
        session, denial = require(request)
        if denial is not None:
            return denial
        token = request.cookies.get(COOKIE_NAME)
        if apply == "seconds":
            try:
                seconds = parse_display_seconds(display_seconds)
            except ValueError:
                return HTMLResponse(
                    _render(page, signed_in=True, error_code="seconds"), status_code=422)
            sessions.update(token, display_seconds=seconds)
        elif apply == "months":
            try:
                chosen = tuple(dict.fromkeys(months))
                if any(not _valid_month(month) for month in chosen):
                    raise ValueError
            except (TypeError, ValueError):
                return HTMLResponse(
                    _render(page, signed_in=True, error_code="months"), status_code=422)
            sessions.update(token, mode="months", months=chosen)
        else:
            album = folder.strip()
            if album and (album in {".", ".."} or "/" in album or "\\" in album):
                return HTMLResponse(
                    _render(page, signed_in=True, error_code="folder"), status_code=422)
            sessions.update(token, mode="folder", folder=album or None)
        return RedirectResponse("/", status_code=303)

    return app


def run_sync(settings, library, open_storage, load_oss_config, sync_once):
    """One background pass. A failure is a flag, not a message for the browser."""
    try:
        storage = open_storage(load_oss_config(settings), settings.network_timeout)
        result = sync_once(settings.cache_dir, storage, settings)
        library.set_sync_problem(not result.success)
    except Exception:
        logger.exception("Photo sync failed")
        library.set_sync_problem(True)


def _render(page, *, signed_in, error_code=""):
    shown = "slideshow" if signed_in else "login"
    return (page.replace("{{BODY_CLASS}}", shown)
            .replace("{{LOGIN_ATTR}}", "" if shown == "login" else "hidden")
            .replace("{{APP_ATTR}}", "" if shown == "slideshow" else "hidden")
            .replace("{{ERROR_CODE}}", error_code)
            .replace("{{ERROR}}", escape(ERRORS.get(error_code, ""))))


def _albums(records):
    counts = {}
    modified = {}
    for record in records:
        counts[record.album] = counts.get(record.album, 0) + 1
        if record.modified and (record.album not in modified or record.modified > modified[record.album]):
            modified[record.album] = record.modified
    return [{"name": name, "count": counts[name], "modified": modified.get(name)}
            for name in sorted(counts)]


def _months(records):
    counts = {}
    for record in records:
        if record.month:
            counts[record.month] = counts.get(record.month, 0) + 1
    return [{"month": month, "count": counts[month]} for month in sorted(counts, reverse=True)]


def _valid_month(value):
    return (isinstance(value, str) and len(value) == 7 and value[4] == "-"
            and value[:4].isdigit() and value[5:].isdigit() and 1 <= int(value[5:]) <= 12)


def _read_manifest(cache):
    try:
        value = json.loads((cache / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _playback_file(cache, relative):
    path = Path(relative)
    if (not isinstance(relative, str) or path.is_absolute() or len(path.parts) != 2
            or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)):
        return None
    if path.suffix.lower() not in CONTENT_TYPES:
        return None
    destination = cache / path
    if destination.is_symlink() or destination.parent.is_symlink() or not destination.is_file():
        return None
    if cache.resolve() not in destination.resolve().parents:
        return None
    return destination
