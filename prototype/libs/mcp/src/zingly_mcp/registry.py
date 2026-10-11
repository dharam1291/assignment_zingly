"""Transport-independent tool registry. ``mcp_server`` exposes it over the MCP protocol
(Streamable HTTP and stdio); tests call it directly."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from zingly_core import IdentityClaims, TenantContext, tracing

from zingly_mcp.ports import GuardPort

# ok | stale | deferred | denied | not_found | conflict | unavailable
Status = str


@dataclass
class ToolResult:
    status: Status
    data: Any = None
    source: str = "pss"            # pss | saved_copy | coalesced | none
    as_of: float | None = None     # epoch seconds, set when the answer came from the saved copy
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status in ("ok", "stale")

    def to_dict(self) -> dict:
        return asdict(self)


Handler = Callable[[TenantContext, dict], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    lane: str
    handler: Handler = field(repr=False)
    booking_scoped: bool = False    # may only act on the booking named in the identity token
    read_only: bool = True


class ToolRegistry:
    """Per-tenant registry. ``call`` runs the policy guard and the booking-scope check before
    any handler, so every client (voice agent, Codex, MCP Inspector) gets the same rules."""

    def __init__(self, guard: GuardPort):
        self._guard = guard
        self._tools: dict[str, Tool] = {}
        self.audit: list[dict] = []

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def list_tools(self) -> list[dict]:
        """MCP ``tools/list`` shape."""
        return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                for t in self._tools.values()]

    async def call(self, ctx: TenantContext, name: str, args: dict, identity: IdentityClaims) -> ToolResult:
        with tracing.span("mcp.tool", "mcp-server", tool=name, tenant=ctx.tenant_id,
                          level=identity.level.label) as sp:
            result = await self._call(ctx, name, args, identity)
            sp.set(status=result.status, source=result.source, detail=result.detail or None)
        self.audit.append({"conversation_id": ctx.conversation_id, "tool": name, "level": identity.level.label,
                           "status": result.status, "source": result.source})
        del self.audit[:-2000]
        return result

    async def _call(self, ctx: TenantContext, name: str, args: dict, identity: IdentityClaims) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult("denied", detail=f"unknown tool {name}", source="none")
        decision = self._guard.check(name, identity.level)
        if not decision.allowed:
            return ToolResult("denied", detail=decision.reason, source="none")
        if tool.booking_scoped:
            ref = str(args.get("booking_ref", "")).replace(" ", "").upper()
            if not identity.booking_ref or ref != identity.booking_ref.upper():
                return ToolResult("denied", detail="booking is not the one this caller verified", source="none")
        return await tool.handler(ctx, args)
