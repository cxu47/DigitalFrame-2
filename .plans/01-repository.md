# Phase 1 — Repository

Date: 2026-10-30  
Status: done in the initial checkout.  
Next: [02-sync-library.md](02-sync-library.md)

## Outcome

`/home/chang/learning/DigitalFrame-2` is its own git repository on `main`, with a uv project and no application behavior. Secrets have example files only. The later phases have a written order.

## Checklist

- [x] Create the repository beside `DigitalFrame`, not inside that checkout.
- [x] Initialize git on `main`. Do not add a remote until one is asked for.
- [x] Add `pyproject.toml` for `digitalframe-2`, Python `>=3.12,<3.15`, and an empty runtime dependency list. Package `digitalframe`.
- [x] Generate `uv.lock` and ignore `.venv`.
- [x] Ignore `.env`, `users.yaml`, `secrets/*` except `oss.env.example`, and `cache/*` except `.gitkeep`.
- [x] Commit `.env.example`, `secrets/oss.env.example`, and `users.example.yaml` with placeholder values. Region example is `cn-hongkong`.
- [x] Write the phase plans and link them from the README.
- [x] Leave sync, HTTP, login, and deployment files for later phases.

## Layout this phase creates

```text
DigitalFrame-2/
├── .plans/
│   ├── 00-sequence.md
│   ├── 01-repository.md
│   ├── 02-sync-library.md
│   ├── 03-slideshow-site.md
│   └── 04-hong-kong-host.md
├── digitalframe/
│   └── __init__.py
├── cache/.gitkeep
├── secrets/oss.env.example
├── .env.example
├── users.example.yaml
├── pyproject.toml
├── uv.lock
└── README.md
```

## Exit check

From the repository root, `uv sync --locked` completes, and `git status` does not list `users.yaml`, `secrets/oss.env`, or `.env`.
