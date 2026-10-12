"""Best-effort process memory readings.

Unlike thermal telemetry, memory needs no external command or privilege: we read
the running process directly. On macOS we ask the kernel for ``task_vm_info``,
which reports the *physical footprint* -- the figure Activity Monitor's "Memory"
column shows -- alongside resident size. The footprint is the more meaningful
number for this project: MLX/Metal buffers live in memory that raw RSS excludes,
so RSS can read a few hundred MB while the real footprint is multiple GB. Else-
where we fall back to peak RSS via ``resource.getrusage``. Units differ per
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

# ``task_info`` flavour that fills a ``task_vm_info`` struct.
_TASK_VM_INFO = 22


class _TaskVmInfo(ctypes.Structure):
    """Mirror of ``struct task_vm_info`` (macOS), truncated after the fields we use.

    The kernel rejects the call unless ``count`` covers at least
    ``phys_footprint_peak``, and the leading fields must match the header byte
    for byte -- including the ``purgeable_volatile_*`` trio -- or every offset
    after them shifts.
    """

    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("region_count", ctypes.c_int32),
        ("page_size", ctypes.c_int32),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_peak", ctypes.c_uint64),
        ("device", ctypes.c_uint64),
        ("device_peak", ctypes.c_uint64),
        ("internal", ctypes.c_uint64),
        ("internal_peak", ctypes.c_uint64),
        ("external", ctypes.c_uint64),
        ("external_peak", ctypes.c_uint64),
        ("reusable", ctypes.c_uint64),
        ("reusable_peak", ctypes.c_uint64),
        ("purgeable_volatile_pmap", ctypes.c_uint64),
        ("purgeable_volatile_resident", ctypes.c_uint64),
        ("purgeable_volatile_virtual", ctypes.c_uint64),
        ("compressed", ctypes.c_uint64),
        ("compressed_peak", ctypes.c_uint64),
        ("compressed_lifetime", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("ledger_phys_footprint_peak", ctypes.c_int64),
    ]


@dataclass(frozen=True)
class _MacosMemory:
    footprint_mib: float | None
    footprint_peak_mib: float | None
    rss_mib: float | None
    rss_peak_mib: float | None


def _macos_memory() -> _MacosMemory:
    """Return the process's memory snapshot on macOS, or all-``None`` fields.

    Uses ``task_info(TASK_VM_INFO)``, which is available without root and
    without spawning a process. ``phys_footprint`` is what Activity Monitor's
    "Memory" column reports; ``resident_size`` is plain RSS.
    """
    empty = _MacosMemory(None, None, None, None)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.mach_task_self.restype = ctypes.c_uint32
        info = _TaskVmInfo()
        count = ctypes.c_uint32(ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32))
        result = libc.task_info(
            libc.mach_task_self(),
            ctypes.c_uint32(_TASK_VM_INFO),
            ctypes.byref(info),
            ctypes.byref(count),
        )
    except (AttributeError, OSError, ValueError):
        return empty
    if result != 0:
        return empty
    return _MacosMemory(
        footprint_mib=_to_mib(info.phys_footprint),
        footprint_peak_mib=_to_mib(info.ledger_phys_footprint_peak),
        rss_mib=_to_mib(info.resident_size),
        rss_peak_mib=_to_mib(info.resident_size_peak),
    )


def _to_mib(raw: int) -> float | None:
    return raw / _BYTES_PER_MIB if raw else None


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
    rss_mib: float | None = None

    def label(self) -> str:
        """Human-readable value for progress output (e.g. ``'2.4GB (rss 178MB)'``)."""
        if self.current_mib is not None:
            text = format_mib(self.current_mib)
            if self.rss_mib is not None:
                return f"{text} (rss {format_mib(self.rss_mib)})"
            return text
        if self.peak_mib is not None:
            return f"{format_mib(self.peak_mib)} peak"
        return "n/a"


def format_mib(value: float) -> str:
    """Format a MiB reading, switching to GB once it reaches four digits."""
    if value >= 1000:
        return f"{value / 1024:.1f}GB"
    return f"{value:.0f}MB"


def read_memory_reading() -> MemoryReading:
    """Return a best-effort memory snapshot for the current process.

    On macOS the lead figure is the physical footprint (with RSS alongside);
    elsewhere it falls back to peak RSS.
    """
    if sys.platform == "darwin":
        snapshot = _macos_memory()
        if snapshot.footprint_mib is not None:
            return MemoryReading(
                current_mib=snapshot.footprint_mib,
                peak_mib=snapshot.footprint_peak_mib,
                rss_mib=snapshot.rss_mib,
            )
    return MemoryReading(peak_mib=_peak_rss_mib())
