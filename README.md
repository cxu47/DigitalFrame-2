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

JPEG, PNG, and WebP play as themselves. HEIC and HEIF are converted once to JPEG. Playback order is newest OSS last-modified first. A folder or a set of UTC months can narrow the show.

## Status

Phase 1 is the repository itself. There is no sync command and no website yet. The work after this is written down, in order, under [`.plans/`](.plans/00-sequence.md).

| Phase | Plan | Result |
| --- | --- | --- |
| 1 | [Repository](.plans/01-repository.md) | This checkout |
| 2 | [Sync library](.plans/02-sync-library.md) | Cache filled from OSS, tested without the network |
| 3 | [Slideshow site](.plans/03-slideshow-site.md) | Login, canvas playback, focus blackout |
| 4 | [Hong Kong host](.plans/04-hong-kong-host.md) | Same process on ECS in `cn-hongkong` |

Do not start a phase until the previous phase's exit check is true.

## Local setup

uv is the package manager. From this directory:

```bash
uv sync --locked
cp -n .env.example .env
cp -n secrets/oss.env.example secrets/oss.env
cp -n users.example.yaml users.yaml
```

Edit `secrets/oss.env` and `users.yaml` on the machine that runs the app. Neither file is committed. `uv sync` currently installs an empty runtime; phase 2 adds the OSS and image libraries.
