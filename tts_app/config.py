"""Application configuration with precedence: CLI > env (``TTS_*``) > TOML > defaults."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_FILE = Path.home() / ".config" / "tts_app" / "config.toml"
_STATE_DIR = Path.home() / ".local" / "state" / "tts_app"

_DURATION_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*"
    r"(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)?\s*$",
    re.IGNORECASE,
)


def parse_duration(value: str) -> timedelta:
    """Parse a human duration such as ``2h``, ``30m``, ``7d`` or ``45`` (seconds)."""
    match = _DURATION_RE.match(value)
    if not match:
        raise ValueError(f"Invalid duration '{value}'. Use e.g. '30s', '2h', '7d'.")
    number = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    factors = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }
    return timedelta(seconds=number * factors[unit])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Model / engine
    model_path: str = "mlx-community/Kokoro-82M-bf16"
    voice: str = "bm_daniel"
    lang_code: str = "b"
    speed: float = 2.0
    sample_rate: int = 24000

    # Chunking
    chunk_target_chars: int = 1000
    chunk_max_chars: int = 1500
    chunk_min_chars: int = 500

    # Synthesis pacing / thermal
    sleep_between_chunks: float = 2.0
    thermal_aware: bool = False
    max_runtime: timedelta | None = None
    thermal_threshold: int = 50

    # Memory monitoring
    memory_aware: bool = False
    max_memory_mb: int | None = None

    # Retries
    retries: int = 2
    retry_backoff: float = 2.0

    # Output / merging
    normalize: bool = True
    mp3_bitrate: str = "192k"
    inter_chunk_silence_ms: int = 250

    # Paths
    state_dir: Path = _STATE_DIR

    @field_validator("max_runtime", mode="before")
    @classmethod
    def _parse_max_runtime(cls, value: Any) -> Any:
        if isinstance(value, str):
            return parse_duration(value)
        return value

    def config_hash(self) -> str:
        """Hash of the settings that affect the synthesized audio."""
        relevant = {
            "model_path": self.model_path,
            "voice": self.voice,
            "lang_code": self.lang_code,
            "speed": self.speed,
            "sample_rate": self.sample_rate,
            "chunk_target_chars": self.chunk_target_chars,
            "chunk_max_chars": self.chunk_max_chars,
            "chunk_min_chars": self.chunk_min_chars,
            "mp3_bitrate": self.mp3_bitrate,
            "normalize": self.normalize,
            "inter_chunk_silence_ms": self.inter_chunk_silence_ms,
        }
        encoded = json.dumps(relevant, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:12]


def load_settings(
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    toml_path: Path | None = None,
) -> Settings:
    """Load settings with precedence defaults < TOML < env < CLI overrides."""
    toml_values: dict[str, Any] = {}
    path = toml_path if toml_path is not None else _CONFIG_FILE
    if path.exists():
        try:
            toml_values = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            toml_values = {}

    init_kwargs: dict[str, Any] = {**toml_values, **_read_env_overrides()}
    if cli_overrides:
        init_kwargs.update(cli_overrides)
    return Settings(**init_kwargs)


def _read_env_overrides() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in Settings.model_fields:
        env_name = f"TTS_{field_name.upper()}"
        value = os.environ.get(env_name)
        if value is not None:
            result[field_name] = value
    return result
