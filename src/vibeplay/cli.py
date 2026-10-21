"""Command-line interface for vibeplay using Typer."""

import logging
from pathlib import Path
from typing import Annotated

import typer

logger = logging.getLogger("vibeplay")

app = typer.Typer(
    name="vibeplay",
    help="Local music library scanner, metadata enricher, and vibe-based smart playlist generator.",
    no_args_is_help=True,
)


@app.command()
def scan(
    path: Annotated[
        Path,
        typer.Argument(
            help="Path to the music directory to scan (strictly read-only)",
        ),
    ] = Path("."),
) -> None:
    """Scan music directory recursively, index audio files, and extract tags."""
    typer.echo("not implemented")


@app.command()
def enrich(
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum number of tracks to enrich"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(help="Re-enrich tracks that already have enrichment records"),
    ] = False,
) -> None:
    """Fingerprint audio tracks and query MusicBrainz for canonical metadata."""
    typer.echo("not implemented")


@app.command()
def analyze(
    fallback_librosa: Annotated[
        bool,
        typer.Option(help="Force fallback to librosa instead of Essentia"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(help="Re-analyze tracks that already have feature records"),
    ] = False,
) -> None:
    """Analyze audio files to extract acoustic features, rhythm, and embeddings."""
    typer.echo("not implemented")


@app.command()
def clusters(
    k: Annotated[
        int,
        typer.Option(help="Number of clusters to generate for k-means"),
    ] = 5,
    algorithm: Annotated[
        str,
        typer.Option(help="Clustering algorithm to use (kmeans, hdbscan)"),
    ] = "kmeans",
) -> None:
    """Compute normalized vibe vectors and generate track clusters."""
    typer.echo("not implemented")


@app.command()
def playlist(
    name: Annotated[
        str,
        typer.Option(help="Name of the generated playlist"),
    ] = "Vibe Playlist",
    seed: Annotated[
        int | None,
        typer.Option(help="Track ID to use as seed for similarity matching"),
    ] = None,
    vibe: Annotated[
        str | None,
        typer.Option(help="Target vibe or mood descriptor"),
    ] = None,
    arc: Annotated[
        str | None,
        typer.Option(help="Trajectory arc name (e.g., warmup-peak-cooldown)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(help="Maximum number of tracks in the playlist"),
    ] = 25,
) -> None:
    """Generate a smart playlist based on seed track, target vibe, or arc."""
    typer.echo("not implemented")


@app.command()
def export(
    playlist_id: Annotated[
        int,
        typer.Argument(help="ID of the playlist to export"),
    ],
    out: Annotated[
        Path,
        typer.Option(help="Destination file path for export"),
    ] = Path("playlist.m3u8"),
    format: Annotated[
        str,
        typer.Option(help="Export format (m3u, m3u8, json, csv)"),
    ] = "m3u8",
) -> None:
    """Export a saved playlist to an M3U, M3U8, JSON, or CSV file."""
    typer.echo("not implemented")


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option(help="Host address to bind to"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option(help="Port number to listen on"),
    ] = 8000,
) -> None:
    """Launch the local FastAPI web server and user interface."""
    typer.echo("not implemented")


if __name__ == "__main__":
    app()
