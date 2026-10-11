"""Tests for config precedence and duration parsing."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tts_app.config import load_settings, parse_duration


def test_parse_duration() -> None:
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("45") == timedelta(seconds=45)
    assert parse_duration("7d") == timedelta(days=7)


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_duration("not-a-duration")


def test_cli_overrides_win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text('voice = "from_toml"\nchunk_target_chars = 777\n', encoding="utf-8")
    monkeypatch.setenv("TTS_VOICE", "from_env")
    settings = load_settings(toml_path=toml, cli_overrides={"voice": "from_cli"})
    assert settings.voice == "from_cli"
    assert settings.chunk_target_chars == 777


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "config.toml"
    toml.write_text('voice = "from_toml"\n', encoding="utf-8")
    monkeypatch.setenv("TTS_VOICE", "from_env")
    settings = load_settings(toml_path=toml)
    assert settings.voice == "from_env"


def test_defaults_apply_without_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TTS_VOICE", raising=False)
    monkeypatch.delenv("TTS_SLEEP_BETWEEN_CHUNKS", raising=False)
    settings = load_settings(toml_path=tmp_path / "missing.toml")
    assert settings.voice == "bm_daniel"
    assert settings.sleep_between_chunks == 2.0
