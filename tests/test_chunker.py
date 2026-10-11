"""Unit tests for the sentence-aware chunker."""

from __future__ import annotations

from tts_app.pipeline.chunker import chunk_text, split_into_sentences


def test_no_punctuation_splits_at_max_chars() -> None:
    text = "word " * 400  # 2000 chars, no punctuation
    chunks = chunk_text(text, target_chars=500, max_chars=800, min_chars=200)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 800 for chunk in chunks)


def test_very_long_sentence_splits_at_clause_boundaries() -> None:
    text = "This is a long sentence, with several clauses, joined by commas, " * 10
    chunks = chunk_text(text, target_chars=120, max_chars=200, min_chars=40)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)


def test_code_block_is_preserved() -> None:
    code = "```\nline one\nline two\nline three\n```"
    text = f"Intro sentence here.\n\n{code}\n\nAfter the code block."
    chunks = chunk_text(text, target_chars=30, max_chars=120, min_chars=10)
    joined = "\n".join(chunks)
    assert code in joined


def test_unicode_content_survives() -> None:
    text = "Café — the “best” place. Next sentence with naïve accents."
    chunks = chunk_text(text, target_chars=20, max_chars=60, min_chars=5)
    joined = " ".join(chunks)
    assert "Café" in joined
    assert "—" in joined
    assert "“best”" in joined
    assert "naïve" in joined


def test_cjk_sentence_splitting() -> None:
    text = "这是第一句话。这是第二句话！第三句呢？"
    sentences = split_into_sentences(text)
    assert len(sentences) == 3


def test_hard_breaks_are_respected() -> None:
    text = "AAA sentence one. BBB sentence two. CCC sentence three. DDD sentence four."
    chunks = chunk_text(text, target_chars=10, max_chars=50, min_chars=5, hard_breaks=[30])
    assert len(chunks) >= 2
    # No chunk may contain both "BBB" (before break) and "DDD" (after break).
    for chunk in chunks:
        assert not ("BBB" in chunk and "DDD" in chunk)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", target_chars=500, max_chars=800, min_chars=200) == []
    assert chunk_text("   \n\n  ", target_chars=500, max_chars=800, min_chars=200) == []
