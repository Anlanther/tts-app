"""Tests for best-effort thermal readings and pressure parsing."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tts_app.utils import thermal

SMC_OUTPUT = """\
Machine model: MacBookPro16,1
**** SMC sensors ****
CPU die temperature: 61.25 C
GPU die temperature: 55.00 C
"""

THERMAL_OUTPUT = """\
**** Thermal pressure ****
Current pressure level: Heavy
"""


class _Completed:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _patch_powermetrics(
    monkeypatch: pytest.MonkeyPatch, outputs: dict[str, str]
) -> Callable[..., _Completed]:
    """Fake ``subprocess.run`` returning canned output per sampler name.

    Samplers absent from ``outputs`` behave like an unsupported sampler: an
    empty result with a non-zero exit code.
    """

    def fake_run(cmd: list[str], **_kwargs: object) -> _Completed:
        sampler = cmd[cmd.index("--samplers") + 1]
        if sampler not in outputs:
            return _Completed("", returncode=1)
        return _Completed(outputs[sampler])

    monkeypatch.setattr(thermal.subprocess, "run", fake_run)
    return fake_run


def test_read_cpu_temperature_parses_smc(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_powermetrics(monkeypatch, {"smc": SMC_OUTPUT})
    assert thermal.read_cpu_temperature() == 61.25


def test_read_cpu_temperature_none_when_sampler_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_powermetrics(monkeypatch, {})
    assert thermal.read_cpu_temperature() is None


def test_read_thermal_pressure_parses_level(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_powermetrics(monkeypatch, {"thermal": THERMAL_OUTPUT})
    assert thermal.read_thermal_pressure() == "Heavy"


def test_read_thermal_reading_prefers_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_powermetrics(monkeypatch, {"smc": SMC_OUTPUT, "thermal": THERMAL_OUTPUT})
    reading = thermal.read_thermal_reading()
    assert reading.label() == "61.2C"


def test_read_thermal_reading_falls_back_to_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Apple Silicon: smc unsupported, thermal available.
    _patch_powermetrics(monkeypatch, {"thermal": THERMAL_OUTPUT})
    reading = thermal.read_thermal_reading()
    assert reading.label() == "Heavy"


def test_read_thermal_reading_empty_when_nothing_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_powermetrics(monkeypatch, {})
    assert thermal.read_thermal_reading().label() == "n/a"


def test_pressure_penalty_mapping() -> None:
    assert thermal.pressure_penalty("Nominal") == 0.0
    assert thermal.pressure_penalty("Moderate") == 1.5
    assert thermal.pressure_penalty("heavy") == 3.0
    assert thermal.pressure_penalty("Trapping") == 5.0
    assert thermal.pressure_penalty(None) == 0.0
    assert thermal.pressure_penalty("Unknown") == 0.0
