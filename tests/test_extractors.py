"""Unit tests for the text extractors and the extension registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from tts_app.adapters.extractors import extractor_for
from tts_app.adapters.extractors.markdown_extractor import MarkdownExtractor
from tts_app.adapters.extractors.pdf_extractor import PdfExtractor, _join_lines
from tts_app.adapters.extractors.txt_extractor import TxtExtractor
from tts_app.domain.models import ExtractionError, UnknownFormatError


def test_txt_extractor(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Hello world.\nSecond sentence.", encoding="utf-8")
    document = TxtExtractor().extract(path)
    assert document.title == "notes"
    assert document.page_count == 1
    assert "Hello world." in document.text
    assert document.warnings == []


def test_markdown_extractor_strips_syntax(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(
        "# My Title\n\nThis is **bold** and [a link](https://example.com).\n\n"
        "```python\nprint('hi')\n```\n",
        encoding="utf-8",
    )
    document = MarkdownExtractor().extract(path)
    assert document.title == "My Title"
    assert "My Title" in document.text
    assert "bold" in document.text
    assert "**" not in document.text
    assert "a link" in document.text
    assert "https://example.com" not in document.text
    assert "print('hi')" in document.text


def test_extractor_registry_rejects_unknown_extension() -> None:
    with pytest.raises(UnknownFormatError):
        extractor_for("docx")


def test_extractor_registry_is_case_insensitive() -> None:
    extractor = extractor_for("TXT")
    assert isinstance(extractor, TxtExtractor)


# --- PDF tests (skipped when pymupdf is unavailable) ---


def _fitz():
    return pytest.importorskip("pymupdf")


def _make_header_footer_pdf(path: Path) -> None:
    fitz = _fitz()
    doc = fitz.open()
    words = ["first", "second", "third"]
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 40), "Book Title")  # repeated header
        body = f"Some body text on the {words[i]} page."
        page.insert_text((72, 200), body)
        page.insert_text((72, 800), str(i + 1))  # page number footer
    doc.set_metadata({"title": "My Book"})
    doc.save(str(path))
    doc.close()


def _make_toc_pdf(path: Path) -> None:
    fitz = _fitz()
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 120), f"Body text for page {i + 1}.")
    doc.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 2]])
    doc.save(str(path))
    doc.close()


def test_pdf_strips_header_footer_and_page_numbers(tmp_path: Path) -> None:
    path = tmp_path / "book.pdf"
    _make_header_footer_pdf(path)
    document = PdfExtractor().extract(path)
    assert document.title == "My Book"
    assert document.page_count == 3
    assert "Book Title" not in document.text
    assert "Some body text on the first page." in document.text
    for digit in ("1", "2", "3"):
        assert digit not in document.text


def test_pdf_toc_produces_chapter_breaks(tmp_path: Path) -> None:
    path = tmp_path / "toc.pdf"
    _make_toc_pdf(path)
    document = PdfExtractor().extract(path)
    assert document.chapter_breaks is not None
    assert len(document.chapter_breaks) == 2
    assert "Chapter One" in document.text
    assert "Chapter Two" in document.text


def test_pdf_encrypted_requires_password(tmp_path: Path) -> None:
    fitz = _fitz()
    path = tmp_path / "enc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Secret body text.")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()

    with pytest.raises(ExtractionError):
        PdfExtractor().extract(path)

    result = PdfExtractor().extract(path, password="secret")
    assert "Secret body text." in result.text


def test_pdf_scanned_page_warns(tmp_path: Path) -> None:
    fitz = _fitz()
    path = tmp_path / "scanned.pdf"
    doc = fitz.open()
    first = doc.new_page()
    first.insert_text((72, 120), "Text on first page.")
    doc.new_page()  # no text: simulates a scanned page
    third = doc.new_page()
    third.insert_text((72, 120), "Text on third page.")
    doc.save(str(path))
    doc.close()

    result = PdfExtractor().extract(path)
    assert result.page_count == 3
    assert any("Pages [2]" in warning for warning in result.warnings)


def test_join_lines_collapses_hyphenation() -> None:
    assert _join_lines(["exam-", "ple dog"]) == "example dog"
    assert _join_lines(["well-known", "word"]) == "well-known word"
    assert _join_lines(["a normal", "sentence"]) == "a normal sentence"
