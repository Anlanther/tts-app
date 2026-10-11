.PHONY: install test lint typecheck run

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check tts_app tests

typecheck:
	uv run mypy --strict tts_app

run:
	uv run tts --help
