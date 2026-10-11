"""Protocols (ports) that adapters implement and the orchestrator depends on."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .models import SourceDocument, SynthesisJob


class TTSEngine(Protocol):
    def synthesize(self, text: str, voice: str, out_path: Path) -> None: ...


class TextExtractor(Protocol):
    def extract(self, path: Path, *, password: str | None = None) -> SourceDocument: ...


class TextSplitter(Protocol):
    def split(self, text: str, hard_breaks: Sequence[int] = ()) -> list[str]: ...


class AudioMerger(Protocol):
    def merge(self, wav_paths: Sequence[Path], out_path: Path) -> None: ...


class JobStore(Protocol):
    def save(self, job: SynthesisJob) -> None: ...

    def load(self, job_id: str) -> SynthesisJob | None: ...

    def list_jobs(self) -> list[SynthesisJob]: ...

    def delete(self, job_id: str) -> None: ...
