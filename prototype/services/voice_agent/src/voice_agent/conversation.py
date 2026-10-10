"""One conversation turn: channel -> AI router -> supervisor/agent -> (handover)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from zingly_agents import AgentState, AgentTurn
from zingly_ai_router import AIRouter, RouterState
from zingly_channel import Outbound
from zingly_core import IdentityLevel, TenantContext
from zingly_handover import AttemptedAction, HandoverRequest

from voice_agent.runtime import TenantRuntime

IN_PROGRESS, COMPLETED, AGENT_HANDOVER = "IN_PROGRESS", "COMPLETED", "AGENT_HANDOVER"


@dataclass
class Session:
    ctx: TenantContext
    caller_number: str
    router: AIRouter
    router_state: RouterState = field(default_factory=RouterState)
    agent_state: AgentState = field(default_factory=AgentState)
    identity: IdentityLevel = IdentityLevel.UNKNOWN
    status: str = IN_PROGRESS
    transcript: list[tuple[str, str]] = field(default_factory=list)
    handover: dict | None = None
    created_at: float = field(default_factory=time.time)


def new_session(rt: TenantRuntime, call_id: str, caller_number: str) -> tuple[Session, dict]:
    ctx = TenantContext(rt.tenant_id, f"conv-{uuid.uuid4().hex[:12]}", call_id)
    session = Session(ctx, caller_number, rt.new_router())
    text, audio_id = session.router.start(ctx, session.router_state)
    session.transcript.append(("bot", text))
    out = rt.channel.outbound(Outbound(text, interruptible=False))  # AI disclosure is not interruptible
    return session, {**out, "audio_id": audio_id}


async def handle_turn(rt: TenantRuntime, session: Session, raw: dict) -> dict:
    started = time.perf_counter()
    if session.status != IN_PROGRESS:
        return _result(rt, session, Outbound("This conversation has ended."), None, None, started)
    utterance = rt.channel.inbound(raw)
    session.transcript.append(("caller", utterance.text))
    decision = session.router.route(session.ctx, session.router_state, utterance.text)

    agent = None
    if decision.kind == "say":
        out = Outbound(decision.text)
    elif decision.kind == "end":
        session.status = COMPLETED
        out = Outbound(decision.text)
    elif decision.kind == "handover":
        out = Outbound(decision.text or rt.handover.config.message)
        _handover(rt, session, decision.category, decision.subcategory, decision.reason)
    else:
        agent = decision.agent
        turn = AgentTurn(utterance.text, session.identity, session.caller_number, decision.yes_no)
        reply = await rt.supervisor.handle(session.ctx, agent, turn, session.agent_state)
        if reply.identity is not None:
            session.identity = reply.identity
        rs = session.router_state
        rs.active_domain = reply.resumed or agent
        rs.pending_question = reply.pending_question
        if reply.done:
            rs.active_domain = None
            session.agent_state.active = None
        out = Outbound(reply.text, reply.interruptible)
        if reply.handover:
            h = reply.handover
            _handover(rt, session, h["category"], h["subcategory"], h["reason"])

    session.transcript.append(("bot", out.text))
    return _result(rt, session, out, decision.path, agent, started)


def _handover(rt: TenantRuntime, session: Session, category: str, subcategory: str, reason: str) -> None:
    st = session.agent_state
    req = HandoverRequest(
        ctx=session.ctx, category=category, subcategory=subcategory, reason=reason,
        identity_level=session.identity, caller_number=session.caller_number, verified_by=st.verified_by,
        booking=st.booking, disruption=st.disruption,
        attempted_actions=[AttemptedAction(a["action"], a["result"], a["detail"], a["args"]) for a in st.attempted],
        transcript_tail=[f"{who}: {text}" for who, text in session.transcript[-6:]],
    )
    session.handover = rt.handover.build(req)
    session.handover["data_notes"] = list(st.data_notes)
    session.status = AGENT_HANDOVER


def _result(rt: TenantRuntime, session: Session, out: Outbound, path: str | None, agent: str | None,
            started: float) -> dict:
    return {
        "conversation_id": session.ctx.conversation_id,
        "reply": rt.channel.outbound(out),
        "turn_path": path,
        "agent": agent,
        "identity_level": session.identity.label,
        "conversation_status": session.status,
        "handover": session.handover if session.status == AGENT_HANDOVER else None,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
