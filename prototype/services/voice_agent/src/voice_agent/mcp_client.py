"""MCP client adapter: implements the agents' ``ToolPort`` and auth's ``BookingLookupPort`` by
calling the Zingly MCP server over Streamable HTTP with the official SDK.

Identity and trace context go in the request ``_meta``; they never enter tool arguments."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zingly_core import TenantContext, tracing


def _unavailable(detail: str) -> SimpleNamespace:
    return SimpleNamespace(status="unavailable", data=None, source="none", as_of=None, detail=detail)


class McpToolClient:
    def __init__(self, base_url: str, tenant_id: str, http: httpx.AsyncClient):
        self.url = f"{base_url.rstrip('/')}/{tenant_id}/mcp"
        self._http = http

    async def call(self, ctx: TenantContext, name: str, args: dict, identity_token: str | None = None) -> Any:
        with tracing.span("mcp.call_tool", "mcp-client", tool=name, endpoint=self.url,
                          identity="token" if identity_token else "none") as sp:
            meta = {"traceparent": sp.traceparent, "conversation_id": ctx.conversation_id}
            if identity_token:
                meta["identity_token"] = identity_token
            try:
                async with streamable_http_client(self.url, http_client=self._http, terminate_on_close=False) as (r, w, _):
                    async with ClientSession(r, w) as session:
                        await session.initialize()
                        result = await session.call_tool(name, args, meta=meta)
            except Exception as exc:  # network, protocol or server failure: the agent degrades safely
                sp.status = "error"
                sp.set(error=type(exc).__name__)
                return _unavailable(f"mcp server unreachable ({type(exc).__name__})")
            if result.isError:
                text = result.content[0].text if result.content else "tool error"
                sp.status = "error"
                return _unavailable(text[:200])
            out = result.structuredContent or json.loads(result.content[0].text)
            sp.set(status=out["status"], source=out["source"])
            return SimpleNamespace(**out)


class AuthLookupAdapter:
    """auth.BookingLookupPort -> MCP tools ``lookup_caller_id`` and ``verify_booking``."""

    def __init__(self, tools: McpToolClient):
        self._tools = tools

    async def caller_id_hint(self, ctx: TenantContext, phone: str) -> Any:
        return await self._tools.call(ctx, "lookup_caller_id", {"phone": phone})

    async def check_booking(self, ctx: TenantContext, booking_ref: str, surname: str) -> Any:
        return await self._tools.call(ctx, "verify_booking", {"booking_ref": booking_ref, "surname": surname})
