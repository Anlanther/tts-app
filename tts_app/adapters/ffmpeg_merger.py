"""FFmpeg-backed audio merger: WAV concat -> single MP3."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from tts_app.domain.models import MergeError, MissingDependencyError


class FfmpegMerger:
    def __init__(
        self,
        *,
        ffmpeg_bin: str = "ffmpeg",
        bitrate: str = "192k",
        normalize: bool = True,
        sample_rate: int = 24000,
        silence_ms: int = 250,
    ) -> None:
        self.ffmpeg = ffmpeg_bin
        self.bitrate = bitrate
        self.normalize = normalize
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms

    def verify(self) -> None:
        """Fail fast if ffmpeg is missing or broken."""
        try:
            subprocess.run(
                [self.ffmpeg, "-version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise MissingDependencyError(
                f"'{self.ffmpeg}' not found on PATH. Install it with `brew install ffmpeg`."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise MissingDependencyError(f"'{self.ffmpeg}' failed to run: {exc}") from exc

    def merge(self, wav_paths: Sequence[Path], out_path: Path) -> None:
        self.verify()
        if not wav_paths:
            raise MergeError("No audio segments to merge.")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        silence = self._make_silence(out_path.parent) if self.silence_ms > 0 else None
        concat_file = out_path.parent / ".concat_list.txt"
        try:
            self._write_concat_list(wav_paths, silence, concat_file)
            command = [
                self.ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
            ]
            command += self._audio_filters()
            command += ["-c:a", "libmp3lame", "-b:a", self.bitrate, str(out_path)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                detail = _ffmpeg_error_detail(result.stderr)
                raise MergeError(f"ffmpeg concat failed (exit {result.returncode}): {detail}")
        finally:
            concat_file.unlink(missing_ok=True)
            if silence is not None:
                silence.unlink(missing_ok=True)

    def _audio_filters(self) -> list[str]:
        """Build the audio filter chain, if any.

        When normalising, an explicit integer-format conversion is inserted after
        ``loudnorm``. Without it, ffmpeg's ``libmp3lame`` encoder can abort with an
        assertion in ``psymodel.c`` (``el >= 0``) when the input contains silent
        frames -- as the inter-chunk silence does -- because it receives float
        samples and computes a negative energy for digital silence.
        """
        if not self.normalize:
            return []
        return ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_fmts=s16"]

    def _write_concat_list(
        self, wav_paths: Sequence[Path], silence: Path | None, concat_file: Path
    ) -> None:
        lines: list[str] = []
        for index, wav in enumerate(wav_paths):
            lines.append(f"file '{wav.resolve()}'")
            if silence is not None and index < len(wav_paths) - 1:
                lines.append(f"file '{silence.resolve()}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _make_silence(self, directory: Path) -> Path:
        path = directory / "_silence.wav"
        duration = self.silence_ms / 1000.0
        command = [
            self.ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={self.sample_rate}:cl=mono",
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            detail = _ffmpeg_error_detail(result.stderr, limit=300)
            raise MergeError(f"ffmpeg silence generation failed: {detail}")
        return path


def _ffmpeg_error_detail(stderr: str | None, *, limit: int = 1200) -> str:
    """Summarise ffmpeg stderr for an error message without dropping the cause.

    ffmpeg prints its banner and stream mapping before the actual failure, so a
    naive head-truncation keeps only the boilerplate. Prefer the lines that name
    the failure (assertions, errors), then fall back to the tail.
    """
    text = (stderr or "").strip()
    if not text:
        return "(no stderr)"
    lines = text.splitlines()
    markers = ("assertion", "abort", "error", "failed", "invalid", "nan", "inf")
    cause = [line for line in lines if any(m in line.lower() for m in markers)]
    detail = "\n".join(cause) if cause else "\n".join(lines[-3:])
    return detail[:limit]
