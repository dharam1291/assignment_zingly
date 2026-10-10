"""What agents need from other modules (structural types)."""

from __future__ import annotations

from typing import Any, Protocol

from zingly_core import IdentityLevel, TenantContext


class ToolPort(Protocol):
    """MCP tool call. Result exposes .status .data .source .as_of .detail"""

    async def call(self, ctx: TenantContext, name: str, args: dict, level: IdentityLevel) -> Any: ...


class AuthPort(Protocol):
    """Result exposes .level .outcome .booking .masked .verified_by .attempts_left .data_as_of"""

    async def identify_by_caller_id(self, ctx: TenantContext, caller_number: str) -> Any: ...

    async def verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> Any: ...
