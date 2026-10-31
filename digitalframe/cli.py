"""Command line. This phase provides sync and does not open a port."""

import logging

import typer

from .config import load_oss_config, load_settings
from .storage import open_storage
from .sync import sync_once


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


def main():
    app()
