"""Command-line interface for vibe-dsp using Typer and Rich."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from vibe_dsp.alsa_reservation import (
    DEFAULT_MPD_CONF_DIR,
    check_alsa_device_status,
    generate_mpd_audio_outputs,
    write_mpd_audio_outputs_config,
)
from vibe_dsp.backup import create_backup, execute_rollback, find_latest_backup
from vibe_dsp.hardware import scan_hardware
from vibe_dsp.latency import audit_latency
from vibe_dsp.models import AudioEndpoint, CardType, LatencyHealthRating
from vibe_dsp.pipewire import (
    DEFAULT_PIPEWIRE_CONF_DIR,
    generate_pipewire_dropin_config,
    reload_pipewire_daemons,
    write_pipewire_dropin,
)

logger = logging.getLogger("vibe-dsp")
console = Console()

app = typer.Typer(
    name="vibe-dsp",
    help="Audio signal chain, hardware audit, and bit-perfect transport suite for PipeWire/ALSA.",
    no_args_is_help=True,
)

hardware_app = typer.Typer(
    name="hardware",
    help="Audio hardware audit and capability inspection commands.",
    no_args_is_help=True,
)
app.add_typer(hardware_app, name="hardware")

route_app = typer.Typer(
    name="route",
    help="Audio routing and bit-perfect transport configuration commands.",
    no_args_is_help=True,
)
app.add_typer(route_app, name="route")

latency_app = typer.Typer(
    name="latency",
    help="Kernel DPC latency watchdog and xrun detection commands.",
    no_args_is_help=True,
)
app.add_typer(latency_app, name="latency")


@hardware_app.command(name="audit")
def hardware_audit(
    procfs: Annotated[
        Path | None,
        typer.Option(help="Path to ALSA procfs directory (defaults to /proc/asound)"),
    ] = None,
) -> None:
    """Audit audio hardware, USB Audio Class DACs, HDMI, and native sample rates."""
    proc_root = procfs or Path("/proc/asound")
    report = scan_hardware(procfs_root=proc_root)

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]Audio Hardware Audit & Capability Scan[/bold white]",
            border_style="cyan",
        )
    )

    if not report.endpoints:
        console.print("[yellow]No ALSA playback endpoints detected on system.[/yellow]")
        return

    table = Table(
        title="Detected Audio Hardware Endpoints",
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("Card", justify="center", style="dim", width=6)
    table.add_column("Type", style="bold", width=14)
    table.add_column("Device Name", style="cyan", max_width=28)
    table.add_column("USB ID / Driver", style="dim", width=16)
    table.add_column("Max Rate", justify="right", style="green", width=11)
    table.add_column("Bit Depth", justify="center", width=10)
    table.add_column("ALSA Direct", style="yellow", width=12)
    table.add_column("Role / Priority", style="bold", width=16)

    for ep in report.endpoints:
        # Determine role label
        is_active = (
            report.active_dac and ep.hw_device == report.active_dac.hw_device
        )
        is_fallback = (
            report.fallback_endpoint
            and ep.hw_device == report.fallback_endpoint.hw_device
        )

        if is_active:
            role = "[bold green]PRIMARY DAC[/bold green]"
        elif is_fallback and not report.active_dac:
            role = "[bold yellow]ACTIVE (SPEAKER)[/bold yellow]"
        elif is_fallback:
            role = "[dim yellow]Fallback Spkr[/dim yellow]"
        else:
            role = "[dim]Secondary[/dim]"

        type_label = (
            "[bold green]USB DAC[/bold green]"
            if ep.card_type == CardType.USB_DAC
            else (
                "[cyan]HDMI[/cyan]"
                if ep.card_type == CardType.HDMI
                else "[magenta]Speaker/Analog[/magenta]"
            )
        )

        usb_label = ep.usb_id if ep.usb_id else ep.driver
        max_rate_str = f"{ep.max_rate / 1000:.1f} kHz"
        bits_str = f"{ep.max_bit_depth}-bit" if ep.bit_depths else "16/24-bit"

        table.add_row(
            f"hw:{ep.card_index},{ep.device_index}",
            type_label,
            ep.card_name,
            usb_label,
            max_rate_str,
            bits_str,
            ep.hw_device,
            role,
        )

    console.print(table)
    console.print()

    if report.active_dac:
        dac = report.active_dac
        rates_summary = ", ".join(f"{r/1000:.1f}k" for r in dac.rates)
        console.print(
            f"[bold green]Priority Target:[/bold green] [bold cyan]{dac.card_name}[/bold cyan] ({dac.hw_device})"
        )
        console.print(f"  [dim]USB ID:[/dim]              {dac.usb_id or 'Class Compliant'}")
        console.print(f"  [dim]Native Clock Rates:[/dim]  {rates_summary or 'Standard'}")
        console.print(f"  [dim]Formats Supported:[/dim]   {', '.join(dac.formats) or 'S16_LE, S24, S32'}")
        if report.fallback_endpoint:
            fb = report.fallback_endpoint
            console.print(
                f"  [dim]Fallback Endpoint:[/dim]   {fb.card_name} ({fb.hw_device})"
            )
    else:
        console.print(
            "[yellow]Notice:[/yellow] No external USB DAC detected. "
            f"Routing will automatically target onboard fallback: [bold cyan]{report.fallback_endpoint.card_name if report.fallback_endpoint else 'Default'}[/bold cyan]."
        )
    console.print()


@route_app.command(name="bitperfect")
def route_bitperfect(
    card: Annotated[
        int | None,
        typer.Option("--card", "-c", help="Override target ALSA card index"),
    ] = None,
    device: Annotated[
        int,
        typer.Option("--device", "-d", help="Override target ALSA device index"),
    ] = 0,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview configuration changes without modifying files"),
    ] = False,
    no_reload: Annotated[
        bool,
        typer.Option("--no-reload", help="Skip restarting PipeWire daemon"),
    ] = False,
    output_mpd: Annotated[
        Path | None,
        typer.Option(help="Custom destination for MPD configuration snippet"),
    ] = None,
    output_pipewire: Annotated[
        Path | None,
        typer.Option(help="Custom destination for PipeWire drop-in configuration"),
    ] = None,
    procfs: Annotated[
        Path | None,
        typer.Option(help="Path to ALSA procfs directory (defaults to /proc/asound)"),
    ] = None,
) -> None:
    """Configure direct ALSA bit-perfect transport, PipeWire sample rate unlocking, and fallback driver chains."""
    proc_root = procfs or Path("/proc/asound")
    report = scan_hardware(procfs_root=proc_root)

    # Determine target endpoint
    target_ep: AudioEndpoint | None = None
    if card is not None:
        matches = [
            ep
            for ep in report.endpoints
            if ep.card_index == card and ep.device_index == device
        ]
        if matches:
            target_ep = matches[0]
        else:
            console.print(
                f"[bold red]Error:[/bold red] Specified ALSA card hw:{card},{device} not found."
            )
            raise typer.Exit(code=1)
    else:
        # Prioritize connected USB DAC; fallback to onboard speakers if none connected
        target_ep = report.active_dac or report.fallback_endpoint

    if not target_ep:
        console.print(
            "[bold red]Error:[/bold red] No audio output endpoints detected to route."
        )
        raise typer.Exit(code=1)

    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]vibe-dsp[/bold cyan] [bold white]Bit-Perfect Routing Engagement[/bold white]\n"
            f"Target: [bold green]{target_ep.card_name}[/bold green] ([yellow]{target_ep.hw_device}[/yellow])",
            border_style="green",
        )
    )

    # Generate configurations
    pipewire_cfg = generate_pipewire_dropin_config(
        unlocked_rates=report.unlocked_rates,
        node_pattern="~alsa_output.usb-.*",
    )

    mpd_cfg = generate_mpd_audio_outputs(
        primary_endpoint=target_ep,
        fallback_endpoint=report.fallback_endpoint,
    )

    target_pw_file = output_pipewire or (
        DEFAULT_PIPEWIRE_CONF_DIR / "99-bitperfect.conf"
    )
    target_mpd_file = output_mpd or (
        DEFAULT_MPD_CONF_DIR / "bitperfect.conf"
    )

    if dry_run:
        console.print("[bold yellow][DRY RUN MODE][/bold yellow] Previewing generated configurations:")
        console.print(f"\n[bold cyan]--- {target_pw_file} ---[/bold cyan]")
        console.print(pipewire_cfg)
        console.print(f"\n[bold cyan]--- {target_mpd_file} ---[/bold cyan]")
        console.print(mpd_cfg)
        console.print("\n[yellow]Dry run completed. No files modified.[/yellow]")
        return

    # Safety: Create backup and rollback script before writing any file
    backup_dir, rollback_script = create_backup(
        targets=[target_pw_file, target_mpd_file]
    )

    # Write configs
    write_pipewire_dropin(
        content=pipewire_cfg,
        conf_dir=target_pw_file.parent,
        filename=target_pw_file.name,
    )

    write_mpd_audio_outputs_config(
        content=mpd_cfg,
        output_path=target_mpd_file,
    )

    # Reload daemons unless suppressed
    reload_msg = "Skipped (--no-reload)"
    if not no_reload:
        success, reload_msg = reload_pipewire_daemons()
        if success:
            console.print(f"[bold green]Daemon Reload:[/bold green] {reload_msg}")
        else:
            console.print(f"[bold yellow]Daemon Notice:[/bold yellow] {reload_msg}")

    # Inspect device status
    status = check_alsa_device_status(target_ep.card_index, target_ep.device_index)

    summary_table = Table(title="Bit-Perfect Transport Status", show_header=False)
    summary_table.add_column("Key", style="bold")
    summary_table.add_column("Value")

    summary_table.add_row("Primary Output", f"[green]{target_ep.hw_device}[/green] ({target_ep.card_name})")
    summary_table.add_row("Fallback Driver", f"[yellow]{target_ep.plughw_device}[/yellow] (transparent format plug)")
    summary_table.add_row("PipeWire Sinks", "resample.disable = true (*.usb-*)")
    summary_table.add_row("Unlocked Rates", "44.1, 48, 88.2, 96, 176.4, 192, 352.8, 384 kHz")
    summary_table.add_row("Device State", f"[cyan]{status}[/cyan]")
    summary_table.add_row("PipeWire Drop-in", str(target_pw_file))
    summary_table.add_row("MPD Output Conf", str(target_mpd_file))
    summary_table.add_row("Backup Directory", str(backup_dir))
    summary_table.add_row("Rollback Script", f"[bold red]{rollback_script}[/bold red]")

    console.print(summary_table)
    console.print(
        f"\n[bold green]Success:[/bold green] Bit-perfect routing engaged. "
        f"To revert anytime, run: [bold]vibe-dsp rollback[/bold] or [bold]bash {rollback_script}[/bold]"
    )
    console.print()


@app.command(name="rollback")
def rollback_cmd() -> None:
    """Execute the latest automatic rollback script to restore system audio configuration."""
    latest_script = find_latest_backup()
    if not latest_script:
        console.print("[yellow]No vibe-dsp backup scripts found to rollback.[/yellow]")
        return

    console.print(f"[bold cyan]Executing Rollback:[/bold cyan] {latest_script}")
    success, output = execute_rollback(latest_script)
    if success:
        console.print("[bold green]Rollback completed successfully:[/bold green]")
        console.print(output)
    else:
        console.print(f"[bold red]Rollback error:[/bold red] {output}")
        raise typer.Exit(code=1)


@latency_app.command(name="monitor")
def latency_monitor(
    card: Annotated[
        int | None,
        typer.Option("--card", "-c", help="Target ALSA card index to audit (defaults to auto-detected DAC)"),
    ] = None,
    device: Annotated[
        int,
        typer.Option("--device", "-d", help="Target ALSA device index"),
    ] = 0,
    samples: Annotated[
        int,
        typer.Option("--samples", "-s", help="Scheduling jitter sample count"),
    ] = 30,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output raw telemetry JSON"),
    ] = False,
    procfs: Annotated[
        Path | None,
        typer.Option(help="Path to ALSA procfs directory (defaults to /proc/asound)"),
    ] = None,
    sysfs: Annotated[
        Path | None,
        typer.Option(help="Path to sysfs directory (defaults to /sys)"),
    ] = None,
) -> None:
    """Monitor real-time audio thread latency, detect buffer underruns (xruns), and audit CPU throttling."""
    proc_root = procfs or Path("/proc/asound")
    sys_root = sysfs or Path("/sys")

    target_card = card
    if target_card is None:
        hw_rep = scan_hardware(procfs_root=proc_root)
        if hw_rep.active_dac:
            target_card = hw_rep.active_dac.card_index
            device = hw_rep.active_dac.device_index
        elif hw_rep.fallback_endpoint:
            target_card = hw_rep.fallback_endpoint.card_index
            device = hw_rep.fallback_endpoint.device_index
        else:
            target_card = 0

    report = audit_latency(
        card_index=target_card,
        device_index=device,
        jitter_samples=samples,
        procfs_root=proc_root,
        sysfs_root=sys_root,
    )

    if json_output:
        print(report.model_dump_json(indent=2))
        return

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]Kernel DPC Latency Watchdog & xrun Detector[/bold white]\n"
            f"Target Endpoint: [yellow]hw:{target_card},{device}[/yellow] • Timestamp: [dim]{report.timestamp}[/dim]",
            border_style="cyan",
        )
    )

    # Health Rating Badge Panel
    if report.health_rating == LatencyHealthRating.GOOD:
        rating_panel = Panel.fit(
            "[bold green]HEALTH RATING: GOOD[/bold green]\n"
            "[white]Real-time audio transport latency optimal. Zero underruns detected.[/white]",
            border_style="green",
        )
    elif report.health_rating == LatencyHealthRating.MARGINAL:
        rating_panel = Panel.fit(
            "[bold yellow]HEALTH RATING: MARGINAL[/bold yellow]\n"
            "[yellow]Elevated scheduling jitter or power saving state detected.[/yellow]",
            border_style="yellow",
        )
    else:
        rating_panel = Panel.fit(
            "[bold red]HEALTH RATING: THROTTLED[/bold red]\n"
            "[red]Active xruns, severe timer jitter, or ACPI CPU throttling detected.[/red]",
            border_style="red",
        )
    console.print(rating_panel)
    console.print()

    # Telemetry Tables
    table = Table(title="Audio Transport & Scheduling Latency", show_lines=True)
    table.add_column("Category", style="bold magenta", width=22)
    table.add_column("Metric", style="cyan", width=26)
    table.add_column("Status / Reading", style="bold", width=34)

    # ALSA & Buffer Telemetry
    rate_str = (
        f"{report.xrun_report.active_rate / 1000.0:.1f} kHz"
        if report.xrun_report.active_rate
        else "Standby / Idle"
    )
    buf_str = (
        f"{report.xrun_report.buffer_size} frames (period {report.xrun_report.period_size})"
        if report.xrun_report.buffer_size
        else "Unallocated"
    )
    xrun_color = "green" if report.xrun_report.xrun_count == 0 else "bold red"

    table.add_row("ALSA Hardware", "Endpoint Address", f"hw:{target_card},{device}")
    table.add_row("ALSA Hardware", "PCM State", report.xrun_report.state)
    table.add_row("ALSA Hardware", "Active Sample Rate", rate_str)
    table.add_row("ALSA Hardware", "Buffer & Period", buf_str)
    table.add_row(
        "ALSA Hardware",
        "Buffer Underruns (xruns)",
        f"[{xrun_color}]{report.xrun_report.xrun_count} dropouts[/{xrun_color}]",
    )

    # Jitter Telemetry
    jit = report.jitter_metrics
    table.add_row("Kernel DPC Jitter", "Avg Scheduling Delay", f"{jit.avg_jitter_us:.1f} µs")
    table.add_row(
        "Kernel DPC Jitter",
        "Peak Jitter / StdDev",
        f"{jit.max_jitter_us:.1f} µs / ±{jit.stddev_jitter_us:.1f} µs",
    )
    table.add_row("Kernel DPC Jitter", "Timer Evaluator", f"{jit.source} ({jit.sample_count} samples)")

    # Power Profile Telemetry
    pwr = report.power_profile
    ac_label = "[bold green]Connected (AC)[/bold green]" if pwr.ac_online else "[bold yellow]Battery Discharging[/bold yellow]"
    pwr_label = "[bold red]THROTTLED[/bold red]" if pwr.is_throttled else "[green]Nominal[/green]"
    table.add_row("ACPI Power State", "Power Supply", ac_label)
    table.add_row("ACPI Power State", "CPU Governor", f"{pwr.active_governor} ({len(pwr.cores)} cores)")
    table.add_row("ACPI Power State", "Frequency Throttling", pwr_label)

    # RealtimeKit
    rt_color = "bold green" if report.rtkit_granted else "yellow"
    table.add_row("RealtimeKit", "Scheduling Priority", f"[{rt_color}]{report.rtkit_details}[/{rt_color}]")

    console.print(table)
    console.print()

    # Recommendations & Diagnostics
    console.print("[bold cyan]Diagnostics & Tuning Advice:[/bold cyan]")
    for diag in report.diagnostics:
        console.print(f"  • {diag}")
    console.print(f"  [dim]Power Advice:[/dim] {pwr.recommendation}")

    # Micro-Stutter Anomalies Log
    if report.anomalies:
        console.print()
        console.print(f"[bold red]Detected Micro-Stutter Anomalies ({len(report.anomalies)}):[/bold red]")
        for anom in report.anomalies:
            console.print(
                f"  [{anom.timestamp}] [bold red]Anomaly:[/bold red] {anom.message} "
                f"(Peak Jitter: {anom.jitter_us:.1f} µs, Load: {anom.system_load:.2f})"
            )
    console.print()
