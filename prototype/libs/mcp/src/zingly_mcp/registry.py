from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from zingly_core import IdentityLevel, TenantContext

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


Handler = Callable[[TenantContext, dict], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    lane: str
    handler: Handler = field(repr=False)


class ToolRegistry:
    """Per-tenant registry. ``call`` enforces the guardrail before any handler runs."""

    def __init__(self, guard: GuardPort):
        self._guard = guard
        self._tools: dict[str, Tool] = {}
        self.audit: list[dict] = []

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict]:
        """MCP ``tools/list`` shape."""
        return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                for t in self._tools.values()]

    async def call(self, ctx: TenantContext, name: str, args: dict, level: IdentityLevel) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            result = ToolResult("denied", detail=f"unknown tool {name}", source="none")
        else:
            decision = self._guard.check(name, level)
            if not decision.allowed:
                result = ToolResult("denied", detail=decision.reason, source="none")
            else:
                result = await tool.handler(ctx, args)
        self.audit.append({"conversation_id": ctx.conversation_id, "tool": name, "level": level.label,
                           "status": result.status, "source": result.source})
        del self.audit[:-1000]
        return result
