"""Inter-chunk cooldown and thermal-aware pacing."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

from tts_app.domain.models import MaxMemoryExceeded, MaxRuntimeExceeded
from tts_app.utils import memory, thermal


class Throttle:
    """Sleeps between chunks, optionally lengthening pauses under thermal load."""

    def __init__(
        self,
        *,
        base_sleep: float = 2.0,
        thermal_aware: bool = False,
        thermal_threshold: int = 50,
        max_runtime: timedelta | None = None,
        memory_aware: bool = False,
        max_memory_mb: int | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.base_sleep = base_sleep
        self.thermal_aware = thermal_aware
        self.thermal_threshold = thermal_threshold
        self.max_runtime = max_runtime
        self.memory_aware = memory_aware
        self.max_memory_mb = max_memory_mb
        self._clock = clock or datetime.now
        self._sleeper = sleeper or time.sleep
        self._started_at = self._clock()

    @property
    def started_at(self) -> datetime:
        return self._started_at

    def wait(self, chunk_index: int) -> float:
        """Sleep before a chunk (skipping the first); returns the sleep duration."""
        self._check_runtime()
        self._check_memory()
        duration = self._compute_duration()
        if chunk_index > 0 and duration > 0:
            self._sleeper(duration)
        return duration

    def _compute_duration(self) -> float:
        duration = self.base_sleep
        if self.thermal_aware:
            duration += self._thermal_penalty()
        return duration

    def _thermal_penalty(self) -> float:
        """Extra cooldown implied by current throttling, or 0.0 when cool/unknown."""
        limit = thermal.read_cpu_speed_limit()
        if limit is not None:
            if limit < self.thermal_threshold:
                return (self.thermal_threshold - limit) / 100.0 * 5.0
            return 0.0
        # No speed limit reported (e.g. Apple Silicon); fall back to the thermal
        # pressure level exposed by powermetrics.
        return thermal.pressure_penalty(thermal.read_thermal_reading().pressure)

    def _check_runtime(self) -> None:
        if self.max_runtime is None:
            return
        if self._clock() - self._started_at >= self.max_runtime:
            raise MaxRuntimeExceeded(
                f"Maximum runtime of {self.max_runtime} exceeded. "
                "Progress saved; run `tts list-jobs` to find the job id."
            )

    def _check_memory(self) -> None:
        if self.max_memory_mb is None:
            return
        current = memory.read_memory_reading().current_mib
        if current is not None and current >= self.max_memory_mb:
            raise MaxMemoryExceeded(
                f"Memory use of {current:.0f}MB reached the {self.max_memory_mb}MB limit. "
                "Progress saved; run `tts list-jobs` to find the job id."
            )
