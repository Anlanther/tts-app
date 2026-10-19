"""Load a pronunciation lexicon from a plain-text file."""

from __future__ import annotations

from pathlib import Path

from tts_app.domain.models import TtsError
from tts_app.domain.pronunciation import Pronunciation, parse_entry


def load_lexicon(path: Path) -> list[Pronunciation]:
    """Read ``TERM[, TERM...] = SPOKEN`` entries, one per line.

    A bad entry is reported as ``path:line`` so a typo never passes silently.
    """
    path = path.expanduser()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise TtsError(f"Cannot read pronunciation lexicon '{path}': {exc}") from exc

    entries: list[Pronunciation] = []
    for number, line in enumerate(lines, start=1):
        try:
            entry = parse_entry(line)
        except TtsError as exc:
            raise TtsError(f"{path}:{number}: {exc}") from exc
        if entry is not None:
            entries.append(entry)
    return entries
