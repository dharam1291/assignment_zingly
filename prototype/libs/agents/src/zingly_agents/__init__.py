"""Supervisor and domain agents (design §2 step 6).

This default implementation is the design's deterministic mode (§7): templates and slot
filling, no LLM. An LLM-backed agent implements the same :class:`DomainAgent` interface
and goes through the AI gateway; nothing else changes.

Agents reach the outside world only through their own ports (``ports.py``): tools (MCP)
and auth. Flight times and entitlements always come from tools, never from wording.
"""

from zingly_agents.base import AgentReply, AgentState, AgentTurn, DomainAgent
from zingly_agents.config import AgentsConfig, Wording
from zingly_agents.faq import FaqAgent
from zingly_agents.flight_status import FlightStatusAgent
from zingly_agents.ports import AuthPort, ToolPort
from zingly_agents.rebooking import RebookingAgent
from zingly_agents.supervisor import Supervisor, build_supervisor

__all__ = [
    "AgentReply", "AgentState", "AgentTurn", "DomainAgent", "AgentsConfig", "Wording", "FaqAgent",
    "FlightStatusAgent", "AuthPort", "ToolPort", "RebookingAgent", "Supervisor", "build_supervisor",
]
