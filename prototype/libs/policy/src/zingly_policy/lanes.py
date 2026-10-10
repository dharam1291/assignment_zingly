"""Priority lanes over one shared rate limit (design §5 "Under the hood").

Each lane is a token bucket refilling at its share of the parent rate. A parent bucket,
set a little below the reservation system's hard limit, caps the total. Higher lanes may
borrow idle capacity from lower lanes, never the other way round. A request waits up to
its lane's budget; if it still has no token the reservation system is NOT called and the
caller gets the lane's fallback.

In production the buckets live in Redis so every instance shares them; this default
implementation keeps them in process memory, one instance per tenant.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol


class Lane(str, Enum):
    P0 = "P0"  # book or hold a seat
    P1 = "P1"  # find the caller's booking
    P2 = "P2"  # refresh options
    P3 = "P3"  # flight status

    @property
    def rank(self) -> int:
        return int(self.value[1])


class AdmissionController(Protocol):
    async def acquire(self, lane: Lane | str, wait_s: float | None = None) -> bool: ...

    def stats(self) -> dict[str, Any]: ...


@dataclass
class LanesConfig:
    parent_rps: float = 4.0
    parent_burst: float = 1.0
    shares: dict[Lane, float] = field(
        default_factory=lambda: {Lane.P0: 0.4, Lane.P1: 0.3, Lane.P2: 0.2, Lane.P3: 0.1}
    )
    wait_s: dict[Lane, float] = field(
        default_factory=lambda: {Lane.P0: 3.0, Lane.P1: 1.5, Lane.P2: 0.5, Lane.P3: 0.0}
    )
    borrow: bool = True

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "LanesConfig":
        lanes = section.get("lanes", {})
        cfg = cls()
        cfg.parent_rps = float(lanes.get("parent_rps", cfg.parent_rps))
        cfg.parent_burst = float(lanes.get("parent_burst", cfg.parent_burst))
        cfg.borrow = bool(lanes.get("borrow", cfg.borrow))
        for lane, share in lanes.get("shares", {}).items():
            cfg.shares[Lane(lane)] = float(share)
        for lane, wait in lanes.get("wait_s", {}).items():
            cfg.wait_s[Lane(lane)] = float(wait)
        total = sum(cfg.shares.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"lane shares must add up to 1.0, got {total}")
        return cfg


class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock: Callable[[], float] = time.monotonic):
        self.rate = rate
        self.capacity = max(1.0, capacity)
        self._clock = clock
        self._tokens = self.capacity
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def available(self) -> bool:
        self._refill()
        return self._tokens >= 1.0

    def take(self) -> None:
        self._tokens -= 1.0

    def seconds_to_token(self) -> float:
        self._refill()
        if self._tokens >= 1.0 or self.rate <= 0:
            return 0.0
        return (1.0 - self._tokens) / self.rate


class LaneAdmission:
    """Default :class:`AdmissionController` for one tenant."""

    def __init__(self, config: LanesConfig, clock: Callable[[], float] = time.monotonic):
        self.config = config
        self._clock = clock
        self._parent = TokenBucket(config.parent_rps, config.parent_burst, clock)
        self._lanes = {
            lane: TokenBucket(config.parent_rps * share, 1.0, clock)
            for lane, share in config.shares.items()
        }
        self._counts: Counter[str] = Counter()

    def _try_take(self, lane: Lane) -> bool:
        # No await in here, so this check-and-take is atomic on the event loop.
        if not self._parent.available():
            return False
        donors = [lane]
        if self.config.borrow:
            donors += [l for l in Lane if l.rank > lane.rank]
        for donor in donors:
            bucket = self._lanes[donor]
            if bucket.available():
                bucket.take()
                self._parent.take()
                if donor is not lane:
                    self._counts[f"{lane.value}.borrowed_from_{donor.value}"] += 1
                return True
        return False

    async def acquire(self, lane: Lane | str, wait_s: float | None = None) -> bool:
        """Wait up to the lane's budget (or ``wait_s`` for background jobs) for a token."""
        lane = Lane(lane)
        budget = self.config.wait_s.get(lane, 0.0) if wait_s is None else wait_s
        deadline = self._clock() + budget
        waited = False
        while True:
            if self._try_take(lane):
                self._counts[f"{lane.value}.admitted"] += 1
                if waited:
                    self._counts[f"{lane.value}.admitted_after_wait"] += 1
                return True
            remaining = deadline - self._clock()
            if remaining <= 0:
                self._counts[f"{lane.value}.rejected"] += 1
                return False
            waited = True
            pause = max(self._parent.seconds_to_token(), self._lanes[lane].seconds_to_token(), 0.01)
            await asyncio.sleep(min(pause, remaining, 0.05))

    def stats(self) -> dict[str, Any]:
        return dict(sorted(self._counts.items()))
