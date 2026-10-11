from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


class CircuitBreaker(Protocol):
    def allow(self) -> bool: ...

    def record_success(self) -> None: ...

    def record_failure(self) -> None: ...

    @property
    def state(self) -> str: ...


@dataclass
class BreakerConfig:
    failure_threshold: int = 5
    open_seconds: float = 10.0

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "BreakerConfig":
        raw = section.get("breaker", {})
        return cls(int(raw.get("failure_threshold", 5)), float(raw.get("open_seconds", 10.0)))


class CountingBreaker:
    """Opens after N consecutive failures; lets one probe through after ``open_seconds``."""

    def __init__(self, config: BreakerConfig, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.config.open_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.config.failure_threshold:
            self._opened_at = self._clock()
