"""Zingly MCP server (design: domain agents reach the airline's systems only through it).

* Model Context Protocol via the official ``mcp`` SDK: Streamable HTTP at ``/{tenant}/mcp``
  (one endpoint per tenant, one process) and stdio (``python -m mcp_server --stdio``).
* The policy engine runs inside it - guard, booking scope, priority lanes, circuit breaker -
  together with the saved copy, so every client gets the same protection: the voice agent,
  Codex, or the MCP Inspector.
"""
