from __future__ import annotations

import re

from zingly_core import TenantContext

from zingly_agents.base import AgentReply, AgentState, AgentTurn, handover
from zingly_agents.config import AgentsConfig


class FaqAgent:
    """Answers only from the tenant's approved FAQ entries; anything else goes to a person."""

    name = "faq"

    def __init__(self, config: AgentsConfig):
        self.cfg = config

    async def handle(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        low = turn.text.lower()
        best, score = None, 0
        for entry in self.cfg.faq:
            hits = sum(1 for k in entry.get("keywords", []) if re.search(rf"\b{re.escape(k.lower())}\b", low))
            if hits > score:
                best, score = entry, hits
        if not best:
            return handover(self.cfg.wording.faq_no_answer, "faq", "no_answer", "question not in approved FAQ")
        return AgentReply(f"{best['answer']} {self.cfg.wording.anything_else}", done=True)
