"""Orchestrator: extract-independent driver of split -> synthesize -> merge."""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tts_app.domain.models import (
    JobStatus,
    ResumeError,
    SourceDocument,
    SynthesisError,
    SynthesisJob,
    TtsError,
    build_job_id,
    hash_text,
)
from tts_app.domain.ports import AudioMerger, JobStore, TextSplitter, TTSEngine
from tts_app.pipeline.throttle import Throttle
from tts_app.utils import thermal


@dataclass
class RunResult:
    job_id: str
    output_path: Path
    chunks_completed: int
    chunks_total: int
    resumed: bool
    complete: bool


class Orchestrator:
    """Drives synthesis for a document. Depends only on ports, never on adapters."""

    def __init__(
        self,
        engine: TTSEngine,
        splitter: TextSplitter,
        merger: AudioMerger,
        store: JobStore,
        throttle: Throttle,
        *,
        voice: str,
        config_hash: str,
        state_dir: Path,
        retries: int = 2,
        retry_backoff: float = 2.0,
        on_progress: Callable[[str], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.engine = engine
        self.splitter = splitter
        self.merger = merger
        self.store = store
        self.throttle = throttle
        self.voice = voice
        self.config_hash = config_hash
        self.state_dir = state_dir
        self.retries = retries
        self.retry_backoff = retry_backoff
        self.on_progress = on_progress
        self.logger = logger
        self.current_job_id: str | None = None

    def run(self, document: SourceDocument, output_path: Path, source_format: str) -> RunResult:
        content_hash = hash_text(document.text)
        chunks = self.splitter.split(document.text, document.chapter_breaks or ())
        if not chunks:
            raise TtsError("No text to synthesize; the document is empty.")
        job_id = build_job_id(content_hash, self.voice, self.config_hash)
        job = self.store.load(job_id)
        if job is None:
            job = SynthesisJob(
                job_id=job_id,
                content_hash=content_hash,
                voice=self.voice,
                config_hash=self.config_hash,
                source_format=source_format,
                title=document.title,
                chunks=chunks,
                completed=[],
                status=JobStatus.PENDING,
                output_path=str(output_path.resolve()),
                temp_dir=str(self._temp_dir_for(job_id)),
                created_at=_now(),
                updated_at=_now(),
                warnings=list(document.warnings),
            )
            self.store.save(job)
        return self._execute(job, output_path)

    def resume(self, job_id: str) -> RunResult:
        job = self.store.load(job_id)
        if job is None:
            raise ResumeError(
                f"No job with id '{job_id}'. Run `tts list-jobs` to see available jobs."
            )
        output_path = Path(job.output_path) if job.output_path else self._default_output(job)
        return self._execute(job, output_path)

    def _execute(self, job: SynthesisJob, output_path: Path) -> RunResult:
        self.current_job_id = job.job_id
        temp_dir = Path(job.temp_dir) if job.temp_dir else self._temp_dir_for(job.job_id)
        temp_dir.mkdir(parents=True, exist_ok=True)

        if job.status == JobStatus.COMPLETE and output_path.exists():
            self._log(f"Job {job.job_id} already complete; nothing to do (idempotent).")
            return RunResult(job.job_id, output_path, job.total, job.total, True, True)

        completed = [i for i in job.completed if self._wav_path(temp_dir, i).exists()]
        was_resumed = bool(completed)
        pending = [i for i in range(len(job.chunks)) if i not in set(completed)]
        job.completed = sorted(completed)

        self._report_start(job, output_path, was_resumed)

        if not pending:
            self._log("All chunks present but output missing; re-merging.")
            self._merge_and_finish(job, temp_dir, completed, output_path)
            return RunResult(job.job_id, output_path, len(completed), job.total, True, True)

        job.status = JobStatus.RUNNING
        self.store.save(job)
        start = time.monotonic()

        for index in pending:
            chunk_text = job.chunks[index]
            wav_path = self._wav_path(temp_dir, index)
            self.throttle.wait(index)
            try:
                self._synthesize_with_retries(chunk_text, wav_path, job.voice)
            except KeyboardInterrupt:
                self.store.save(job)
                self._log(f"Interrupted; progress saved. Resume with `tts resume {job.job_id}`.")
                raise
            except SynthesisError:
                self.store.save(job)
                raise
            completed.append(index)
            job.completed = sorted(completed)
            job.updated_at = _now()
            self.store.save(job)
            self._report(index, len(job.chunks), len(chunk_text), start)

        self._merge_and_finish(job, temp_dir, completed, output_path)
        return RunResult(job.job_id, output_path, len(completed), job.total, was_resumed, True)

    def _synthesize_with_retries(self, text: str, wav_path: Path, voice: str) -> None:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self.engine.synthesize(text, voice, wav_path)
                return
            except Exception as exc:  # noqa: BLE001 - engine raises arbitrary errors
                last_error = exc
                self._log(f"Chunk synthesis failed (attempt {attempt + 1}): {exc}")
                if attempt < self.retries:
                    time.sleep(self.retry_backoff * (attempt + 1))
        raise SynthesisError(f"Synthesis failed after {self.retries + 1} attempts: {last_error}")

    def _merge_and_finish(
        self, job: SynthesisJob, temp_dir: Path, completed: list[int], output_path: Path
    ) -> None:
        wav_paths = [self._wav_path(temp_dir, i) for i in completed]
        self._log(f"Merging {len(wav_paths)} chunks into {output_path}.")
        self.merger.merge(wav_paths, output_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        job.completed = sorted(completed)
        job.status = JobStatus.COMPLETE
        job.temp_dir = None
        job.updated_at = _now()
        self.store.save(job)
        self._log(f"Done. Output: {output_path}")

    def _report(self, index: int, total: int, chars: int, start: float) -> None:
        elapsed = time.monotonic() - start
        done = index + 1
        eta = elapsed / done * (total - done) if done else 0.0
        thermal_str = (
            thermal.read_thermal_reading().label() if self.throttle.thermal_aware else "n/a"
        )
        message = (
            f"chunk {done}/{total} | chars={chars} | "
            f"elapsed={elapsed:.1f}s | eta={eta:.1f}s | thermal={thermal_str}"
        )
        self._emit(message)

    def _report_start(self, job: SynthesisJob, output_path: Path, resumed: bool) -> None:
        self._emit(
            f"Job {job.job_id} | {job.total} chunks | resumed={resumed} | output -> {output_path}"
        )

    def _emit(self, message: str) -> None:
        """Write to the file logger and stream to the console progress channel."""
        self._log(message)
        if self.on_progress is not None:
            self.on_progress(message)

    def _wav_path(self, temp_dir: Path, index: int) -> Path:
        return temp_dir / f"chunk_{index:06d}.wav"

    def _temp_dir_for(self, job_id: str) -> Path:
        return self.state_dir / "tmp" / job_id

    def _default_output(self, job: SynthesisJob) -> Path:
        stem = _safe_stem(job.title) or job.job_id
        return Path(f"{stem}.mp3")

    def _log(self, message: str) -> None:
        if self.logger is not None:
            self.logger.info(message)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_stem(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip()
    return cleaned or "tts_output"
