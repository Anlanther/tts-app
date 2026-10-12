"""Best-effort process memory readings.

Unlike thermal telemetry, memory needs no external command or privilege: we read
the running process directly. On macOS we ask the kernel for
``mach_task_basic_info`` (which reports current *and* peak resident size), and
elsewhere we fall back to ``resource.getrusage`` peak RSS. Units differ per
platform (macOS reports bytes, Linux kibibytes), so we normalise everything to
MiB. Readings degrade quietly to ``None`` when nothing is available.
"""

from __future__ import annotations

import ctypes
import resource
import sys
from dataclasses import dataclass

_BYTES_PER_MIB = 1024 * 1024
_KIB_PER_MIB = 1024

# ``task_info`` flavour that fills a ``mach_task_basic_info`` struct.
_MACH_TASK_BASIC_INFO = 20


class _MachTaskBasicInfo(ctypes.Structure):
    """Mirror of ``struct mach_task_basic_info`` (macOS)."""

    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_max", ctypes.c_uint64),
        ("user_time_sec", ctypes.c_int32),
        ("user_time_usec", ctypes.c_int32),
        ("system_time_sec", ctypes.c_int32),
        ("system_time_usec", ctypes.c_int32),
        ("policy", ctypes.c_int32),
        ("suspend_count", ctypes.c_int32),
    ]


def _macos_rss_mib() -> tuple[float | None, float | None]:
    """Return ``(current, peak)`` resident size in MiB on macOS, else ``(None, None)``.

    Uses ``task_info(MACH_TASK_BASIC_INFO)``, which is available without root and
    without spawning a process.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mach_task_self.restype = ctypes.c_uint32
        info = _MachTaskBasicInfo()
        count = ctypes.c_uint32(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32))
        result = libc.task_info(
            libc.mach_task_self(),
            ctypes.c_uint32(_MACH_TASK_BASIC_INFO),
            ctypes.byref(info),
            ctypes.byref(count),
        )
    except (AttributeError, OSError, ValueError):
        return None, None
    if result != 0:
        return None, None
    current = info.resident_size / _BYTES_PER_MIB if info.resident_size else None
    peak = info.resident_size_max / _BYTES_PER_MIB if info.resident_size_max else None
    return current, peak


def _peak_rss_mib() -> float | None:
    """Return peak resident size in MiB via ``getrusage``, or None.

    ``ru_maxrss`` is reported in bytes on macOS but kibibytes on Linux and other
    Unixes, so the divisor depends on the platform.
    """
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except (ValueError, OSError):
        return None
    raw = usage.ru_maxrss
    if raw <= 0:
        return None
    return raw / _BYTES_PER_MIB if sys.platform == "darwin" else raw / _KIB_PER_MIB


@dataclass(frozen=True)
class MemoryReading:
    """A single best-effort memory snapshot, in mebibytes (MiB)."""

    current_mib: float | None = None
    peak_mib: float | None = None

    def label(self) -> str:
        """Human-readable value for progress output (e.g. ``'412MB'``)."""
        if self.current_mib is not None:
            return f"{self.current_mib:.0f}MB"
        if self.peak_mib is not None:
            return f"{self.peak_mib:.0f}MB peak"
        return "n/a"


def read_memory_reading() -> MemoryReading:
    """Return a best-effort memory snapshot for the current process.

    Prefers current+peak RSS on macOS and falls back to peak RSS elsewhere.
    """
    if sys.platform == "darwin":
        current, peak = _macos_rss_mib()
        if current is not None:
            return MemoryReading(current_mib=current, peak_mib=peak)
    return MemoryReading(peak_mib=_peak_rss_mib())
