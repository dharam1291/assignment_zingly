from __future__ import annotations

from zingly_core import TenantContext

from zingly_agents import text as slots
from zingly_agents.base import AgentReply, AgentState, AgentTurn, ask, handover
from zingly_agents.config import AgentsConfig
from zingly_agents.ports import ToolPort


class FlightStatusAgent:
    """Public information: needs no identity check (design §4)."""

    name = "flight_status"

    def __init__(self, config: AgentsConfig, tools: ToolPort):
        self.cfg = config
        self.w = config.wording
        self.tools = tools

    async def handle(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply:
        flight = slots.flight_number(turn.text)
        if not flight and state.booking:
            flight = state.booking["flight"]
        if not flight:
            if state.pending.get(self.name) == "flight_number":
                return handover("Let me pass you to a colleague.", "flight_status", "flight_unknown",
                                "could not get a flight number")
            return ask("", self.w.ask_flight_number, "flight_number")
        res = await self.tools.call(ctx, "get_flight_status", {"flight": flight}, turn.identity)
        state.attempt("get_flight_status", res.status, res.detail, flight=flight)
        if res.status == "not_found":
            return ask(f"I couldn't find {flight}.", self.w.ask_flight_number, "flight_number")
        if res.status not in ("ok", "stale"):
            return handover("I can't check flight status right now. Let me pass you to a colleague.",
                            "flight_status", "status_unavailable", f"flight status {res.status}")
        d = res.data
        status = d["status"].lower().replace("_", " ")
        if d.get("delay_minutes"):
            status += f" by about {d['delay_minutes']} minutes"
        line = self.w.status_line.format(flight=flight, destination=self.cfg.place(d["destination"]), status=status)
        if res.source == "saved_copy":
            line += " " + self.w.p3_as_of.format(as_of=slots.hhmm(res.as_of))
        if d["status"] == "CANCELLED":
            line += " " + self.w.status_cancelled_hint
        return AgentReply(f"{line} {self.w.anything_else}", done=True)
