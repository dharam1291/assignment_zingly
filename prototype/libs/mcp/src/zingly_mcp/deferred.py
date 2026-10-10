"""Deferred commit (design §5, P0 fallback): the caller's choice is recorded and committed
later under the same idempotency key, then confirmed by SMS. Needs business sign-off."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class PendingCommit:
    tenant_id: str
    booking_ref: str
    from_flight: str
    to_flight: str
    idempotency_key: str
    created_at: float = field(default_factory=time.time)
    attempts: int = 0
    status: str = "pending"  # pending | confirmed | failed
    detail: str = ""


class DeferredCommits:
    def __init__(self, max_attempts: int = 20):
        self.max_attempts = max_attempts
        self._items: dict[str, PendingCommit] = {}

    def add(self, item: PendingCommit) -> PendingCommit:
        return self._items.setdefault(item.idempotency_key, item)

    def pending(self, tenant_id: str | None = None) -> list[PendingCommit]:
        return [i for i in self._items.values()
                if i.status == "pending" and (tenant_id is None or i.tenant_id == tenant_id)]

    async def drain(self, commit: Callable[[PendingCommit], Awaitable[str]], tenant_id: str | None = None) -> int:
        """``commit`` returns confirmed | retry | failed. Returns how many were confirmed."""
        done = 0
        for item in self.pending(tenant_id):
            item.attempts += 1
            outcome = await commit(item)
            if outcome == "confirmed":
                item.status, done = "confirmed", done + 1
            elif outcome == "failed" or item.attempts >= self.max_attempts:
                item.status = "failed"
        return done

    def summary(self, tenant_id: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self._items.values():
            if tenant_id is None or i.tenant_id == tenant_id:
                out[i.status] = out.get(i.status, 0) + 1
        return out
