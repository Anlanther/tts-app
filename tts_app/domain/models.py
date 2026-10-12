"""Core domain models, application exceptions, and hashing helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class JobStatus(StrEnum):
    """Lifecycle of a synthesis job."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    FAILED = "failed"


class TtsError(Exception):
    """Base class for all application errors."""


class MissingDependencyError(TtsError):
    """A required external dependency (binary or library) is missing."""


class UnknownFormatError(TtsError):
    """The input file extension is not recognized."""


class ExtractionError(TtsError):
    """Text extraction failed."""


class SynthesisError(TtsError):
    """Audio synthesis failed for a chunk."""


class MergeError(TtsError):
    """Audio merging failed."""


class MaxRuntimeExceeded(TtsError):
    """The configured maximum runtime was reached."""


class MaxMemoryExceeded(TtsError):
    """The configured memory ceiling was reached."""


class ResumeError(TtsError):
    """Job state could not be loaded or resumed."""


@dataclass
class SourceDocument:
    """Text extracted from an input file, plus optional chapter boundaries."""

    title: str
    text: str
    page_count: int
    warnings: list[str] = field(default_factory=list)
    chapter_breaks: list[int] | None = None


@dataclass
class Chunk:
    """A single unit of text handed to the synthesis engine."""

    index: int
    text: str


@dataclass
class AudioSegment:
    """A synthesized WAV file for one chunk."""

    chunk_index: int
    wav_path: Path


@dataclass
class SynthesisJob:
    """Persisted state for a (content-hash, voice, config-hash) synthesis run."""

    job_id: str
    content_hash: str
    voice: str
    config_hash: str
    source_format: str
    title: str
    chunks: list[str]
    completed: list[int]
    status: JobStatus
    output_path: str | None
    temp_dir: str | None
    created_at: str
    updated_at: str
    warnings: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.chunks)

    @property
    def completed_set(self) -> set[int]:
        return set(self.completed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "content_hash": self.content_hash,
            "voice": self.voice,
            "config_hash": self.config_hash,
            "source_format": self.source_format,
            "title": self.title,
            "chunks": self.chunks,
            "completed": sorted(self.completed),
            "status": self.status.value,
            "output_path": self.output_path,
            "temp_dir": self.temp_dir,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisJob:
        try:
            status = JobStatus(str(data.get("status", "pending")))
        except ValueError:
            status = JobStatus.FAILED
        return cls(
            job_id=_as_str(data.get("job_id")),
            content_hash=_as_str(data.get("content_hash")),
            voice=_as_str(data.get("voice")),
            config_hash=_as_str(data.get("config_hash")),
            source_format=_as_str(data.get("source_format")),
            title=_as_str(data.get("title")),
            chunks=_as_str_list(data.get("chunks")),
            completed=_as_int_list(data.get("completed")),
            status=status,
            output_path=_as_optional_str(data.get("output_path")),
            temp_dir=_as_optional_str(data.get("temp_dir")),
            created_at=_as_str(data.get("created_at")),
            updated_at=_as_str(data.get("updated_at")),
            warnings=_as_str_list(data.get("warnings")),
        )


def hash_text(text: str) -> str:
    """SHA-256 of the extracted text (the content that determines audio)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_job_id(content_hash: str, voice: str, config_hash: str) -> str:
    """Stable job id for a (content-hash, voice, config-hash) tuple."""
    seed = f"{content_hash}:{voice}:{config_hash}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _as_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _as_optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
