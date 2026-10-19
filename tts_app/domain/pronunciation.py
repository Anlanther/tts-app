"""Dictionary-based pronunciation overrides applied before synthesis.

Kokoro phonemizes text with a G2P model that mlx-audio exposes no lexicon hook
for, so the reliable way to correct a word is to rewrite it to a respelling the
voice reads correctly (``"Kubernetes = koober nett ease"``).

This module is pure text processing. Reading a lexicon file lives in
``tts_app.adapters.lexicon_file`` so the pipeline depends only on this data
type, never on the filesystem.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from tts_app.domain.models import TtsError

# A term is bounded by whitespace or punctuation, but not by '.', "'" or '-',
# so "Dr." and "Wi-Fi" stay intact while "cat" does not match "concatenate".
_TERM_PATTERN = r"(?<![\w.'\-]){}(?![\w'\-])"


@dataclass(frozen=True)
class Pronunciation:
    """One lexicon entry: trigger spellings and what the voice should say."""

    spoken: str
    written: tuple[str, ...]


def parse_entry(line: str) -> Pronunciation | None:
    """Parse one ``TERM[, TERM...] = SPOKEN`` line.

    Returns ``None`` for blank lines and ``#`` comments, and raises ``TtsError``
    for anything else that is not a valid entry.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    term_side, separator, spoken = stripped.partition("=")
    terms = tuple(term.strip() for term in term_side.split(",") if term.strip())
    spoken = spoken.strip()
    if not separator or not terms or not spoken:
        raise TtsError(
            f"Invalid entry {stripped!r}: expected 'TERM = SPOKEN', "
            "e.g. 'Kubernetes = koober nett ease'."
        )
    if "=" in spoken:
        raise TtsError(f"Invalid entry {stripped!r}: expected a single '=' separator.")
    return Pronunciation(spoken=spoken, written=terms)


def apply_lexicon(text: str, entries: list[Pronunciation]) -> str:
    """Replace each written form with its entry's spoken form.

    Matching is case-sensitive and whole-term. Entries are applied in order, so
    an earlier entry can affect the text a later entry sees.
    """
    for entry in entries:
        for written in entry.written:
            pattern = _TERM_PATTERN.format(re.escape(written))
            text = re.sub(pattern, _literal(entry.spoken), text)
    return text


def _literal(replacement: str) -> Callable[[re.Match[str]], str]:
    """Substitution callable that treats ``replacement`` as literal text.

    Unlike a string replacement, this keeps backslashes (``\\1``, ``\\g<x>``)
    in the respelling from being interpreted as regex escapes.
    """

    def substitute(_match: re.Match[str]) -> str:
        return replacement

    return substitute
