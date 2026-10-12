"""Best-effort macOS thermal/performance readings.

macOS exposes thermal telemetry in fragments: ``pmset -g therm`` reports the CPU
speed limit (a throttling signal), while ``powermetrics`` reports die temperature
and thermal pressure. The ``smc`` sampler that carries die temperature only
exists on Intel Macs; Apple Silicon instead exposes a ``thermal`` sampler whose
readings are a pressure *level* (``Nominal``, ``Moderate``, ``Heavy``, ...).
We probe whichever sampler the running Mac supports so a reading is surfaced on
both, and degrade quietly to ``None`` when nothing is available (for example when
``powermetrics`` is not run as root).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

# Extra cooldown seconds implied by each powermetrics thermal pressure level.
_PRESSURE_PENALTY = {
    "nominal": 0.0,
    "moderate": 1.5,
    "heavy": 3.0,
    "trapping": 5.0,
    "sleeping": 5.0,
}


def read_cpu_speed_limit() -> int | None:
    """Return the macOS CPU speed limit percentage (100 = no throttling), or None.

    Parses ``pmset -g therm``. Returns None on non-macOS or if the value cannot
    be read. Apple Silicon does not populate this line until the machine has
    actually throttled, so a None result does not imply the CPU is cool.
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


def _run_powermetrics(sampler: str) -> str | None:
    """Run a single powermetrics sample for ``sampler`` and return stdout.

    Returns None when ``powermetrics`` is missing, not permitted (it usually
    requires root), or does not support the requested sampler.
    """
    try:
        result = subprocess.run(
            ["powermetrics", "--samplers", sampler, "-i", "100", "-n", "1"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout or None


def read_cpu_temperature() -> float | None:
    """Return CPU die temperature in Celsius via the SMC sampler, or None.

    The ``smc`` sampler only exists on Intel Macs; on Apple Silicon the request
    is rejected and this returns None. Use :func:`read_thermal_reading` to get a
    reading on either platform.
    """
    output = _run_powermetrics("smc")
    if output is None:
        return None
    for line in output.splitlines():
        if "CPU die temperature" in line:
            try:
                return float(line.split(":")[-1].strip().split()[0])
            except (ValueError, IndexError):
                return None
    return None


def read_thermal_pressure() -> str | None:
    """Return the current thermal pressure level (e.g. ``'Nominal'``), or None.

    Reads ``powermetrics --samplers thermal``. This sampler is available on
    Apple Silicon, where the SMC temperature sampler is not.
    """
    output = _run_powermetrics("thermal")
    if output is None:
        return None
    for line in output.splitlines():
        if "Current pressure level:" in line:
            level = line.split(":", 1)[1].strip()
            return level or None
    return None


def pressure_penalty(pressure: str | None) -> float:
    """Return the extra cooldown seconds implied by a thermal pressure level."""
    if not pressure:
        return 0.0
    return _PRESSURE_PENALTY.get(pressure.strip().lower(), 0.0)


@dataclass(frozen=True)
class ThermalReading:
    """A single best-effort thermal snapshot."""

    temperature_c: float | None = None
    pressure: str | None = None

    def label(self) -> str:
        """Human-readable value for progress output (e.g. ``'44.2C'``, ``'Nominal'``)."""
        if self.temperature_c is not None:
            return f"{self.temperature_c:.1f}C"
        if self.pressure is not None:
            return self.pressure
        return "n/a"


def read_thermal_reading() -> ThermalReading:
    """Return whatever thermal telemetry this Mac exposes, in one probe.

    Prefers the Intel SMC die-temperature sampler (supported on Intel Macs) and
    falls back to the thermal pressure sampler (supported on Apple Silicon and
    Intel). Returns an empty reading when neither is available.
    """
    temperature = read_cpu_temperature()
    if temperature is not None:
        return ThermalReading(temperature_c=temperature)
    return ThermalReading(pressure=read_thermal_pressure())
