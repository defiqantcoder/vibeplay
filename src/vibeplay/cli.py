"""Command-line interface for vibeplay using Typer and Rich."""

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from vibeplay.config import get_settings
from vibeplay.enrichment import enrich_tracks, get_report_data
from vibeplay.scanner import scan_directory

logger = logging.getLogger("vibeplay")
console = Console()

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
    db: Annotated[
        Path | None,
        typer.Option(
            help="Path to SQLite database (defaults to configured path)",
        ),
    ] = None,
) -> None:
    """Scan music directory recursively, index audio files, and extract tags."""
    resolved_path = path.expanduser().resolve()
    if not resolved_path.exists() or not resolved_path.is_dir():
        console.print(
            f"[bold red]Error:[/bold red] '{resolved_path}' is not a directory."
        )
        raise typer.Exit(code=1)

    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    console.print(f"[bold]Scanning library:[/bold] [cyan]{resolved_path}[/cyan]")
    console.print(f"[bold]Target database:[/bold]  [cyan]{db_path}[/cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Discovering audio files...", total=None)

        def progress_callback(current: int, total: int, file_path: Path) -> None:
            if progress.tasks[task_id].total != total:
                progress.update(task_id, total=total)
            progress.update(
                task_id,
                completed=current,
                description=f"Scanning: [dim]{file_path.name[:35]}[/dim]",
            )

        summary = scan_directory(
            library_path=resolved_path,
            db_path=db_path,
            progress_callback=progress_callback,
        )

    # Final summary display
    table = Table(title=f"Scan Summary: {resolved_path.name}", show_header=True)
    table.add_column("Category", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("New", f"[green]{summary.new}[/green]")
    table.add_row("Updated", f"[yellow]{summary.updated}[/yellow]")
    table.add_row("Unchanged", f"[blue]{summary.unchanged}[/blue]")
    table.add_row("Missing", f"[red]{summary.missing}[/red]")
    table.add_row(
        "Errors",
        f"[magenta]{summary.errors}[/magenta]" if summary.errors else "0",
    )
    table.add_section()
    table.add_row("Total Processed", str(summary.total_processed))

    console.print()
    console.print(table)


@app.command()
def enrich(
    report: Annotated[
        bool,
        typer.Option(
            "--report",
            "-r",
            help="Display report of unmatched and low-confidence tracks",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum number of tracks to enrich in this run"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(help="Re-enrich tracks that already have enrichment records"),
    ] = False,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database"),
    ] = None,
) -> None:
    """Fingerprint audio tracks and query MusicBrainz for canonical metadata."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    if report:
        report_rows = get_report_data(db_path)
        if not report_rows:
            console.print(
                f"[bold green]✓[/bold green] All active tracks are matched with high confidence "
                f"(>= {settings.enrichment_confidence_threshold:.0%}). No tracks need review."
            )
            return

        table = Table(
            title=f"Enrichment Review Report (Threshold: {settings.enrichment_confidence_threshold:.0%})",
            show_header=True,
        )
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Original Metadata", style="bold")
        table.add_column("Canonical Match")
        table.add_column("Status", justify="center")
        table.add_column("Confidence", justify="right")

        for row in report_rows:
            orig = f"{row.get('original_artist') or 'Unknown'} - {row.get('original_title') or 'Unknown'}"
            canon_artist = row.get("canonical_artist")
            canon_title = row.get("canonical_title")
            canon = (
                f"{canon_artist} - {canon_title}"
                if canon_artist and canon_title
                else "[dim]None[/dim]"
            )

            status = row.get("enrichment_status") or "not_enriched"
            if status == "matched":
                status_style = "[green]matched[/green]"
            elif status == "needs_review":
                status_style = "[yellow]needs_review[/yellow]"
            elif status == "unmatched":
                status_style = "[red]unmatched[/red]"
            else:
                status_style = f"[magenta]{status}[/magenta]"

            conf = row.get("confidence")
            conf_str = f"{conf:.1%}" if conf is not None else "N/A"

            table.add_row(
                str(row["track_id"]),
                orig,
                canon,
                status_style,
                conf_str,
            )

        console.print()
        console.print(table)
        console.print(
            f"\n[dim]Found {len(report_rows)} track(s) needing review or unmatched.[/dim]"
        )
        return

    console.print(f"[bold]Target database:[/bold] [cyan]{db_path}[/cyan]")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Enriching tracks...", total=None)

            def progress_callback(current: int, total: int, track_name: str) -> None:
                if progress.tasks[task_id].total != total:
                    progress.update(task_id, total=total)
                progress.update(
                    task_id,
                    completed=current,
                    description=f"Enriching: [dim]{track_name[:35]}[/dim]",
                )

            summary = enrich_tracks(
                db_path=db_path,
                limit=limit,
                force=force,
                progress_callback=progress_callback,
            )

    except ValueError as err:
        console.print(f"[bold red]Configuration Error:[/bold red] {err}")
        raise typer.Exit(code=1)

    table = Table(title="Enrichment Summary", show_header=True)
    table.add_column("Category", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Matched (High Confidence)", f"[green]{summary.matched}[/green]")
    table.add_row("Needs Review", f"[yellow]{summary.needs_review}[/yellow]")
    table.add_row("Unmatched", f"[blue]{summary.unmatched}[/blue]")
    table.add_row(
        "Errors", f"[magenta]{summary.errors}[/magenta]" if summary.errors else "0"
    )
    table.add_section()
    table.add_row("Total Processed", str(summary.total))

    console.print()
    console.print(table)


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
