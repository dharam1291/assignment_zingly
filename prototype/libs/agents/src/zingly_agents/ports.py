"""What agents need from other modules (structural types)."""

from __future__ import annotations

from typing import Any, Protocol

from zingly_core import TenantContext


class ToolPort(Protocol):
    """MCP ``tools/call``. Result exposes .status .data .source .as_of .detail.

    ``identity_token`` is the signed assertion from auth; it travels in MCP ``_meta``, never in
    the tool arguments, so a model can neither see nor forge it."""

    async def call(self, ctx: TenantContext, name: str, args: dict, identity_token: str | None = None) -> Any: ...


class AuthPort(Protocol):
    """Result exposes .level .outcome .booking .masked .verified_by .attempts_left .data_as_of"""

    async def identify_by_caller_id(self, ctx: TenantContext, caller_number: str) -> Any: ...

    async def verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> Any: ...
