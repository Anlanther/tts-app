"""JSON-file-backed job store with atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from tts_app.domain.models import SynthesisJob


class JsonJobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def save(self, job: SynthesisJob) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(job.job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, job_id: str) -> SynthesisJob | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        return self._load_path(path)

    def list_jobs(self) -> list[SynthesisJob]:
        jobs: list[SynthesisJob] = []
        if not self.root.exists():
            return jobs
        for path in sorted(self.root.glob("*.json")):
            job = self._load_path(path)
            if job is not None:
                jobs.append(job)
        return jobs

    def delete(self, job_id: str) -> None:
        self._path(job_id).unlink(missing_ok=True)

    def _load_path(self, path: Path) -> SynthesisJob | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return SynthesisJob.from_dict(cast(dict[str, Any], data))
