# Phase 2 — Sync library

Date: 2026-10-30  
Status: not started.  
Requires: [01-repository.md](01-repository.md) exit check.  
Next: [03-slideshow-site.md](03-slideshow-site.md)

## Outcome

A `digitalframe sync` command fills `cache/` from the Hong Kong bucket using the photo rules in [00-sequence.md](00-sequence.md). Tests prove those rules with a fake OSS client. This phase does not open a port.

## Packages

Add these direct dependencies and lock them. Start from the pins already used by DigitalFrame for the shared libraries. Do not upgrade them in this phase.

| Package | Pin to start from | Role |
| --- | --- | --- |
| `alibabacloud-oss-v2` | `1.4.0` | List and download |
| `pillow` | `12.3.0` | Decode, transpose, resize |
| `pillow_heif` | `1.4.0` | HEIC and HEIF |
| `python-dotenv` | `1.2.3` | Read `.env` and `secrets/oss.env` |
| `typer` | `0.27.2` | `digitalframe sync` |

Development group: `pytest==9.1.1`. Runtime install stays `uv sync --locked --no-dev`.

`OSS_CREDENTIALS_FILE` is read with `dotenv_values` on each sync. Its values are not exported into the process environment.

## Modules

```text
digitalframe/
├── config.py      settings and OSS credentials
├── catalog.py     records, month buckets, newest-first order
├── storage.py     confined list and download
├── images.py      HEIC conversion, EXIF, resize, publish
├── sync.py        one pass, manifest, lock, cleanup
└── cli.py         digitalframe sync
tests/
├── test_catalog.py
├── test_storage.py
├── test_images.py
└── test_sync.py
```

`[project.scripts]` maps `digitalframe` to `digitalframe.cli:main`. The only command in this phase is `sync`.

## OSS listing

Match the current DigitalFrame confinement rules.

- `OSS_PREFIX` defaults to `photos/`. Reject empty, absolute, and `..` prefixes.
- `OSS_ENDPOINT`, when set, must start with `https://`.
- List the prefix with `ListObjectsV2` and delimiter `/`. Each common prefix is one album. An album name is a single path segment.
- Inside an album, list again with delimiter `/`. Keep objects whose key is `photos/<album>/<file>` and whose suffix is a source suffix.
- Skip the album marker key (`photos/<album>/`). Remember its last-modified time as the album time when present.
- Ignore loose objects directly under `photos/` and any key with more than one slash after the prefix.
- Paginate until the listing ends. One client is used for the whole pass.
- `created` and `modified` are the object last-modified time in UTC `Z` form. ListObjects does not provide capture time.
- `month` is `YYYY-MM` from that timestamp, or absent when the timestamp is missing.
- A download path must still match `photos/<album>/<file>` before `GetObject`.

## Cache publication

- Stream the body to a temporary file under a staging directory inside the cache. Check size. When the response includes CRC-64, check it. Delete the temp file on any failure.
- HEIC and HEIF always become `<stem>.jpg` at `IPHONE_JPEG_QUALITY`. A JPEG with the same stem in that album gets a stable suffix derived from the object key.
- JPEG, PNG, and WebP: apply EXIF transpose and a proportional shrink only when the oriented pixels exceed `CACHE_MAX_WIDTH` by `CACHE_MAX_HEIGHT`. Quality for a reduced JPEG or WebP is `OTHER_IMAGE_QUALITY`. Reduced PNG stays lossless. Otherwise keep the original bytes.
- Never enlarge. Never stretch.
- Unsafe album or file names are normalized. Duplicate playback names in one album get distinct stable suffixes. Published paths have exactly two components and are not symlinks.
- Write `cache/.photos.json` only at the end of a fully successful pass. Record the object key, etag, source size, modified time, month, processing profile, published path, and SHA-256 of the published file.
- Reuse a published file when the etag, processing profile, and SHA-256 still match. Do not download it again.
- After success, delete supported photos in immediate cache albums that are absent from the new catalog, then remove album directories that are empty and absent from OSS. Leave dotfiles, including `.photos.json` and `.sync.lock`, in place.
- If listing or any download fails, leave the previous catalog and files untouched. Do not run deletion.
- `.sync.lock` in the cache directory allows one sync at a time. A second process exits with a nonzero status.

## Ordering helper

`catalog.py` sorts a photo list newest-modified first. Equal timestamps sort by published path. Photos with no timestamp sort last, then by path. Filtering accepts one album name, or a set of `YYYY-MM` months. Month filtering ignores album boundaries. An empty result is valid and means the waiting screen in phase 3.

This module does not sleep, start threads, or open sockets.

## Tests

No network, no `.env`, and no real credentials. Pass a fake client into the storage functions.

- Prefix rejection, including a non-HTTPS endpoint.
- An object outside the prefix cannot be downloaded.
- Loose and nested keys are absent from the catalog.
- An empty album marker still yields the album.
- HEIC becomes a same-stem JPEG. A colliding JPEG keeps a different name.
- A second successful sync removes a photo deleted from the fake bucket.
- A failed download in the middle leaves the previous cache file in place.
- Month buckets and newest-first order follow the fixture timestamps.

## Exit check

`uv run --no-sync python -m pytest -q` passes. With a real `secrets/oss.env`, `uv run --no-sync digitalframe sync` is the manual check against the Hong Kong bucket and is not part of the automated exit.
