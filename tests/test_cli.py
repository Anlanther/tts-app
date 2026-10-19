"""CLI tests that avoid loading the real model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tts_app import cli, config

runner = CliRunner()


class _StubEngine:
    """Records the text it is asked to speak and writes a placeholder WAV."""

    instances: list[_StubEngine] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.spoken: list[str] = []
        _StubEngine.instances.append(self)

    def synthesize(self, text: str, voice: str, out_path: Path) -> None:
        self.spoken.append(text)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"RIFF")


@pytest.fixture
def stub_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> type[_StubEngine]:
    _StubEngine.instances = []
    monkeypatch.setattr(cli, "KokoroEngine", _StubEngine)
    monkeypatch.setattr(config, "_CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setenv("TTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("TTS_LEXICON_PATH", raising=False)
    return _StubEngine


def _speak(result: Any) -> list[str]:
    return _StubEngine.instances[-1].spoken


def _combined_output(result: Any) -> str:
    """stdout plus stderr, whichever way Click exposes them."""
    text = result.output
    try:
        text += result.stderr or ""
    except (AttributeError, ValueError):
        pass
    return text


def test_say_applies_a_lexicon(stub_engine: type[_StubEngine], tmp_path: Path) -> None:
    lexicon = tmp_path / "lexicon.txt"
    lexicon.write_text("Kubernetes = koober nett ease\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["say", "Kubernetes", "--lexicon", str(lexicon), "--no-play"])

    assert result.exit_code == 0, _combined_output(result)
    assert _speak(result) == ["koober nett ease"]
    assert "Spoken: koober nett ease" in result.output


def test_say_no_lexicon_hears_the_raw_text(stub_engine: type[_StubEngine], tmp_path: Path) -> None:
    lexicon = tmp_path / "lexicon.txt"
    lexicon.write_text("Cat = dog\n", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["say", "Cat", "--lexicon", str(lexicon), "--no-lexicon", "--no-play"],
    )

    assert result.exit_code == 0, _combined_output(result)
    assert _speak(result) == ["Cat"]


def test_say_uses_the_configured_lexicon(
    stub_engine: type[_StubEngine], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lexicon = tmp_path / "lexicon.txt"
    lexicon.write_text("nginx = engine ex\n", encoding="utf-8")
    monkeypatch.setenv("TTS_LEXICON_PATH", str(lexicon))

    result = runner.invoke(cli.app, ["say", "nginx", "--no-play"])

    assert result.exit_code == 0, _combined_output(result)
    assert _speak(result) == ["engine ex"]


def test_say_writes_the_requested_output(stub_engine: type[_StubEngine], tmp_path: Path) -> None:
    out = tmp_path / "preview.wav"

    result = runner.invoke(cli.app, ["say", "Hello", "-o", str(out), "--no-play"])

    assert result.exit_code == 0, _combined_output(result)
    assert out.exists()
    assert str(out) in result.output


def test_say_rejects_zero_repeat(stub_engine: type[_StubEngine]) -> None:
    result = runner.invoke(cli.app, ["say", "Hello", "--repeat", "0", "--no-play"])

    assert result.exit_code == 2
    assert "--repeat must be at least 1" in _combined_output(result)


def test_say_reports_a_bad_lexicon_line(stub_engine: type[_StubEngine], tmp_path: Path) -> None:
    lexicon = tmp_path / "lexicon.txt"
    lexicon.write_text("Kubernetes = koober\nbroken\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["say", "Kubernetes", "--lexicon", str(lexicon), "--no-play"])

    assert result.exit_code == 1
    assert ":2:" in _combined_output(result)
    assert not _StubEngine.instances  # never reached the engine


def test_inspect_accounts_for_the_lexicon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.delenv("TTS_LEXICON_PATH", raising=False)
    source = tmp_path / "doc.txt"
    source.write_text("Kubernetes is hard.", encoding="utf-8")
    lexicon = tmp_path / "lexicon.txt"
    lexicon.write_text("Kubernetes = koober nett ease\n", encoding="utf-8")

    result = runner.invoke(cli.app, ["inspect", str(source), "--lexicon", str(lexicon)])

    rewritten = "koober nett ease is hard."
    assert result.exit_code == 0, _combined_output(result)
    assert f"Characters: {len(rewritten)}" in result.output
    assert "Lexicon:    1 override(s) applied" in result.output


def test_resume_does_not_require_the_lexicon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A half-finished job must still resume if the lexicon file was moved.
    monkeypatch.setattr(config, "_CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setenv("TTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TTS_LEXICON_PATH", str(tmp_path / "missing.txt"))

    result = runner.invoke(cli.app, ["resume", "nope"])

    assert result.exit_code == 1
    assert "No job with id" in _combined_output(result)


def test_help_lists_the_lexicon_options() -> None:
    for command in ("convert", "inspect", "say"):
        result = runner.invoke(cli.app, [command, "--help"])
        assert result.exit_code == 0, _combined_output(result)
        assert "--lexicon" in result.output
