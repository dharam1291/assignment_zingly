from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Protocol

from zingly_core import IdentityLevel, TenantContext


@dataclass
class AttemptedAction:
    action: str
    result: str             # ok | stale | deferred | failed | denied | ...
    detail: str = ""
    args: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)


@dataclass
class HandoverRequest:
    ctx: TenantContext
    category: str
    subcategory: str
    reason: str
    identity_level: IdentityLevel
    caller_number: str = ""
    verified_by: str | None = None
    booking: dict | None = None
    disruption: dict | None = None
    attempted_actions: list[AttemptedAction] = field(default_factory=list)
    transcript_tail: list[str] = field(default_factory=list)


@dataclass
class HandoverConfig:
    queues: dict[str, str] = field(default_factory=dict)   # category -> Genesys queue
    default_queue: str = "General_Support"
    priority: dict[str, int] = field(default_factory=dict)  # category -> Genesys priority
    callback_eligible: bool = True
    context_ttl_hours: float = 24
    message: str = "I'll connect you to a colleague now. They'll see everything we've covered."

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "HandoverConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


class HandoverBuilder(Protocol):
    def build(self, req: HandoverRequest) -> dict: ...


def mask_phone(number: str) -> str:
    return number[:3] + "*" * max(0, len(number) - 6) + number[-3:] if len(number) > 6 else "***"


def _mask_ref(ref: str) -> str:
    return ref[0] + "*" * (len(ref) - 3) + ref[-2:] if len(ref) > 3 else "***"


class GenesysHandoverBuilder:
    def __init__(self, config: HandoverConfig, clock: Callable[[], float] = time.time):
        self.config = config
        self._clock = clock

    def summary(self, req: HandoverRequest) -> str:
        parts = [f"Caller {req.identity_level.label}"
                 + (f" by {req.verified_by.replace('+', ' and ')}" if req.verified_by else "") + "."]
        if req.booking:
            parts.append(f"Booking {_mask_ref(req.booking['ref'])} on {req.booking['flight']}.")
        if req.disruption:
            parts.append(f"{req.disruption.get('flight')} {str(req.disruption.get('status', '')).lower()}"
                         f" ({req.disruption.get('reason') or 'reason n/a'}).")
        parts.append(f"Reason for handover: {req.reason}.")
        tried = [f"{a.action} {a.args.get('to_flight', '')}".strip() + f" -> {a.result}"
                 + (f" ({a.detail})" if a.detail else "") for a in req.attempted_actions]
        if tried:
            parts.append("Tried: " + "; ".join(tried) + ".")
        return " ".join(parts)

    def build(self, req: HandoverRequest) -> dict:
        cfg = self.config
        queue = cfg.queues.get(req.category, cfg.default_queue)
        now = self._clock()
        summary = self.summary(req)
        payload = {
            "conversation_status": "AGENT_HANDOVER",
            "tenant_id": req.ctx.tenant_id,
            "conversation_id": req.ctx.conversation_id,
            "call_id": req.ctx.call_id,
            "routing": {"queue": queue, "category": req.category, "subcategory": req.subcategory,
                        "priority": cfg.priority.get(req.category, 0), "callback_eligible": cfg.callback_eligible},
            "summary": summary,
            "caller": {"number_masked": mask_phone(req.caller_number), "identity_level": req.identity_level.label,
                       "verified_by": req.verified_by},
            "booking": ({"ref_masked": _mask_ref(req.booking["ref"]), "flight": req.booking["flight"],
                         "cabin": req.booking.get("cabin")} if req.booking else None),
            "disruption": req.disruption,
            "attempted_actions": [asdict(a) for a in req.attempted_actions],
            "context_ref": str(uuid.uuid4()),
            "context_expires_at": now + cfg.context_ttl_hours * 3600,
        }
        # Genesys participant data is a flat string map; this is what the screen-pop script reads.
        payload["genesys_participant_data"] = {
            "zingly.conversationStatus": "AGENT_HANDOVER",
            "zingly.category": req.category,
            "zingly.subcategory": req.subcategory,
            "zingly.summary": summary[:1000],
            "zingly.identityLevel": req.identity_level.label,
            "zingly.bookingRefMasked": payload["booking"]["ref_masked"] if payload["booking"] else "",
            "zingly.attemptedActions": str(len(req.attempted_actions)),
            "zingly.contextRef": payload["context_ref"],
        }
        return payload
