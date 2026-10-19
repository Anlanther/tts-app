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

import logging
import re
import wave
from pathlib import Path
from typing import Any

from tts_app.domain.models import MissingDependencyError, SynthesisError

logger = logging.getLogger("tts_app.kokoro")

# Kokoro's context window is 510 phonemes. mlx-audio already splits text at
# punctuation (``!.?...`` then ``:;`` then ``,``) so each synthesised piece fits,
# so we hand it the whole chunk and let it chunk -- pre-splitting on a character
# budget severed sentences mid-clause and made adjacent words run together.
#
# The one case mlx-audio cannot rescue is a *single* token whose own phonemes
# exceed the window (a long number, hash, base64 blob, URL slug). Its punctuation
# waterfall finds no break and emits the token whole, which is then truncated to
# 510 phonemes -- the tail is silently dropped. Phoneme density is what matters,
# not characters: digits are the worst offenders (~14 phonemes per digit), while
# ordinary words are ~1. An unbroken alphanumeric run longer than this budget is
# broken into small groups that tokenize to a few phonemes each.
_ALNUM_RUN_CHARS = 32  # 32 digits ~= 341 phonemes, comfortably under 510
_ALNUM_GROUP = 4
_ALNUM_RUN_RE = re.compile(r"[A-Za-z0-9]{" + str(_ALNUM_RUN_CHARS + 1) + r",}")


def _break_alnum_run(match: re.Match[str]) -> str:
    run = match.group(0)
    return " ".join(run[i : i + _ALNUM_GROUP] for i in range(0, len(run), _ALNUM_GROUP))


def _prepare_segments(text: str) -> list[str]:
    """Return text ready for synthesis, breaking tokens that would overflow Kokoro.

    Ordinary prose is returned unchanged (as a single segment) so mlx-audio can
    chunk it at natural punctuation. Only pathologically long unbroken
    alphanumeric runs are split, since a single such token can exceed the
    510-phoneme window on its own.
    """
    prepared = _ALNUM_RUN_RE.sub(_break_alnum_run, text)
    _warn_on_long_token(prepared)
    return [prepared]


def _warn_on_long_token(segment: str) -> None:
    """Warn about a token that may still overflow Kokoro's phoneme window.

    mlx-audio silently truncates any single token over 510 phonemes, dropping the
    tail of the audio. We split long alphanumeric runs, but a token carrying other
    punctuation (e.g. a URL or dotted identifier) can slip through; surface it so
    the loss is never silent.
    """
    longest = max(segment.split(), key=len, default="")
    if len(longest) > _ALNUM_RUN_CHARS:
        logger.warning(
            "Token of %d chars (%r...) may exceed Kokoro's 510-phoneme window and "
            "could be truncated, dropping the tail of the audio.",
            len(longest),
            longest[:32],
        )


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
        segments = _prepare_segments(text)
        for index, segment_text in enumerate(segments):
            # The first segment creates the file; every later segment appends to it.
            self._synthesize_segment(segment_text, voice, out_path, append=index > 0)

    def _synthesize_segment(self, text: str, voice: str, out_path: Path, *, append: bool) -> None:
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
        _write_segments(out_path, segments, self.sample_rate, append=append)


def _write_segments(
    out_path: Path, segments: list[Any], sample_rate: int, *, append: bool = False
) -> None:
    import numpy as np

    arrays = [np.asarray(segment.audio) for segment in segments]
    # Convert the freshly generated float waveform to int16-scaled samples once.
    # Converting again on write would clip every non-zero sample to full scale
    # (a square wave, heard as harsh static), so downstream code must not scale.
    joined = _to_int16(np.concatenate(arrays))
    if append:
        if not out_path.exists():
            raise SynthesisError(
                f"Cannot append to '{out_path}': the file does not exist. "
                "The first segment must create it before later segments append."
            )
        with wave.open(str(out_path), "rb") as wf:
            existing = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        joined = np.concatenate([existing, joined])
    _write_int16_wav(out_path, joined, sample_rate)


def _to_int16(samples: Any) -> Any:
    import numpy as np

    arr = np.asarray(samples)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    if np.issubdtype(arr.dtype, np.integer):
        return arr.astype(np.int16)
    arr = np.clip(arr.astype(np.float32), -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16)


def _write_int16_wav(path: Path, samples: Any, sample_rate: int) -> None:
    """Write already-int16-scaled samples to a mono 16-bit WAV file."""
    import numpy as np

    arr = np.asarray(samples, dtype=np.int16)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(arr.tobytes())
