"""Tests for best-effort process memory readings."""

from __future__ import annotations

import sys

import pytest

from tts_app.utils import memory


def test_label_prefers_current() -> None:
    assert memory.MemoryReading(current_mib=412.6).label() == "413MB"


def test_label_includes_rss_when_present() -> None:
    reading = memory.MemoryReading(current_mib=2437.0, rss_mib=178.4)
    assert reading.label() == "2.4GB (rss 178MB)"


def test_label_switches_to_gb_above_1000_mib() -> None:
    assert memory.MemoryReading(current_mib=5120.0).label() == "5.0GB"


def test_label_falls_back_to_peak() -> None:
    assert memory.MemoryReading(peak_mib=512.0).label() == "512MB peak"


def test_label_unknown() -> None:
    assert memory.MemoryReading().label() == "n/a"


def test_read_memory_reading_returns_a_reading() -> None:
    reading = memory.read_memory_reading()
    assert isinstance(reading, memory.MemoryReading)
    assert isinstance(reading.label(), str)


@pytest.mark.skipif(sys.platform != "darwin", reason="footprint is read via mach on macOS")
def test_macos_reports_footprint_and_rss() -> None:
    reading = memory.read_memory_reading()
    assert reading.current_mib is not None
    assert reading.current_mib > 0
    assert reading.rss_mib is not None
    assert reading.rss_mib > 0
