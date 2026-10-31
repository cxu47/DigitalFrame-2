# DigitalFrame-2

DigitalFrame-2 is a private family slideshow. A Python process lists photos in an Alibaba Cloud OSS bucket in Hong Kong, keeps a local derivative cache, and shows them in a browser. Viewers in mainland China open the site over HTTPS. They never receive OSS credentials or object URLs.

This is a new repository. The Raspberry Pi frame in `../DigitalFrame` stays as it is: MPV, the Wi-Fi hotspot, and offline playback are not part of this rewrite.

The photo layout is the same. Only files directly inside an immediate album folder are used:

```text
photos/
├── Theo/
│   └── IMG_2417.jpeg
├── holidays/
│   └── IMG_2413.jpeg
└── loose.jpg          (ignored)
```

JPEG, PNG, and WebP are shown as stored. HEIC and HEIF are converted to JPEG in memory for that request and are not saved again.

## Status

Phases 1 through 5 are in this checkout. `digitalframe serve` reads photos from OSS. Phase 4 is the always-on Hong Kong virtual machine. Phase 5 can also run as Function Compute; creating that function is still a manual step in [the runbook](deploy/function-compute.md).

| Phase | Plan | Result |
| --- | --- | --- |
| 1 | [Repository](.plans/01-repository.md) | This checkout |
| 2 | [Sync library](.plans/02-sync-library.md) | Cache filled from OSS, tested without the network |
| 3 | [Slideshow site](.plans/03-slideshow-site.md) | Login, canvas playback, focus blackout |
| 4 | [Hong Kong host](.plans/04-hong-kong-host.md) | Same process on ECS in `cn-hongkong` |
| 5 | [Function Compute](.plans/05-function-compute.md) | Reads OSS on a visit. The cloud function is still created by hand |

Do not start a phase until the previous phase's exit check is true.

## Local setup

uv is the package manager. From this directory:

```bash
uv sync --locked
cp -n .env.example .env
cp -n secrets/oss.env.example secrets/oss.env
cp -n users.example.yaml users.yaml
```

Edit `secrets/oss.env` and `users.yaml` on the machine that runs the app. Neither file is committed. Quote each passcode in `users.yaml` so it stays text.

Sync once the OSS file points at the Hong Kong bucket:

```bash
uv run --no-sync digitalframe sync
```

The command lists `photos/<album>/<file>`, downloads into `cache/`, and writes `cache/.photos.json` only after a pass that had no failures. A failed download leaves the previous cache in place.

Open the site on this machine:

```bash
uv run --no-sync digitalframe serve
```

That listens on `127.0.0.1:8000` unless `.env` says otherwise. A passcode from `users.yaml` opens the slideshow. The names in that file are labels. The page is black while the window is in the background. Photos are drawn on a canvas, so the usual Save image action is not offered. Reset reloads the show from the beginning.

Automated checks use a fake OSS client:

```bash
uv run --no-sync python -m pytest -q
```
