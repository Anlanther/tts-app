"""Text extractor registry: dispatch by file extension (case-insensitive)."""

from __future__ import annotations

from collections.abc import Callable

from tts_app.domain.models import UnknownFormatError
from tts_app.domain.ports import TextExtractor

from .markdown_extractor import MarkdownExtractor
from .pdf_extractor import PdfExtractor
from .txt_extractor import TxtExtractor

_EXTRACTORS: dict[str, Callable[[], TextExtractor]] = {
    "txt": lambda: TxtExtractor(),
    "md": lambda: MarkdownExtractor(),
    "markdown": lambda: MarkdownExtractor(),
    "pdf": lambda: PdfExtractor(),
}


def available_formats() -> list[str]:
    return sorted(set(_EXTRACTORS) - {"markdown"})


def extractor_for(extension: str) -> TextExtractor:
    ext = extension.lower().lstrip(".")
    factory = _EXTRACTORS.get(ext)
    if factory is None:
        supported = ", ".join(available_formats())
        raise UnknownFormatError(
            f"Unsupported file extension '.{ext}'. Supported: {supported}. "
            "Use --format to override."
        )
    return factory()
