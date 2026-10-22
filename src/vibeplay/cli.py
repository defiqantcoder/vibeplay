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

from vibeplay.analysis import analyze_tracks
from vibeplay.config import get_settings
from vibeplay.db import get_connection, get_tracks_with_features
from vibeplay.enrichment import enrich_tracks, get_report_data
from vibeplay.exporter import export_playlist_to_file
from vibeplay.llm import batch_vibe_tag_tracks, parse_prompt_to_plan
from vibeplay.player import PlaybackError, play_playlist, play_seed
from vibeplay.playlist import PlaylistRuleConfig, generate_playlist
from vibeplay.scanner import scan_directory
from vibeplay.vectors import compute_clusters

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
        typer.Option(
            "--fallback-librosa",
            help="Force fallback to librosa instead of Essentia",
        ),
    ] = False,
    backend: Annotated[
        str | None,
        typer.Option(
            "--backend",
            help="Preferred analysis backend ('essentia' or 'librosa')",
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(
            "--workers",
            "-w",
            help="Number of parallel worker processes (default: CPU count - 1)",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Re-analyze tracks that already have feature records",
        ),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help="Maximum number of tracks to analyze",
        ),
    ] = None,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database"),
    ] = None,
) -> None:
    """Analyze audio files to extract acoustic features, rhythm, and embeddings."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    selected_backend = (
        "librosa" if fallback_librosa else (backend or settings.analyzer_backend)
    )

    console.print(f"[bold]Target database:[/bold]   [cyan]{db_path}[/cyan]")
    console.print(f"[bold]Analysis engine:[/bold]   [cyan]{selected_backend}[/cyan]")
    console.print(
        f"[bold]Workers:[/bold]           [cyan]{workers or settings.analyzer_workers}[/cyan]"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Analyzing audio features...", total=None)

        def progress_callback(
            current: int, total: int, track_name: str, elapsed: float
        ) -> None:
            if progress.tasks[task_id].total != total:
                progress.update(task_id, total=total)
            progress.update(
                task_id,
                completed=current,
                description=f"Analyzing: [dim]{track_name[:30]}[/dim] ({elapsed:.1f}s)",
            )

        summary = analyze_tracks(
            db_path=db_path,
            backend=selected_backend,
            workers=workers,
            force=force,
            limit=limit,
            progress_callback=progress_callback,
        )

    # Format timing
    def format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

    table = Table(title="Audio Analysis Summary & Timing", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Tracks Analyzed", f"[green]{summary.analyzed}[/green]")
    table.add_row(
        "Failures / Errors",
        f"[magenta]{summary.failed}[/magenta]" if summary.failed else "0",
    )
    table.add_row("Total Time Taken", format_time(summary.total_seconds))
    table.add_row("Average Speed", f"{summary.avg_seconds_per_track:.2f} s/track")
    table.add_section()
    table.add_row("Full Library Tracks", str(summary.full_library_tracks))
    table.add_row(
        "Full Library Estimate",
        f"[bold cyan]{format_time(summary.full_library_estimate_seconds)}[/bold cyan]",
    )

    console.print()
    console.print(table)


@app.command()
def clusters(
    k: Annotated[
        int,
        typer.Option(help="Number of clusters to generate for k-means"),
    ] = 5,
    algorithm: Annotated[
        str,
        typer.Option(help="Clustering algorithm to use ('kmeans' or 'hdbscan')"),
    ] = "kmeans",
    min_cluster_size: Annotated[
        int,
        typer.Option(help="Minimum cluster size for HDBSCAN"),
    ] = 3,
    rebuild_cache: Annotated[
        bool,
        typer.Option(
            "--rebuild-cache",
            help="Force rebuilding cached vibe vectors",
        ),
    ] = False,
    db: Annotated[
        Path | None,
        typer.Option(
            "--db",
            help="Path to SQLite database file",
        ),
    ] = None,
) -> None:
    """Compute normalized vibe vectors and generate track clusters."""
    settings = get_settings()
    db_path = db or settings.db_path

    if not db_path.is_file():
        console.print(f"[bold red]Database not found:[/bold red] {db_path}")
        raise typer.Exit(code=1)

    console.print(f"[bold]Target database:[/bold] [cyan]{db_path}[/cyan]")
    console.print(
        f"[dim]Running {algorithm.upper()} clustering (k={k if algorithm.lower() == 'kmeans' else 'auto'}, "
        f"cache={'rebuild' if rebuild_cache else 'auto'})...[/dim]\n"
    )

    try:
        result = compute_clusters(
            db_path=db_path,
            k=k,
            algorithm=algorithm,
            min_cluster_size=min_cluster_size,
            rebuild_cache=rebuild_cache,
            settings=settings,
        )
    except Exception as err:
        console.print(f"[bold red]Clustering Error:[/bold red] {err}")
        raise typer.Exit(code=1)

    if not result.clusters or result.total_tracks == 0:
        console.print(
            "[yellow]No analyzed tracks found to cluster. Run 'vibeplay analyze' first.[/yellow]"
        )
        return

    for cluster in result.clusters:
        # Format dominant moods
        moods_str = (
            ", ".join(f"{mood} ({score:.2f})" for mood, score in cluster.dominant_moods)
            or "N/A"
        )

        # Format top artists
        artists_str = (
            ", ".join(f"{artist} ({count})" for artist, count in cluster.top_artists)
            or "None"
        )

        table = Table(
            title=f"{cluster.label} — {cluster.size} tracks | Avg BPM: {cluster.avg_bpm:.1f}",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("ID", style="dim", width=5)
        table.add_column("Representative Track", style="bold")
        table.add_column("Artist", style="cyan")
        table.add_column("Album", style="dim")
        table.add_column("BPM", justify="right", style="yellow")
        table.add_column("Match", justify="right", style="green")

        for rep in cluster.representative_tracks:
            sim_pct = (
                f"{rep['similarity_to_centroid']:.1%}"
                if rep["similarity_to_centroid"] > 0
                else "N/A"
            )
            bpm_str = f"{rep['bpm']:.1f}" if rep.get("bpm") is not None else "N/A"
            table.add_row(
                str(rep["track_id"]),
                rep.get("title") or "Unknown",
                rep.get("artist") or "Unknown",
                rep.get("album") or "Unknown",
                bpm_str,
                sim_pct,
            )

        console.print(f"[bold cyan]Dominant Moods:[/bold cyan] {moods_str}")
        console.print(f"[bold cyan]Top Artists:[/bold cyan]    {artists_str}")
        console.print(table)
        console.print()

    console.print(
        f"[bold green]Clustering Complete:[/bold green] Grouped {result.total_tracks} tracks into "
        f"{len(result.clusters)} clusters using {result.algorithm.upper()}."
    )


@app.command()
def playlist(
    name: Annotated[
        str,
        typer.Option(help="Name of the generated playlist"),
    ] = "Vibe Playlist",
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            "-p",
            help="Natural language prompt for playlist vibe (e.g. 'rainy night focus, no vocals')",
        ),
    ] = None,
    seed: Annotated[
        str | None,
        typer.Option(
            help="Single track ID or comma-separated track IDs for similarity matching"
        ),
    ] = None,
    cluster: Annotated[
        int | None,
        typer.Option(help="Cluster ID to convert into a playlist"),
    ] = None,
    vibe: Annotated[
        str | None,
        typer.Option(
            help="Target vibe preset (chill, party, acoustic, electronic, workout, melancholy)"
        ),
    ] = None,
    arc: Annotated[
        str | None,
        typer.Option(help="Energy trajectory arc (ramp_up, cooldown, peak, steady)"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(help="Maximum number of tracks in the playlist"),
    ] = 25,
    minutes: Annotated[
        float | None,
        typer.Option(help="Target total duration in minutes"),
    ] = None,
    max_artist_tracks: Annotated[
        int,
        typer.Option(help="Maximum allowed tracks by the same artist"),
    ] = 2,
    export_m3u8: Annotated[
        Path | None,
        typer.Option(
            help="Destination path to immediately export an M3U8 playlist file"
        ),
    ] = None,
    relative: Annotated[
        bool,
        typer.Option(
            help="Use relative paths in exported M3U8 instead of absolute paths"
        ),
    ] = False,
    play: Annotated[
        bool,
        typer.Option(
            help="Immediately queue and initiate playback on local MPD daemon"
        ),
    ] = False,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database (defaults to configured path)"),
    ] = None,
) -> None:
    """Generate a cohesive smart playlist based on seeds, vibe, cluster, energy arc, or AI prompt."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    seed_ids: list[int] = []
    if seed:
        try:
            seed_ids = [int(s.strip()) for s in seed.split(",") if s.strip()]
        except ValueError:
            console.print(
                f"[bold red]Error:[/bold red] Invalid seed track ID format: '{seed}'. Expected integer(s)."
            )
            raise typer.Exit(code=1)

    description: str | None = None
    custom_rules: PlaylistRuleConfig | None = None

    if prompt:
        console.print(
            f"[bold cyan]AI Vibe Planner:[/bold cyan] Translating prompt: [italic]\"{prompt}\"[/italic]"
        )
        plan = parse_prompt_to_plan(prompt, db_path=db_path, settings=settings)
        console.print(
            f"[bold green]Thematic Concept:[/bold green] [bold]{plan.name}[/bold]"
        )
        console.print(f"[bold dim]Vibe Summary:[/bold dim]     {plan.description}")

        if name == "Vibe Playlist":
            name = plan.name
        description = plan.description
        if vibe is None and plan.vibe:
            vibe = plan.vibe
        if arc is None and plan.arc:
            arc = plan.arc

        custom_rules = PlaylistRuleConfig(
            mode=plan.mode,
            arc=plan.arc,
            vibe=plan.vibe,
            bpm_min=plan.bpm_min,
            bpm_max=plan.bpm_max,
            energy_min=plan.energy_min,
            energy_max=plan.energy_max,
            danceability_min=plan.danceability_min,
            danceability_max=plan.danceability_max,
            mood_min=plan.mood_min,
            genre_include=plan.genre_include,
            genre_exclude=plan.genre_exclude,
            limit=plan.limit if limit == 25 else limit,
            max_artist_tracks=max_artist_tracks,
        )

    try:
        gen = generate_playlist(
            db_path=db_path,
            name=name,
            seed_track_ids=seed_ids,
            cluster_id=cluster,
            vibe=vibe,
            arc=arc,
            limit=limit,
            minutes=minutes,
            max_artist_tracks=max_artist_tracks,
            rules=custom_rules,
            description=description,
            settings=settings,
        )
    except Exception as err:
        console.print(f"[bold red]Playlist Generation Error:[/bold red] {err}")
        raise typer.Exit(code=1)

    # Render playlist table
    table = Table(
        title=f"Playlist: {gen.name} (ID: {gen.playlist_id})",
        header_style="bold magenta",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="cyan", width=4)
    table.add_column("Title", style="bold", max_width=30, overflow="ellipsis")
    table.add_column("Artist", max_width=22, overflow="ellipsis")
    table.add_column("Album", max_width=22, overflow="ellipsis")
    table.add_column("Time", justify="right", width=6)
    table.add_column("BPM", justify="right", width=6)
    table.add_column("Key", justify="center", width=8)
    table.add_column("Energy", justify="right", width=7)
    table.add_column("Transition", justify="right", width=12)

    for item in gen.tracks:
        duration_sec = int(round(item.duration))
        dur_mins, dur_secs = divmod(duration_sec, 60)
        time_str = f"{dur_mins}:{dur_secs:02d}"
        bpm_str = f"{item.bpm:.1f}" if item.bpm is not None else "-"
        key_str = f"{item.camelot or item.key or '-'}"
        energy_str = f"{item.energy:.2f}" if item.energy is not None else "-"

        if item.position == 1 or not item.transition:
            trans_str = "[dim]start[/dim]"
        else:
            score = item.transition.total_score
            color = "green" if score >= 0.8 else ("yellow" if score >= 0.6 else "red")
            trans_str = f"[{color}]{score:.2f}[/{color}]"

        table.add_row(
            str(item.position),
            item.title,
            item.artist,
            item.album,
            time_str,
            bpm_str,
            key_str,
            energy_str,
            trans_str,
        )

    console.print()
    console.print(table)
    console.print()

    tot_mins, tot_secs = divmod(int(round(gen.total_duration)), 60)
    console.print(
        f"[bold green]Playlist Saved:[/bold green] ID [bold cyan]{gen.playlist_id}[/bold cyan] | "
        f"Mode: [cyan]{gen.mode}[/cyan] | Tracks: [cyan]{len(gen.tracks)}[/cyan] | "
        f"Length: [cyan]{tot_mins}m {tot_secs:02d}s[/cyan] | "
        f"Avg Smoothness: [cyan]{gen.avg_transition_score:.2f}[/cyan]"
    )

    if export_m3u8 is not None:
        try:
            exported_file = export_playlist_to_file(
                db_path=db_path,
                playlist_id=gen.playlist_id,
                output_path=export_m3u8,
                export_format="m3u8",
                relative=relative,
            )
            console.print(
                f"[bold green]Exported M3U8:[/bold green] [cyan]{exported_file}[/cyan]"
            )
        except Exception as err:
            console.print(f"[bold red]M3U8 Export Failed:[/bold red] {err}")

    if play:
        try:
            play_res = play_playlist(
                db_path=db_path, playlist_id=gen.playlist_id, settings=settings
            )
            console.print(
                f"[bold green]MPD Playback Started:[/bold green] Queued {play_res['queued_tracks']} tracks. "
                f"Now playing: [cyan]{play_res['first_track']['artist']} - {play_res['first_track']['title']}[/cyan]"
            )
        except PlaybackError as err:
            console.print(f"[bold yellow]MPD Daemon Notice:[/bold yellow] {err}")
        except Exception as err:
            console.print(f"[bold red]Playback Error:[/bold red] {err}")


@app.command()
def tag(
    track_ids: Annotated[
        list[int] | None,
        typer.Argument(help="Specific track IDs to tag (optional)"),
    ] = None,
    all_tracks: Annotated[
        bool,
        typer.Option("--all", "-a", help="Tag all tracks in the database"),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option(help="Batch size for LLM requests"),
    ] = 20,
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum number of tracks to process"),
    ] = None,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database (defaults to configured path)"),
    ] = None,
) -> None:
    """Batch-tag audio tracks with mood and genre descriptors using an LLM."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    with get_connection(db_path) as conn:
        all_tracks_rows = get_tracks_with_features(conn)

    target_tracks: list[dict[str, Any]] = []
    id_set = set(track_ids) if track_ids else None

    for r in all_tracks_rows:
        tid = int(r["track_id"])
        if id_set is not None and tid not in id_set:
            continue
        target_tracks.append(
            {
                "track_id": tid,
                "title": r["title"] or "Unknown Title",
                "artist": r["artist"] or "Unknown Artist",
                "bpm": r["bpm"],
                "energy": r["energy"],
                "danceability": r["danceability"],
                "loudness": r["loudness"],
                "key": r["key"],
                "scale": r["scale"],
            }
        )
        if limit is not None and len(target_tracks) >= limit:
            break

    if not target_tracks:
        console.print("[yellow]No eligible analyzed tracks found to tag.[/yellow]")
        return

    console.print(
        f"[bold cyan]Batch Vibe Tagging:[/bold cyan] Processing {len(target_tracks)} tracks "
        f"(batch size: {batch_size}, provider: {settings.llm_provider})..."
    )

    results = batch_vibe_tag_tracks(
        tracks=target_tracks,
        db_path=db_path,
        settings=settings,
        batch_size=batch_size,
    )

    table = Table(
        title=f"Vibe Tagging Results ({len(results)} tracks updated)",
        show_header=True,
    )
    table.add_column("ID", style="dim", width=5)
    table.add_column("Mood Tags", style="cyan")
    table.add_column("Genre Tags", style="magenta")

    for item in results:
        table.add_row(
            str(item.track_id),
            ", ".join(item.mood_tags) or "-",
            ", ".join(item.genre_tags) or "-",
        )

    console.print(table)
    console.print(
        f"[bold green]Successfully tagged {len(results)} tracks in database.[/bold green]"
    )


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
    relative: Annotated[
        bool,
        typer.Option(help="Use relative paths in exported playlist"),
    ] = False,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database (defaults to configured path)"),
    ] = None,
) -> None:
    """Export a saved playlist to an M3U, M3U8, JSON, or CSV file."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    try:
        exported_path = export_playlist_to_file(
            db_path=db_path,
            playlist_id=playlist_id,
            output_path=out,
            export_format=format,
            relative=relative,
        )
        console.print(
            f"[bold green]Playlist Exported:[/bold green] Playlist ID {playlist_id} saved to "
            f"[cyan]{exported_path}[/cyan] (format: {format.lower()})"
        )
    except Exception as err:
        console.print(f"[bold red]Export Error:[/bold red] {err}")
        raise typer.Exit(code=1)


@app.command()
def play(
    playlist_id: Annotated[
        int | None,
        typer.Option(help="ID of the saved playlist to queue and play"),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option(help="Track ID to generate seed playlist and play"),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(help="Maximum number of tracks if generating from seed"),
    ] = 25,
    db: Annotated[
        Path | None,
        typer.Option(help="Path to SQLite database (defaults to configured path)"),
    ] = None,
) -> None:
    """Queue a playlist or seed track into local Music Player Daemon (MPD) for bit-perfect playback."""
    settings = get_settings()
    db_path = (
        db.expanduser().resolve() if db else settings.db_path.expanduser().resolve()
    )

    if playlist_id is None and seed is None:
        console.print(
            "[bold red]Error:[/bold red] Must specify either --playlist-id or --seed."
        )
        raise typer.Exit(code=1)

    try:
        if playlist_id is not None:
            res = play_playlist(
                db_path=db_path, playlist_id=playlist_id, settings=settings
            )
            console.print(
                f"[bold green]Playing Playlist:[/bold green] '{res['playlist_name']}' "
                f"({res['queued_tracks']} tracks queued to MPD daemon)"
            )
            first = res.get("first_track")
            if first:
                console.print(
                    f"[bold cyan]Now Playing:[/bold cyan] {first['artist']} - {first['title']}"
                )
        elif seed is not None:
            res = play_seed(
                db_path=db_path, seed_track_id=seed, limit=limit, settings=settings
            )
            console.print(
                f"[bold green]Playing Vibe Seed:[/bold green] '{res['playlist_name']}' "
                f"({res['queued_tracks']} tracks queued to MPD daemon)"
            )
            first = res.get("first_track")
            if first:
                console.print(
                    f"[bold cyan]Now Playing:[/bold cyan] {first['artist']} - {first['title']}"
                )
    except PlaybackError as err:
        console.print(f"[bold red]MPD Playback Error:[/bold red] {err}")
        raise typer.Exit(code=1)
    except Exception as err:
        console.print(f"[bold red]Error:[/bold red] {err}")
        raise typer.Exit(code=1)


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
    from vibeplay.web import run_server

    cfg = get_settings()
    console.print(f"[bold cyan]vibeplay Web UI starting on http://{host}:{port}[/bold cyan]")
    try:
        run_server(db_path=cfg.db_path, host=host, port=port)
    except KeyboardInterrupt:
        console.print("[dim]Web server stopped.[/dim]")


if __name__ == "__main__":
    app()
