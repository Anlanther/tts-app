"""Playback of preview audio via macOS ``afplay``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tts_app.domain.models import MissingDependencyError, TtsError


def supports_playback() -> bool:
    """Whether built-in preview playback is available on this platform."""
    return sys.platform == "darwin"


def play(path: Path, *, player: str = "afplay") -> None:
    """Play ``path`` and block until playback finishes."""
    try:
        result = subprocess.run([player, str(path)], capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise MissingDependencyError(
            f"'{player}' not found on PATH; pass --no-play to skip playback."
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"exit {result.returncode}"
        raise TtsError(f"'{player}' failed to play '{path}': {detail}")
