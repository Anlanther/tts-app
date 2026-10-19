"""Tests for pronunciation lexicon parsing, application, and file loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from tts_app.adapters.lexicon_file import load_lexicon
from tts_app.domain.models import TtsError
from tts_app.domain.pronunciation import Pronunciation, apply_lexicon, parse_entry


def test_parse_simple_entry() -> None:
    entry = parse_entry("Kubernetes = koober nett ease")
    assert entry == Pronunciation(spoken="koober nett ease", written=("Kubernetes",))


def test_parse_trims_surrounding_whitespace() -> None:
    assert parse_entry("  CAT  =  cat  ") == Pronunciation(spoken="cat", written=("CAT",))


def test_parse_ignores_comments_and_blank_lines() -> None:
    assert parse_entry("") is None
    assert parse_entry("   ") is None
    assert parse_entry("# TERM = SPOKEN") is None


def test_parse_lists_alternate_spellings() -> None:
    entry = parse_entry("Dr., Dr = doctor")
    assert entry is not None
    assert entry.written == ("Dr.", "Dr")
    assert entry.spoken == "doctor"


def test_parse_rejects_missing_separator() -> None:
    with pytest.raises(TtsError, match="expected 'TERM = SPOKEN'"):
        parse_entry("Kubernetes koober")


def test_parse_rejects_empty_term_or_respelling() -> None:
    with pytest.raises(TtsError):
        parse_entry(" = koober")
    with pytest.raises(TtsError):
        parse_entry("Kubernetes = ")


def test_parse_rejects_second_separator() -> None:
    with pytest.raises(TtsError, match="single '=' separator"):
        parse_entry("A = B = C")


def test_apply_replaces_whole_terms_only() -> None:
    entries = [Pronunciation(spoken="cat", written=("CAT",))]
    assert apply_lexicon("CAT and concatenate", entries) == "cat and concatenate"
    assert apply_lexicon("the (CAT).", entries) == "the (cat)."


def test_apply_is_case_sensitive() -> None:
    entries = [Pronunciation(spoken="kat", written=("cat",))]
    assert apply_lexicon("cat Cat CAT", entries) == "kat Cat CAT"


def test_apply_handles_trailing_period_and_hyphenated_terms() -> None:
    assert apply_lexicon("Dr. Smith", [Pronunciation("doctor", ("Dr.",))]) == "doctor Smith"
    assert apply_lexicon("Wi-Fi here", [Pronunciation("wifi", ("Wi-Fi",))]) == "wifi here"


def test_apply_replaces_every_alternate_spelling() -> None:
    entries = [Pronunciation(spoken="doctor", written=("Dr.", "Dr"))]
    assert apply_lexicon("Dr. Smith and Dr Jones", entries) == "doctor Smith and doctor Jones"


def test_apply_keeps_backslashes_literal() -> None:
    # A string replacement would read r"\1" as a regex group reference.
    entries = [Pronunciation(spoken=r"a\1b", written=("Q",))]
    assert apply_lexicon("Q", entries) == r"a\1b"


def test_apply_handles_unicode_terms() -> None:
    entries = [Pronunciation(spoken="nee hao", written=("你好",))]
    assert apply_lexicon("你好 world", entries) == "nee hao world"


def test_apply_uses_file_order_as_precedence() -> None:
    entries = [
        Pronunciation(spoken="first", written=("X",)),
        Pronunciation(spoken="second", written=("X",)),
    ]
    assert apply_lexicon("X", entries) == "first"


def test_apply_returns_text_unchanged_without_entries() -> None:
    assert apply_lexicon("Kubernetes", []) == "Kubernetes"


def test_load_lexicon_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.txt"
    path.write_text("# comment\n\nKubernetes = koober nett ease\n", encoding="utf-8")
    assert load_lexicon(path) == [Pronunciation(spoken="koober nett ease", written=("Kubernetes",))]


def test_load_lexicon_reports_the_offending_line(tmp_path: Path) -> None:
    path = tmp_path / "lexicon.txt"
    path.write_text("Kubernetes = koober\nbroken\n", encoding="utf-8")
    with pytest.raises(TtsError, match=r":2: Invalid entry"):
        load_lexicon(path)


def test_load_lexicon_reports_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(TtsError, match="Cannot read pronunciation lexicon"):
        load_lexicon(tmp_path / "missing.txt")
