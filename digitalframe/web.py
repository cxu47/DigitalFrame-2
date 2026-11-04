"""The slideshow site. Photo bytes stay behind the session cookie."""

from html import escape
import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .auth import COOKIE_NAME, authenticate
from .config import parse_display_seconds
from .library import Library


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

    @app.get("/")
    @app.get("/login")
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
        response = HTMLResponse(_render(page, signed_in=True))
        _set_session_cookie(response, token, request, settings, sessions)
        return response

    @app.get("/catalog")
    def catalog(request: Request):
        session, denial = require(request)
        if denial is not None:
            return denial
        return library.catalog(session, session_key)

    @app.get("/media/{token}")
    def media(token: str, request: Request, descale: str = ""):
        session, denial = require(request)
        if denial is not None:
            return denial
        played = library.media(token, session_key, session, descale=descale in {"1", "true", "on"})
        if played is None:
            return Response(status_code=404)
        body, media_type = played
        return Response(body, media_type=media_type, headers=MEDIA_HEADERS)

    @app.post("/reset")
    def reset(request: Request):
        session, denial = require(request)
        if denial is not None:
            return denial
        token = sessions.update(
            session_key, request.cookies.get(COOKIE_NAME), mode="folder", folder=None,
            months=(), display_seconds=settings.display_seconds)
        if token is None:
            return JSONResponse({"detail": "Sign in."}, status_code=401)
        response = HTMLResponse(_render(page, signed_in=True))
        _set_session_cookie(response, token, request, settings, sessions)
        return response

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
            updated = sessions.update(session_key, token, display_seconds=seconds)
        elif apply == "months":
            try:
                chosen = tuple(dict.fromkeys(months))
                if any(not _valid_month(month) for month in chosen):
                    raise ValueError
            except (TypeError, ValueError):
                return HTMLResponse(
                    _render(page, signed_in=True, error_code="months"), status_code=422)
            updated = sessions.update(session_key, token, mode="months", months=chosen)
        else:
            album = folder.strip()
            if album and (album in {".", ".."} or "/" in album or "\\" in album):
                return HTMLResponse(
                    _render(page, signed_in=True, error_code="folder"), status_code=422)
            updated = sessions.update(session_key, token, mode="folder", folder=album or None)
        if updated is None:
            return JSONResponse({"detail": "Sign in."}, status_code=401)
        response = HTMLResponse(_render(page, signed_in=True))
        _set_session_cookie(response, updated, request, settings, sessions)
        return response

    return app


def _set_session_cookie(response, token, request, settings, sessions):
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", path="/",
        secure=_browser_is_https(request), max_age=sessions.ttl)


def _browser_is_https(request):
    """Use the scheme the browser used, not an internal HTTP hop."""
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded in {"https", "http"}:
        return forwarded == "https"
    return request.url.scheme == "https"


def run_sync(library):
    """List once. A failure is a flag, not a message for the browser."""
    library.ensure()


def _render(page, *, signed_in, error_code=""):
    shown = "slideshow" if signed_in else "login"
    return (page.replace("{{BODY_CLASS}}", shown)
            .replace("{{LOGIN_ATTR}}", "" if shown == "login" else "hidden")
            .replace("{{APP_ATTR}}", "" if shown == "slideshow" else "hidden")
            .replace("{{ERROR_CODE}}", error_code)
            .replace("{{ERROR}}", escape(ERRORS.get(error_code, ""))))


def _valid_month(value):
    return (isinstance(value, str) and len(value) == 7 and value[4] == "-"
            and value[:4].isdigit() and value[5:].isdigit() and 1 <= int(value[5:]) <= 12)
