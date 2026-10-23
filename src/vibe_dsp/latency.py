"""Kernel DPC latency watchdog, xrun detector, and RealtimeKit scheduler (Phase 5.2).

Tracks ALSA/PipeWire buffer underruns, kernel scheduling jitter, ACPI CPU
throttling, and negotiates low-latency real-time thread priorities via rtkit.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from vibe_dsp.models import (
    CpuCorePowerState,
    JitterMetrics,
    LatencyHealthRating,
    LatencyMonitorReport,
    MicroStutterAnomaly,
    PowerProfileReport,
    XrunReport,
)

logger = logging.getLogger(__name__)


def check_alsa_xruns(
    procfs_root: Path = Path("/proc/asound"),
    card_index: int = 1,
    device_index: int = 0,
) -> XrunReport:
    """Parse ALSA procfs subdevice status and hw_params for underruns (xruns).

    Args:
        procfs_root: Base path to ALSA procfs.
        card_index: ALSA card index.
        device_index: ALSA device index.

    Returns:
        XrunReport: Status, active sampling rate, period size, and xrun counter.
    """
    card_dir = procfs_root / f"card{card_index}"
    sub_dir = card_dir / f"pcm{device_index}p" / "sub0"
    status_file = sub_dir / "status"
    hw_params_file = sub_dir / "hw_params"

    state = "closed"
    xrun_count = 0
    active_rate: int | None = None
    buffer_size: int | None = None
    period_size: int | None = None

    if status_file.exists():
        try:
            status_text = status_file.read_text(encoding="utf-8", errors="replace")
            for line in status_text.splitlines():
                line = line.strip()
                if line.startswith("state:"):
                    state = line.split(":", 1)[1].strip()
                    if "XRUN" in state.upper():
                        xrun_count += 1
                elif "xrun" in line.lower():
                    # Some sound drivers export explicit xrun counters
                    nums = re.findall(r"\d+", line)
                    if nums:
                        xrun_count = max(xrun_count, int(nums[0]))
        except Exception as err:
            logger.debug("Could not read ALSA status %s: %s", status_file, err)

    if hw_params_file.exists():
        try:
            hw_text = hw_params_file.read_text(encoding="utf-8", errors="replace")
            for line in hw_text.splitlines():
                line = line.strip()
                if line.startswith("rate:"):
                    nums = re.findall(r"\d+", line)
                    if nums:
                        active_rate = int(nums[0])
                elif line.startswith("buffer_size:"):
                    nums = re.findall(r"\d+", line)
                    if nums:
                        buffer_size = int(nums[0])
                elif line.startswith("period_size:"):
                    nums = re.findall(r"\d+", line)
                    if nums:
                        period_size = int(nums[0])
        except Exception as err:
            logger.debug("Could not read ALSA hw_params %s: %s", hw_params_file, err)

    # Optional PipeWire event error counters
    pw_errors = 0
    pw_rate: int | None = None
    if shutil.which("pw-dump"):
        try:
            # Quick non-blocking inspection of PipeWire ALSA nodes
            res = subprocess.run(
                ["pw-dump", "Node"],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if res.returncode == 0 and "xrun" in res.stdout.lower():
                pw_errors += len(re.findall(r'"xrun"', res.stdout, re.IGNORECASE))
        except Exception:
            pass

    return XrunReport(
        card_index=card_index,
        device_index=device_index,
        state=state,
        xrun_count=xrun_count,
        active_rate=active_rate,
        buffer_size=buffer_size,
        period_size=period_size,
        pipewire_errors=pw_errors,
        pipewire_rate=pw_rate,
    )


def measure_scheduling_jitter(
    samples: int = 50,
    interval_ms: float = 1.0,
) -> JitterMetrics:
    """Measure real-time kernel thread scheduling delay and jitter.

    Uses high-precision timer loop to calculate timer latency and jitter
    deviations in microseconds.

    Args:
        samples: Number of timer samples to evaluate.
        interval_ms: Target wake-up interval in milliseconds.

    Returns:
        JitterMetrics: Microsecond scheduling latency statistics.
    """
    jitters_us: list[float] = []
    interval_ns = int(interval_ms * 1_000_000)

    # High-precision timer latency measurement loop
    for _ in range(samples):
        t_start = time.perf_counter_ns()
        time.sleep(interval_ms / 1000.0)
        t_elapsed = time.perf_counter_ns() - t_start
        jitter_ns = abs(t_elapsed - interval_ns)
        jitters_us.append(jitter_ns / 1_000.0)

    if not jitters_us:
        return JitterMetrics()

    min_j = min(jitters_us)
    max_j = max(jitters_us)
    avg_j = sum(jitters_us) / len(jitters_us)
    variance = sum((x - avg_j) ** 2 for x in jitters_us) / len(jitters_us)
    stddev_j = math.sqrt(variance)

    return JitterMetrics(
        min_jitter_us=round(min_j, 2),
        avg_jitter_us=round(avg_j, 2),
        max_jitter_us=round(max_j, 2),
        stddev_jitter_us=round(stddev_j, 2),
        sample_count=len(jitters_us),
        source="python_perf_counter",
    )


def detect_cpu_power_profile(
    sysfs_root: Path = Path("/sys"),
) -> PowerProfileReport:
    """Audit ACPI CPU throttling and frequency scaling states across CPU cores.

    Args:
        sysfs_root: Base path to sysfs (/sys).

    Returns:
        PowerProfileReport: Power profile status, throttling flags, and advice.
    """
    cpu_dir = sysfs_root / "devices" / "system" / "cpu"
    cores: list[CpuCorePowerState] = []
    is_throttled = False
    active_governor = "unknown"

    core_dirs = sorted(
        cpu_dir.glob("cpu[0-9]*"),
        key=lambda d: int(d.name.replace("cpu", "")),
    )

    for c_dir in core_dirs:
        core_id = int(c_dir.name.replace("cpu", ""))
        cpufreq_dir = c_dir / "cpufreq"
        if not cpufreq_dir.exists():
            continue

        gov_file = cpufreq_dir / "scaling_governor"
        cur_file = cpufreq_dir / "scaling_cur_freq"
        max_file = cpufreq_dir / "scaling_max_freq"
        epp_file = cpufreq_dir / "energy_performance_preference"

        gov = gov_file.read_text().strip() if gov_file.exists() else "unknown"
        active_governor = gov
        cur_mhz = float(cur_file.read_text().strip()) / 1000.0 if cur_file.exists() else 0.0
        max_mhz = float(max_file.read_text().strip()) / 1000.0 if max_file.exists() else 0.0
        epp = epp_file.read_text().strip() if epp_file.exists() else None

        # Detect throttling if core is capped below 65% of max clock in powersave
        core_throttled = max_mhz > 0 and cur_mhz > 0 and (cur_mhz / max_mhz) < 0.45 and gov in ("powersave", "power")
        if core_throttled:
            is_throttled = True

        cores.append(
            CpuCorePowerState(
                core_id=core_id,
                governor=gov,
                cur_freq_mhz=round(cur_mhz, 1),
                max_freq_mhz=round(max_mhz, 1),
                epp=epp,
                is_throttled=core_throttled,
            )
        )

    # Check Power Supply status (AC vs Battery)
    ac_online = True
    battery_present = False
    battery_status: str | None = None
    power_supply_dir = sysfs_root / "class" / "power_supply"

    if power_supply_dir.exists():
        for psy in power_supply_dir.iterdir():
            name = psy.name.upper()
            if "ADP" in name or "AC" in name or "LINE" in name:
                online_file = psy / "online"
                if online_file.exists():
                    try:
                        ac_online = online_file.read_text().strip() == "1"
                    except Exception:
                        pass
            elif "BAT" in name:
                battery_present = True
                status_file = psy / "status"
                if status_file.exists():
                    try:
                        battery_status = status_file.read_text().strip()
                    except Exception:
                        pass

    rec = "System power profile optimal."
    if not ac_online and is_throttled:
        rec = "AC power disconnected and CPU throttling active. Connect charger to prevent high-res DSD/PCM dropouts."
    elif not ac_online:
        rec = "Running on battery power. Latency is acceptable, but background CPU scaling may introduce jitter."
    elif is_throttled:
        rec = "CPU scaling governor is throttling clock speeds. Consider governor=performance."

    return PowerProfileReport(
        ac_online=ac_online,
        battery_present=battery_present,
        battery_status=battery_status,
        cores=cores,
        is_throttled=is_throttled,
        active_governor=active_governor,
        recommendation=rec,
    )


def request_realtime_scheduling(
    priority: int = 50,
    target_pid: int | None = None,
) -> tuple[bool, str]:
    """Request low-latency real-time scheduling permissions via RealtimeKit (rtkit).

    Communicates with org.freedesktop.RealtimeKit1 via busctl or dbus-send.

    Args:
        priority: Desired real-time priority (e.g. 1-99).
        target_pid: Process or thread ID (defaults to current process).

    Returns:
        tuple[bool, str]: Success boolean and descriptive status details.
    """
    pid = target_pid or os.getpid()

    # 1. Try busctl call to RealtimeKit1
    if shutil.which("busctl"):
        try:
            res = subprocess.run(
                [
                    "busctl",
                    "call",
                    "--system",
                    "org.freedesktop.RealtimeKit1",
                    "/org/freedesktop/RealtimeKit1",
                    "org.freedesktop.RealtimeKit1",
                    "MakeThreadRealtimeWithPID",
                    "uu",
                    str(pid),
                    str(priority),
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if res.returncode == 0:
                logger.info("RealtimeKit granted RT priority %d to PID %d", priority, pid)
                return True, f"RealtimeKit: Granted SCHED_RR priority {priority}"
        except Exception as err:
            logger.debug("busctl rtkit call failed: %s", err)

    # 2. Try chrt check/request
    if shutil.which("chrt"):
        try:
            res = subprocess.run(
                ["chrt", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=1.0,
                check=False,
            )
            if "SCHED_FIFO" in res.stdout or "SCHED_RR" in res.stdout:
                return True, f"Scheduler: Current policy {res.stdout.strip()}"
        except Exception:
            pass

    return False, "RealtimeKit permission not acquired (standard CFS scheduling)"


def evaluate_latency_health(
    xrun_report: XrunReport,
    jitter_metrics: JitterMetrics,
    power_profile: PowerProfileReport,
    rtkit_granted: bool,
) -> tuple[LatencyHealthRating, list[str]]:
    """Determine concise system latency health rating (Good / Marginal / Throttled).

    Args:
        xrun_report: Detected hardware buffer underruns.
        jitter_metrics: Audio thread scheduling latency in microseconds.
        power_profile: CPU frequency scaling and ACPI power state.
        rtkit_granted: Whether low-latency real-time permissions are active.

    Returns:
        tuple[LatencyHealthRating, list[str]]: Rating and diagnostic bullet points.
    """
    diagnostics: list[str] = []

    # Check for hard failures
    if xrun_report.xrun_count > 0 or xrun_report.state == "XRUN":
        diagnostics.append(f"Hardware underrun (xrun) detected on card {xrun_report.card_index}: {xrun_report.xrun_count} dropouts")
    if jitter_metrics.max_jitter_us > 2500.0:
        diagnostics.append(f"Extreme scheduling jitter spike: {jitter_metrics.max_jitter_us:.1f} µs (>2.5 ms)")
    if power_profile.is_throttled and not power_profile.ac_online:
        diagnostics.append("ACPI battery throttling active: CPU frequency severely depressed")

    if diagnostics:
        return LatencyHealthRating.THROTTLED, diagnostics

    # Check for marginal warning signs
    if jitter_metrics.max_jitter_us > 1000.0:
        diagnostics.append(f"Elevated DPC jitter: {jitter_metrics.max_jitter_us:.1f} µs (>1.0 ms)")
    if not power_profile.ac_online:
        diagnostics.append("Battery power active: dynamic frequency scaling may induce jitter")
    if power_profile.active_governor == "powersave":
        diagnostics.append("CPU governor set to powersave; recommends performance mode for DSD")
    if not rtkit_granted:
        diagnostics.append("RealtimeKit priority not active for thread")

    if diagnostics:
        return LatencyHealthRating.MARGINAL, diagnostics

    diagnostics.append("Ultra-low scheduling jitter (<1.0 ms)")
    diagnostics.append("Zero buffer underruns (xruns)")
    diagnostics.append("AC power and frequency scaling optimal")
    return LatencyHealthRating.GOOD, diagnostics


def audit_latency(
    card_index: int = 1,
    device_index: int = 0,
    jitter_samples: int = 30,
    procfs_root: Path = Path("/proc/asound"),
    sysfs_root: Path = Path("/sys"),
) -> LatencyMonitorReport:
    """Execute complete real-time latency audit and return watchdog report."""
    now_str = datetime.now().isoformat()
    load_avg = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0

    xrun_rep = check_alsa_xruns(
        procfs_root=procfs_root,
        card_index=card_index,
        device_index=device_index,
    )

    jitter_rep = measure_scheduling_jitter(samples=jitter_samples)
    power_rep = detect_cpu_power_profile(sysfs_root=sysfs_root)
    rtkit_ok, rtkit_msg = request_realtime_scheduling()

    rating, diags = evaluate_latency_health(
        xrun_report=xrun_rep,
        jitter_metrics=jitter_rep,
        power_profile=power_rep,
        rtkit_granted=rtkit_ok,
    )

    anomalies: list[MicroStutterAnomaly] = []
    if jitter_rep.max_jitter_us > 1000.0 or xrun_rep.xrun_count > 0:
        msg = "Micro-stutter anomaly detected"
        if xrun_rep.xrun_count > 0:
            msg += f": ALSA xruns={xrun_rep.xrun_count}"
        if jitter_rep.max_jitter_us > 1000.0:
            msg += f": jitter={jitter_rep.max_jitter_us:.1f}µs"
        anomalies.append(
            MicroStutterAnomaly(
                timestamp=now_str,
                jitter_us=jitter_rep.max_jitter_us,
                xrun_detected=xrun_rep.xrun_count > 0,
                active_rate=xrun_rep.active_rate,
                system_load=load_avg,
                cpu_throttled=power_rep.is_throttled,
                message=msg,
            )
        )

    return LatencyMonitorReport(
        timestamp=now_str,
        health_rating=rating,
        xrun_report=xrun_rep,
        jitter_metrics=jitter_rep,
        power_profile=power_rep,
        rtkit_granted=rtkit_ok,
        rtkit_details=rtkit_msg,
        system_load=load_avg,
        anomalies=anomalies,
        diagnostics=diags,
    )
