"""Shared test helpers: fake engine, fake merger, and a dummy WAV writer."""

from __future__ import annotations

import wave
from pathlib import Path

from tts_app.domain.ports import AudioMerger, TTSEngine


def write_dummy_wav(path: Path, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * 100)


class FakeEngine:
    """Records calls and writes a dummy WAV; can fail the first N calls."""

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls: list[tuple[str, str, Path]] = []
        self._counter = 0

    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        self.calls.append((text, voice, out_path))
        if self._counter < self.fail_times:
            self._counter += 1
            raise RuntimeError("synthetic engine failure")
        self._counter += 1
        write_dummy_wav(out_path)


class FakeMerger:
    def __init__(self) -> None:
        self.merges: list[tuple[list[Path], Path]] = []

    def merge(self, wav_paths: list[Path], out_path: Path) -> None:
        self.merges.append((list(wav_paths), out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("fake-mp3", encoding="utf-8")


class FailingEngine(TTSEngine):
    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        raise RuntimeError("boom")


class RecordingMerger(AudioMerger):
    def __init__(self) -> None:
        self.wav_paths: list[Path] = []
        self.out_path: Path | None = None

    def merge(self, wav_paths: list[Path], out_path: Path) -> None:
        self.wav_paths = list(wav_paths)
        self.out_path = out_path
