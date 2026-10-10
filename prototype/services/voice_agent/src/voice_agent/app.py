"""Genesys-facing gateway (design §2 step 3, §5 capacity check, §8 interfaces).

Run: ``uvicorn voice_agent.app:app --port 8080``  (env ZINGLY_TENANTS_CONFIG)

Stubbed for the prototype: OAuth client-credentials on these endpoints and SIP/LiveKit
rooms (the room id is returned so the contract is visible).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from zingly_core import TenantConfigStore, TenantContext, TenantNotFound

from voice_agent.conversation import AGENT_HANDOVER, IN_PROGRESS, Session, handle_turn, new_session
from voice_agent.runtime import Platform

DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "tenants.toml"


def create_app(config_path: str | Path | None = None, http: httpx.AsyncClient | None = None,
               drain_interval_s: float = 2.0) -> FastAPI:
    store = TenantConfigStore.from_file(config_path or os.environ.get("ZINGLY_TENANTS_CONFIG", DEFAULT_CONFIG))
    client = http or httpx.AsyncClient(limits=httpx.Limits(max_connections=200))
    platform = Platform(store, client)
    sessions: dict[str, Session] = {}
    by_call: dict[tuple[str, str], str] = {}
    contexts: dict[str, dict] = {}

    async def drain_deferred() -> None:
        while True:
            await asyncio.sleep(drain_interval_s)
            for rt in platform.runtimes.values():
                await rt.deferred.drain(rt.tools.commit_deferred)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(drain_deferred())
        yield
        task.cancel()
        if http is None:
            await client.aclose()

    app = FastAPI(title="Zingly Voice Agent", lifespan=lifespan)
    app.state.platform = platform
    app.state.sessions = sessions

    def resolve(tenant_id: str | None, dialed_number: str | None) -> str:
        try:
            return store.resolve(tenant_id=tenant_id, dialed_number=dialed_number)
        except TenantNotFound:
            raise HTTPException(404, "unknown tenant or dialed number")

    def active(tenant_id: str) -> int:
        return sum(1 for s in sessions.values() if s.ctx.tenant_id == tenant_id and s.status == IN_PROGRESS)

    @app.get("/health")
    async def health():
        return {"ok": True, "tenants": store.tenant_ids}

    @app.get("/v1/capacity")
    async def capacity(tenant_id: str | None = None, dialed_number: str | None = None):
        """Genesys asks before routing each call to the bot. 'accept: false' -> human queue."""
        rt = platform.runtime(resolve(tenant_id, dialed_number))
        n, limit = active(rt.tenant_id), rt.gateway.max_concurrent_sessions
        reasons = []
        if n >= limit:
            reasons.append("at_capacity")
        if rt.breaker.state == "open":
            reasons.append("reservation_system_unhealthy")
        return {"tenant_id": rt.tenant_id, "accept": not reasons, "reasons": reasons,
                "active_sessions": n, "max_sessions": limit, "pss_breaker": rt.breaker.state}

    @app.post("/v1/conversations")
    async def create_conversation(body: dict):
        """Idempotent on call_id: a Genesys retry gets the same conversation back."""
        rt = platform.runtime(resolve(body.get("tenant_id"), body.get("dialed_number")))
        call_id = str(body.get("call_id") or "")
        if not call_id:
            raise HTTPException(400, "call_id is required")
        existing = by_call.get((rt.tenant_id, call_id))
        if existing:
            s = sessions[existing]
            return {"conversation_id": existing, "tenant_id": rt.tenant_id, "replayed": True,
                    "conversation_status": s.status}
        if active(rt.tenant_id) >= rt.gateway.max_concurrent_sessions:
            return JSONResponse({"error": "at_capacity"}, status_code=503)
        session, welcome = new_session(rt, call_id, str(body.get("caller_number", "")))
        sessions[session.ctx.conversation_id] = session
        by_call[(rt.tenant_id, call_id)] = session.ctx.conversation_id
        return {"conversation_id": session.ctx.conversation_id, "tenant_id": rt.tenant_id,
                "room": {"room_id": f"lk-{rt.tenant_id}-{session.ctx.conversation_id}", "transport": "simulated"},
                "reply": welcome, "conversation_status": IN_PROGRESS}

    @app.post("/v1/conversations/{conversation_id}/utterances")
    async def utterance(conversation_id: str, body: dict):
        session = sessions.get(conversation_id)
        if not session:
            raise HTTPException(404, "conversation not found")
        rt = platform.runtime(session.ctx.tenant_id)
        result = await handle_turn(rt, session, body)
        if result["conversation_status"] == AGENT_HANDOVER and result["handover"]:
            contexts[result["handover"]["context_ref"]] = {"tenant_id": rt.tenant_id, "session": session}
        return result

    @app.get("/v1/handover-context/{context_ref}")
    async def handover_context(context_ref: str, tenant_id: str):
        """Genesys Data Action (OAuth in production): full context for the agent desktop."""
        item = contexts.get(context_ref)
        if not item or item["tenant_id"] != tenant_id:
            raise HTTPException(404, "not found")
        s: Session = item["session"]
        return {"handover": s.handover, "booking": s.agent_state.booking,
                "transcript": [f"{who}: {text}" for who, text in s.transcript]}

    @app.post("/v1/events/disruption")
    async def disruption(request: Request, x_zingly_signature: str | None = Header(None)):
        """Signed webhook from the airline's disruption feed: pre-warm the saved copy."""
        raw = await request.body()
        body = await request.json()
        rt = platform.runtime(resolve(body.get("tenant_id"), None))
        secret = os.environ.get(rt.gateway.webhook_secret_env, "") if rt.gateway.webhook_secret_env else ""
        if secret:
            expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not x_zingly_signature or not hmac.compare_digest(expected, x_zingly_signature):
                raise HTTPException(401, "bad signature")
        return await rt.tools.prewarm(TenantContext(rt.tenant_id, "disruption-worker"), body["flight"])

    @app.get("/v1/admin/stats")
    async def stats():
        out = {}
        for t, rt in platform.runtimes.items():
            tenant_sessions = [s for s in sessions.values() if s.ctx.tenant_id == t]
            statuses: dict[str, int] = {}
            for s in tenant_sessions:
                statuses[s.status] = statuses.get(s.status, 0) + 1
            tool_sources: dict[str, int] = {}
            for a in rt.registry.audit:
                key = f"{a['tool']}:{a['status']}:{a['source']}"
                tool_sources[key] = tool_sources.get(key, 0) + 1
            out[t] = {"sessions": statuses, "lanes": rt.admission.stats(), "saved_copy": rt.saved_copy.stats(t),
                      "deferred_commits": rt.deferred.summary(), "breaker": rt.breaker.state,
                      "protection_enabled": rt.tools.cfg.protection_enabled, "tool_results": tool_sources}
        return out

    @app.post("/v1/admin/tenants/{tenant_id}/protection")
    async def protection(tenant_id: str, body: dict):
        """Demo switch for the load test: turn lanes + saved copy off to show the difference."""
        rt = platform.runtime(resolve(tenant_id, None))
        rt.tools.cfg.protection_enabled = bool(body.get("enabled", True))
        return {"tenant_id": tenant_id, "protection_enabled": rt.tools.cfg.protection_enabled}

    return app


app = create_app()
