"""Logging configuration: file-per-job plus a warning-level console stream."""

from __future__ import annotations

import logging
from pathlib import Path

_ROOT_LOGGER = "tts_app"


def configure_logging(log_dir: Path, job_id: str | None = None) -> logging.Logger:
    """Configure the ``tts_app`` logger and return it."""
    log_dir.mkdir(parents=True, exist_ok=True)
    name = job_id or "tts_app"
    logger = logging.getLogger(_ROOT_LOGGER)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{_ROOT_LOGGER}.{name}")
