"""Genesys simulator HTTP server (:8090): softphone + agent desktop UI and a JSON API.

Run: ``uvicorn genesys_sim.server:app --port 8090`` (env GENESYS_SIM_CONFIG, ZINGLY_TRACE_FILE)
"""

from __future__ import annotations

import os
import random
import time
import uuid
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from zingly_core import tracing

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE.parents[1] / "genesys.yml"


def load_config() -> dict:
    with open(os.environ.get("GENESYS_SIM_CONFIG", DEFAULT_CONFIG), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def create_app(config: dict | None = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    cfg = config or load_config()
    va = cfg["voice_agent_url"].rstrip("/")
    client = http or httpx.AsyncClient(timeout=60)
    calls: dict[str, dict] = {}
    app = FastAPI(title="Genesys simulator (northbound)")
    app.state.calls = calls

    def route_to_human(call: dict, reason: str, queue: str | None = None) -> None:
        queue = queue or cfg["fallback_queue"]
        wait = cfg["queues"].get(queue, 60)
        call.update(status="HUMAN_QUEUE", routed_to="human_queue", queue=queue, reason=reason,
                    estimated_wait_s=wait,
                    disposition="callback_offered" if wait > cfg["callback_after_s"] else "queued")

    @app.get("/health")
    async def health():
        return {"ok": True, "inbound_flows": list(cfg["inbound_flows"])}

    @app.post("/api/calls")
    async def start_call(body: dict):
        """Twilio delivers the call; the Genesys inbound flow decides bot or human."""
        dialed, caller = body.get("dialed", ""), body.get("caller", "")
        flow = cfg["inbound_flows"].get(dialed)
        if not flow:
            raise HTTPException(404, f"no inbound flow for {dialed}")
        call_id = f"gen-{uuid.uuid4().hex[:10]}"
        call = {"call_id": call_id, "dialed": dialed, "caller": caller, "flow": flow["name"],
                "started_at": time.time(), "transcript": [], "turns": [], "screen_pop": None}
        calls[call_id] = call
        with tracing.span("genesys.inbound_flow", "genesys", flow=flow["name"], call_id=call_id,
                          caller=tracing.mask(caller, 3)) as sp:
            call["trace_id"] = sp.trace_id
            pct = int(body.get("bot_percent", flow.get("bot_percent", 100)))
            if random.randint(1, 100) > pct:
                call.update(status="LEGACY_IVR", routed_to="legacy_ivr", reason=f"A/B split ({pct}% to bot)")
                sp.set(routed_to="legacy_ivr")
                return call
            headers = {"traceparent": sp.traceparent}
            try:
                cap = (await client.get(f"{va}/v1/capacity", params={"dialed_number": dialed}, headers=headers)).json()
            except httpx.HTTPError:
                cap = {"accept": False, "reasons": ["zingly_unreachable"]}
            call["capacity"] = cap
            if not cap.get("accept"):
                route_to_human(call, "capacity check: " + ",".join(cap.get("reasons", [])))
                sp.set(routed_to="human_queue", reason=call["reason"])
                return call
            try:
                r = await client.post(f"{va}/v1/conversations", headers=headers,
                                      json={"call_id": call_id, "dialed_number": dialed, "caller_number": caller})
            except httpx.HTTPError:
                r = None
            if r is None or r.status_code != 200:
                route_to_human(call, f"create conversation failed ({getattr(r, 'status_code', 'unreachable')})")
                sp.set(routed_to="human_queue", reason=call["reason"])
                return call
            conv = r.json()
            call.update(status="IN_BOT", routed_to="zingly", tenant_id=conv["tenant_id"],
                        conversation_id=conv["conversation_id"], room_id=conv["room"]["room_id"])
            call["transcript"].append({"who": "bot", "text": conv["reply"]["text"]})
            sp.set(routed_to="zingly", conversation_id=conv["conversation_id"])
        return call

    @app.post("/api/calls/{call_id}/say")
    async def say(call_id: str, body: dict):
        call = calls.get(call_id)
        if not call:
            raise HTTPException(404, "unknown call")
        if call["status"] != "IN_BOT":
            raise HTTPException(409, f"call is {call['status']}")
        text = str(body.get("text", ""))
        call["transcript"].append({"who": "caller", "text": text})
        with tracing.span("genesys.caller_turn", "genesys", call_id=call_id) as sp:
            r = await client.post(f"{va}/v1/conversations/{call['conversation_id']}/utterances",
                                  json={"text": text}, headers={"traceparent": sp.traceparent})
            turn = r.json()
            sp.set(status=turn["conversation_status"])
            if turn["conversation_status"] == "AGENT_HANDOVER":
                with tracing.span("genesys.route_to_agent", "genesys") as rs:
                    h = turn["handover"]
                    queue = h["routing"]["queue"]
                    wait = cfg["queues"].get(queue, 60)
                    callback = h["routing"]["callback_eligible"] and wait > cfg["callback_after_s"]
                    call.update(status="AGENT_HANDOVER", queue=queue, estimated_wait_s=wait,
                                disposition="callback_offered" if callback else "queued")
                    call["screen_pop"] = h
                    rs.set(queue=queue, wait_s=wait, disposition=call["disposition"])
            elif turn["conversation_status"] == "COMPLETED":
                call["status"] = "COMPLETED"
        turn["genesys_trace_id"] = sp.trace_id
        call["transcript"].append({"who": "bot", "text": turn["reply"]["text"]})
        call["turns"].append({"caller": text, "bot": turn["reply"]["text"], "path": turn["turn_path"],
                              "agent": turn["agent"], "identity": turn["identity_level"],
                              "latency_ms": turn["latency_ms"], "trace_id": sp.trace_id})
        return {"call": {k: v for k, v in call.items() if k not in ("transcript", "turns")}, "turn": turn}

    @app.get("/api/calls")
    async def list_calls():
        return [{k: call[k] for k in ("call_id", "dialed", "caller", "status") if k in call} for call in calls.values()]

    @app.get("/api/calls/{call_id}")
    async def get_call(call_id: str):
        if call_id not in calls:
            raise HTTPException(404, "unknown call")
        return calls[call_id]

    @app.get("/api/agent-desktop")
    async def agent_desktop():
        """Calls waiting for a human, with their screen-pop."""
        return [c for c in calls.values() if c["status"] in ("AGENT_HANDOVER", "HUMAN_QUEUE")]

    @app.post("/admin/flows/bot-percent")
    async def set_bot_percent(body: dict):
        cfg["inbound_flows"][body["dialed"]]["bot_percent"] = int(body["bot_percent"])
        return cfg["inbound_flows"][body["dialed"]]

    @app.get("/api/traces/{trace_id}")
    async def trace(trace_id: str):
        path = os.environ.get("ZINGLY_TRACE_FILE", "")
        spans = tracing.read_spans(path, trace_id)
        return {"trace_id": trace_id, "spans": spans, "tree": tracing.render_tree(spans)}

    @app.get("/", response_class=HTMLResponse)
    async def ui():
        return (HERE / "ui.html").read_text(encoding="utf-8")

    return app


tracing.configure("genesys")  # sink path from ZINGLY_TRACE_FILE, if set
app = create_app() if os.environ.get("ZINGLY_NO_APP") != "1" else None
