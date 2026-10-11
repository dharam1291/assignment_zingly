"""Shared test harness: the whole southbound -> MCP server -> voice agent stack in one process.

A routing transport sends each host:port to its ASGI app, so the voice agent really talks
MCP (Streamable HTTP, official SDK) to the MCP server, which really talks HTTP to the PSS.
"""

from __future__ import annotations

import contextlib
import os

import httpx
import pytest

os.environ.setdefault("ZINGLY_NO_APP", "1")  # import service modules without building default apps

PSS = "127.0.0.1:9001"
MCP = "127.0.0.1:8100"
VA = "127.0.0.1:8080"


class RoutingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.routes: dict[str, httpx.ASGITransport] = {}

    def add(self, hostport: str, app) -> None:
        self.routes[hostport] = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.routes[f"{request.url.host}:{request.url.port}"].handle_async_request(request)


@contextlib.asynccontextmanager
async def running_stack(pss_rps: int = 5):
    from mcp_server.app import create_app as create_mcp, load_store
    from mock_pss.app import create_app as create_pss
    from voice_agent.app import create_app as create_va

    router = RoutingTransport()
    http = httpx.AsyncClient(transport=router, timeout=30)
    store = load_store()
    pss_app = create_pss(rps=pss_rps, latency_ms=(0, 0))
    mcp_app = create_mcp(store, http, drain_interval_s=3600)
    va_app = create_va(store, http)
    router.add(PSS, pss_app)
    router.add(MCP, mcp_app)
    router.add(VA, va_app)
    async with mcp_app.router.lifespan_context(mcp_app):
        yield {"http": http, "va": f"http://{VA}", "mcp": f"http://{MCP}", "pss": f"http://{PSS}",
               "va_app": va_app, "mcp_app": mcp_app, "pss_app": pss_app}
    await http.aclose()


@pytest.fixture
def stack():
    return running_stack
