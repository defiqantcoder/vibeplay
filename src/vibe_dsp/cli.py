"""Command-line interface for vibe-dsp using Typer and Rich."""

from __future__ import annotations

import json
import logging
import re
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
from vibe_dsp.ipc import (
    AVAILABLE_PROFILES,
    DEFAULT_IPC_SOCKET_PATH,
    DSPClient,
    start_ipc_server,
    switch_audio_profile,
)
from vibe_dsp.latency import audit_latency
from vibe_dsp.models import AudioEndpoint, CardType, LatencyHealthRating
from vibe_dsp.passthrough import (
    CODEC_DESCRIPTIONS,
    CODEC_MAP,
    configure_sink_passthrough,
    discover_receiver_endpoints,
)
from vibe_dsp.peq import (
    DEFAULT_EASYEFFECTS_OUTPUT_DIR,
    PEQProfile,
    apply_peq_preset,
    export_easyeffects_preset,
    get_active_peq_state,
    ingest_peq_source,
    list_available_presets,
    lookup_autoeq_model,
)
from vibe_dsp.pipewire import (
    DEFAULT_PIPEWIRE_CONF_DIR,
    generate_pipewire_dropin_config,
    reload_pipewire_daemons,
    write_pipewire_dropin,
)
from vibe_dsp.spatial import (
    DEFAULT_SPATIAL_CONF_FILE,
    SPATIAL_SINK_NAME,
    STANDARD_7_1_4_BASE_PREAMP_DB,
    calculate_composite_preamp,
    ensure_default_sofa_hrtf,
    get_spatial_virtualization_status,
    inspect_sofa_file,
    set_spatial_virtualization_mode,
    write_spatial_filter_chain,
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

peq_app = typer.Typer(
    name="peq",
    help="Transducer-specific parametric EQ engine, anti-clipping gain staging, and EasyEffects presets.",
    no_args_is_help=True,
)
app.add_typer(peq_app, name="peq")

spatial_app = typer.Typer(
    name="spatial",
    help="PipeWire 7.1.4 spatial audio bridge, SOFA HRTF convolution, and binaural virtualization.",
    no_args_is_help=True,
)
app.add_typer(spatial_app, name="spatial")

profile_app = typer.Typer(
    name="profile",
    help="Audio profile management and dynamic transport switching (pure-bitperfect, spatial-headphones, receiver-passthrough).",
    no_args_is_help=True,
)
app.add_typer(profile_app, name="profile")


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
        is_active = report.active_dac and ep.hw_device == report.active_dac.hw_device
        is_fallback = report.fallback_endpoint and ep.hw_device == report.fallback_endpoint.hw_device

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
            else ("[cyan]HDMI[/cyan]" if ep.card_type == CardType.HDMI else "[magenta]Speaker/Analog[/magenta]")
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
        rates_summary = ", ".join(f"{r / 1000:.1f}k" for r in dac.rates)
        console.print(f"[bold green]Priority Target:[/bold green] [bold cyan]{dac.card_name}[/bold cyan] ({dac.hw_device})")
        console.print(f"  [dim]USB ID:[/dim]              {dac.usb_id or 'Class Compliant'}")
        console.print(f"  [dim]Native Clock Rates:[/dim]  {rates_summary or 'Standard'}")
        console.print(f"  [dim]Formats Supported:[/dim]   {', '.join(dac.formats) or 'S16_LE, S24, S32'}")
        if report.fallback_endpoint:
            fb = report.fallback_endpoint
            console.print(f"  [dim]Fallback Endpoint:[/dim]   {fb.card_name} ({fb.hw_device})")
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
        matches = [ep for ep in report.endpoints if ep.card_index == card and ep.device_index == device]
        if matches:
            target_ep = matches[0]
        else:
            console.print(f"[bold red]Error:[/bold red] Specified ALSA card hw:{card},{device} not found.")
            raise typer.Exit(code=1)
    else:
        # Prioritize connected USB DAC; fallback to onboard speakers if none connected
        target_ep = report.active_dac or report.fallback_endpoint

    if not target_ep:
        console.print("[bold red]Error:[/bold red] No audio output endpoints detected to route.")
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

    target_pw_file = output_pipewire or (DEFAULT_PIPEWIRE_CONF_DIR / "99-bitperfect.conf")
    target_mpd_file = output_mpd or (DEFAULT_MPD_CONF_DIR / "bitperfect.conf")

    if dry_run:
        console.print("[bold yellow][DRY RUN MODE][/bold yellow] Previewing generated configurations:")
        console.print(f"\n[bold cyan]--- {target_pw_file} ---[/bold cyan]")
        console.print(pipewire_cfg)
        console.print(f"\n[bold cyan]--- {target_mpd_file} ---[/bold cyan]")
        console.print(mpd_cfg)
        console.print("\n[yellow]Dry run completed. No files modified.[/yellow]")
        return

    # Safety: Create backup and rollback script before writing any file
    backup_dir, rollback_script = create_backup(targets=[target_pw_file, target_mpd_file])

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

    summary_table.add_row(
        "Primary Output",
        f"[green]{target_ep.hw_device}[/green] ({target_ep.card_name})",
    )
    summary_table.add_row(
        "Fallback Driver",
        f"[yellow]{target_ep.plughw_device}[/yellow] (transparent format plug)",
    )
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


@route_app.command(name="passthrough")
def route_passthrough(
    sink: Annotated[
        str | None,
        typer.Option("--sink", "-s", help="Target HDMI or S/PDIF sink identifier or name"),
    ] = None,
    codecs: Annotated[
        str | None,
        typer.Option("--codecs", "-c", help="Comma-separated list of codecs to enable (e.g. 'ac3,eac3,truehd,dts,dts-hd')"),
    ] = None,
    all_codecs: Annotated[
        bool,
        typer.Option("--all", "-a", help="Enable all supported codecs detected on the receiver"),
    ] = False,
    set_default: Annotated[
        bool,
        typer.Option("--default/--no-default", help="Set receiver sink as default system audio output"),
    ] = True,
    interactive: Annotated[
        bool,
        typer.Option("--interactive/--non-interactive", help="Prompt user interactively to select codecs"),
    ] = True,
) -> None:
    """Configure raw multichannel bitstream passthrough (AC3, EAC3, TrueHD, DTS-HD) for AV receivers."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]Receiver Bitstream Passthrough Setup[/bold white]",
            border_style="cyan",
        )
    )

    receivers = discover_receiver_endpoints()
    if not receivers:
        console.print("[bold red]Error:[/bold red] No HDMI or digital optical S/PDIF endpoints detected.")
        raise typer.Exit(code=1)

    target_receiver = receivers[0]
    if sink:
        matched = [r for r in receivers if r.sink_id == sink or r.sink_name == sink]
        if matched:
            target_receiver = matched[0]
        else:
            console.print(f"[yellow]Specified sink '{sink}' not found; using detected {target_receiver.sink_name}[/yellow]")

    console.print(f"[bold]Detected Digital Receiver:[/bold] [green]{target_receiver.description}[/green]")
    console.print(f"[bold]Sink Name:[/bold] [yellow]{target_receiver.sink_name}[/yellow] (ID: {target_receiver.sink_id})\n")

    # List supported options table
    table = Table(title="Supported Receiver Bitstream Codecs", header_style="bold magenta")
    table.add_column("Codec Key", style="cyan", width=12)
    table.add_column("IEC 61937 Format", style="green", width=18)
    table.add_column("Description", style="white")

    for c in target_receiver.supported_codecs:
        fmt_str = CODEC_MAP.get(c, c)
        desc_str = CODEC_DESCRIPTIONS.get(c, "Multichannel Audio Bitstream")
        table.add_row(c, fmt_str, desc_str)

    console.print(table)
    console.print()

    # Determine selected codecs
    chosen_codecs: list[str] = []
    if codecs:
        chosen_codecs = [c.strip().lower() for c in codecs.split(",") if c.strip()]
    elif all_codecs:
        chosen_codecs = list(target_receiver.supported_codecs)
    else:
        # Prompt the user with supported options
        default_choice = ",".join(target_receiver.supported_codecs)
        prompt_text = f"[bold yellow]Select codecs to enable on receiver[/bold yellow] ({', '.join(target_receiver.supported_codecs)})"
        try:
            val = typer.prompt(prompt_text, default=default_choice)
            chosen_codecs = [c.strip().lower() for c in val.split(",") if c.strip()]
        except Exception:
            chosen_codecs = list(target_receiver.supported_codecs)

    console.print(f"\n[cyan]Configuring passthrough codecs:[/cyan] {', '.join(chosen_codecs)}")
    success, msg = configure_sink_passthrough(
        sink_name_or_id=target_receiver.sink_name,
        selected_codecs=chosen_codecs,
        set_as_default=set_default,
    )

    if success:
        # Update persistent state
        switch_audio_profile("receiver-passthrough", {"sink": target_receiver.sink_name, "codecs": chosen_codecs})
        console.print(f"[bold green]Success:[/bold green] {msg}")
        if set_default:
            console.print("[green]HDMI/SPDIF sink set as default audio output.[/green]")
    else:
        console.print(f"[bold red]Configuration notice:[/bold red] {msg}")
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
        typer.Option(
            "--card",
            "-c",
            help="Target ALSA card index to audit (defaults to auto-detected DAC)",
        ),
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
            "[bold green]HEALTH RATING: GOOD[/bold green]\n[white]Real-time audio transport latency optimal. Zero underruns detected.[/white]",
            border_style="green",
        )
    elif report.health_rating == LatencyHealthRating.MARGINAL:
        rating_panel = Panel.fit(
            "[bold yellow]HEALTH RATING: MARGINAL[/bold yellow]\n[yellow]Elevated scheduling jitter or power saving state detected.[/yellow]",
            border_style="yellow",
        )
    else:
        rating_panel = Panel.fit(
            "[bold red]HEALTH RATING: THROTTLED[/bold red]\n[red]Active xruns, severe timer jitter, or ACPI CPU throttling detected.[/red]",
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
    rate_str = f"{report.xrun_report.active_rate / 1000.0:.1f} kHz" if report.xrun_report.active_rate else "Standby / Idle"
    buf_str = (
        f"{report.xrun_report.buffer_size} frames (period {report.xrun_report.period_size})" if report.xrun_report.buffer_size else "Unallocated"
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
    table.add_row(
        "Kernel DPC Jitter",
        "Timer Evaluator",
        f"{jit.source} ({jit.sample_count} samples)",
    )

    # Power Profile Telemetry
    pwr = report.power_profile
    ac_label = "[bold green]Connected (AC)[/bold green]" if pwr.ac_online else "[bold yellow]Battery Discharging[/bold yellow]"
    pwr_label = "[bold red]THROTTLED[/bold red]" if pwr.is_throttled else "[green]Nominal[/green]"
    table.add_row("ACPI Power State", "Power Supply", ac_label)
    table.add_row(
        "ACPI Power State",
        "CPU Governor",
        f"{pwr.active_governor} ({len(pwr.cores)} cores)",
    )
    table.add_row("ACPI Power State", "Frequency Throttling", pwr_label)

    # RealtimeKit
    rt_color = "bold green" if report.rtkit_granted else "yellow"
    table.add_row(
        "RealtimeKit",
        "Scheduling Priority",
        f"[{rt_color}]{report.rtkit_details}[/{rt_color}]",
    )

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


@peq_app.command(name="generate")
def peq_generate(
    input_source: Annotated[
        str | None,
        typer.Option(
            "--input",
            "-i",
            help="Path to AutoEq text file, JSON filter file, or raw string/stdin.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Headphone or IEM model name to lookup in AutoEq database / bundled targets.",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Custom name for the generated PEQ preset.",
        ),
    ] = None,
    safety_margin: Annotated[
        float,
        typer.Option(
            "--safety-margin",
            help="Headroom safety margin in dB added to peak gain (default 0.3 dB).",
        ),
    ] = 0.3,
    export_easyeffects: Annotated[
        bool,
        typer.Option(
            "--export-easyeffects/--no-export-easyeffects",
            help="Export preset directly to EasyEffects output presets directory.",
        ),
    ] = True,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Destination directory for EasyEffects preset JSON (defaults to ~/.local/share/easyeffects/output).",
        ),
    ] = None,
    backup: Annotated[
        bool,
        typer.Option(
            "--backup/--no-backup",
            help="Generate automatic backup and rollback script before writing preset.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output generated profile and gain staging in JSON format."),
    ] = False,
) -> None:
    """Generate calibrated parametric EQ profile with inter-sample anti-clipping gain staging."""
    profile: PEQProfile | None = None

    if input_source:
        profile = ingest_peq_source(input_source, name=name)
    elif model:
        profile = lookup_autoeq_model(model)
        if not profile:
            console.print(
                f"[bold red]Error:[/bold red] Could not locate AutoEq profile for model '[yellow]{model}[/yellow]'.\n"
                "Please check the model spelling, specify an AutoEq file with --input, or use 'vibe-dsp peq list'."
            )
            raise typer.Exit(code=1)
        if name:
            profile.name = name
    else:
        # Default to bundled reference profile if nothing specified
        profile = lookup_autoeq_model("Moondrop Blessing 2")
        if not profile:
            console.print("[bold red]Error:[/bold red] Must provide either --input or --model.")
            raise typer.Exit(code=1)

    # Re-apply headroom calculation with specified safety margin
    from vibe_dsp.peq import apply_headroom_calculation

    profile = apply_headroom_calculation(profile, safety_margin_db=safety_margin)

    preset_path: Path | None = None
    rollback_script: Path | None = None

    if export_easyeffects:
        preset_path, rollback_script = export_easyeffects_preset(
            profile=profile,
            target_dir=output_dir,
            backup=backup,
        )

    if json_output:
        out_dict = profile.model_dump()
        if preset_path:
            out_dict["preset_path"] = str(preset_path)
        if rollback_script:
            out_dict["rollback_script"] = str(rollback_script)
        print(json.dumps(out_dict, indent=2))
        return

    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]vibe-dsp[/bold cyan] [bold white]Parametric EQ Engine & Anti-Clipping Gain Staging[/bold white]\n"
            f"Profile: [bold yellow]{profile.name}[/bold yellow] • Source: [dim]{profile.source}[/dim]",
            border_style="cyan",
        )
    )

    # Headroom Gain Staging Banner
    gain_color = "bold green" if profile.calculated_preamp >= 0 else "bold red"
    preamp_str = f"[{gain_color}]{profile.calculated_preamp:+.2f} dB[/{gain_color}]"
    peak_str = f"[bold yellow]{profile.peak_positive_gain:+.2f} dB[/bold yellow]"
    margin_str = f"[dim]{profile.safety_margin_db:.2f} dB[/dim]"

    headroom_panel = Panel.fit(
        f"[bold]Inter-Sample Clipping Headroom Protection:[/bold]\n"
        f" • Continuous Peak Positive Boost: {peak_str}\n"
        f" • Anti-Clipping Safety Margin:    {margin_str}\n"
        f" • Digital Pre-Amplification:       {preamp_str} [dim](Applied to prevent 32-bit float ISP clipping)[/dim]",
        border_style="green" if profile.calculated_preamp == 0 else "yellow",
    )
    console.print(headroom_panel)
    console.print()

    # Filters Table
    table = Table(
        title=f"Calibrated Biquad Filter Stages ({len(profile.filters)} bands)",
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("#", justify="center", style="dim", width=4)
    table.add_column("Status", justify="center", width=8)
    table.add_column("Filter Type", style="cyan", width=14)
    table.add_column("Frequency", justify="right", style="bold green", width=12)
    table.add_column("Gain (dB)", justify="right", style="bold", width=11)
    table.add_column("Q Factor", justify="right", style="dim", width=10)
    table.add_column("EasyEffects Mapping", style="yellow", width=20)

    for flt in profile.filters:
        status_lbl = "[green]ON[/green]" if flt.enabled else "[dim red]OFF[/dim red]"
        gain_styled = f"[green]+{flt.gain:.1f}[/green]" if flt.gain > 0 else (f"[red]{flt.gain:.1f}[/red]" if flt.gain < 0 else "0.0")
        table.add_row(
            str(flt.filter_index),
            status_lbl,
            flt.filter_type.value,
            f"{flt.frequency:.1f} Hz",
            gain_styled,
            f"{flt.q:.2f}",
            flt.filter_type.to_easyeffects_type(),
        )

    console.print(table)
    console.print()

    if preset_path:
        console.print(f"[bold green]✓ EasyEffects Output Preset Exported:[/bold green] [cyan]{preset_path}[/cyan]")
    if rollback_script:
        console.print(f"[dim]Automatic Rollback Script:[/dim] [dim cyan]{rollback_script}[/dim cyan]")
    console.print()


@peq_app.command(name="apply")
def peq_apply(
    profile: Annotated[
        str,
        typer.Argument(help="Name of EasyEffects preset, bundled model, or file path to apply."),
    ] = "moondrop_blessing_2",
    toggle: Annotated[
        bool,
        typer.Option(
            "--toggle",
            "-t",
            help="Toggle preset: if currently active, unload to bypass; if inactive, load.",
        ),
    ] = False,
    unload: Annotated[
        bool,
        typer.Option(
            "--unload",
            "-u",
            help="Unload current PEQ preset and reset EasyEffects equalizer to flat bypass.",
        ),
    ] = False,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory containing EasyEffects presets.",
        ),
    ] = None,
    easyeffects_bin: Annotated[
        str,
        typer.Option(
            "--easyeffects-bin",
            help="Name or path of easyeffects executable.",
        ),
    ] = "easyeffects",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output apply status and state in JSON format."),
    ] = False,
) -> None:
    """Dynamically load or unload calibrated PEQ profiles via the EasyEffects CLI."""
    ee_dir = output_dir or DEFAULT_EASYEFFECTS_OUTPUT_DIR
    clean_target = Path(profile).stem

    # If not unloading and target preset file doesn't exist, check if we can auto-generate it
    if not unload and not (ee_dir / f"{clean_target}.json").exists():
        found = lookup_autoeq_model(profile)
        if found:
            export_easyeffects_preset(found, target_dir=ee_dir, backup=True)
            clean_target = Path(re.sub(r"[^\w\-_]", "_", found.name.lower().strip())).stem

    success, message, state = apply_peq_preset(
        preset_name_or_path=clean_target,
        toggle=toggle,
        unload=unload,
        presets_dir=ee_dir,
        easyeffects_bin=easyeffects_bin,
    )

    if json_output:
        print(json.dumps({"success": success, "message": message, "state": state}, indent=2))
        return

    console.print()
    if success:
        if state.get("is_active"):
            console.print(
                Panel.fit(
                    f"[bold green]PEQ PROFILE LOADED[/bold green]\n"
                    f"Active Profile: [bold yellow]{state.get('active_profile')}[/bold yellow]\n"
                    f"Digital Preamp: [bold cyan]{state.get('preamp_db'):.2f} dB[/bold cyan] (Inter-sample clipping protection active)\n"
                    f"Filter Bands:   [dim]{state.get('filter_count')} bands active[/dim]",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel.fit(
                    "[bold yellow]PEQ EQUALIZER UNLOADED[/bold yellow]\n"
                    "[white]EasyEffects equalizer reset to bypass. Signal passing uncolored.[/white]",
                    border_style="yellow",
                )
            )
    else:
        console.print(
            Panel.fit(
                f"[bold red]PEQ Load Warning[/bold red]\n{message}",
                border_style="red",
            )
        )
    console.print()


@peq_app.command(name="list")
def peq_list(
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Directory containing EasyEffects presets.",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output presets list in JSON format."),
    ] = False,
) -> None:
    """List available EasyEffects presets and bundled transducer calibration profiles."""
    presets = list_available_presets(target_dir=output_dir)

    if json_output:
        print(json.dumps(presets, indent=2))
        return

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]Transducer PEQ Profiles & EasyEffects Presets[/bold white]",
            border_style="cyan",
        )
    )

    if not presets:
        console.print("[yellow]No PEQ presets found in EasyEffects output directory or bundled catalog.[/yellow]")
        return

    table = Table(
        title=f"Discovered PEQ Calibration Presets ({len(presets)})",
        header_style="bold magenta",
        show_lines=True,
    )
    table.add_column("Status", justify="center", width=10)
    table.add_column("Preset Name", style="bold cyan", width=26)
    table.add_column("Category", style="dim", width=18)
    table.add_column("Bands", justify="right", width=8)
    table.add_column("Digital Preamp", justify="right", style="bold yellow", width=16)
    table.add_column("Preset Path", style="dim", max_width=40)

    for p in presets:
        status_lbl = "[bold green]ACTIVE[/bold green]" if p.get("is_active") else "[dim]Standby[/dim]"
        preamp_val = p.get("preamp_db", 0.0)
        p_styled = f"{preamp_val:+.2f} dB"
        table.add_row(
            status_lbl,
            p["name"],
            p["type"],
            str(p["bands"]),
            p_styled,
            p["path"],
        )

    console.print(table)
    console.print()


@peq_app.command(name="show")
def peq_show(
    profile: Annotated[
        str,
        typer.Argument(help="Name, model, or file path of PEQ profile to inspect."),
    ] = "moondrop_blessing_2",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output profile in JSON format."),
    ] = False,
) -> None:
    """Inspect the frequency curves, filter biquad parameters, and headroom of a profile."""
    prof = lookup_autoeq_model(profile)
    if not prof:
        prof = ingest_peq_source(profile)

    if json_output:
        print(prof.model_dump_json(indent=2))
        return

    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]vibe-dsp[/bold cyan] [bold white]Profile Inspection: {prof.name}[/bold white]\n"
            f"Peak Boost: [yellow]{prof.peak_positive_gain:+.2f} dB[/yellow] • Anti-Clipping Preamp: [red]{prof.calculated_preamp:+.2f} dB[/red]",
            border_style="cyan",
        )
    )

    table = Table(title="Filter Parameters", header_style="bold magenta", show_lines=True)
    table.add_column("#", justify="center", style="dim", width=4)
    table.add_column("Type", style="cyan", width=14)
    table.add_column("Frequency", justify="right", style="bold green", width=12)
    table.add_column("Gain (dB)", justify="right", width=11)
    table.add_column("Q Factor", justify="right", width=10)

    for flt in prof.filters:
        gain_str = f"+{flt.gain:.1f}" if flt.gain > 0 else f"{flt.gain:.1f}"
        table.add_row(
            str(flt.filter_index),
            flt.filter_type.value,
            f"{flt.frequency:.1f} Hz",
            gain_str,
            f"{flt.q:.2f}",
        )

    console.print(table)
    console.print()


# ==============================================================================
# SPATIAL COMMANDS (Phase 5.4)
# ==============================================================================


@spatial_app.command(name="setup")
def spatial_setup(
    sofa: Annotated[
        Path | None,
        typer.Option("--sofa", "-s", help="Path to custom .sofa HRTF impulse file (downloads default KEMAR if omitted)"),
    ] = None,
    preamp: Annotated[
        float | None,
        typer.Option("--preamp", "-p", help="Override base spatial attenuation in dB (default: -8.0 dB)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview configuration changes without writing files"),
    ] = False,
    no_reload: Annotated[
        bool,
        typer.Option("--no-reload", help="Skip restarting PipeWire daemon"),
    ] = False,
    output_dir: Annotated[
        Path | None,
        typer.Option(help="Custom destination directory for PipeWire drop-in config"),
    ] = None,
) -> None:
    """Set up PipeWire 7.1.4 virtual spatial audio sink with SOFA HRTF convolution and anti-clipping preamp."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]PipeWire 7.1.4 Spatial Binaural Virtualization Setup[/bold white]",
            border_style="cyan",
        )
    )

    # 1. Resolve or download standard SOFA HRTF dataset
    if sofa:
        if not sofa.exists():
            console.print(f"[bold red]Error:[/bold red] Specified SOFA file not found: {sofa}")
            raise typer.Exit(code=1)
        resolved_sofa = sofa.resolve()
    else:
        resolved_sofa = ensure_default_sofa_hrtf()

    sofa_info = inspect_sofa_file(resolved_sofa)
    console.print(f"[bold]HRTF Impulse Dataset:[/bold] [green]{resolved_sofa.name}[/green] ({sofa_info['size_bytes']} bytes)")

    # 2. Gain Staging: Dynamic composite preamp attenuation
    base_p = preamp if preamp is not None else STANDARD_7_1_4_BASE_PREAMP_DB
    active_peq = get_active_peq_state()
    peq_headroom = active_peq.get("preamp_gain", 0.0) if active_peq else 0.0
    composite_preamp = calculate_composite_preamp(base_preamp_db=base_p, peq_preamp_db=peq_headroom)

    console.print(
        f"[bold]Gain Staging:[/bold] Base 7.1.4 Preamp: [yellow]{base_p:+.1f} dB[/yellow] • "
        f"Transducer PEQ Headroom: [yellow]{peq_headroom:+.1f} dB[/yellow] -> "
        f"Composite Anti-Clipping Preamp: [bold red]{composite_preamp:+.2f} dB[/bold red]\n"
    )

    target_dir = output_dir or DEFAULT_PIPEWIRE_CONF_DIR
    target_file = target_dir / DEFAULT_SPATIAL_CONF_FILE

    if dry_run:
        from vibe_dsp.spatial import generate_pipewire_spatial_filter_chain_config

        cfg_preview = generate_pipewire_spatial_filter_chain_config(
            sofa_path=resolved_sofa,
            composite_preamp_db=composite_preamp,
        )
        console.print(f"[bold yellow][DRY RUN MODE][/bold yellow] Previewing {target_file}:")
        console.print(cfg_preview)
        console.print("\n[yellow]Dry run completed. No files modified.[/yellow]")
        return

    # 3. Write persistent configuration with automatic backup and rollback
    written_file = write_spatial_filter_chain(
        sofa_path=resolved_sofa,
        composite_preamp_db=composite_preamp,
        conf_dir=target_dir,
        filename=DEFAULT_SPATIAL_CONF_FILE,
    )

    # 4. Reload PipeWire daemons unless suppressed
    reload_msg = "Skipped (--no-reload)"
    if not no_reload:
        success, reload_msg = reload_pipewire_daemons()
        if success:
            console.print(f"[bold green]Daemon Reload:[/bold green] {reload_msg}")
        else:
            console.print(f"[bold yellow]Daemon Notice:[/bold yellow] {reload_msg}")

    # 5. Output summary table
    table = Table(title="7.1.4 Spatial Convolver Status", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Virtual Sink Name", f"[bold green]{SPATIAL_SINK_NAME}[/bold green]")
    table.add_row("Channel Layout", "7.1.4 (FL, FR, FC, LFE, SL, SR, BL, BR, TFL, TFR, TBL, TBR)")
    table.add_row("Virtualization Mode", "3D Binaural Headphone Output")
    table.add_row("HRTF Impulse Model", f"{resolved_sofa.name} ({sofa_info.get('format', 'SOFA')})")
    table.add_row("Composite Preamp", f"{composite_preamp:+.2f} dB (guarantees 0 dBFS ceiling)")
    table.add_row("Drop-in File", str(written_file))

    console.print(table)
    console.print(
        "\n[bold green]Success:[/bold green] PipeWire 7.1.4 spatial audio bridge installed. "
        "Switch profiles anytime via [bold]vibe-dsp profile set spatial-headphones[/bold] or "
        "[bold]vibe-dsp spatial toggle[/bold]\n"
    )


@spatial_app.command(name="status")
def spatial_status() -> None:
    """Check current status of the 7.1.4 virtual spatial audio sink in PipeWire."""
    status = get_spatial_virtualization_status()

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]vibe-dsp[/bold cyan] [bold white]Spatial Virtualization Status[/bold white]",
            border_style="cyan",
        )
    )

    table = Table(show_header=False)
    table.add_column("Property", style="bold")
    table.add_column("Value")

    inst_str = "[green]Yes[/green]" if status.get("installed") else "[yellow]No (run vibe-dsp spatial setup)[/yellow]"
    active_str = "[green]Active in PipeWire graph[/green]" if status.get("is_active") else "[yellow]Inactive / Standby[/yellow]"
    mode_str = (
        "[bold magenta]3D Binaural Virtualization[/bold magenta]" if status.get("mode") == "3d_binaural" else "[cyan]Stereo Direct Bypass[/cyan]"
    )

    table.add_row("Drop-in Installed", inst_str)
    table.add_row("Sink Name", status.get("sink_name", SPATIAL_SINK_NAME))
    table.add_row("Graph State", active_str)
    table.add_row("Node ID", str(status.get("node_id") or "N/A"))
    table.add_row("Routing Mode", mode_str)
    table.add_row("Channel Architecture", "7.1.4 (12 input channels -> 2 binaural ears)")

    console.print(table)
    console.print()


@spatial_app.command(name="toggle")
def spatial_toggle(
    mode: Annotated[
        str | None,
        typer.Option("--mode", "-m", help="Target mode: '3d_binaural' or 'stereo_direct' (toggles if omitted)"),
    ] = None,
) -> None:
    """Toggle between 3D Binaural Virtualization and Stereo Direct bypass."""
    status = get_spatial_virtualization_status()
    current_mode = status.get("mode", "stereo_direct")

    if mode:
        target_mode = mode.lower().strip()
    else:
        target_mode = "stereo_direct" if current_mode == "3d_binaural" else "3d_binaural"

    success = set_spatial_virtualization_mode(target_mode)
    label = "3D Binaural Virtualization" if target_mode in {"3d_binaural", "3d", "enable"} else "Stereo Direct Bypass"

    if success:
        console.print(f"[bold green]Spatial Mode Updated:[/bold green] Switched to [bold]{label}[/bold]")
    else:
        console.print(f"[bold yellow]Notice:[/bold yellow] Set spatial mode to {label} (saved to persistent state)")


# ==============================================================================
# PROFILE COMMANDS (Phase 5.4 Integration API)
# ==============================================================================


@profile_app.command(name="get")
def profile_get() -> None:
    """Display the currently active audio profile."""
    client = DSPClient()
    active = client.get_profile()
    matched = [p for p in AVAILABLE_PROFILES if p["id"] == active]
    desc = matched[0]["description"] if matched else ""
    console.print(f"[bold cyan]Active Audio Profile:[/bold cyan] [bold green]{active}[/bold green] ({desc})")


@profile_app.command(name="set")
def profile_set(
    profile_id: Annotated[
        str,
        typer.Argument(help="Target profile: 'pure-bitperfect', 'spatial-headphones', or 'receiver-passthrough'"),
    ],
) -> None:
    """Switch active audio profile on the fly across ALSA, PipeWire, and HDMI outputs."""
    client = DSPClient()
    try:
        res = client.set_profile(profile_id)
        if res.get("status") == "ok":
            console.print(f"[bold green]Success:[/bold green] {res.get('message')}")
        else:
            console.print(f"[bold red]Error:[/bold red] {res.get('message')}")
            raise typer.Exit(code=1)
    except Exception as err:
        console.print(f"[bold red]Profile switch failed:[/bold red] {err}")
        raise typer.Exit(code=1)


@profile_app.command(name="list")
def profile_list() -> None:
    """List all available audio profiles and their hardware routing targets."""
    client = DSPClient()
    profiles = client.list_profiles()
    active = client.get_profile()

    console.print()
    table = Table(title="Available Vibe-DSP Audio Profiles", header_style="bold cyan")
    table.add_column("Profile ID", style="bold green", width=22)
    table.add_column("Name", style="white", width=26)
    table.add_column("Routing Target", style="yellow", width=18)
    table.add_column("Description", style="dim")

    for p in profiles:
        is_active = p["id"] == active
        id_str = f"[bold green]* {p['id']}[/bold green]" if is_active else f"  {p['id']}"
        table.add_row(id_str, p["name"], p.get("target", "dsp"), p["description"])

    console.print(table)
    console.print()


@profile_app.command(name="serve")
def profile_serve(
    socket_path: Annotated[
        Path | None,
        typer.Option("--socket", "-s", help="Path to UNIX domain socket for IPC"),
    ] = None,
) -> None:
    """Start the vibe-dsp IPC socket server daemon for real-time web profile switching."""
    import asyncio

    sock = socket_path or DEFAULT_IPC_SOCKET_PATH
    console.print(f"[bold cyan]Starting Vibe-DSP IPC server on:[/bold cyan] [green]{sock}[/green]")

    async def _run() -> None:
        server = await start_ipc_server(sock)
        async with server:
            await server.serve_forever()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]IPC server stopped by user.[/yellow]")
