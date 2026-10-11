"""Run the Zingly MCP server.

    python -m mcp_server --stdio --tenant atlantica      # for Codex / Claude Desktop / Inspector
    python -m mcp_server --http --port 8100              # all tenants, /{tenant}/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx
import uvicorn


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--stdio", action="store_true", help="serve one tenant over stdio")
    mode.add_argument("--http", action="store_true", help="serve every tenant over Streamable HTTP (default)")
    p.add_argument("--tenant", default=os.environ.get("ZINGLY_TENANT", "atlantica"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    args = p.parse_args()

    os.environ["ZINGLY_NO_APP"] = "1"  # build the app explicitly below
    from mcp_server.app import configure_tracing, create_app, load_store
    from mcp_server.runtime import Runtimes
    from mcp_server.server import build_server

    store = load_store()
    if args.stdio:
        configure_tracing(store, "mcp-server-stdio")
        if args.tenant not in store.tenant_ids:
            print(f"unknown tenant {args.tenant}; known: {store.tenant_ids}", file=sys.stderr)
            return 2

        async def run_stdio() -> None:
            async with httpx.AsyncClient() as http:
                server = build_server(args.tenant, Runtimes(store, http))
                await server.run_stdio_async()

        asyncio.run(run_stdio())
        return 0

    configure_tracing(store, "mcp-server")
    uvicorn.run(create_app(store), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
