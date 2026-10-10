"""Business routing owned by Zingly, per tenant: which domain agents are on and what share
of calls each one takes (canary rollout). The IVR-vs-bot split is NOT here: Genesys owns
that in its inbound flow (design §2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from zingly_core import TenantContext


@dataclass
class RoutingConfig:
    enabled_agents: list[str] = field(default_factory=lambda: ["rebooking", "flight_status", "faq"])
    rollout_percent: dict[str, int] = field(default_factory=dict)  # missing agent = 100

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "RoutingConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


@dataclass(frozen=True)
class RoutingVerdict:
    allowed: bool
    reason: str = ""


class BusinessRouter:
    def __init__(self, config: RoutingConfig):
        self.config = config

    @staticmethod
    def bucket(ctx: TenantContext, agent: str) -> int:
        """Stable 0..99 per conversation, so a call never flips between bot and human mid-way."""
        digest = hashlib.sha256(f"{ctx.tenant_id}:{ctx.conversation_id}:{agent}".encode()).hexdigest()
        return int(digest[:8], 16) % 100

    def admit(self, ctx: TenantContext, agent: str) -> RoutingVerdict:
        if agent not in self.config.enabled_agents:
            return RoutingVerdict(False, "agent_disabled")
        if self.bucket(ctx, agent) >= self.config.rollout_percent.get(agent, 100):
            return RoutingVerdict(False, "not_in_rollout")
        return RoutingVerdict(True)
