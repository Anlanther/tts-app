"""Sentence-aware chunking adapter implementing the TextSplitter port."""

from __future__ import annotations

from collections.abc import Sequence

from tts_app.pipeline.chunker import chunk_text


class SentenceSplitter:
    def __init__(
        self,
        target_chars: int = 1000,
        max_chars: int = 1500,
        min_chars: int = 500,
    ) -> None:
        self.target_chars = target_chars
        self.max_chars = max_chars
        self.min_chars = min_chars

    def split(self, text: str, hard_breaks: Sequence[int] = ()) -> list[str]:
        return chunk_text(
            text,
            target_chars=self.target_chars,
            max_chars=self.max_chars,
            min_chars=self.min_chars,
            hard_breaks=hard_breaks,
        )
