"""Tests for the Kokoro engine's token preparation and audio writing."""

from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tts_app.adapters.kokoro_engine import (
    _ALNUM_RUN_CHARS,
    KokoroEngine,
    _prepare_segments,
    _write_segments,
)
from tts_app.domain.models import SynthesisError


def test_ordinary_prose_is_a_single_segment() -> None:
    # Prose is handed to mlx-audio whole so it can chunk at natural punctuation;
    # character-budget pre-splitting used to sever sentences mid-clause and made
    # adjacent words run together.
    text = "A short sentence. And another one. Then a much longer clause, with a comma."
    assert _prepare_segments(text) == [text]


def test_long_prose_is_not_split_here() -> None:
    text = ("This is a reasonably long sentence used to exercise the splitter. " * 10).strip()
    assert _prepare_segments(text) == [text]


def test_long_digit_run_is_broken_up() -> None:
    # A single 58-digit token phonemizes to ~851 phonemes, past Kokoro's 510
    # window, so mlx-audio would truncate and drop the tail. Break it into groups.
    run = "1050218739445882319041277310665521199820034588776612345678"
    (prepared,) = _prepare_segments(run)

    assert prepared != run
    assert all(len(token) <= _ALNUM_RUN_CHARS for token in prepared.split())
    # Rejoining (ignoring the inserted spaces) preserves every digit.
    assert prepared.replace(" ", "") == run


def test_short_number_in_prose_is_untouched() -> None:
    text = "The year was 2024 and the code is 411111."
    assert _prepare_segments(text) == [text]


def test_long_digit_run_inside_a_sentence_is_broken() -> None:
    (prepared,) = _prepare_segments("Account 1050218739445882319041277310665521 closed.")
    assert "Account" in prepared and "closed." in prepared
    assert all(len(token) <= _ALNUM_RUN_CHARS for token in prepared.split())


def test_overlong_token_is_warned_about(caplog: pytest.LogCaptureFixture) -> None:
    # A long token we cannot safely break (e.g. a dotted identifier) must surface
    # a warning rather than being silently truncated by mlx-audio.
    token = ".".join(["abcdefghij"] * 6)
    with caplog.at_level(logging.WARNING, logger="tts_app.kokoro"):
        _prepare_segments(f"See {token} now.")
    assert any("truncated" in record.message for record in caplog.records)


class _StubModel:
    """Model stand-in whose ``generate`` yields one segment per call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, *, text: str, **_kwargs: Any) -> list[Any]:
        self.calls.append(text)
        # A low-amplitude ramp, so a double-scaling bug (which squashes samples
        # to full scale) is observable in the written PCM rather than masked.
        return [_Segment(np.linspace(-0.8, 0.8, len(text), dtype=np.float32))]


class _Segment:
    def __init__(self, audio: Any) -> None:
        self.audio = audio


def _engine_with(model: _StubModel) -> KokoroEngine:
    engine = KokoroEngine()
    engine._model = model
    engine._loaded = True
    return engine


def test_chunk_with_broken_run_writes_audio(tmp_path: Path) -> None:
    # A chunk whose long alphanumeric run is broken into groups still synthesises
    # to a single WAV. A past bug appended to a non-existent file for *every*
    # piece, silently writing nothing so the job looked complete while its temp
    # dir stayed empty.
    text = "1050218739445882319041277310665521 8877665544332211"
    assert len(_prepare_segments(text)) == 1  # broken internally, still one segment

    model = _StubModel()
    out_path = tmp_path / "chunk_000000.wav"
    _engine_with(model).synthesize(text, "bm_daniel", out_path)

    assert out_path.exists()
    expected_frames = sum(len(segment) for segment in model.calls)
    with wave.open(str(out_path), "rb") as wf:
        assert wf.getnframes() == expected_frames


def test_appended_audio_is_not_clipped(tmp_path: Path) -> None:
    # Regression: the append path used to convert the freshly generated float
    # audio and the already-int16 existing samples through the float->int16
    # scaling a second time. The clip to [-1, 1] then pinned every appended
    # sample to +/-32767 -- a square wave heard as harsh static.
    first = np.array([0.0, 0.3, -0.7, 0.95, -0.2, 0.05], dtype=np.float32)
    second = np.array([0.11, -0.42, 0.88, -0.05], dtype=np.float32)
    out_path = tmp_path / "chunk_000000.wav"

    _write_segments(out_path, [_Segment(first)], 24000, append=False)
    _write_segments(out_path, [_Segment(second)], 24000, append=True)

    with wave.open(str(out_path), "rb") as wf:
        written = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)

    appended = written[len(first) :]
    assert np.array_equal(appended, (second * 32767.0).astype(np.int16))
    # No sample in the appended region was squashed to full scale.
    assert not np.isin(appended, (32767, -32767)).any()


def test_appending_without_existing_file_raises(tmp_path: Path) -> None:
    # The append path must fail loudly rather than silently no-op, so a missing
    # base file surfaces instead of producing a "complete" job with no audio.
    from tts_app.adapters.kokoro_engine import _write_segments

    with pytest.raises(SynthesisError):
        _write_segments(tmp_path / "missing.wav", [_Segment(np.zeros(4))], 24000, append=True)
