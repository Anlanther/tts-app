"""Tests for the FFmpeg merger using a fake ffmpeg binary."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from tts_app.adapters.ffmpeg_merger import FfmpegMerger, _ffmpeg_error_detail
from tts_app.domain.models import MergeError, MissingDependencyError


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


def test_normalize_forces_integer_format_before_lame() -> None:
    # Regression: without the aformat step, libmp3lame aborts on silent frames
    # (calc_energy assertion in psymodel.c) when loudnorm emits float samples.
    filters = FfmpegMerger(normalize=True)._audio_filters()
    assert filters[0] == "-af"
    assert "loudnorm" in filters[1]
    assert "aformat=sample_fmts=s16" in filters[1]


def test_no_filters_when_normalize_disabled() -> None:
    assert FfmpegMerger(normalize=False)._audio_filters() == []


def test_error_detail_prefers_cause_over_banner() -> None:
    banner = "\n".join(f"banner line {i}" for i in range(50))
    stderr = (
        f"{banner}\nAssertion failed: (el >= 0), function calc_energy, file psymodel.c, line 576.\n"
    )
    detail = _ffmpeg_error_detail(stderr)
    assert "calc_energy" in detail
    assert "banner line 0" not in detail


def test_error_detail_falls_back_to_tail_without_marker() -> None:
    stderr = "\n".join(f"line {i}" for i in range(10))
    detail = _ffmpeg_error_detail(stderr)
    assert detail.endswith("line 9")
    assert "line 0" not in detail


def test_merge_error_surfaces_abort_line(tmp_path: Path) -> None:
    script = tmp_path / "ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" -version "*) exit 0 ;; esac\n'
        'echo "banner noise" >&2\n'
        'echo "Assertion failed: (el >= 0), function calc_energy" >&2\n'
        "exit 254\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    wav = tmp_path / "seg_0.wav"
    wav.write_bytes(b"\x00")
    merger = FfmpegMerger(ffmpeg_bin=str(script), silence_ms=0)

    with pytest.raises(MergeError) as excinfo:
        merger.merge([wav], tmp_path / "out.mp3")
    assert "calc_energy" in str(excinfo.value)
