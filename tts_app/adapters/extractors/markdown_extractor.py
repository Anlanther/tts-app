"""Markdown (.md) extractor: strip syntax via markdown-it-py -> HTML -> text."""

from __future__ import annotations

import html
import re
from pathlib import Path

from markdown_it import MarkdownIt

from tts_app.domain.models import ExtractionError, SourceDocument

_BLOCK_TAG_RE = re.compile(r"</?(p|div|h[1-6]|li|ul|ol|blockquote|pre|br|hr)\b[^>]*>")
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


class MarkdownExtractor:
    def __init__(self) -> None:
        self._md = MarkdownIt("commonmark")

    def extract(self, path: Path, *, password: str | None = None) -> SourceDocument:
        del password
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ExtractionError(f"Could not read Markdown file '{path}': {exc}") from exc
        title = self._first_heading(raw) or path.stem
        return SourceDocument(
            title=title,
            text=self._strip_markdown(raw),
            page_count=1,
            warnings=[],
        )

    def _first_heading(self, raw: str) -> str | None:
        for line in raw.splitlines():
            match = _HEADING_RE.match(line.strip())
            if match:
                return match.group(1).strip()
        return None

    def _strip_markdown(self, raw: str) -> str:
        rendered = self._md.render(raw)
        text = _BLOCK_TAG_RE.sub("\n", rendered)
        text = _TAG_RE.sub("", text)
        text = html.unescape(text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
