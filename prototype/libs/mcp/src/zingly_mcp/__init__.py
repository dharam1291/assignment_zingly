"""Reservation tools behind the MCP server: the one door from Zingly to the airline's systems.

This library is transport-free: :class:`ToolRegistry` holds the tools and enforces the guard
and booking scope; the ``mcp_server`` service publishes it over the Model Context Protocol
(Streamable HTTP per tenant, and stdio).

This module owns its *ports* (``ports.py``): what it needs from the policy engine and the
saved copy. It never imports those libraries; the service plugs them in.
"""

from zingly_mcp.backend import (BackendError, BackendUnavailable, Conflict, HttpPssBackend, NotFound,
                                PssBackend, RateLimited)
from zingly_mcp.config import McpConfig
from zingly_mcp.deferred import DeferredCommits
from zingly_mcp.registry import Tool, ToolRegistry, ToolResult
from zingly_mcp.tools import ReservationTools, build_registry, idempotency_key, mask_ref

__all__ = [
    "BackendError", "BackendUnavailable", "Conflict", "HttpPssBackend", "NotFound", "PssBackend",
    "RateLimited", "McpConfig", "DeferredCommits", "Tool", "ToolRegistry", "ToolResult",
    "ReservationTools", "build_registry", "idempotency_key", "mask_ref",
]
