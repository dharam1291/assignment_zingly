"""HTTP host for the MCP server: ``/{tenant}/mcp`` per tenant plus an ops API under ``/admin``.

Run: ``uvicorn mcp_server.app:app --port 8100`` (env ZINGLY_TENANTS_CONFIG, ZINGLY_TRACE_FILE)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException

from zingly_core import TenantConfigStore, TenantContext, tracing

from mcp_server.runtime import Runtimes
from mcp_server.server import build_server

PROTOTYPE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = PROTOTYPE_ROOT / "config" / "tenants.yml"


def load_store() -> TenantConfigStore:
    return TenantConfigStore.from_file(os.environ.get("ZINGLY_TENANTS_CONFIG", DEFAULT_CONFIG))


def configure_tracing(store: TenantConfigStore, service: str) -> None:
    path = os.environ.get("ZINGLY_TRACE_FILE")
    if path is None:
        path = str(PROTOTYPE_ROOT / store.platform("trace_file", ".run/traces.jsonl"))
    tracing.configure(service, sink_path=path)


def create_app(store: TenantConfigStore | None = None, http: httpx.AsyncClient | None = None,
               drain_interval_s: float = 2.0) -> FastAPI:
    store = store or load_store()
    client = http or httpx.AsyncClient(limits=httpx.Limits(max_connections=200))
    runtimes = Runtimes(store, client)
    servers = {t: build_server(t, runtimes) for t in store.tenant_ids}
    mounted = {t: s.streamable_http_app() for t, s in servers.items()}  # creates session managers

    async def drain_loop() -> None:
        while True:
            await asyncio.sleep(drain_interval_s)
            await runtimes.drain_deferred()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with contextlib.AsyncExitStack() as stack:
            for server in servers.values():
                await stack.enter_async_context(server.session_manager.run())
            task = asyncio.create_task(drain_loop())
            try:
                yield
            finally:
                task.cancel()
                if http is None:
                    await client.aclose()

    app = FastAPI(title="Zingly MCP server", lifespan=lifespan)
    app.state.runtimes = runtimes

    def tenant(tenant_id: str):
        if tenant_id not in runtimes.by_tenant:
            raise HTTPException(404, "unknown tenant")
        return runtimes[tenant_id]

    @app.get("/health")
    async def health():
        return {"ok": True, "endpoints": {t: f"/{t}/mcp" for t in store.tenant_ids}}

    @app.get("/admin/stats")
    async def stats():
        return {t: rt.stats() for t, rt in runtimes.by_tenant.items()}

    @app.get("/admin/{tenant_id}/health")
    async def tenant_health(tenant_id: str):
        rt = tenant(tenant_id)
        return {"tenant_id": tenant_id, "breaker": rt.breaker.state, "pending_deferred": len(rt.deferred.pending())}

    @app.post("/admin/{tenant_id}/prewarm")
    async def prewarm(tenant_id: str, body: dict, traceparent: str | None = Header(None)):
        """Disruption event: pre-warm the saved copy (forwarded by the voice agent's webhook)."""
        rt = tenant(tenant_id)
        with tracing.continue_trace(traceparent):
            return await rt.tools.prewarm(TenantContext(tenant_id, "disruption-worker"), body["flight"].upper())

    @app.post("/admin/{tenant_id}/protection")
    async def protection(tenant_id: str, body: dict):
        """Demo switch: lanes and saved copy off, every call straight to the PSS."""
        rt = tenant(tenant_id)
        rt.tools.cfg.protection_enabled = bool(body.get("enabled", True))
        return {"tenant_id": tenant_id, "protection_enabled": rt.tools.cfg.protection_enabled}

    @app.post("/admin/{tenant_id}/lanes/pause")
    async def pause_lanes(tenant_id: str, body: dict):
        """Demo/ops: treat lanes as saturated for N seconds (shows the per-lane fallbacks)."""
        lanes, seconds = body.get("lanes", ["P0"]), float(body.get("seconds", 10))
        tenant(tenant_id).admission.pause(lanes, seconds)
        return {"tenant_id": tenant_id, "paused": lanes, "seconds": seconds}

    @app.post("/admin/{tenant_id}/reset")
    async def reset(tenant_id: str):
        """Fresh lanes, saved copy, breaker and deferred queue for this tenant."""
        tenant(tenant_id)
        runtimes.reset(tenant_id)
        return {"tenant_id": tenant_id, "reset": True}

    for tenant_id, sub_app in mounted.items():
        app.mount(f"/{tenant_id}", sub_app)
    return app


def _app() -> FastAPI:
    store = load_store()
    configure_tracing(store, "mcp-server")
    return create_app(store)


app = _app() if os.environ.get("ZINGLY_NO_APP") != "1" else None
