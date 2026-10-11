"""What MCP needs from other modules. Structural types: any object with these methods fits."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from zingly_core import IdentityLevel, TenantContext


class GuardPort(Protocol):
    def check(self, tool: str, level: IdentityLevel) -> Any: ...  # -> .allowed, .reason


class AdmissionPort(Protocol):
    async def acquire(self, lane: str, wait_s: float | None = None) -> bool: ...


class BreakerPort(Protocol):
    def allow(self) -> bool: ...

    def record_success(self) -> None: ...

    def record_failure(self) -> None: ...


class CachePort(Protocol):
    async def get_or_load(self, ctx: TenantContext, key: str, loader: Callable[[], Awaitable[Any]],
                          ttl_s: float | None = None) -> Any: ...  # -> .value .source .as_of .error

    def peek(self, ctx: TenantContext, key: str) -> Any: ...

    def put(self, ctx: TenantContext, key: str, value: Any, ttl_s: float | None = None) -> None: ...
