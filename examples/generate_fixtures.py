"""Regenerate the example fixtures in this directory.

Usage: `uv run python examples/generate_fixtures.py`
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).parent

_SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "A journey of a thousand miles begins with a single step.",
    "She sells seashells by the seashore on a bright and sunny day.",
    "Every great story starts with a single, well-chosen word.",
    "The old library smelled of paper, dust, and quiet patience.",
    "He opened the window and let the cool evening air drift in.",
    "There is nothing quite as satisfying as finishing a good book.",
    "The mountains stood silent beneath a sky full of stars.",
    "Time flows like a river, never pausing for anyone.",
    "Curiosity is the engine that drives all human discovery.",
    "The garden bloomed with colour after the first spring rain.",
    "A well-told story can change the way we see the world.",
]

_CHAPTERS = [
    "Chapter One: The Beginning",
    "Chapter Two: The Journey",
    "Chapter Three: The Discovery",
    "Chapter Four: The Return",
]


def _build_text(target_chars: int) -> str:
    paragraphs: list[str] = []
    total = 0
    index = 0
    chapter = 0
    while total < target_chars:
        if index % 24 == 0:
            paragraphs.append(_CHAPTERS[chapter % len(_CHAPTERS)])
            chapter += 1
            total += len(paragraphs[-1])
        sentences = [_SENTENCES[(index + offset) % len(_SENTENCES)] for offset in range(5)]
        paragraph = " ".join(sentences)
        paragraphs.append(paragraph)
        total += len(paragraph) + 2
        index += 1
    return "\n\n".join(paragraphs)


def write_sample_txt() -> None:
    (_HERE / "sample.txt").write_text(_build_text(12000), encoding="utf-8")


def write_sample_md() -> None:
    markdown = (
        "# The Example Book\n\n"
        "## Introduction\n\n"
        "This is **bold** text with [a link](https://example.com) and _emphasis_.\n\n"
        "```python\n"
        "def hello():\n"
        "    print('hello')\n"
        "```\n\n"
        "A paragraph with a list:\n\n"
        "- first item\n"
        "- second item\n"
        "- third item\n\n"
        "> A quoted line of wisdom.\n\n"
        "## Conclusion\n\n"
        "And a final paragraph to close things out.\n"
    )
    (_HERE / "sample.md").write_text(markdown, encoding="utf-8")


def write_sample_pdf() -> None:
    try:
        import pymupdf
    except ImportError:
        print("pymupdf not installed; skipping sample.pdf")
        return

    doc = pymupdf.open()
    for page_no in range(6):
        page = doc.new_page()
        page.insert_text((72, 40), "The Example Book")  # repeated header
        body = f"This is page {page_no + 1} of the example book. " * 8
        page.insert_text((72, 110), body)
        page.insert_text((72, 800), str(page_no + 1))  # page number footer
    doc.set_metadata({"title": "The Example Book"})
    doc.set_toc(
        [
            [1, "Chapter One", 1],
            [1, "Chapter Two", 3],
            [1, "Chapter Three", 5],
        ]
    )
    doc.save(str(_HERE / "sample.pdf"))
    doc.close()
    print("wrote sample.pdf")


def main() -> None:
    write_sample_txt()
    write_sample_md()
    write_sample_pdf()
    print("done")


if __name__ == "__main__":
    main()
