from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from zingly_core import IdentityLevel, TenantContext


@dataclass
class AgentTurn:
    text: str
    identity: IdentityLevel
    caller_number: str = ""
    yes_no: str | None = None  # resolved by the router's fast path against the pending question


@dataclass
class AgentState:
    """The agents' slice of a conversation. Shared by all domain agents so identity, booking
    and a half-finished task survive a topic change (design §3)."""

    active: str | None = None
    suspended: str | None = None
    pending: dict[str, str] = field(default_factory=dict)        # agent -> pending question id
    last_question: dict[str, str] = field(default_factory=dict)  # agent -> question to re-ask
    booking: dict | None = None
    verified_by: str | None = None
    ref_candidate: str | None = None
    caller_hint: dict | None = None
    hint_checked: bool = False
    disruption: dict | None = None
    options: list[dict] = field(default_factory=list)
    chosen: dict | None = None
    conflicts: int = 0
    attempted: list[dict] = field(default_factory=list)          # every attempted action and result
    data_notes: list[str] = field(default_factory=list)          # e.g. "options as of 14:02"

    def attempt(self, action: str, result: str, detail: str = "", **args: str) -> None:
        self.attempted.append({"action": action, "result": result, "detail": detail, "args": args})


@dataclass
class AgentReply:
    text: str
    pending_question: str | None = None
    question: str | None = None            # the bare question, re-asked when a task resumes
    done: bool = False
    handover: dict | None = None           # {category, subcategory, reason}
    identity: IdentityLevel | None = None  # new level if this turn changed it
    interruptible: bool = True
    resumed: str | None = None


def ask(preface: str, question: str, pending: str, **kw) -> AgentReply:
    text = f"{preface} {question}".strip()
    return AgentReply(text, pending_question=pending, question=question, **kw)


def handover(text: str, category: str, subcategory: str, reason: str, **kw) -> AgentReply:
    return AgentReply(text, handover={"category": category, "subcategory": subcategory, "reason": reason}, **kw)


class DomainAgent(Protocol):
    name: str

    async def handle(self, ctx: TenantContext, turn: AgentTurn, state: AgentState) -> AgentReply: ...
