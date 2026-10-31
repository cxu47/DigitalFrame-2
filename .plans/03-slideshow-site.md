# Phase 3 — Slideshow site

Date: 2026-10-30  
Status: not started.  
Requires: [02-sync-library.md](02-sync-library.md) exit check.  
Next: [04-hong-kong-host.md](04-hong-kong-host.md)

## Outcome

`digitalframe serve` listens on `HOST` and `PORT` from `.env` (default `127.0.0.1:8000`). A person in `users.yaml` can sign in and watch the cached photos. The page goes black when it loses focus. Ordinary browser save-image actions do not work. OSS keys and URLs never appear in HTML, JSON, or response headers.

## Packages

Add and lock, starting from the DigitalFrame pins where they exist:

| Package | Pin to start from | Role |
| --- | --- | --- |
| `fastapi` | `0.141.1` | Routes |
| `uvicorn` | `0.52.4` | Server |
| `python-multipart` | `0.0.32` | Login form |
| `PyYAML` | version uv resolves, then pin it | `users.yaml` |

Keep `starlette` as a transitive dependency of FastAPI. Do not add a frontend toolchain.

## Modules

```text
digitalframe/
├── auth.py
├── web.py
└── templates/slideshow.html
tests/
├── test_auth.py
└── test_web.py
```

`digitalframe sync` from phase 2 stays a one-shot command with no HTTP server. `digitalframe serve` starts the site and a background sync loop at `SYNC_INTERVAL`. The site serves the cache it already has while a sync is running or failing.

## Passcodes

- Load `USERS_FILE` (default `users.yaml`) at process start. The file is a YAML list under `users`, each entry a `name` and a `passcode`.
- Reject a missing file, an empty user list, a blank name, a blank passcode, and duplicate names, and exit before binding the port.
- Compare name and passcode with `hmac.compare_digest` after encoding both as UTF-8. Do not trim the passcode.
- The login error is always `That name or passcode is not recognized.`
- Do not log the passcode, the YAML body, or the session token.
- After 5 failed attempts from one client address inside 15 minutes, respond `429` and accept no further attempt from that address until the window passes. Keep the counter in memory.

Session:

- On success, set one cookie. Name: `digitalframe_session`. `HttpOnly`, `SameSite=Strict`, path `/`. `Secure` follows `COOKIE_SECURE`.
- The cookie value is an opaque random token. The server stores the user name and expiry in memory. Sessions last 12 hours and are renewed when a signed-in page is used.
- The signing key is `secrets/session.key`, created on first run with 32 random bytes and mode `0600`. It is gitignored because the whole `secrets/` directory is ignored except the OSS example.
- `POST /logout` clears the cookie and forgets the token.

## Routes

| Method and path | Who | Behavior |
| --- | --- | --- |
| `GET /` | Public | Login form when signed out. Slideshow page when signed in. |
| `POST /login` | Public | Form fields `name` and `passcode`. Success redirects to `/`. Failure redisplays the form with the single error sentence. |
| `POST /logout` | Session | Clear the session and redirect to `/`. |
| `GET /catalog` | Session | JSON: albums, months, and photo ids for the caller's current filter. Photo ids are random tokens for this process, not object keys. |
| `GET /media/{id}` | Session | Bytes of one cached playback file. Unknown or logged-out id is 404. |
| `POST /view` | Session | Update this session's folder, months, and `display_seconds`. |

Every route except `GET /` and `POST /login` returns 401 without a live session. `/media` and `/catalog` do not redirect.

`/media` headers:

- `Cache-Control: no-store`
- `X-Content-Type-Options: nosniff`
- `Content-Disposition: inline`
- `Referrer-Policy: no-referrer`
- `Content-Security-Policy: default-src 'self'`

The catalog JSON contains album names, `YYYY-MM` months, picture counts, playback ids, and modified times. It does not contain object keys, etags, the bucket, or the endpoint.

## Page behavior

One HTML file, served by the app, with a plain `<style>` and `<script>` block. No image elements. No remote fonts, scripts, or stylesheets.

- The stage background is black. Photos are drawn onto a canvas from `fetch` of `/media/{id}` as a blob, then `createImageBitmap`, then `drawImage`. Revoke the blob URL in the same function that created it.
- A transparent shield covers the canvas and receives pointer events. `contextmenu`, drag start, and drop call `preventDefault`. CSS sets `user-select: none` and `-webkit-touch-callout: none` on the stage.
- A black veil sits above the shield. Show it, clear the canvas bitmap, and pause the timer when `document.hidden` is true or `document.hasFocus()` is false. Hide it and resume only when the document is visible and focused again. Clicking a control on this page does not count as losing focus.
- Folder control: `All` plus one entry per album. Month control: the UTC months present in the cache, any subset. Applying months shows the union of those months across albums. Applying a folder leaves the month checkboxes as they were and switches the active mode back to folder. One small label shows which mode is active.
- `display_seconds` accepts a positive integer, the same rule as DigitalFrame (`5` is valid, `5.0` is not). The value lives in the session, defaulting from `DISPLAY_SECONDS`. It applies to the next photo.
- Order inside the active filter is the phase 2 newest-first order. When a sync publishes ids the page has not shown yet, those ids play next, once, then the rotation continues.
- No photos in the active filter: show `Waiting for photos` on the black stage.
- A failed background sync keeps playing the current cache and shows `Cannot reach the photo library`. The page does not show the exception text.

## Tests

Use FastAPI's test client and a temporary cache. No browser and no OSS.

- Missing and wrong passcodes receive the same response and set no cookie.
- A correct passcode sets the cookie. `/media` without the cookie is 401.
- `/catalog` and `/media` bodies contain no `oss-`, `aliyuncs`, or `photos/` object-key string from the fixture.
- `/media` sends `no-store` and `inline`.
- The sixth failure from one address inside the window is 429.
- The template contains no `<img`.
- A unit test of the page script's focus rule is not required. The manual exit check below covers blur.

## Exit check

Automated tests pass. Manually, on localhost: a wrong passcode stays on the login form, a correct one plays a fixture image, right-click on the photo does not offer Save image as, and clicking another window turns the page black until focus returns.
