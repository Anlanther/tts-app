"""Sentence-aware chunking.

Splits arbitrary text into chunks targeting ``target_chars`` and never
exceeding ``max_chars`` (except for un-splittable single units such as a huge
code block). Chunk boundaries prefer paragraph ends, then sentence ends, then
clause ends, and finally a hard character cut.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# Default chunk-size targets (characters), shared by every layer.
DEFAULT_TARGET_CHARS = 1000
DEFAULT_MAX_CHARS = 1500
DEFAULT_MIN_CHARS = 500

_SENTINEL = "\x00"
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_FENCE_TOKEN_RE = re.compile(r"\x01F(\d+)E\x01")
_CLAUSE_RE = re.compile(r"(?<=[,;:，；：])\s+")


@dataclass(frozen=True)
class _Unit:
    text: str
    ends_paragraph: bool = False


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving paragraph structure as separate items."""
    return [unit.text for unit in split_into_units(text)]


def split_into_units(text: str) -> list[_Unit]:
    """Split text into sentence units, marking paragraph-final units."""
    work, fences = _stash_fences(text)
    paragraphs = re.split(r"\n\s*\n", work)
    units: list[_Unit] = []
    for paragraph in paragraphs:
        pieces = _split_paragraph(paragraph)
        if not pieces:
            continue
        for index, piece in enumerate(pieces):
            units.append(_Unit(piece, ends_paragraph=(index == len(pieces) - 1)))
    return [_Unit(_restore_fences(unit.text, fences), unit.ends_paragraph) for unit in units]


def chunk_text(
    text: str,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    hard_breaks: Sequence[int] = (),
) -> list[str]:
    """Split ``text`` into chunks, respecting ``hard_breaks`` (char offsets)."""
    max_chars = max(1, max_chars)
    target_chars = min(max(1, target_chars), max_chars)
    min_chars = min(max(0, min_chars), target_chars)

    breaks = _normalize_breaks(hard_breaks, len(text))
    chunks: list[str] = []
    start = 0
    for break_at in breaks:
        if break_at > start and break_at < len(text):
            chunks.extend(_chunk_segment(text[start:break_at], target_chars, max_chars, min_chars))
            start = break_at
    chunks.extend(_chunk_segment(text[start:], target_chars, max_chars, min_chars))
    return [chunk for chunk in chunks if chunk]


def _normalize_breaks(breaks: Sequence[int], length: int) -> list[int]:
    return sorted({break_at for break_at in breaks if 0 < break_at < length})


def _chunk_segment(text: str, target: int, max_chars: int, min_chars: int) -> list[str]:
    return group_units(split_into_units(text), target, max_chars, min_chars)


def group_units(units: Sequence[_Unit], target: int, max_chars: int, min_chars: int) -> list[str]:
    """Greedily group sentence units into chunks of ~target chars."""
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_len = 0

    def flush() -> None:
        nonlocal buffer, buffer_len
        if buffer:
            chunks.append(" ".join(buffer))
            buffer = []
            buffer_len = 0

    for unit in units:
        text = unit.text
        if len(text) > max_chars:
            flush()
            chunks.extend(_split_long_unit(text, max_chars))
            continue
        if buffer and buffer_len + 1 + len(text) > max_chars:
            flush()
        buffer.append(text)
        buffer_len += len(text) + (1 if len(buffer) > 1 else 0)
        if unit.ends_paragraph and buffer_len >= target and buffer_len >= min_chars:
            flush()

    flush()
    return chunks


def _split_long_unit(text: str, max_chars: int) -> list[str]:
    clauses = _CLAUSE_RE.split(text)
    pieces: list[str] = []
    buffer = ""
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        if len(clause) > max_chars:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(_hard_split(clause, max_chars))
        elif buffer and len(buffer) + 1 + len(clause) > max_chars:
            pieces.append(buffer)
            buffer = clause
        else:
            buffer = f"{buffer} {clause}".strip()
    if buffer:
        pieces.append(buffer)
    return [piece for piece in pieces if piece]


def _hard_split(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _split_paragraph(paragraph: str) -> list[str]:
    collapsed = re.sub(r"[ \t]*\r?\n[ \t]*", " ", paragraph)
    collapsed = re.sub(r"[ \t]{2,}", " ", collapsed).strip()
    if not collapsed:
        return []
    return _split_sentences(collapsed)


def _split_sentences(text: str) -> list[str]:
    marked = re.sub(r"(?<=[。！？])(?=[^\s。！？])", _SENTINEL, text)
    marked = re.sub(
        r"(?<=[.!?])\s+(?=[A-Z0-9\u201c\u2018\u00ab\u00bf\u00a1(\[])",
        _SENTINEL,
        marked,
    )
    return [piece.strip() for piece in marked.split(_SENTINEL) if piece.strip()]


def _stash_fences(text: str) -> tuple[str, list[str]]:
    fences: list[str] = []

    def replace(match: re.Match[str]) -> str:
        fences.append(match.group(0))
        return f"\n\x01F{len(fences) - 1}E\x01\n"

    return _FENCE_RE.sub(replace, text), fences


def _restore_fences(text: str, fences: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return fences[index]

    return _FENCE_TOKEN_RE.sub(replace, text)
