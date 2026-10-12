"""Tests for inter-chunk cooldown and thermal-aware pacing."""

from __future__ import annotations

import pytest

from tts_app.domain.models import MaxMemoryExceeded
from tts_app.pipeline.throttle import Throttle
from tts_app.utils import memory, thermal


def test_first_chunk_does_not_sleep() -> None:
    slept: list[float] = []
    throttle = Throttle(base_sleep=2.0, sleeper=slept.append)
    assert throttle.wait(0) == 2.0
    assert slept == []


def test_subsequent_chunk_sleeps_base_duration() -> None:
    slept: list[float] = []
    throttle = Throttle(base_sleep=2.0, sleeper=slept.append)
    assert throttle.wait(1) == 2.0
    assert slept == [2.0]


def test_thermal_aware_extends_pause_via_speed_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thermal, "read_cpu_speed_limit", lambda: 20)
    slept: list[float] = []
    throttle = Throttle(
        base_sleep=2.0, thermal_aware=True, thermal_threshold=50, sleeper=slept.append
    )
    # penalty = (50 - 20) / 100 * 5 = 1.5
    assert throttle.wait(1) == 3.5
    assert slept == [3.5]


def test_thermal_aware_falls_back_to_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Apple Silicon: pmset reports no speed limit, powermetrics reports pressure.
    monkeypatch.setattr(thermal, "read_cpu_speed_limit", lambda: None)
    monkeypatch.setattr(
        thermal,
        "read_thermal_reading",
        lambda: thermal.ThermalReading(pressure="Heavy"),
    )
    slept: list[float] = []
    throttle = Throttle(base_sleep=2.0, thermal_aware=True, sleeper=slept.append)
    assert throttle.wait(1) == 5.0
    assert slept == [5.0]


def test_not_thermal_aware_ignores_thermals(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail() -> None:
        raise AssertionError("thermals must not be read when not thermal-aware")

    monkeypatch.setattr(thermal, "read_cpu_speed_limit", _fail)
    throttle = Throttle(base_sleep=2.0, thermal_aware=False, sleeper=lambda _s: None)
    assert throttle.wait(1) == 2.0


def test_memory_limit_raises_when_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        memory, "read_memory_reading", lambda: memory.MemoryReading(current_mib=2048.0)
    )
    throttle = Throttle(base_sleep=0.0, max_memory_mb=1024, sleeper=lambda _s: None)
    with pytest.raises(MaxMemoryExceeded):
        throttle.wait(1)


def test_memory_limit_ignored_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        memory, "read_memory_reading", lambda: memory.MemoryReading(current_mib=512.0)
    )
    throttle = Throttle(base_sleep=0.0, max_memory_mb=1024, sleeper=lambda _s: None)
    assert throttle.wait(1) == 0.0


def test_no_memory_limit_skips_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail() -> None:
        raise AssertionError("memory must not be read without a limit")

    monkeypatch.setattr(memory, "read_memory_reading", _fail)
    throttle = Throttle(base_sleep=0.0, sleeper=lambda _s: None)
    assert throttle.wait(1) == 0.0
