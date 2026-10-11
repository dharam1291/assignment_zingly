"""MCP protocol surface: one FastMCP server per tenant, all backed by the same registry code.

Identity and trace context travel out of band, never through the model:
  1. request ``_meta``: ``identity_token``, ``traceparent``, ``conversation_id`` (voice agent)
  2. HTTP headers ``X-Identity-Token`` / ``traceparent`` (any Streamable HTTP client)
  3. environment ``ZINGLY_IDENTITY_TOKEN`` (stdio clients such as Codex)
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from pydantic import BaseModel, Field

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from zingly_core import TenantContext, tracing

from mcp_server.runtime import Runtimes


class ToolOutcome(BaseModel):
    """Every tool returns the same envelope, so a client always knows where an answer came from."""

    status: str = Field(description="ok | stale | deferred | denied | not_found | conflict | unavailable")
    data: Any = Field(default=None, description="Tool-specific payload")
    source: str = Field(default="pss", description="pss | saved_copy | coalesced | none")
    as_of: float | None = Field(default=None, description="Epoch seconds when served from the saved copy")
    detail: str = Field(default="", description="Why, when status is not ok")


def _meta(ctx: Context) -> dict[str, Any]:
    meta = getattr(ctx.request_context, "meta", None)
    return dict(meta.model_extra or {}) if meta is not None else {}


def _header(ctx: Context, name: str) -> str | None:
    request = getattr(ctx.request_context, "request", None)
    return request.headers.get(name) if request is not None else None


def build_server(tenant_id: str, runtimes: Runtimes, allowed_hosts: list[str] | None = None) -> FastMCP:
    display = runtimes.store.meta(tenant_id)["display_name"]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts or ["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    mcp = FastMCP(
        name=f"zingly-reservations-{tenant_id}",
        instructions=(f"Reservation tools for {display}. Flight status and alternatives are public. "
                      "lookup_caller_id gives only a masked summary. verify_booking checks a reference "
                      "and surname. get_booking and rebook need a VERIFIED identity token for that booking, "
                      "issued by the Zingly Auth service and sent in _meta.identity_token, the "
                      "X-Identity-Token header, or ZINGLY_IDENTITY_TOKEN for stdio."),
        stateless_http=True, json_response=True, streamable_http_path="/mcp", transport_security=security,
        log_level="WARNING",
    )

    async def invoke(ctx: Context, name: str, args: dict) -> ToolOutcome:
        rt = runtimes[tenant_id]
        meta = _meta(ctx)
        token = (meta.get("identity_token") or _header(ctx, "x-identity-token")
                 or os.environ.get("ZINGLY_IDENTITY_TOKEN"))
        traceparent = meta.get("traceparent") or _header(ctx, "traceparent")
        with tracing.continue_trace(traceparent):
            claims, problem = rt.identify(token)
            conversation = meta.get("conversation_id") or claims.conversation_id or "mcp-client"
            result = await rt.registry.call(TenantContext(tenant_id, conversation), name, args, claims)
        if problem and result.status == "denied":
            result.detail = f"{result.detail}; {problem}"
        return ToolOutcome(**result.to_dict())

    read_only = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

    @mcp.tool(description=_desc(runtimes, tenant_id, "get_flight_status"), annotations=read_only)
    async def get_flight_status(flight: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "get_flight_status", {"flight": flight})

    @mcp.tool(description=_desc(runtimes, tenant_id, "get_alternatives"), annotations=read_only)
    async def get_alternatives(origin: str, destination: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "get_alternatives", {"origin": origin, "destination": destination})

    @mcp.tool(description=_desc(runtimes, tenant_id, "lookup_caller_id"), annotations=read_only)
    async def lookup_caller_id(phone: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "lookup_caller_id", {"phone": phone})

    @mcp.tool(description=_desc(runtimes, tenant_id, "verify_booking"), annotations=read_only)
    async def verify_booking(booking_ref: str, surname: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "verify_booking", {"booking_ref": booking_ref, "surname": surname})

    @mcp.tool(description=_desc(runtimes, tenant_id, "get_booking"), annotations=read_only)
    async def get_booking(booking_ref: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "get_booking", {"booking_ref": booking_ref})

    @mcp.tool(description=_desc(runtimes, tenant_id, "rebook"),
              annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                                          openWorldHint=True))
    async def rebook(booking_ref: str, from_flight: str, to_flight: str, ctx: Context) -> ToolOutcome:
        return await invoke(ctx, "rebook", {"booking_ref": booking_ref, "from_flight": from_flight,
                                            "to_flight": to_flight})

    @mcp.resource(f"zingly://{tenant_id}/admission", name="admission-status", mime_type="application/json",
                  description="Live priority-lane, saved-copy, breaker and deferred-commit counters.")
    def admission_status() -> str:
        return json.dumps(runtimes[tenant_id].stats(), indent=2)

    return mcp


def _desc(runtimes: Runtimes, tenant_id: str, tool: str) -> str:
    for t in runtimes[tenant_id].registry.tools:
        if t.name == tool:
            return f"{t.description} Priority lane {t.lane}."
    raise KeyError(tool)


ServerFactory = Callable[[str], FastMCP]
