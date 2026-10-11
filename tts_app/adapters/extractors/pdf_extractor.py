"""PDF text extractor using PyMuPDF.

Extracts text page-by-page in reading order, strips repeated headers/footers
and page numbers, collapses hyphenated line-wraps, reads metadata title and
TOC chapter boundaries, and warns (without OCR) about pages that yield no
text (likely scanned images).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf as _pymupdf

from tts_app.domain.models import ExtractionError, SourceDocument

# pymupdf ships partial type hints; treat the module as Any at our boundary.
pymupdf: Any = _pymupdf

_PAGE_NUM_RE = re.compile(r"^(?:page\s+)?\d{1,6}(?:\s*(?:of|/)\s*\d{1,6})?$", re.IGNORECASE)

_TOP_RATIO = 0.15
_BOTTOM_RATIO = 0.85
_EDGE_MAX_CHARS = 80


class PdfExtractor:
    def extract(self, path: Path, *, password: str | None = None) -> SourceDocument:
        try:
            doc = pymupdf.open(str(path))
        except Exception as exc:  # noqa: BLE001 - pymupdf raises various error types
            raise ExtractionError(f"Could not open PDF '{path}': {exc}") from exc

        try:
            if doc.needs_pass:
                if password is None:
                    raise ExtractionError(
                        f"PDF '{path}' is password-protected. "
                        "Provide a password via --pdf-password."
                    )
                if not doc.authenticate(password):
                    raise ExtractionError("Incorrect PDF password.")

            page_count = int(doc.page_count)
            title = _read_title(doc, path)
            chapters = _read_toc(doc)

            page_lines: list[list[tuple[float, float, str]]] = []
            page_heights: list[float] = []
            for index in range(page_count):
                page = doc.load_page(index)
                page_lines.append(_page_lines(page))
                page_heights.append(float(page.rect.height))

            header_set, footer_set = _detect_edge_lines(page_lines, page_heights)

            page_texts: list[str] = []
            empty_pages: list[int] = []
            for index in range(page_count):
                page = doc.load_page(index)
                text = _extract_page_text(page, header_set, footer_set, page_heights[index])
                page_texts.append(text)
                if not text.strip():
                    empty_pages.append(index + 1)

            warnings: list[str] = []
            if empty_pages:
                warnings.append(
                    f"Pages {empty_pages} produced no extractable text; they are likely "
                    "scanned images. Run OCR (e.g. `ocrmypdf`) before conversion."
                )

            full_text, chapter_breaks = _assemble(page_texts, chapters)
            return SourceDocument(
                title=title,
                text=full_text,
                page_count=page_count,
                warnings=warnings,
                chapter_breaks=chapter_breaks,
            )
        finally:
            doc.close()


def _page_lines(page: Any) -> list[tuple[float, float, str]]:
    data = page.get_text("dict")
    lines: list[tuple[float, float, str]] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            bbox = line.get("bbox")
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if text and bbox:
                lines.append((float(bbox[1]), float(bbox[3]), text))
    return lines


def _detect_edge_lines(
    page_lines: list[list[tuple[float, float, str]]], page_heights: list[float]
) -> tuple[set[str], set[str]]:
    header_candidates: Counter[str] = Counter()
    footer_candidates: Counter[str] = Counter()
    for lines, height in zip(page_lines, page_heights, strict=True):
        for y0, y1, text in lines:
            normalized = _normalize(text)
            if not _is_edge_candidate(normalized):
                continue
            if y0 < height * _TOP_RATIO:
                header_candidates[normalized] += 1
            elif y1 > height * _BOTTOM_RATIO:
                footer_candidates[normalized] += 1

    page_count = len(page_lines)
    if page_count < 2:
        return set(), set()
    threshold = max(2, (page_count * 2) // 3)
    header_set = {text for text, count in header_candidates.items() if count >= threshold}
    footer_set = {text for text, count in footer_candidates.items() if count >= threshold}
    return header_set, footer_set


def _extract_page_text(
    page: Any, header_set: set[str], footer_set: set[str], page_height: float
) -> str:
    data = page.get_text("dict")
    paragraphs: list[str] = []
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        kept_lines: list[str] = []
        for line in block.get("lines", []):
            bbox = line.get("bbox")
            if not bbox:
                continue
            y0, y1 = float(bbox[1]), float(bbox[3])
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            normalized = _normalize(text)
            if y0 < page_height * _TOP_RATIO and (
                normalized in header_set or _is_page_number(text)
            ):
                continue
            if y1 > page_height * _BOTTOM_RATIO and (
                normalized in footer_set or _is_page_number(text)
            ):
                continue
            kept_lines.append(text)
        if kept_lines:
            paragraphs.append(_join_lines(kept_lines))
    return "\n\n".join(paragraphs)


def _join_lines(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        if out and out[-1].endswith("-") and not out[-1].endswith("--") and line[:1].islower():
            out[-1] = out[-1][:-1] + line
        else:
            out.append(line)
    return " ".join(out)


def _assemble(
    page_texts: list[str], chapters: list[tuple[int, str]]
) -> tuple[str, list[int] | None]:
    chapter_pages = {page: title for page, title in chapters}
    parts: list[str] = []
    offsets: list[int] = []
    offset = 0
    for index, text in enumerate(page_texts):
        page_no = index + 1
        if page_no in chapter_pages:
            heading = chapter_pages[page_no] + "\n\n"
            parts.append(heading)
            offsets.append(offset)
            offset += len(heading)
        parts.append(text)
        offset += len(text)
        if index < len(page_texts) - 1:
            parts.append("\n\n")
            offset += 2
    return "".join(parts).rstrip(), offsets if offsets else None


def _read_title(doc: Any, path: Path) -> str:
    metadata = doc.metadata
    if metadata:
        title = str(metadata.get("title", "")).strip()
        if title:
            return title
    return path.stem


def _read_toc(doc: Any) -> list[tuple[int, str]]:
    toc = doc.get_toc()
    chapters: list[tuple[int, str]] = []
    for entry in toc:
        if len(entry) < 3:
            continue
        level = int(entry[0])
        if level > 2:
            continue
        title = str(entry[1]).strip()
        page = int(entry[2])
        if title:
            chapters.append((page, title))
    return chapters


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_page_number(text: str) -> bool:
    return bool(_PAGE_NUM_RE.match(text.strip()))


def _is_edge_candidate(normalized: str) -> bool:
    return (
        bool(normalized) and len(normalized) <= _EDGE_MAX_CHARS and not _is_page_number(normalized)
    )
