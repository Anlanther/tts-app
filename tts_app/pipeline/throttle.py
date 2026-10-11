"""Inter-chunk cooldown and thermal-aware pacing."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from tts_app.domain.models import MaxRuntimeExceeded
from tts_app.utils import thermal


class Throttle:
    """Sleeps between chunks, optionally lengthening pauses under thermal load."""

    def __init__(
        self,
        *,
        base_sleep: float = 2.0,
        thermal_aware: bool = False,
        thermal_threshold: int = 50,
        max_runtime: timedelta | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.base_sleep = base_sleep
        self.thermal_aware = thermal_aware
        self.thermal_threshold = thermal_threshold
        self.max_runtime = max_runtime
        self._clock = clock or datetime.now
        self._sleeper = sleeper or time.sleep
        self._started_at = self._clock()

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def wait(self, chunk_index: int) -> float:
        """Sleep before a chunk (skipping the first); returns the sleep duration."""
        self._check_runtime()
        duration = self._compute_duration()
        if chunk_index > 0 and duration > 0:
            self._sleeper(duration)
        return duration

    def _compute_duration(self) -> float:
        duration = self.base_sleep
        if self.thermal_aware:
            limit = thermal.read_cpu_speed_limit()
            if limit is not None and limit < self.thermal_threshold:
                duration += (self.thermal_threshold - limit) / 100.0 * 5.0
        return duration

    def _check_runtime(self) -> None:
        if self.max_runtime is None:
            return
        if self._clock() - self._started_at >= self.max_runtime:
            raise MaxRuntimeExceeded(
                f"Maximum runtime of {self.max_runtime} exceeded. "
                "Progress saved; resume with `tts resume <job_id>`."
            )
