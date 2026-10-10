from __future__ import annotations

from zingly_core import TenantContext

from zingly_agents.base import AgentReply, AgentState, AgentTurn, DomainAgent
from zingly_agents.config import AgentsConfig
from zingly_agents.faq import FaqAgent
from zingly_agents.flight_status import FlightStatusAgent
from zingly_agents.ports import AuthPort, ToolPort
from zingly_agents.rebooking import RebookingAgent


class Supervisor:
    """Runs the domain agent the router chose. A side question (say, an FAQ during a
    rebooking) suspends the open task; when the side question is done the task resumes
    and its pending question is asked again."""

    def __init__(self, agents: dict[str, DomainAgent], config: AgentsConfig):
        self.agents = agents
        self.cfg = config

    async def handle(self, ctx: TenantContext, agent: str, turn: AgentTurn, state: AgentState) -> AgentReply:
        if state.active and state.active != agent and state.pending.get(state.active):
            state.suspended = state.active
        state.active = agent
        reply = await self.agents[agent].handle(ctx, turn, state)

        if reply.pending_question:
            state.pending[agent] = reply.pending_question
            state.last_question[agent] = reply.question or reply.text
        else:
            state.pending.pop(agent, None)

        if reply.done and state.suspended and not reply.handover:
            back = state.suspended
            state.suspended, state.active = None, back
            task = back.replace("_", " ")
            text = reply.text.replace(self.cfg.wording.anything_else, "").strip()
            question = state.last_question[back]
            question = question[:1].lower() + question[1:]
            reply = AgentReply(f"{text} {self.cfg.wording.resume.format(task=task)} {question}",
                               pending_question=state.pending[back], question=state.last_question[back],
                               identity=reply.identity, resumed=back)
        return reply


def build_supervisor(config: AgentsConfig, tools: ToolPort, auth: AuthPort, enabled: list[str]) -> Supervisor:
    available: dict[str, DomainAgent] = {
        "rebooking": RebookingAgent(config, tools, auth),
        "flight_status": FlightStatusAgent(config, tools),
        "faq": FaqAgent(config),
    }
    return Supervisor({name: a for name, a in available.items() if name in enabled}, config)
