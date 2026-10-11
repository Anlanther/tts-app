"""Typer CLI entrypoint with dependency injection at the boundary."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from tts_app import __version__
from tts_app.adapters.extractors import extractor_for
from tts_app.adapters.ffmpeg_merger import FfmpegMerger
from tts_app.adapters.json_job_store import JsonJobStore
from tts_app.adapters.kokoro_engine import KokoroEngine
from tts_app.adapters.sentence_splitter import SentenceSplitter
from tts_app.config import Settings, load_settings, parse_duration
from tts_app.domain.models import SourceDocument, TtsError
from tts_app.pipeline.orchestrator import Orchestrator, RunResult
from tts_app.pipeline.throttle import Throttle
from tts_app.utils import logging as logging_utils

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"tts {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """Convert text/PDF files into MP3 audiobooks, fully offline."""


@app.command()
def convert(
    input: str = typer.Argument(..., help="Input file (.txt/.md/.pdf) or '-' for stdin."),
    output: Path | None = typer.Option(None, "-o", "--output", help="Output MP3 path."),
    voice: str | None = typer.Option(None, "--voice", help="Voice name to use (e.g. bm_daniel)."),
    lang_code: str | None = typer.Option(
        None, "--lang-code", help="Kokoro language code (a=US English, b=British, ...)."
    ),
    chunk_chars: int | None = typer.Option(None, "--chunk-chars", help="Target chunk size."),
    sleep: float | None = typer.Option(None, "--sleep", help="Cooldown seconds between chunks."),
    retries: int | None = typer.Option(None, "--retries", help="Retries per chunk."),
    resume: bool = typer.Option(False, "--resume", help="Resume (automatic; kept for parity)."),
    normalize: bool | None = typer.Option(
        None, "--normalize/--no-normalize", help="Apply loudness normalization."
    ),
    pdf_password: str | None = typer.Option(None, "--pdf-password", help="Encrypted PDF password."),
    fmt: str | None = typer.Option(None, "--format", help="Force format: txt, md, or pdf."),
    thermal_aware: bool | None = typer.Option(
        None, "--thermal-aware/--no-thermal-aware", help="Thermal-throttling-aware pacing."
    ),
    max_runtime: str | None = typer.Option(None, "--max-runtime", help="Max runtime, e.g. 2h."),
) -> None:
    """Convert an input file (or stdin) into a single MP3 audiobook."""
    del resume
    settings = _settings_from_flags(
        voice=voice,
        lang_code=lang_code,
        chunk_chars=chunk_chars,
        sleep=sleep,
        retries=retries,
        normalize=normalize,
        thermal_aware=thermal_aware,
        max_runtime=max_runtime,
    )
    try:
        document = _load_document(input, fmt, pdf_password)
        output_path = output if output is not None else _default_output(input, document)
        _ensure_writable(output_path)
        orchestrator = _build_orchestrator(settings)
        result = orchestrator.run(document, output_path, _detect_format(input, fmt))
        _print_result(result)
    except KeyboardInterrupt:
        typer.echo("Interrupted; progress saved. Resume with `tts resume <job_id>`.")
        raise typer.Exit(130) from None
    except TtsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def resume(job_id: str = typer.Argument(..., help="Job id to resume.")) -> None:
    """Resume an interrupted or incomplete job."""
    settings = load_settings()
    try:
        orchestrator = _build_orchestrator(settings)
        result = orchestrator.resume(job_id)
        _print_result(result)
    except KeyboardInterrupt:
        typer.echo("Interrupted; progress saved. Resume again with `tts resume <job_id>`.")
        raise typer.Exit(130) from None
    except TtsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command("list-jobs")
def list_jobs() -> None:
    """List known synthesis jobs."""
    settings = load_settings()
    store = JsonJobStore(settings.state_dir / "jobs")
    jobs = store.list_jobs()
    if not jobs:
        typer.echo("No jobs found.")
        return
    for job in jobs:
        typer.echo(
            f"{job.job_id}  {job.status.value:8}  {len(job.completed)}/{job.total}  "
            f"{job.title}  {job.updated_at}"
        )


@app.command()
def clean(
    older_than: str = typer.Option("7d", "--older-than", help="Age threshold, e.g. 7d."),
) -> None:
    """Remove jobs older than the given threshold."""
    settings = load_settings()
    try:
        cutoff = datetime.now().astimezone() - parse_duration(older_than)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from None
    store = JsonJobStore(settings.state_dir / "jobs")
    removed = 0
    for job in store.list_jobs():
        updated = _parse_timestamp(job.updated_at)
        if updated is None or updated < cutoff:
            store.delete(job.job_id)
            removed += 1
    typer.echo(f"Removed {removed} job(s).")


@app.command()
def inspect(
    input: str = typer.Argument(..., help="Input file to inspect (dry-run)."),
    fmt: str | None = typer.Option(None, "--format", help="Force format."),
    pdf_password: str | None = typer.Option(None, "--pdf-password", help="Encrypted PDF password."),
    chunk_chars: int | None = typer.Option(None, "--chunk-chars", help="Target chunk size."),
) -> None:
    """Dry-run: show extractor, char count, chunk count, and warnings."""
    settings = load_settings()
    target = settings.chunk_target_chars if chunk_chars is None else chunk_chars
    try:
        document = _load_document(input, fmt, pdf_password)
    except TtsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    splitter = SentenceSplitter(
        target_chars=target,
        max_chars=max(target + 500, settings.chunk_max_chars),
        min_chars=settings.chunk_min_chars,
    )
    chunks = splitter.split(document.text, document.chapter_breaks or ())
    typer.echo(f"Title:      {document.title}")
    typer.echo(f"Format:     {_detect_format(input, fmt)}")
    typer.echo(f"Pages:      {document.page_count}")
    typer.echo(f"Characters: {len(document.text)}")
    typer.echo(f"Chunks:     {len(chunks)}")
    if document.chapter_breaks:
        typer.echo(f"Chapters:   {len(document.chapter_breaks)}")
    for warning in document.warnings:
        typer.echo(f"Warning:    {warning}")


def _settings_from_flags(
    *,
    voice: str | None,
    lang_code: str | None,
    chunk_chars: int | None,
    sleep: float | None,
    retries: int | None,
    normalize: bool | None,
    thermal_aware: bool | None,
    max_runtime: str | None,
) -> Settings:
    overrides: dict[str, Any] = {}
    if voice is not None:
        overrides["voice"] = voice
    if lang_code is not None:
        overrides["lang_code"] = lang_code
    if chunk_chars is not None:
        overrides["chunk_target_chars"] = chunk_chars
    if sleep is not None:
        overrides["sleep_between_chunks"] = sleep
    if retries is not None:
        overrides["retries"] = retries
    if normalize is not None:
        overrides["normalize"] = normalize
    if thermal_aware is not None:
        overrides["thermal_aware"] = thermal_aware
    if max_runtime is not None:
        try:
            overrides["max_runtime"] = parse_duration(max_runtime)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(2) from None
    return load_settings(cli_overrides=overrides)


def _build_orchestrator(settings: Settings) -> Orchestrator:
    merger = FfmpegMerger(
        bitrate=settings.mp3_bitrate,
        normalize=settings.normalize,
        sample_rate=settings.sample_rate,
        silence_ms=settings.inter_chunk_silence_ms,
    )
    merger.verify()

    engine = KokoroEngine(
        model_path=settings.model_path,
        sample_rate=settings.sample_rate,
        lang_code=settings.lang_code,
        speed=settings.speed,
    )
    splitter = SentenceSplitter(
        target_chars=settings.chunk_target_chars,
        max_chars=settings.chunk_max_chars,
        min_chars=settings.chunk_min_chars,
    )
    store = JsonJobStore(settings.state_dir / "jobs")
    throttle = Throttle(
        base_sleep=settings.sleep_between_chunks,
        thermal_aware=settings.thermal_aware,
        thermal_threshold=settings.thermal_threshold,
        max_runtime=settings.max_runtime,
    )
    logger = logging_utils.get_logger("orchestrator")
    return Orchestrator(
        engine=engine,
        splitter=splitter,
        merger=merger,
        store=store,
        throttle=throttle,
        voice=settings.voice,
        config_hash=settings.config_hash(),
        state_dir=settings.state_dir,
        retries=settings.retries,
        retry_backoff=settings.retry_backoff,
        on_progress=lambda message: typer.echo(message),
        logger=logger,
    )


def _load_document(input: str, fmt: str | None, pdf_password: str | None) -> SourceDocument:
    if input == "-":
        return SourceDocument(title="stdin", text=sys.stdin.read(), page_count=1, warnings=[])
    path = Path(input)
    extractor = extractor_for(_detect_format(input, fmt))
    return extractor.extract(path, password=pdf_password)


def _detect_format(input: str, fmt: str | None) -> str:
    if fmt:
        return fmt.lower()
    if input == "-":
        return "txt"
    return Path(input).suffix.lstrip(".").lower()


def _default_output(input: str, document: SourceDocument) -> Path:
    stem = (
        _safe_filename(document.title)
        if document.title
        else (Path(input).stem if input != "-" else "tts_output")
    )
    return Path(f"{stem}.mp3")


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip()
    return cleaned or "tts_output"


def _ensure_writable(output_path: Path) -> None:
    parent = output_path.parent
    if not parent.is_dir():
        raise TtsError(f"Output directory does not exist: {parent}")
    if not os.access(parent, os.W_OK):
        raise TtsError(f"Output directory is not writable: {parent}")


def _print_result(result: RunResult) -> None:
    typer.echo(
        f"Done. {result.chunks_completed}/{result.chunks_total} chunks -> {result.output_path}"
    )


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def main() -> None:
    app()


if __name__ == "__main__":
    main()
