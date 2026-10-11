"""Best-effort macOS thermal/performance readings."""

from __future__ import annotations

import subprocess


def read_cpu_speed_limit() -> int | None:
    """Return the macOS CPU speed limit percentage (100 = no throttling), or None.

    Parses ``pmset -g therm``. Returns None on non-macOS or if the value cannot
    be read.
    """
    try:
        result = subprocess.run(
            ["pmset", "-g", "therm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in result.stdout.splitlines():
        if "CPU_Speed_Limit" in line:
            try:
                return int(line.split("=")[-1].strip())
            except ValueError:
                return None
    return None


def read_cpu_temperature() -> float | None:
    """Return CPU die temperature in Celsius if readable, else None.

    Requires ``powermetrics`` which usually needs ``sudo``; returns None when
    unavailable or permission is denied.
    """
    try:
        result = subprocess.run(
            ["powermetrics", "--samplers", "smc", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in result.stdout.splitlines():
        if "CPU die temperature" in line:
            try:
                return float(line.split(":")[-1].strip().split()[0])
            except ValueError:
                return None
    return None
