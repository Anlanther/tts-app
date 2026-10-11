"""Plain-text (.txt) extractor."""

from __future__ import annotations

from pathlib import Path

from tts_app.domain.models import ExtractionError, SourceDocument


class TxtExtractor:
    def extract(self, path: Path, *, password: str | None = None) -> SourceDocument:
        del password
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ExtractionError(f"Could not read '{path}': {exc}") from exc
        return SourceDocument(
            title=path.stem,
            text=_decode(data, path),
            page_count=1,
            warnings=[],
        )


def _decode(data: bytes, path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError(f"Could not decode '{path}' as text. Convert it to UTF-8 and retry.")
