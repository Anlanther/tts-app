"""Tests for the FFmpeg merger using a fake ffmpeg binary."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from tts_app.adapters.ffmpeg_merger import FfmpegMerger
from tts_app.domain.models import MissingDependencyError


def _make_fake_ffmpeg(directory: Path) -> Path:
    script = directory / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" -version "*) exit 0 ;; esac\n'
        'echo "ARGS: $*" >> "$FAKE_FFMPEG_LOG"\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "-i" ]; then\n'
        '    echo "INPUT_BEGIN" >> "$FAKE_FFMPEG_LOG"\n'
        '    cat "$a" >> "$FAKE_FFMPEG_LOG" 2>/dev/null\n'
        '    echo "INPUT_END" >> "$FAKE_FFMPEG_LOG"\n'
        "  fi\n"
        '  prev="$a"\n'
        "done\n"
        "for last; do :; done\n"
        'if [ -n "$last" ]; then\n'
        '  mkdir -p "$(dirname "$last")"\n'
        "  printf 'fake' > \"$last\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def test_verify_raises_when_ffmpeg_missing() -> None:
    merger = FfmpegMerger(ffmpeg_bin="/nonexistent/ffmpeg")
    with pytest.raises(MissingDependencyError):
        merger.verify()


def test_merge_runs_concat_then_lame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _make_fake_ffmpeg(tmp_path)
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))

    wavs = [tmp_path / f"seg_{i}.wav" for i in range(3)]
    for wav in wavs:
        wav.write_bytes(b"\x00")

    out = tmp_path / "out.mp3"
    merger = FfmpegMerger(
        ffmpeg_bin=str(fake),
        bitrate="128k",
        normalize=True,
        sample_rate=24000,
        silence_ms=250,
    )
    merger.merge(wavs, out)

    assert out.exists()
    content = log.read_text(encoding="utf-8")
    assert "concat" in content
    assert "libmp3lame" in content
    assert "128k" in content
    assert "loudnorm" in content
    assert "seg_0.wav" in content
    assert "seg_1.wav" in content
    assert "seg_2.wav" in content
    assert "_silence.wav" in content


def test_merge_without_normalize_omits_loudnorm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _make_fake_ffmpeg(tmp_path)
    log = tmp_path / "ffmpeg.log"
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))

    wavs = [tmp_path / "seg_0.wav"]
    wavs[0].write_bytes(b"\x00")

    merger = FfmpegMerger(ffmpeg_bin=str(fake), normalize=False, silence_ms=0)
    merger.merge(wavs, tmp_path / "out.mp3")

    content = log.read_text(encoding="utf-8")
    assert "loudnorm" not in content
    assert "_silence.wav" not in content
