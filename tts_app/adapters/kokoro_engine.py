"""Kokoro-82M TTS engine via mlx-audio.

Targets the mlx-audio >= 0.5 API, where ``load_model`` returns a single
``nn.Module`` and ``model.generate(...)`` is a generator of ``GenerationResult``
objects (each carrying a 1-D ``audio`` array and ``sample_rate``).

Kokoro additionally requires the optional ``misaki`` package for text
processing (G2P). It is pulled in via the project dependencies.

All interaction with mlx-audio is centralised here so an upstream API change
only requires adjusting this one file.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from tts_app.domain.models import MissingDependencyError, SynthesisError


class KokoroEngine:
    def __init__(
        self,
        model_path: str = "mlx-community/Kokoro-82M-bf16",
        sample_rate: int = 24000,
        lang_code: str = "a",
        speed: float = 1.0,
    ) -> None:
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.lang_code = lang_code
        self.speed = speed
        self._model: Any = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from mlx_audio.tts.utils import load_model as _load_model
        except ImportError as exc:
            raise MissingDependencyError(
                "mlx-audio is not installed. Run `uv sync` first."
            ) from exc

        load_model: Any = _load_model
        try:
            self._model = load_model(self.model_path)
        except ImportError as exc:
            # e.g. the optional `misaki` package is missing for Kokoro.
            raise MissingDependencyError(
                f"Could not load model '{self.model_path}': {exc}"
            ) from exc
        self._loaded = True

    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        self._ensure_loaded()
        assert self._model is not None
        try:
            segments = list(
                self._model.generate(
                    text=text,
                    voice=voice,
                    speed=self.speed,
                    lang_code=self.lang_code,
                )
            )
        except Exception as exc:  # noqa: BLE001 - engine raises arbitrary errors
            raise SynthesisError(f"Kokoro synthesis failed: {exc}") from exc

        if not segments:
            raise SynthesisError("Kokoro returned no audio.")
        _write_segments(out_path, segments, self.sample_rate)


def _write_segments(out_path: Path, segments: list[Any], sample_rate: int) -> None:
    import numpy as np

    arrays = [np.asarray(segment.audio) for segment in segments]
    joined = np.concatenate(arrays) if len(arrays) > 1 else arrays[0]
    _write_wav(out_path, joined, sample_rate)


def _write_wav(path: Path, samples: Any, sample_rate: int) -> None:
    import numpy as np

    arr = np.asarray(samples)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    arr = np.clip(arr.astype(np.float32), -1.0, 1.0)
    arr = (arr * 32767.0).astype(np.int16)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())
