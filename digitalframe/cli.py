"""Command line. sync fills the cache. serve is the slideshow site."""

import logging
from threading import Event, Thread

import typer
import uvicorn

from .auth import LoginLimiter, Sessions, load_session_key, load_users
from .config import load_oss_config, load_settings
from .library import Library
from .storage import open_storage
from .sync import sync_once
from .web import create_app, run_sync


app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def cli():
    """Private family slideshow backed by Alibaba Cloud OSS."""


@app.command()
def sync():
    """List the OSS albums and fill the local cache."""
    try:
        settings = load_settings()
        logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
        storage = open_storage(load_oss_config(settings), settings.network_timeout)
        result = sync_once(settings.cache_dir, storage, settings)
    except Exception as exc:
        typer.echo(f"{type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from None
    if not result.success:
        typer.echo(result.error or "Sync failed.", err=True)
        raise typer.Exit(1)
    typer.echo(f"Photo sync completed: {result.downloaded} downloaded.")


@app.command()
def serve():
    """Open the slideshow site and keep syncing in the background."""
    try:
        settings = load_settings()
        logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
        users = load_users(settings.root / settings.users_file)
        session_key = load_session_key(settings)
    except Exception as exc:
        typer.echo(f"{type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from None
    storage = None
    try:
        storage = open_storage(load_oss_config(settings), settings.network_timeout)
    except Exception:
        logging.exception("OSS is not configured; the show will wait for photos")
    library = Library(
        storage, interval=settings.sync_interval,
        jpeg_quality=settings.iphone_jpeg_quality,
        other_quality=settings.other_image_quality,
        max_width=settings.cache_max_width,
        max_height=settings.cache_max_height)
    web = create_app(settings, library, users, Sessions(), LoginLimiter(), session_key)
    stop = Event()

    def loop():
        while not stop.is_set():
            run_sync(library)
            stop.wait(settings.sync_interval)

    worker = None
    if settings.background_sync:
        worker = Thread(target=loop, name="digitalframe-sync", daemon=True)
        worker.start()
    try:
        uvicorn.run(web, host=settings.host, port=settings.port,
                    log_level=settings.log_level.lower())
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=1)


def main():
    app()
