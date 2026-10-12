"""Integration tests for the orchestrator with fakes (pipeline + resume)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.helpers import FakeEngine, FakeMerger, write_dummy_wav
from tts_app.adapters.json_job_store import JsonJobStore
from tts_app.adapters.sentence_splitter import SentenceSplitter
from tts_app.domain.models import (
    JobStatus,
    SourceDocument,
    SynthesisError,
    SynthesisJob,
    build_job_id,
    hash_text,
)
from tts_app.pipeline.orchestrator import Orchestrator
from tts_app.pipeline.throttle import Throttle
from tts_app.utils import memory

VOICE = "bm_daniel"
CONFIG_HASH = "testcfg"
TEXT = "Alpha sentence here. Beta sentence here. Gamma sentence here. Delta sentence here."


def _splitter() -> SentenceSplitter:
    return SentenceSplitter(target_chars=20, max_chars=40, min_chars=5)


def _orchestrator(
    store: JsonJobStore,
    engine: FakeEngine,
    tmp_path: Path,
    retries: int = 0,
    on_progress: Callable[[str], None] | None = None,
    memory_aware: bool = False,
) -> Orchestrator:
    return Orchestrator(
        engine=engine,
        splitter=_splitter(),
        merger=FakeMerger(),
        store=store,
        throttle=Throttle(base_sleep=0.0, sleeper=lambda _s: None, memory_aware=memory_aware),
        voice=VOICE,
        config_hash=CONFIG_HASH,
        state_dir=tmp_path / "state",
        retries=retries,
        retry_backoff=0.0,
        on_progress=on_progress,
    )


def test_run_synthesizes_each_chunk_in_order(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    engine = FakeEngine()
    orchestrator = _orchestrator(store, engine, tmp_path)
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])
    out = tmp_path / "out.mp3"

    result = orchestrator.run(document, out, "txt")

    assert result.complete
    assert out.exists()
    expected = _splitter().split(TEXT)
    assert [text for text, _voice, _path in engine.calls] == expected


def test_resume_skips_completed_chunks(tmp_path: Path) -> None:
    chunks = _splitter().split(TEXT)
    content_hash = hash_text(TEXT)
    job_id = build_job_id(content_hash, VOICE, CONFIG_HASH)
    temp_dir = tmp_path / "state" / "tmp" / job_id
    temp_dir.mkdir(parents=True)
    write_dummy_wav(temp_dir / "chunk_000000.wav")

    store = JsonJobStore(tmp_path / "jobs")
    store.save(
        SynthesisJob(
            job_id=job_id,
            content_hash=content_hash,
            voice=VOICE,
            config_hash=CONFIG_HASH,
            source_format="txt",
            title="t",
            chunks=chunks,
            completed=[0],
            status=JobStatus.RUNNING,
            output_path=str(tmp_path / "out.mp3"),
            temp_dir=str(temp_dir),
            created_at="",
            updated_at="",
            warnings=[],
        )
    )

    engine = FakeEngine()
    orchestrator = _orchestrator(store, engine, tmp_path)
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])
    result = orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert result.resumed
    assert [text for text, _voice, _path in engine.calls] == chunks[1:]


def test_run_is_idempotent(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])
    out = tmp_path / "out.mp3"

    orchestrator = _orchestrator(store, FakeEngine(), tmp_path)
    orchestrator.run(document, out, "txt")

    second_engine = FakeEngine()
    second = _orchestrator(store, second_engine, tmp_path)
    result = second.run(document, out, "txt")

    assert result.complete
    assert second_engine.calls == []


def test_retries_recover_from_transient_failure(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    engine = FakeEngine(fail_times=1)
    orchestrator = _orchestrator(store, engine, tmp_path, retries=1)
    document = SourceDocument(title="t", text="One sentence. Two sentence.", page_count=1)
    result = orchestrator.run(document, tmp_path / "out.mp3", "txt")
    assert result.complete


def test_run_reports_job_id_in_start_header(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    messages: list[str] = []
    orchestrator = _orchestrator(store, FakeEngine(), tmp_path, on_progress=messages.append)
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])

    result = orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert messages[0].startswith(f"Job {result.job_id} ")
    assert orchestrator.current_job_id == result.job_id


def test_resume_reports_stored_job_id(tmp_path: Path) -> None:
    chunks = _splitter().split(TEXT)
    content_hash = hash_text(TEXT)
    job_id = build_job_id(content_hash, VOICE, CONFIG_HASH)
    temp_dir = tmp_path / "state" / "tmp" / job_id
    temp_dir.mkdir(parents=True)
    write_dummy_wav(temp_dir / "chunk_000000.wav")

    store = JsonJobStore(tmp_path / "jobs")
    store.save(
        SynthesisJob(
            job_id=job_id,
            content_hash=content_hash,
            voice=VOICE,
            config_hash=CONFIG_HASH,
            source_format="txt",
            title="t",
            chunks=chunks,
            completed=[0],
            status=JobStatus.RUNNING,
            output_path=str(tmp_path / "out.mp3"),
            temp_dir=str(temp_dir),
            created_at="",
            updated_at="",
            warnings=[],
        )
    )

    messages: list[str] = []
    orchestrator = _orchestrator(store, FakeEngine(), tmp_path, on_progress=messages.append)
    result = orchestrator.resume(job_id)

    assert messages[0].startswith(f"Job {job_id} ")
    assert "resumed=True" in messages[0]
    assert result.job_id == job_id


def test_report_includes_memory_when_aware(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        memory, "read_memory_reading", lambda: memory.MemoryReading(current_mib=321.0)
    )
    store = JsonJobStore(tmp_path / "jobs")
    messages: list[str] = []
    orchestrator = _orchestrator(
        store, FakeEngine(), tmp_path, memory_aware=True, on_progress=messages.append
    )
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])

    orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert any("mem=321MB" in message for message in messages)


def test_reports_peak_memory_at_end_when_aware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        memory,
        "read_memory_reading",
        lambda: memory.MemoryReading(current_mib=321.0, peak_mib=5120.0),
    )
    store = JsonJobStore(tmp_path / "jobs")
    messages: list[str] = []
    orchestrator = _orchestrator(
        store, FakeEngine(), tmp_path, memory_aware=True, on_progress=messages.append
    )
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])

    orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert any("Peak memory: 5.0GB" in message for message in messages)


def test_no_peak_memory_line_when_not_aware(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    messages: list[str] = []
    orchestrator = _orchestrator(store, FakeEngine(), tmp_path, on_progress=messages.append)
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])

    orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert not any("Peak memory" in message for message in messages)


def test_report_omits_memory_when_not_aware(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    messages: list[str] = []
    orchestrator = _orchestrator(store, FakeEngine(), tmp_path, on_progress=messages.append)
    document = SourceDocument(title="t", text=TEXT, page_count=1, warnings=[])

    orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert any("mem=n/a" in message for message in messages)


def test_exhausted_retries_raises_and_persists(tmp_path: Path) -> None:
    store = JsonJobStore(tmp_path / "jobs")
    engine = FakeEngine(fail_times=100)
    orchestrator = _orchestrator(store, engine, tmp_path, retries=1)
    document = SourceDocument(title="t", text="One sentence. Two sentence.", page_count=1)

    with pytest.raises(SynthesisError):
        orchestrator.run(document, tmp_path / "out.mp3", "txt")

    assert len(store.list_jobs()) == 1


def test_resume_uses_job_stored_voice(tmp_path: Path) -> None:
    chunks = _splitter().split(TEXT)
    content_hash = hash_text(TEXT)
    job_id = build_job_id(content_hash, "stored_voice", CONFIG_HASH)
    temp_dir = tmp_path / "state" / "tmp" / job_id
    temp_dir.mkdir(parents=True)
    write_dummy_wav(temp_dir / "chunk_000000.wav")

    store = JsonJobStore(tmp_path / "jobs")
    store.save(
        SynthesisJob(
            job_id=job_id,
            content_hash=content_hash,
            voice="stored_voice",
            config_hash=CONFIG_HASH,
            source_format="txt",
            title="t",
            chunks=chunks,
            completed=[0],
            status=JobStatus.RUNNING,
            output_path=str(tmp_path / "out.mp3"),
            temp_dir=str(temp_dir),
            created_at="",
            updated_at="",
            warnings=[],
        )
    )

    engine = FakeEngine()
    orchestrator = _orchestrator(store, engine, tmp_path)
    result = orchestrator.resume(job_id)

    assert result.complete
    assert all(voice == "stored_voice" for _text, voice, _path in engine.calls)
