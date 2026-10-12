# tts-app

A local, offline text-to-speech desktop/CLI tool for macOS (Apple Silicon) that
converts long-form `.txt`, `.md`, and `.pdf` files into a single MP3 audiobook.
It is designed as a self-hosted replacement for paid services like Natural
Reader, with thermal safety for fanless MacBooks.

- **Fully offline** — no cloud APIs.
- **Apple Silicon acceleration** — Kokoro-82M via MLX (`mlx-audio`).
- **Chunked, serial synthesis** with configurable cooldowns to avoid thermal
  throttling.
- **Resumable** — crash or thermal shutdown mid-run, then pick up where you
  left off.
- **PDF-first** — layout-aware extraction, header/footer/page-number stripping,
  TOC-based chapter breaks.

## Requirements

- macOS (Apple Silicon recommended).
- Python 3.11+ managed by [`uv`](https://docs.astral.sh/uv/).
- `ffmpeg` and `ffprobe` on `PATH` (`brew install ffmpeg`). Verified at startup.

## Install

```sh
uv sync
```

This creates the virtualenv, installs dependencies, and (on first run)
downloads the Kokoro model from Hugging Face when you first synthesize.

## First run

```sh
# Inspect a PDF before committing to a long conversion (strongly recommended).
uv run tts inspect book.pdf

# Convert a PDF to MP3.
uv run tts convert book.pdf -o book.mp3

# From a Markdown or plain-text file.
uv run tts convert notes.md
uv run tts convert novel.txt --voice af_heart --sleep 2.5

# From stdin.
cat story.txt | uv run tts convert - -o story.mp3
```

The default voice is `bm_daniel` (British English, male) with `lang_code` `b`.
Voices follow the `<lang><gender>_<name>` convention, e.g. `af_heart` (American
female), `bf_emma` (British female), `bm_george` (British male). The first letter
selects the language: `a`=American English, `b`=British English, `e`=Spanish,
`f`=French, `h`=Hindi, `i`=Italian, `j`=Japanese, `p`=Brazilian Portuguese,
`z`=Mandarin. Set the matching language with `--lang-code` (e.g. `--voice bf_emma
--lang-code b`). Two voices can be blended with a comma:
`--voice bm_daniel,bm_george`.

List the voicepacks available in your model cache with:

```sh
ls ~/.cache/huggingface/hub/models--mlx-community--Kokoro-82M-bf16/snapshots/*/voices/
```

### Configuration

Precedence: **CLI flags > env vars (`TTS_*`) > `~/.config/tts_app/config.toml` >
defaults**.

Example `~/.config/tts_app/config.toml`:

```toml
voice = "bf_emma"
lang_code = "b"
sleep_between_chunks = 3.0
mp3_bitrate = "160k"
normalize = true
```

Any setting can be overridden per-invocation, e.g. `TTS_VOICE=am_michael
uv run tts convert book.pdf`.

## CLI reference

```text
tts convert INPUT [-o OUT.mp3] [--voice NAME] [--lang-code CODE] [--chunk-chars 1200]
                  [--sleep 2.0] [--retries 2] [--resume] [--no-normalize]
                  [--pdf-password PW] [--format {txt,md,pdf}]
                  [--thermal-aware] [--max-runtime 2h]
                  [--memory-aware] [--max-memory-mb 2048]
tts resume JOB_ID
tts list-jobs
tts clean [--older-than 7d]
tts inspect INPUT          # dry-run: extractor, char count, chunk count, warnings
```

## PDF caveats

- **Scanned PDFs are not OCR'd.** If a page yields no extractable text, `tts`
  prints a warning listing the affected page numbers and suggests running
  `ocrmypdf` first. OCR is intentionally out of scope for this pass.
- **Encrypted PDFs** prompt for `--pdf-password`.
- **Layout quality varies.** Two-column academic papers, footnotes, and math
  can produce messy text. Always run `tts inspect` first to eyeball the
  extracted text and chunk count.
- Headers, footers, and standalone page numbers are detected (by repetition and
  vertical position) and stripped.

## Resume behavior

Each job is keyed by a stable id derived from `(content-hash, voice,
config-hash)`. Running the same command twice is idempotent: already-synthesized
chunks are never re-synthesized.

If a run is interrupted (Ctrl-C, crash, thermal shutdown), state is persisted
to `~/.local/state/tts_app/jobs/<job_id>.json` with per-chunk WAVs in a
job-specific temp dir. Resume with:

```sh
uv run tts resume <job_id>   # find the id with `uv run tts list-jobs`
```

Temp files are cleaned up automatically on success.

## Thermal tuning

- `--sleep` (default `2.0s`) inserts a cooldown between chunks.
- `--thermal-aware` lengthens the pause when the machine is thermally loaded.
  It reads `pmset -g therm` (the CPU speed limit) where available, and otherwise
  falls back to the thermal pressure level reported by `powermetrics` — which is
  what Apple Silicon Macs expose, since their `powermetrics` has no SMC sampler.
  The per-chunk progress line reports whichever signal is available under
  `thermal=` (a temperature such as `61.2C`, or a pressure level such as
  `Moderate`).
- `--max-runtime 2h` caps the total runtime; when hit, progress is persisted and
  the run exits cleanly.

**Measured behaviour (fanless M1 Air):** a 30-minute batch run at the default
settings stays below the thermal-throttling threshold on a cool, well-ventilated
surface. On a warm lap or in a hot room, raise `--sleep` to `3.0s` or enable
`--thermal-aware`. (Your mileage will vary by ambient temperature; treat these
as starting points, not guarantees.)

## Memory monitoring

- `--memory-aware` reports the process's resident memory in the per-chunk
  progress line under `mem=` (e.g. `mem=412MB`). On macOS this is the current
  RSS read straight from the kernel (`mach_task_basic_info`); elsewhere it
  falls back to peak RSS via `resource.getrusage`.
- `--max-memory-mb 2048` caps resident memory; when the process reaches the
  limit before a chunk, progress is persisted and the run exits cleanly,
  mirroring `--max-runtime`.

These read the running process directly, so they need no extra dependency or
privilege. Note that MLX/Metal buffers live in unified memory on Apple Silicon,
so the figure is indicative rather than exact.

## Development

```sh
make install      # uv sync
make test         # uv run pytest
make lint         # uv run ruff check tts_app tests
make typecheck    # uv run mypy --strict tts_app
```

## Architecture

```
tts_app/
  cli.py                     # typer entrypoint + dependency injection
  config.py                  # pydantic-settings (CLI > env > toml > defaults)
  domain/
    models.py                # dataclasses + errors
    ports.py                 # Protocols: TTSEngine, TextExtractor, TextSplitter, ...
  adapters/
    kokoro_engine.py         # mlx-audio Kokoro wrapper
    sentence_splitter.py     # TextSplitter impl
    ffmpeg_merger.py         # AudioMerger impl (concat -> mp3)
    json_job_store.py        # JobStore impl (resume)
    extractors/              # txt / md / pdf, dispatched by extension
  pipeline/
    orchestrator.py          # drives split -> synth -> merge (ports only)
    chunker.py               # sentence-aware chunking
    throttle.py              # cooldown + thermal pacing
  utils/
    logging.py
    thermal.py
    memory.py
```

The orchestrator depends only on the domain `Protocol`s; concrete adapters are
constructed in `cli.py` and injected at the boundary, so new engines (Piper,
Coqui, macOS `say`) or extractors can be added without touching the pipeline.
