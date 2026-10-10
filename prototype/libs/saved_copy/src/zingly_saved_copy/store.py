from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from zingly_core import TenantContext


@dataclass(frozen=True)
class Lookup:
    """Result of a read. ``source`` is one of fresh | origin | coalesced | stale | miss."""

    value: Any
    source: str
    as_of: float | None = None  # wall-clock epoch seconds of the data
    error: str | None = None

    @property
    def found(self) -> bool:
        return self.source != "miss"

    @property
    def is_stale(self) -> bool:
        return self.source == "stale"


@dataclass
class SavedCopyConfig:
    default_ttl_s: float = 25.0
    keep_stale_s: float = 3600.0

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "SavedCopyConfig":
        return cls(float(section.get("default_ttl_s", 25.0)), float(section.get("keep_stale_s", 3600.0)))


Loader = Callable[[], Awaitable[Any]]


class SavedCopy(Protocol):
    async def get_or_load(self, ctx: TenantContext, key: str, loader: Loader,
                          ttl_s: float | None = None) -> Lookup: ...

    def peek(self, ctx: TenantContext, key: str) -> Lookup: ...

    def put(self, ctx: TenantContext, key: str, value: Any, ttl_s: float | None = None) -> None: ...

    def stats(self, tenant_id: str | None = None) -> dict[str, int]: ...


@dataclass
class _Entry:
    value: Any
    as_of: float
    fresh_until: float
    drop_after: float


class InMemorySavedCopy:
    """One store shared by all tenants; every key is prefixed with the tenant id.

    The Redis version replaces the in-flight map with ``SET lock:<key> NX PX <ms>``:
    the winner loads and writes, the others poll the key for the fresh value.
    """

    def __init__(self, config: SavedCopyConfig | None = None,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.config = config or SavedCopyConfig()
        self._clock = clock
        self._wall = wall
        self._data: dict[str, _Entry] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._counts: Counter[str] = Counter()

    def _count(self, ctx: TenantContext, what: str) -> None:
        self._counts[f"{ctx.tenant_id}:{what}"] += 1

    def put(self, ctx: TenantContext, key: str, value: Any, ttl_s: float | None = None) -> None:
        now = self._clock()
        ttl = self.config.default_ttl_s if ttl_s is None else ttl_s
        self._data[ctx.key(key)] = _Entry(value, self._wall(), now + ttl, now + ttl + self.config.keep_stale_s)

    def peek(self, ctx: TenantContext, key: str) -> Lookup:
        entry = self._data.get(ctx.key(key))
        now = self._clock()
        if entry is None or now > entry.drop_after:
            return Lookup(None, "miss")
        return Lookup(entry.value, "fresh" if now <= entry.fresh_until else "stale", entry.as_of)

    async def get_or_load(self, ctx: TenantContext, key: str, loader: Loader,
                          ttl_s: float | None = None) -> Lookup:
        current = self.peek(ctx, key)
        if current.source == "fresh":
            self._count(ctx, "hit")
            return current

        full_key = ctx.key(key)
        inflight = self._inflight.get(full_key)
        if inflight is not None:
            self._count(ctx, "coalesced")
            try:
                value = await asyncio.shield(inflight)
                return Lookup(value, "coalesced", self.peek(ctx, key).as_of)
            except Exception as exc:  # the shared load failed: same fallback as the leader
                return self._fallback(ctx, key, exc)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[full_key] = future
        self._count(ctx, "origin_load")
        try:
            value = await loader()
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved; waiters re-raise their own copy
            return self._fallback(ctx, key, exc)
        else:
            self.put(ctx, key, value, ttl_s)
            future.set_result(value)
            return Lookup(value, "origin", self._wall())
        finally:
            self._inflight.pop(full_key, None)

    def _fallback(self, ctx: TenantContext, key: str, exc: Exception) -> Lookup:
        current = self.peek(ctx, key)
        reason = type(exc).__name__
        if current.found:
            self._count(ctx, "served_stale")
            return Lookup(current.value, "stale", current.as_of, reason)
        self._count(ctx, "miss")
        return Lookup(None, "miss", None, reason)

    def stats(self, tenant_id: str | None = None) -> dict[str, int]:
        if tenant_id is None:
            return dict(sorted(self._counts.items()))
        prefix = f"{tenant_id}:"
        return {k[len(prefix):]: v for k, v in sorted(self._counts.items()) if k.startswith(prefix)}
