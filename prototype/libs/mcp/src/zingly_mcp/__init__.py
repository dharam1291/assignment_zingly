"""MCP server: the one door from Zingly agents to the airline's systems (design §2 step 8).

Tools are described MCP-style (name, description, JSON input schema) and run in process.
A real MCP transport (stdio / streamable HTTP) would wrap :class:`ToolRegistry` unchanged.

This module owns its *ports* (``ports.py``): what it needs from the policy engine and the
saved copy. It never imports those libraries; the service plugs them in.
"""

from zingly_mcp.backend import (BackendError, BackendUnavailable, Conflict, HttpPssBackend, NotFound,
                                PssBackend, RateLimited)
from zingly_mcp.config import McpConfig
from zingly_mcp.deferred import DeferredCommits
from zingly_mcp.registry import Tool, ToolRegistry, ToolResult
from zingly_mcp.tools import ReservationTools, build_registry

__all__ = [
    "BackendError", "BackendUnavailable", "Conflict", "HttpPssBackend", "NotFound", "PssBackend",
    "RateLimited", "McpConfig", "DeferredCommits", "Tool", "ToolRegistry", "ToolResult",
    "ReservationTools", "build_registry",
]
