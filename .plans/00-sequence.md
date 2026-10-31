# DigitalFrame-2 sequence

Date: 2026-10-30  
Status: phases 1 through 4 are in the repository. Phase 5 is a plan only.

## Decision

Build one Python process with FastAPI and a single slideshow page. Run it locally with uv first. Later, run that same process on an Alibaba Cloud ECS instance in `cn-hongkong`, next to the existing Hong Kong bucket.

Streamlit is the model for how the app should feel: one command, one URL, settings in files, no frontend build. The Streamlit library is not the server. It renders photos as image tags and remounts the page on each advance, which fights the focus blackout and the download shield.

The browser talks only to the app. The app talks to OSS. A CDN and public signed object URLs are out of scope because each one is a download link.

## Order

Each phase starts only after the previous exit check passes. Later plans assume the files and names from earlier plans.

| Phase | Plan | Depends on | Exit check |
| --- | --- | --- | --- |
| 1 | [01-repository.md](01-repository.md) | Nothing | `uv sync --locked` works and `git status` shows no secrets |
| 2 | [02-sync-library.md](02-sync-library.md) | Phase 1 | `pytest` covers album rules with a fake OSS client |
| 3 | [03-slideshow-site.md](03-slideshow-site.md) | Phase 2 | On localhost, a wrong passcode stays out, a focused page plays, and blur turns the page black |
| 4 | [04-hong-kong-host.md](04-hong-kong-host.md) | Phase 3 | The container image builds locally. Creating the VM is a separate, manual step |
| 5 | [05-function-compute.md](05-function-compute.md) | Phase 4 stays available | A visit wakes Function Compute in `cn-hongkong`, and idle time does not keep a virtual machine |

## Kept from DigitalFrame

- Prefix default `photos/`. Immediate child folders only. Loose objects and deeper keys are ignored.
- Source suffixes `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`. Playback suffixes omit HEIC and HEIF.
- Order by OSS last-modified, newest first. Equal timestamps use the path. Missing timestamps sort last.
- Month buckets are UTC `YYYY-MM` from that same timestamp.
- Fit inside 1600×900. Never enlarge. Other-image quality 85. iPhone JPEG quality 75. PNG stays lossless.
- EXIF orientation is applied when an image is converted or reduced. A file already inside the limit, and not HEIC/HEIF, stays byte-for-byte unchanged.
- Download to a temporary file. Publish only after the size matches and, when OSS sends one, CRC-64 matches.
- A failed sync does not delete cached photos. A fully successful sync removes album photos that OSS no longer has.

## Left in the Pi app

MPV, HDMI mode selection, the Wi-Fi hotspot, Google Drive, the on-device control panel, and board self-update. This web app does not play while the server is unreachable.

## Privacy limits

The focus blackout and the canvas shield remove the ordinary save-image actions. They do not stop a screenshot, a photo of the screen, or someone who is already logged in and uses developer tools. The plans state that limit in the tests so it is not treated as a bug later.
