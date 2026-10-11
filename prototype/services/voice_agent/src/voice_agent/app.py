"""Genesys-facing gateway of the voice agent.

Run: ``uvicorn voice_agent.app:app --port 8080`` (env ZINGLY_TENANTS_CONFIG, ZINGLY_TRACE_FILE)

Stubbed for the prototype: OAuth client credentials on these endpoints, and SIP/LiveKit rooms
(the room id is returned so the contract is visible).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from zingly_core import TenantConfigStore, TenantNotFound, tracing

from voice_agent.conversation import AGENT_HANDOVER, IN_PROGRESS, Session, handle_turn, new_session
from voice_agent.runtime import Platform

PROTOTYPE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = PROTOTYPE_ROOT / "config" / "tenants.yml"


def load_store() -> TenantConfigStore:
    return TenantConfigStore.from_file(os.environ.get("ZINGLY_TENANTS_CONFIG", DEFAULT_CONFIG))


def trace_file(store: TenantConfigStore) -> str:
    return os.environ.get("ZINGLY_TRACE_FILE") or str(PROTOTYPE_ROOT / store.platform("trace_file", ".run/traces.jsonl"))


def create_app(store: TenantConfigStore | None = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    store = store or load_store()
    client = http or httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=500))
    platform = Platform(store, client)
    mcp_admin = store.platform("mcp_server_url", "http://127.0.0.1:8100").rstrip("/") + "/admin"
    sessions: dict[str, Session] = {}
    by_call: dict[tuple[str, str], str] = {}
    contexts: dict[str, dict] = {}

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
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

    def expire_idle() -> None:
        """Drop idle conversations (a session store with TTLs does this in production)."""
        now = time.time()
        for cid, s in list(sessions.items()):
            rt = platform.runtime(s.ctx.tenant_id)
            if now - s.last_activity > rt.gateway.session_idle_timeout_s:
                sessions.pop(cid, None)
                by_call.pop((s.ctx.tenant_id, s.ctx.call_id), None)

    def active(tenant_id: str) -> int:
        return sum(1 for s in sessions.values() if s.ctx.tenant_id == tenant_id and s.status == IN_PROGRESS)

    async def mcp_health(tenant_id: str) -> dict:
        try:
            r = await client.get(f"{mcp_admin}/{tenant_id}/health", timeout=1.0)
            return r.json() if r.status_code == 200 else {"breaker": "unknown"}
        except httpx.HTTPError:
            return {"breaker": "unreachable"}

    @app.get("/health")
    async def health():
        return {"ok": True, "tenants": store.tenant_ids}

    @app.get("/v1/capacity")
    async def capacity(tenant_id: str | None = None, dialed_number: str | None = None,
                       traceparent: str | None = Header(None)):
        """Genesys asks before routing each call to the bot. ``accept: false`` -> human queue."""
        rt = platform.runtime(resolve(tenant_id, dialed_number))
        with tracing.continue_trace(traceparent), tracing.span("gateway.capacity_check", "gateway",
                                                                tenant=rt.tenant_id) as sp:
            n, limit = active(rt.tenant_id), rt.gateway.max_concurrent_sessions
            mcp = await mcp_health(rt.tenant_id)
            reasons = []
            if n >= limit:
                reasons.append("at_capacity")
            if mcp.get("breaker") == "open":
                reasons.append("reservation_system_unhealthy")
            if mcp.get("breaker") == "unreachable":
                reasons.append("mcp_server_unreachable")
            sp.set(accept=not reasons, active=n, limit=limit, breaker=mcp.get("breaker"),
                   reasons=",".join(reasons) or None)
        return {"tenant_id": rt.tenant_id, "accept": not reasons, "reasons": reasons,
                "active_sessions": n, "max_sessions": limit, "pss_breaker": mcp.get("breaker")}

    @app.post("/v1/conversations")
    async def create_conversation(body: dict, traceparent: str | None = Header(None)):
        """Idempotent on call_id: a Genesys retry gets the same conversation back."""
        rt = platform.runtime(resolve(body.get("tenant_id"), body.get("dialed_number")))
        expire_idle()
        call_id = str(body.get("call_id") or "")
        if not call_id:
            raise HTTPException(400, "call_id is required")
        with tracing.continue_trace(traceparent), tracing.span("gateway.create_conversation", "gateway",
                                                                tenant=rt.tenant_id, call_id=call_id) as sp:
            existing = by_call.get((rt.tenant_id, call_id))
            if existing:
                sp.set(replayed=True)
                return {"conversation_id": existing, "tenant_id": rt.tenant_id, "replayed": True,
                        "conversation_status": sessions[existing].status}
            if active(rt.tenant_id) >= rt.gateway.max_concurrent_sessions:
                sp.set(rejected="at_capacity")
                return JSONResponse({"error": "at_capacity"}, status_code=503)
            with tracing.span("ai_router.welcome", "ai-router"):
                session, welcome = new_session(rt, call_id, str(body.get("caller_number", "")))
            sessions[session.ctx.conversation_id] = session
            by_call[(rt.tenant_id, call_id)] = session.ctx.conversation_id
            sp.set(conversation_id=session.ctx.conversation_id, audio_id=welcome["audio_id"])
            return {"conversation_id": session.ctx.conversation_id, "tenant_id": rt.tenant_id,
                    "room": {"room_id": f"lk-{rt.tenant_id}-{session.ctx.conversation_id}", "transport": "simulated"},
                    "reply": welcome, "conversation_status": IN_PROGRESS, "trace_id": sp.trace_id}

    @app.post("/v1/conversations/{conversation_id}/utterances")
    async def utterance(conversation_id: str, body: dict, traceparent: str | None = Header(None)):
        session = sessions.get(conversation_id)
        if not session:
            raise HTTPException(404, "conversation not found")
        rt = platform.runtime(session.ctx.tenant_id)
        with tracing.continue_trace(traceparent), tracing.span(
                "gateway.turn", "gateway", tenant=rt.tenant_id, conversation_id=conversation_id,
                turn=sum(1 for who, _ in session.transcript if who == "caller") + 1) as sp:
            result = await handle_turn(rt, session, body)
            sp.set(status=result["conversation_status"], path=result["turn_path"], agent=result["agent"],
                   identity=result["identity_level"])
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
    async def disruption(request: Request, x_zingly_signature: str | None = Header(None),
                         traceparent: str | None = Header(None)):
        """Signed webhook from the airline's disruption feed -> pre-warm the saved copy on the MCP server."""
        raw = await request.body()
        body = json.loads(raw)
        rt = platform.runtime(resolve(body.get("tenant_id"), None))
        secret = os.environ.get(rt.gateway.webhook_secret_env, "") if rt.gateway.webhook_secret_env else ""
        if secret:
            expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not x_zingly_signature or not hmac.compare_digest(expected, x_zingly_signature):
                raise HTTPException(401, "bad signature")
        with tracing.continue_trace(traceparent), tracing.span("gateway.disruption_event", "gateway",
                                                                tenant=rt.tenant_id, flight=body["flight"]) as sp:
            r = await client.post(f"{mcp_admin}/{rt.tenant_id}/prewarm", json={"flight": body["flight"]},
                                  headers={"traceparent": sp.traceparent}, timeout=60)
        return r.json()

    @app.get("/v1/admin/stats")
    async def stats():
        try:
            mcp = (await client.get(f"{mcp_admin}/stats", timeout=2)).json()
        except httpx.HTTPError:
            mcp = {}
        out = {}
        for t in platform.runtimes:
            statuses: dict[str, int] = {}
            for s in sessions.values():
                if s.ctx.tenant_id == t:
                    statuses[s.status] = statuses.get(s.status, 0) + 1
            out[t] = {"sessions": statuses, "mcp_server": mcp.get(t, {})}
        return out

    @app.post("/v1/admin/tenants/{tenant_id}/max-sessions")
    async def set_max_sessions(tenant_id: str, body: dict):
        """Ops/demo: change the tenant's concurrent-session ceiling at runtime."""
        rt = platform.runtime(resolve(tenant_id, None))
        rt.gateway.max_concurrent_sessions = int(body["max_sessions"])
        return {"tenant_id": tenant_id, "max_sessions": rt.gateway.max_concurrent_sessions}

    @app.post("/v1/admin/reset")
    async def reset():
        """Demo: forget conversations and auth lockouts (fresh flows)."""
        sessions.clear()
        by_call.clear()
        contexts.clear()
        platform.runtimes = {t: type(rt).build(store, t, client) for t, rt in platform.runtimes.items()}
        return {"reset": True}

    @app.get("/v1/traces/{trace_id}")
    async def trace(trace_id: str):
        """Dev only: spans for one trace from the local collector file."""
        path = trace_file(store)
        if not os.path.exists(path):
            return {"spans": []}
        with open(path, encoding="utf-8") as fh:
            spans = [json.loads(line) for line in fh if trace_id in line]
        return {"spans": [s for s in spans if s["trace_id"] == trace_id]}

    return app


def _app() -> FastAPI:
    store = load_store()
    tracing.configure("voice-agent", sink_path=trace_file(store))
    return create_app(store)


app = _app() if os.environ.get("ZINGLY_NO_APP") != "1" else None
